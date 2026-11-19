"""คิวอีเมล notification_outbox ส่งทีหลังในเธรดพื้นหลัง

หลาย pod แย่งแถวในธุรกรรมเดียว Postgres ใช้ FOR UPDATE SKIP LOCKED
SMTP ไม่ได้ตั้ง = ไม่เข้าคิว (notify.send บันทึก log อย่างเดียว)
พอร์ต 587 ต้อง EHLO แล้ว STARTTLS ก่อน AUTH เซิร์ฟเวอร์ไม่ประกาศ STARTTLS = ตายทันที ไม่ล็อกอินแบบเคลียร์เท็กซ์
"""
import json
import logging
import re
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from . import accounts, config

log = logging.getLogger("dubbing.notify")

# หลังส่งไม่สำเร็จครั้งที่ 1..4 รอ 1 นาที, 5 นาที, 30 นาที, 2 ชม. ครั้งที่ 5 แล้วตาย
# 6 ชม. เป็นช่วงสุดท้ายของตารางที่ประกาศไว้ แต่ไม่ถูกตั้งคิวเพราะครบ 5 ครั้งแล้วเป็น dead
BACKOFF_SEC = (60, 5 * 60, 30 * 60, 2 * 3600, 6 * 3600)
MAX_ATTEMPTS = 5
STUCK_SEC = 15 * 60  # ค้างสถานะ sending นานกว่านี้ถูกดึงกลับ
_CTRL = re.compile(r"[\r\n\x00-\x1f\x7f]+")

_DDL = (
    "CREATE TABLE IF NOT EXISTS notification_outbox ("
    "id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT '', to_email TEXT NOT NULL, kind TEXT NOT NULL, "
    "subject TEXT NOT NULL, text_body TEXT NOT NULL, html_body TEXT NOT NULL, headers TEXT NOT NULL DEFAULT '{}', "
    "status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, "
    "next_attempt_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '', "
    "created_at REAL NOT NULL, sent_at REAL, dedupe_key TEXT NOT NULL, "
    "CHECK (status IN ('pending', 'sending', 'sent', 'dead')))"
)

# พารามิเตอร์: now, limit, now+STUCK  Postgres ล็อกแถวที่หยิบ ไม่ให้ pod อื่นส่งซ้ำ
PG_CLAIM = (
    "WITH picked AS ("
    "SELECT id FROM notification_outbox "
    "WHERE status = 'pending' AND next_attempt_at <= ? "
    "ORDER BY next_attempt_at, id "
    "LIMIT ? "
    "FOR UPDATE SKIP LOCKED"
    ") "
    "UPDATE notification_outbox AS o "
    "SET status = 'sending', attempts = o.attempts + 1, next_attempt_at = ? "
    "FROM picked WHERE o.id = picked.id "
    "RETURNING o.id, o.user_id, o.to_email, o.kind, o.subject, o.text_body, o.html_body, o.headers, o.attempts, o.status"
)

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_thread_lock = threading.Lock()


class PermanentDelivery(Exception):
    """ส่งซ้ำไม่ได้ เช่น SMTP 5xx หรือเซิร์ฟเวอร์ไม่ยอม STARTTLS"""


def enabled() -> bool:
    return bool(config.settings.smtp_host and config.settings.mail_from)


def clean_header(value: str, limit: int = 200) -> str:
    """ตัด CR/LF และอักขระควบคุม กัน header injection และกัน EmailMessage โยน ValueError"""
    text = _CTRL.sub(" ", value or "")
    return " ".join(text.split())[:limit]


def mask_email(addr: str) -> str:
    local, sep, domain = (addr or "").partition("@")
    if not sep or not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


def _safe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    secret = config.settings.smtp_password or ""
    if secret and secret in text:
        text = text.replace(secret, "***")
    return clean_header(text, 300)


def _ensure(db) -> None:
    db.execute(_DDL)
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS notification_outbox_dedupe ON notification_outbox(dedupe_key)")
    db.execute("CREATE INDEX IF NOT EXISTS notification_outbox_due ON notification_outbox(status, next_attempt_at)")


def enqueue(to_email: str, subject: str, text_body: str, html_body: str, headers: dict,
            kind: str, user_id: str, dedupe_key: str) -> bool:
    """เข้าคิว คีย์ซ้ำถูกทิ้ง ไม่โยนออกไปหาผู้เรียก"""
    if not enabled():
        return False
    now = time.time()
    try:
        with accounts._tx() as db:
            _ensure(db)
            db.execute(
                "INSERT OR IGNORE INTO notification_outbox ("
                "id, user_id, to_email, kind, subject, text_body, html_body, headers, "
                "status, attempts, next_attempt_at, last_error, created_at, sent_at, dedupe_key"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, '', ?, NULL, ?)",
                (secrets.token_hex(16), user_id[:80], to_email, kind[:40], subject, text_body, html_body,
                 json.dumps(headers, ensure_ascii=False), now, now, dedupe_key[:180]),
            )
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("outbox enqueue failed: %s", type(exc).__name__)
        return False


def _reclaim(db, now: float) -> None:
    db.execute(
        "UPDATE notification_outbox SET status = 'dead', last_error = ? "
        "WHERE status = 'sending' AND next_attempt_at <= ? AND attempts >= ?",
        ("stuck in sending", now, MAX_ATTEMPTS),
    )
    db.execute(
        "UPDATE notification_outbox SET status = 'pending', next_attempt_at = ? "
        "WHERE status = 'sending' AND next_attempt_at <= ? AND attempts < ?",
        (now, now, MAX_ATTEMPTS),
    )


