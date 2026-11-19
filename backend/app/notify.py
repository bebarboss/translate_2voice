"""แจ้งเตือนทางอีเมล เข้าคิว notification_outbox แล้วให้เธรดพื้นหลังส่ง

ไม่ได้ตั้ง SMTP_HOST และ MAIL_FROM = ไม่เข้าคิว บันทึก log อย่างเดียว (ปิดที่อยู่อีเมล)
ผู้ใช้ปิดทั้งกลุ่มได้ที่ users.notify_email และปิดรายข้อใน notify_prefs
อีเมลนักพากย์และค่าตอบแทนส่งเสมอ ไม่มีลิงก์ยกเลิกรับ
งานที่เสร็จภายใน NOTIFY_MIN_SECONDS ไม่ส่งอีเมล (ยังเขียน inbox)
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from . import accounts, config, inbox, outbox

log = logging.getLogger("dubbing.notify")
BRAND = "พากย์ดี"
# ปุ่มหลักของแอปคือ --ink / --on-ink ไม่ใช้สีส้ม
_BTN = "background:#141414;color:#ffffff;padding:11px 20px;border-radius:9px;text-decoration:none;font-weight:600"
TOKEN_TTL = 60 * 24 * 3600  # ลิงก์ยกเลิกรับมีอายุ 60 วัน
UNSUBSCRIBE_PATH = "/notifications/unsubscribe"
# access log ของ uvicorn ใส่ query ทั้งก้อน โทเคนต้องไม่โผล่ในไฟล์ log
_TOKEN_QUERY = re.compile(r"(?i)([?&]token=)[^&\s\"']*")
FAILED_INBOX = "งาน “{name}” ทำไม่สำเร็จ เครดิตของขั้นที่ไม่สำเร็จคืนให้อัตโนมัติ กดเปิดงานเพื่อดูรายละเอียดและลองใหม่"
_JOB_KIND = {"review": "job_review", "done": "job_done", "failed": "job_failed"}

public_router = APIRouter()


def is_unsubscribe_path(path: str) -> bool:
    """เส้นทางยกเลิกอีเมล ไม่สน query และเครื่องหมาย / ท้าย"""
    raw = (path or "").split("?", 1)[0]
    raw = urllib.parse.unquote(raw)
    if len(raw) > 1:
        raw = raw.rstrip("/")
    return raw == UNSUBSCRIBE_PATH


def redact_access_record(record: logging.LogRecord) -> None:
    """แทน token=... ด้วย token=REDACTED เฉพาะเส้นทางยกเลิกอีเมล"""
    args = record.args
    if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
        full_path = args[2]
        if is_unsubscribe_path(full_path) and "token=" in full_path.lower():
            record.args = (*args[:2], _TOKEN_QUERY.sub(r"\1REDACTED", full_path), *args[3:])
    msg = record.msg
    if isinstance(msg, str) and "token=" in msg.lower() and is_unsubscribe_path(msg):
        record.msg = _TOKEN_QUERY.sub(r"\1REDACTED", msg)


class AccessTokenFilter(logging.Filter):
    """กรอง log ของ uvicorn.access ไม่ทิ้งบรรทัด แค่ปิดบังโทเคน"""

    def filter(self, record: logging.LogRecord) -> bool:
        redact_access_record(record)
        return True


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessTokenFilter) for item in logger.filters):
        logger.addFilter(AccessTokenFilter())


install_access_log_filter()


class UnsubscribeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return outbox.enabled()


def start_mailer() -> None:
    outbox.start()


def stop_mailer() -> None:
    outbox.stop()


def _secret() -> bytes:
    return (config.settings.unsubscribe_secret or "").strip().encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + pad).encode())


def sign_token(uid: str, category: str, exp: int) -> str:
    """HMAC-SHA256 ของ user id + หมวด + เวลาหมดอายุ ไม่มีอีเมลในโทเคน"""
    if not _secret() or not uid or not category:
        return ""
    payload = f"{uid}|{category}|{int(exp)}".encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)


def make_token(uid: str, category: str, *, now: Optional[float] = None) -> str:
    if category not in accounts.EMAIL_PREF_KEYS:
        return ""
    exp = int((time.time() if now is None else now) + TOKEN_TTL)
    return sign_token(uid, category, exp)


def read_token(token: str, *, now: Optional[float] = None) -> tuple[str, str]:
    """คืน (user id, หมวด) โทเคนเสีย 400 หมดอายุ 410 ไม่ส่งค่านี้ออกทาง HTTP"""
    secret = _secret()
    if not secret or not token or token.count(".") != 1:
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    left, right = token.split(".", 1)
    try:
        payload = _b64d(left)
        sig = _b64d(right)
    except Exception:
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    expected = hmac.new(secret, payload, hashlib.sha256).digest()
    if len(sig) != len(expected) or not hmac.compare_digest(sig, expected):
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    parts = payload.split(b"|")
    if len(parts) != 3:
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    try:
        uid = parts[0].decode("utf-8")
        category = parts[1].decode("utf-8")
        exp = int(parts[2].decode("ascii"))
    except (UnicodeError, ValueError):
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    if not uid or category not in accounts.EMAIL_PREF_KEYS:
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    if (time.time() if now is None else now) > exp:
        raise UnsubscribeError(410, "ลิงก์ยกเลิกหมดอายุ")
    return uid, category


def preview_unsubscribe(token: str) -> dict:
    """อ่านอย่างเดียว ไม่เปลี่ยนการตั้งค่า"""
    _uid, category = read_token(token)
    return {"category": category}


def apply_unsubscribe(token: str) -> dict:
    uid, category = read_token(token)
    try:
        accounts.disable_email_pref(uid, category)
    except accounts.AccountError:
        raise UnsubscribeError(400, "ลิงก์ยกเลิกไม่ถูกต้อง")
    return {"ok": True, "category": category}


async def _token_from_request(request: Request, token: str) -> str:
    if token and token.strip():
        return token.strip()
    raw = await request.body()
    if not raw:
        return ""
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        if isinstance(data, dict) and isinstance(data.get("token"), str):
            return data["token"].strip()
        return ""
    parsed = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
    vals = parsed.get("token") or []
    return vals[0].strip() if vals else ""


def _fail(exc: UnsubscribeError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@public_router.get(UNSUBSCRIBE_PATH)
def unsubscribe_preview(token: str = ""):
    """ให้หน้าเว็บรู้ว่าลิงก์นี้เป็นหมวดไหน ไม่เปลี่ยนการตั้งค่า"""
    try:
        return preview_unsubscribe(token)
    except UnsubscribeError as exc:
        raise _fail(exc)


@public_router.post(UNSUBSCRIBE_PATH)
async def unsubscribe_apply(request: Request, token: str = ""):
    """one-click (query token + ฟอร์ม List-Unsubscribe=One-Click) หรือ JSON {token} จากหน้าเว็บ"""
    try:
        chosen = await _token_from_request(request, token)
        return apply_unsubscribe(chosen)
    except UnsubscribeError as exc:
        raise _fail(exc)


# / ท้ายต้องไม่ตกไปที่ access_guard แล้วโดน 401 (proxy จะลบคุกกี้ session)
public_router.add_api_route(UNSUBSCRIBE_PATH + "/", unsubscribe_preview, methods=["GET"], include_in_schema=False)
public_router.add_api_route(UNSUBSCRIBE_PATH + "/", unsubscribe_apply, methods=["POST"], include_in_schema=False)


def _web(path: str) -> Optional[str]:
    base = (config.settings.web_url or "").strip().rstrip("/")
    if not base or not path:
        return None
    path = outbox.clean_header(path, 300)
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _compose(to: str, subject: str, lines: list[str], path: Optional[str], button: str,
             kind: str, user_id: str) -> tuple[str, str, dict]:
    import html as html_lib
    link = _web(path) if path else None
    configurable = kind in accounts.EMAIL_PREF_KEYS
    token = make_token(user_id, kind) if configurable and user_id else ""
    base = (config.settings.web_url or "").strip().rstrip("/")
    api = (config.settings.api_url or "").strip().rstrip("/")
    settings_url = f"{base}/account?tab=prefs" if base else ""
    unsub_url = f"{base}/unsubscribe?token={token}" if token and base else ""
    api_unsub = f"{api}{UNSUBSCRIBE_PATH}?token={token}" if token and api else ""
    text = "\n\n".join(lines)
    if link:
        text += f"\n\n{button}: {link}"
    text += f"\n\n— {BRAND}"
    foot_lines = []
    if settings_url:
        foot_lines.append(f"ตั้งค่าการแจ้งเตือน: {settings_url}")
    if unsub_url:
        foot_lines.append(f"ยกเลิกการรับอีเมลนี้: {unsub_url}")
    if foot_lines:
        text += "\n\n" + "\n".join(foot_lines)
    body = "".join(f'<p style="margin:0 0 14px">{html_lib.escape(x)}</p>' for x in lines)
    if link:
        body += (f'<p style="margin:22px 0"><a href="{html_lib.escape(link, quote=True)}" style="{_BTN}">'
                 f'{html_lib.escape(button)}</a></p>')
    foot_html = []
    if settings_url:
        foot_html.append(f'<a href="{html_lib.escape(settings_url, quote=True)}">ตั้งค่าการแจ้งเตือน</a>')
    if unsub_url:
        foot_html.append(f'<a href="{html_lib.escape(unsub_url, quote=True)}">ยกเลิกการรับอีเมลนี้</a>')
    footer = ""
    if foot_html:
        footer = '<p style="color:#888;font-size:12px;margin-top:8px">' + " · ".join(foot_html) + "</p>"
    html_body = (
        '<div style="font-family:Sarabun,Tahoma,sans-serif;font-size:15px;line-height:1.6;color:#222;max-width:600px">'
        f'{body}<p style="color:#888;font-size:13px;margin-top:28px">— {html_lib.escape(BRAND)}</p>{footer}</div>'
    )
    headers: dict[str, str] = {}
    if api_unsub:
        headers["List-Unsubscribe"] = f"<{api_unsub}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return text + "\n", html_body, headers


def _send(to: str, subject: str, lines: list[str], path: Optional[str], button: str,
          kind: str, user_id: str, dedupe_key: str) -> None:
    to = outbox.clean_header(to, 254)
    if not to or "@" not in to or to.endswith("@deleted.invalid"):
        return
    subject = outbox.clean_header(subject, 180) or BRAND
    lines = [outbox.clean_header(x, 1000) for x in lines if outbox.clean_header(x, 1000)]
    kind = outbox.clean_header(kind, 40)
    user_id = outbox.clean_header(user_id, 80)
    if kind in accounts.EMAIL_PREF_KEYS:
        if not user_id:
            return
        row = accounts.user_by_id(user_id)
        if row is None or not accounts.email_pref_on(row, kind):
            return
    if not enabled():
        log.info("mail (not configured) to %s: %s", outbox.mask_email(to), subject)
        return
    if not dedupe_key:
        dedupe_key = secrets.token_hex(16)
    dedupe_key = outbox.clean_header(dedupe_key, 180) or secrets.token_hex(16)
    text, html_body, headers = _compose(to, subject, lines, path, button or "เปิดดู", kind, user_id)
    outbox.enqueue(to, subject, text, html_body, headers, kind, user_id, dedupe_key)


def send(to: str, subject: str, lines: list[str], path: Optional[str] = None, button: str = "เปิดดู", *,
         kind: str = "", user_id: str = "", dedupe_key: str = "") -> None:
    """เข้าคิวอีเมล ไม่ส่งตรงและไม่โยนข้อผิดพลาดออกไปหาคำขอ"""
    try:
        _send(to, subject, lines, path, button, kind, user_id, dedupe_key)
    except Exception as exc:  # noqa: BLE001
        log.error("mail enqueue failed: %s", type(exc).__name__)


def _user(uid: Optional[str]):
    if not uid or not accounts.auth_enabled():
        return None
    u = accounts.user_by_id(uid)
    return u if u is not None and u["deleted_at"] is None else None


def admins() -> list[str]:
    if not accounts.auth_enabled():
        return []
    rows = accounts._read("SELECT email FROM users WHERE admin = 1 AND deleted_at IS NULL")
    return sorted(set(config.settings.admin_emails) | {r["email"] for r in rows})


def _name(value: str) -> str:
    return outbox.clean_header(value or "", 80)


def _filename(job) -> str:
    return outbox.clean_header(getattr(job, "filename", "") or "งาน", 120)


# ---------------------------------------------------------------- งาน
def _inbox_job(u, job, job_id: str, kind: str) -> None:
    name = _filename(job)
    link = f"/jobs/{job_id}"
    if kind == "review":
        inbox.add(u["id"], "job_review", "รอตรวจบท", f"งาน “{name}” แปลเสร็จแล้ว รอคุณตรวจบทก่อนพากย์", link, job_id)
    elif kind == "done":
        inbox.add(u["id"], "job_done", "พากย์เสร็จแล้ว", f"งาน “{name}” พร้อมดูผลและดาวน์โหลด", link, job_id)
    elif kind == "failed":
        log.info("job %s failed: %s", job_id, (getattr(job, "error", None) or "")[:2000])
        inbox.add(u["id"], "job_failed", "งานไม่สำเร็จ", FAILED_INBOX.replace("{name}", name), link, job_id)


def deliver_job_notice(u, job, job_id: str, kind: str, elapsed: float) -> None:
    _inbox_job(u, job, job_id, kind)
    cat = _JOB_KIND.get(kind)
    if cat is None:
        return
    if kind != "failed" and elapsed < config.settings.notify_min_seconds:
        return
    fresh = accounts.user_by_id(u["id"]) or u
    if not accounts.email_pref_on(fresh, cat):
        return
    name = _filename(job)
    who = _name(fresh["name"])
    hello = f"สวัสดีคุณ{who}"
    if kind == "review":
        library = bool(getattr(job, "library", False))
        what = "แยกเสียงเสร็จแล้ว เลือกบันทึกเสียงของแต่ละคนลงคลังได้" if library else "ถอดเสียงและแปลเสร็จแล้ว รอคุณตรวจบทก่อนพากย์"
        send(fresh["email"], f"รอตรวจบท: {name}", [hello, f"งาน “{name}” {what}"], f"/jobs/{job_id}", "ตรวจบท",
             kind=cat, user_id=u["id"], dedupe_key=f"{u['id']}:{cat}:{job_id}")
    elif kind == "done":
        timeline = bool(getattr(job, "timeline", False))
        what = "พากย์เสร็จแล้ว ดาวน์โหลดไฟล์สำหรับโปรแกรมตัดต่อได้" if timeline else "พากย์เสร็จแล้ว ดูผลและดาวน์โหลดวิดีโอได้"
        send(fresh["email"], f"พากย์เสร็จแล้ว: {name}", [hello, f"งาน “{name}” {what}"], f"/jobs/{job_id}", "ดูผลงาน",
             kind=cat, user_id=u["id"], dedupe_key=f"{u['id']}:{cat}:{job_id}")
    elif kind == "failed":
        send(fresh["email"], f"งานไม่สำเร็จ: {name}", [hello, FAILED_INBOX.replace("{name}", name)], f"/jobs/{job_id}", "เปิดงาน",
             kind=cat, user_id=u["id"], dedupe_key=f"{u['id']}:{cat}:{job_id}")


def job_event(job_id: str, kind: str, elapsed: float) -> None:
    """kind: review = แปลเสร็จรอตรวจบท, done = พากย์เสร็จ, failed = ล้มเหลว"""
    from .main import store
    job = store.get(job_id)
    u = _user(job.owner if job else None)
    if job is None or u is None:
        return
    deliver_job_notice(u, job, job_id, kind, elapsed)


def credits_low(uid: str, units: int) -> None:
    """แจ้งเมื่อยอดที่ใช้ได้เหลือไม่เกิน 1.00 เขียน inbox แม้ปิดอีเมล"""
    try:
        _credits_low(uid, units)
    except Exception as exc:  # noqa: BLE001
        log.error("credits_low failed: %s", type(exc).__name__)


def _credits_low(uid: str, units: int) -> None:
    u = _user(uid)
    if u is None:
        return
    n = accounts.fmt_credits(int(units))
    body = f"ยอดที่ใช้ได้เหลือ {n} เครดิต เติมเพื่อส่งงานต่อได้"
    inbox.add(uid, "credits_low", "เครดิตใกล้หมด", body, "/promotions")
    if not accounts.email_pref_on(u, "credits_low"):
        return
    send(u["email"], "เครดิตใกล้หมดแล้ว", [f"สวัสดีคุณ{_name(u['name'])}", body], "/promotions", "เติมเครดิต",
         kind="credits_low", user_id=uid, dedupe_key=f"{uid}:credits_low:{secrets.token_hex(8)}")


# ---------------------------------------------------------------- นักพากย์
def actor_applied(uid: str, stage_name: str) -> None:
    who = _name(stage_name)
    for to in admins():
        send(to, f"ผู้สมัครนักพากย์ใหม่: {who}", [f"“{who}” สมัครเป็นนักพากย์ รอตรวจใบสมัคร"], "/actors", "ตรวจใบสมัคร",
             kind="actor_applied", user_id=uid, dedupe_key=f"{uid}:actor_applied:{secrets.token_hex(8)}")


def actor_voice_submitted(uid: str, voice_name: str) -> None:
    from . import actors
    a = actors.actor(uid)
    who = _name(a["stage_name"] if a else "")
    voice = _name(voice_name)
    for to in admins():
        send(to, f"เสียงนักพากย์รอตรวจ: {voice}", [f"{who} ส่งเสียง “{voice}” เข้าคลัง รอตรวจฟังก่อนเปิดให้ผู้ใช้"],
             "/actors", "ตรวจฟังเสียง", kind="actor_voice_submitted", user_id=uid,
             dedupe_key=f"{uid}:actor_voice_submitted:{secrets.token_hex(8)}")


def actor_reviewed(uid: str, approve: bool, note: str) -> None:
    u = _user(uid)
    if u is None:
        return
    note = _name(note)
    lines = [f"สวัสดีคุณ{_name(u['name'])}"]
    if approve:
        lines.append("ใบสมัครนักพากย์ของคุณได้รับอนุมัติแล้ว เข้าไปอัดเสียงเข้าคลังได้เลย")
    else:
        lines.append("ใบสมัครนักพากย์ของคุณยังไม่ผ่าน" + (f": {note}" if note else "") + " แก้ไขแล้วสมัครใหม่ได้")
    inbox.add(uid, "actor_approved" if approve else "actor_rejected",
              "ใบสมัครนักพากย์ได้รับอนุมัติ" if approve else "ใบสมัครนักพากย์ยังไม่ผ่าน", lines[1], "/actor")
    send(u["email"], "ใบสมัครนักพากย์ได้รับอนุมัติ" if approve else "ผลใบสมัครนักพากย์", lines, "/actor", "ไปหน้านักพากย์",
         kind="actor_reviewed", user_id=uid, dedupe_key=f"{uid}:actor_reviewed:{secrets.token_hex(8)}")


def voice_reviewed(uid: str, voice_name: str, approve: bool, note: str, bonus: int = 0) -> None:
    u = _user(uid)
    if u is None:
        return
    voice = _name(voice_name)
    note = _name(note)
    lines = [f"สวัสดีคุณ{_name(u['name'])}"]
    if approve:
        lines.append(f"เสียง “{voice}” ผ่านการตรวจแล้ว ผู้ใช้ทุกคนเลือกใช้พากย์ได้ตั้งแต่ตอนนี้")
        if bonus > 0:
            lines.append(f"ได้รับโบนัส {bonus} เครดิตจากการอนุมัติเสียงนี้ (เครดิตเติม ไม่หมดอายุ)")
    else:
        lines.append(f"เสียง “{voice}” ยังไม่ผ่านการตรวจ" + (f": {note}" if note else "") + " อัดใหม่แล้วส่งอีกครั้งได้")
    inbox.add(uid, "voice_approved" if approve else "voice_rejected", f"ผลตรวจเสียง: {voice}", " ".join(lines[1:]), "/actor")
    send(u["email"], f"ผลตรวจเสียง: {voice}", lines, "/actor", "ไปหน้านักพากย์",
         kind="voice_reviewed", user_id=uid, dedupe_key=f"{uid}:voice_reviewed:{secrets.token_hex(8)}")


def actor_paid(uid: str, month: str, amount: int, wht: int) -> None:
    u = _user(uid)
    if u is None:
        return
    baht = lambda s: f"{s / 100:,.2f} บาท"  # noqa: E731
    month = _name(month)
    lines = [f"สวัสดีคุณ{_name(u['name'])}", f"โอนค่าตอบแทนของเดือน {month} ให้แล้ว {baht(amount - wht)}"]
    if wht:
        lines.append(f"ยอดก่อนหักภาษี {baht(amount)} หักภาษี ณ ที่จ่าย {baht(wht)}")
    inbox.add(uid, "actor_paid", f"โอนค่าตอบแทนเดือน {month} แล้ว", lines[1], "/actor")
    send(u["email"], f"โอนค่าตอบแทนเดือน {month} แล้ว", lines, "/actor", "ดูรายละเอียด",
         kind="actor_paid", user_id=uid, dedupe_key=f"{uid}:actor_paid:{month}")