def claim_due(limit: int = 8) -> list[dict]:
    """หยิบแถว pending ที่ถึงเวลา เปลี่ยนเป็น sending ในธุรกรรมเดียว"""
    now = time.time()
    with accounts._tx() as db:
        _ensure(db)
        _reclaim(db, now)
        from .pgstore import is_pg
        if is_pg(db):
            rows = db.execute(PG_CLAIM, (now, max(1, limit), now + STUCK_SEC)).fetchall()
            return [dict(r) for r in rows]
        out = []
        for _ in range(max(1, limit)):
            # ตราประทับใน last_error เพื่อรู้ว่าแถวนี้ถูก UPDATE รอบนี้จริง ไม่พึ่ง rowcount
            stamp = secrets.token_hex(8)
            db.execute(
                "UPDATE notification_outbox SET status = 'sending', attempts = attempts + 1, "
                "next_attempt_at = ?, last_error = ? "
                "WHERE id = ("
                "SELECT id FROM notification_outbox WHERE status = 'pending' AND next_attempt_at <= ? "
                "ORDER BY next_attempt_at, id LIMIT 1"
                ") AND status = 'pending'",
                (now + STUCK_SEC, stamp, now),
            )
            full = db.execute(
                "SELECT * FROM notification_outbox WHERE last_error = ? AND status = 'sending'",
                (stamp,),
            ).fetchone()
            if full is None:
                break
            out.append(dict(full))
        return out


def _message_from_row(row: dict) -> EmailMessage:
    mail_from = clean_header(config.settings.mail_from or "", 254)
    msg = EmailMessage()
    msg["Subject"] = clean_header(row["subject"], 180) or "พากย์ดี"
    msg["From"] = formataddr(("พากย์ดี", mail_from))
    msg["To"] = clean_header(row["to_email"], 254)
    domain = mail_from.rpartition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    try:
        headers = json.loads(row["headers"] or "{}")
    except json.JSONDecodeError:
        headers = {}
    if isinstance(headers, dict):
        for key, value in headers.items():
            name = clean_header(str(key), 80)
            text = clean_header(str(value), 2000)
            if name and text:
                msg[name] = text
    msg.set_content(row["text_body"] or "")
    msg.add_alternative(row["html_body"] or "", subtype="html")
    return msg


def _auth_and_send(client, msg: EmailMessage) -> None:
    user = config.settings.smtp_user
    if user:
        client.login(user, config.settings.smtp_password)
    client.send_message(msg)


def transmit(msg: EmailMessage) -> None:
    """465 = TLS ตั้งแต่เชื่อม อย่างอื่นต้อง STARTTLS ก่อน AUTH"""
    host = config.settings.smtp_host
    port = int(config.settings.smtp_port)
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
        with client:
            _auth_and_send(client, msg)
        return
    client = smtplib.SMTP(host, port, timeout=20)
    with client:
        client.ehlo()
        if not client.has_extn("starttls"):
            raise PermanentDelivery("STARTTLS is not advertised; refusing to send or authenticate in cleartext")
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        _auth_and_send(client, msg)


def _permanent(exc: BaseException) -> bool:
    if isinstance(exc, (PermanentDelivery, ValueError)):
        return True
    code = getattr(exc, "smtp_code", None)
    if isinstance(code, int) and 500 <= code <= 599:
        return True
    recipients = getattr(exc, "recipients", None)
    if isinstance(recipients, dict) and recipients:
        codes = []
        for val in recipients.values():
            if isinstance(val, tuple) and val and isinstance(val[0], int):
                codes.append(val[0])
        if codes and all(500 <= c <= 599 for c in codes):
            return True
    return False


def _settle(row: dict, *, sent: bool = False, dead: bool = False, error: Optional[BaseException] = None) -> None:
    now = time.time()
    err = _safe_error(error) if error else ""
    who = mask_email(row.get("to_email") or "")
    with accounts._tx() as db:
        _ensure(db)
        if sent:
            db.execute("UPDATE notification_outbox SET status = 'sent', sent_at = ?, last_error = '' WHERE id = ?",
                       (now, row["id"]))
            log.info("mail sent to %s: %s", who, clean_header(row.get("subject") or "", 80))
            return
        attempts = int(row.get("attempts") or 0)
        if dead or attempts >= MAX_ATTEMPTS:
            db.execute("UPDATE notification_outbox SET status = 'dead', last_error = ? WHERE id = ?",
                       (err, row["id"]))
            log.info("mail to %s dead: %s", who, err)
            return
        # ครั้งที่ 1–4 ใช้ช่วง 1 นาที ถึง 2 ชม. ช่วง 6 ชม. ไม่ถูกตั้งเพราะครั้งที่ 5 เป็น dead
        delay = BACKOFF_SEC[min(max(attempts - 1, 0), MAX_ATTEMPTS - 2)]
        db.execute(
            "UPDATE notification_outbox SET status = 'pending', next_attempt_at = ?, last_error = ? WHERE id = ?",
            (now + delay, err, row["id"]),
        )
        log.info("mail to %s retry in %ss: %s", who, delay, err)


def deliver_one(row: dict) -> None:
    try:
        transmit(_message_from_row(row))
    except Exception as exc:  # noqa: BLE001
        _settle(row, dead=_permanent(exc), error=exc)
    else:
        _settle(row, sent=True)


def pump(limit: int = 8) -> int:
    if not enabled():
        return 0
    rows = claim_due(limit)
    for row in rows:
        deliver_one(row)
    return len(rows)


def _loop() -> None:
    while not _stop.is_set():
        n = 0
        try:
            if enabled():
                n = pump()
        except Exception as exc:  # noqa: BLE001
            log.error("outbox pump failed: %s", type(exc).__name__)
        _stop.wait(1.0 if n else 5.0)


def start() -> None:
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="mail-outbox", daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()
