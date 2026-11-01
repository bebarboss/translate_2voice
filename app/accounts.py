"""บัญชีผู้ใช้ เครดิต และแพ็กเกจ เก็บใน data/accounts.db (SQLite)

AUTH_ENABLED=1 เปิดระบบล็อกอิน (ทุกคำขอต้องล็อกอิน เห็นเฉพาะงานของตัวเอง) สมัครและเข้าสู่ระบบด้วยบัญชี Google
(GOOGLE_CLIENT_ID) เท่านั้น ไม่มีรหัสผ่าน
BILLING_ENABLED=1 เปิดเครดิตและแพ็กเกจ (ตัดเครดิตเมื่อเริ่มวิเคราะห์งาน) ต้องเปิดคู่กับ AUTH_ENABLED
ผู้ดูแลระบบ (ADMIN_EMAILS) พากย์ได้ไม่จำกัด ไม่ถูกตัดเครดิต

1 เครดิต = คลิป 1 นาที (ปัดขึ้น) มีสองแบบ:
- เครดิตแพ็กเกจ (subscriptions.minutes_left) ได้จากแพ็กเกจรายเดือน หมดอายุพร้อมแพ็กเกจ ใช้ก่อน
- เครดิตเติม (users.credits) ซื้อเพิ่มหรือผู้ดูแลให้ ไม่หมดอายุ
เงินเก็บเป็นสตางค์ (จำนวนเต็ม) ใช้แค่ตอนชำระเงิน
ทุกการเปลี่ยนยอดลงสมุดบัญชี (ledger) ref ของการตัดและคืนเครดิตเป็น id งาน กันตัดซ้ำ
"""
import hashlib
import math
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

from .config import settings

SESSION_DAYS = 30
TOPUP_MIN, TOPUP_MAX = 5, 2000  # ซื้อเครดิตเติมได้ครั้งละกี่เครดิต


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price: int  # สตางค์ต่อรอบ
    minutes: int  # เครดิตต่อรอบ (1 เครดิต = 1 นาที)
    days: int = 30


# ราคาตั้งต้น ปรับได้ก่อนเปิดใช้งานจริง
PLANS = [
    Plan("starter", "เริ่มต้น", 299_00, 30),
    Plan("pro", "มือโปร", 990_00, 120),
    Plan("studio", "สตูดิโอ", 2_990_00, 400),
]
CREDIT_PRICE = 15_00  # ราคาเครดิตเติม (สตางค์ต่อเครดิต) แพ็กเกจรายเดือนตกเครดิตละถูกกว่า
CREDIT_PACKS = (10, 30, 100, 300)  # จำนวนเครดิตที่หน้าเว็บให้เลือกซื้อ


class AccountError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def auth_enabled() -> bool:
    return settings.auth_enabled


def billing_enabled() -> bool:
    return settings.auth_enabled and settings.billing_enabled


def plan(plan_id: str) -> Optional[Plan]:
    return next((p for p in PLANS if p.id == plan_id), None)


# ---------------------------------------------------------------- ฐานข้อมูล
_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, pw_hash TEXT NOT NULL,
  balance INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions (
  user_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, minutes_left INTEGER NOT NULL,
  started_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, kind TEXT NOT NULL,
  amount INTEGER NOT NULL DEFAULT 0, minutes INTEGER NOT NULL DEFAULT 0, ref TEXT, note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id, id);
CREATE TABLE IF NOT EXISTS topups (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, amount INTEGER NOT NULL, provider TEXT NOT NULL,
  status TEXT NOT NULL, created_at REAL NOT NULL, paid_at REAL);
"""


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(settings.data_dir / "accounts.db", check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        if "credits" not in {r["name"] for r in _conn.execute("PRAGMA table_info(ledger)")}:
            _conn.execute("ALTER TABLE ledger ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        _migrate(_conn)
    return _conn


def _migrate(db: sqlite3.Connection) -> None:
    """ฐานข้อมูลรุ่นก่อนเก็บยอดเป็นเงินบาท (users.balance): แปลงเป็นเครดิตเติมตามราคาเครดิต"""
    cols = lambda t: {r["name"] for r in db.execute(f"PRAGMA table_info({t})")}
    if "credits" not in cols("users"):
        db.execute("ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        for u in db.execute("SELECT id, balance FROM users WHERE balance > 0").fetchall():
            n = u["balance"] // CREDIT_PRICE
            db.execute("UPDATE users SET credits = ?, balance = 0 WHERE id = ?", (n, u["id"]))
            db.execute("INSERT INTO ledger (user_id, kind, credits, note, created_at) VALUES (?, 'adjust', ?, ?, ?)",
                       (u["id"], n, f"แปลงเงิน {u['balance'] / 100:,.0f} บาทเป็นเครดิต", time.time()))
    if "credits" not in cols("topups"):
        db.execute("ALTER TABLE topups ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE topups ADD COLUMN plan_id TEXT")


class _tx:
    """ธุรกรรมเดียว (ล็อกทั้งโปรเซส + BEGIN IMMEDIATE) ยอดเงินกับสมุดบัญชีเปลี่ยนพร้อมกันเสมอ"""
    def __enter__(self) -> sqlite3.Connection:
        _lock.acquire()
        self.db = _db()
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, *_):
        try:
            self.db.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            _lock.release()


def _read(sql: str, *args) -> list[sqlite3.Row]:
    with _lock:
        return _db().execute(sql, args).fetchall()


# ---------------------------------------------------------------- ผู้ใช้และการล็อกอิน (บัญชี Google เท่านั้น)
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_admin(email: str) -> bool:
    return email.lower() in settings.admin_emails


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "admin": is_admin(row["email"]),
            "credits": row["credits"]}


def _verify_google(credential: str) -> dict:
    """ตรวจ ID token จากปุ่ม "เข้าสู่ระบบด้วย Google" กับ Google คืนข้อมูลในโทเคน (email, name, ...)"""
    if not settings.google_client_id:
        raise AccountError(503, "ยังไม่ได้ตั้ง GOOGLE_CLIENT_ID เข้าสู่ระบบด้วย Google ไม่ได้")
    try:
        r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=10)
    except requests.RequestException:
        raise AccountError(502, "ติดต่อ Google ไม่ได้ ลองใหม่อีกครั้ง")
    info = r.json() if r.ok else {}
    if (info.get("aud") != settings.google_client_id or info.get("iss") not in GOOGLE_ISSUERS
            or float(info.get("exp", 0)) < time.time()):
        raise AccountError(401, "ยืนยันบัญชี Google ไม่สำเร็จ ลองใหม่อีกครั้ง")
    if info.get("email_verified") not in (True, "true") or not info.get("email"):
        raise AccountError(401, "บัญชี Google นี้ยังไม่ได้ยืนยันอีเมล")
    return info


def google_login(credential: str) -> dict:
    """เข้าสู่ระบบด้วย Google ครั้งแรกสร้างบัญชีให้เลย (สมัครกับล็อกอินคือขั้นเดียวกัน)
    คืน {token, user} token ส่งกลับมาใน header X-User-Token (หน้าเว็บเก็บไว้ในคุกกี้ httpOnly)"""
    info = _verify_google(credential)
    email = info["email"].strip().lower()
    token = secrets.token_urlsafe(32)
    with _tx() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            uid = secrets.token_hex(8)
            db.execute("INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (?, ?, ?, '', ?)",
                       (uid, email, (info.get("name") or email.split("@")[0])[:80], time.time()))
            row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                   (_token_hash(token), row["id"], time.time() + SESSION_DAYS * 86400))
    return {"token": token, "user": public_user(row)}


def logout(token: str) -> None:
    with _tx() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_by_token(token: Optional[str]) -> Optional[sqlite3.Row]:
    if not token:
        return None
    rows = _read("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                 "WHERE s.token_hash = ? AND s.expires_at > ?", _token_hash(token), time.time())
    return rows[0] if rows else None


def user_by_id(uid: str) -> Optional[sqlite3.Row]:
    rows = _read("SELECT * FROM users WHERE id = ?", uid)
    return rows[0] if rows else None


def all_users() -> list[dict]:
    """สำหรับหน้าผู้ดูแล: ผู้ใช้ทุกคนพร้อมเครดิตและแพ็กเกจ"""
    with _lock:
        db = _db()
        rows = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [{**public_user(r), "created_at": r["created_at"],
                 "subscription": dict(sub) if (sub := _subscription(db, r["id"])) else None} for r in rows]


# ---------------------------------------------------------------- เครดิตและแพ็กเกจ
def _log(db, uid: str, kind: str, credits: int = 0, minutes: int = 0, amount: int = 0,
         ref: Optional[str] = None, note: str = ""):
    """credits = เครดิตเติมที่เปลี่ยน, minutes = เครดิตแพ็กเกจที่เปลี่ยน, amount = เงินที่จ่าย (สตางค์ บันทึกไว้ดู)"""
    db.execute("INSERT INTO ledger (user_id, kind, credits, minutes, amount, ref, note, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uid, kind, credits, minutes, amount, ref, note, time.time()))


def _subscription(db, uid: str) -> Optional[sqlite3.Row]:
    row = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (uid,)).fetchone()
    return row if row and row["expires_at"] > time.time() else None


def wallet(uid: str) -> dict:
    with _lock:
        db = _db()
        u = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
        sub = _subscription(db, uid)
        ledger = db.execute("SELECT kind, credits, minutes, amount, ref, note, created_at FROM ledger "
                            "WHERE user_id = ? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    return {
        "credits": u["credits"] if u else 0,
        "subscription": dict(sub) if sub else None,
        "credit_price": CREDIT_PRICE,
        "ledger": [dict(r) for r in ledger],
    }


def credit(uid: str, credits: int, kind: str = "topup", amount: int = 0, ref: Optional[str] = None,
           note: str = "") -> None:
    """เพิ่ม (หรือหักถ้าติดลบ) เครดิตเติม: ชำระเงินสำเร็จ หรือผู้ดูแลให้"""
    with _tx() as db:
        u = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        if u["credits"] + credits < 0:
            raise AccountError(400, f"หักได้ไม่เกิน {u['credits']} เครดิต")
        db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (credits, uid))
        _log(db, uid, kind, credits=credits, amount=amount, ref=ref, note=note)


def _activate(db, uid: str, p: Plan, kind: str, amount: int, note: str) -> None:
    """เริ่มแพ็กเกจใหม่วันนี้ เครดิตแพ็กเกจที่เหลือของรอบเดิมไม่ทบ"""
    now = time.time()
    db.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?, ?, ?, ?)",
               (uid, p.id, p.minutes, now, now + p.days * 86400))
    _log(db, uid, kind, minutes=p.minutes, amount=amount, ref=p.id, note=note)


def grant_plan(uid: str, plan_id: str, admin_email: str) -> None:
    """ผู้ดูแลให้แพ็กเกจโดยไม่ต้องชำระ (รับโอนนอกระบบ ชดเชย ฯลฯ)"""
    p = plan(plan_id)
    if p is None:
        raise AccountError(404, "ไม่พบแพ็กเกจนี้")
    with _tx() as db:
        if db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone() is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        _activate(db, uid, p, "adjust", 0, f"แพ็กเกจ{p.name} {p.minutes} เครดิต ให้โดย {admin_email}")


def _exempt(db, uid: str) -> bool:
    """ผู้ดูแลระบบพากย์ได้ไม่จำกัด ไม่ต้องมีเครดิตหรือแพ็กเกจ"""
    u = db.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
    return u is not None and is_admin(u["email"])


def job_minutes(seconds: float) -> int:
    return max(1, math.ceil(seconds / 60))


def can_start(uid: str) -> None:
    """เช็กก่อนรับงาน: มีเครดิตอย่างน้อยหนึ่งเครดิต (ยังไม่รู้ความยาวคลิปจากลิงก์)"""
    if not billing_enabled():
        return
    with _lock:
        db = _db()
        if _exempt(db, uid):
            return
        sub = _subscription(db, uid)
        u = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
    if (sub and sub["minutes_left"] > 0) or (u and u["credits"] > 0):
        return
    raise AccountError(402, "เครดิตหมด ซื้อแพ็กเกจหรือเติมเครดิตก่อนส่งงาน")


def charge_job(uid: str, job_id: str, seconds: float) -> None:
    """ตัดเครดิตของงานเมื่อรู้ความยาวคลิป (ต้นขั้นวิเคราะห์) ตัดครั้งเดียวต่องาน พากย์ซ้ำหรือแก้บทไม่ตัดเพิ่ม"""
    if not billing_enabled():
        return
    need = job_minutes(seconds)
    with _tx() as db:
        if _exempt(db, uid) or db.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'charge' AND ref = ?",
                                          (uid, job_id)).fetchone():
            return
        sub = _subscription(db, uid)
        from_plan = min(need, sub["minutes_left"]) if sub else 0
        rest = need - from_plan
        have = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()["credits"]
        if rest > have:
            raise AccountError(402, f"คลิปนี้ยาว {need} นาที ใช้ {need} เครดิต แต่มีเพียง {from_plan + have} เครดิต "
                                    f"(ขาด {rest - have} เครดิต)")
        if from_plan:
            db.execute("UPDATE subscriptions SET minutes_left = minutes_left - ? WHERE user_id = ?", (from_plan, uid))
        if rest:
            db.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (rest, uid))
        _log(db, uid, "charge", credits=-rest, minutes=-from_plan, ref=job_id, note=f"งานพากย์ {need} นาที")


def refund_job(uid: str, job_id: str) -> None:
    """คืนเครดิตของงานที่วิเคราะห์ไม่สำเร็จ (ครั้งเดียวต่องาน) เครดิตแพ็กเกจคืนเฉพาะถ้าแพ็กเกจยังไม่หมดอายุ"""
    with _tx() as db:
        charge = db.execute("SELECT credits, minutes FROM ledger WHERE user_id = ? AND kind = 'charge' AND ref = ?",
                            (uid, job_id)).fetchone()
        if charge is None or db.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'refund' AND ref = ?",
                                        (uid, job_id)).fetchone():
            return
        minutes = -charge["minutes"] if charge["minutes"] and _subscription(db, uid) else 0
        if minutes:
            db.execute("UPDATE subscriptions SET minutes_left = minutes_left + ? WHERE user_id = ?", (minutes, uid))
        db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (-charge["credits"], uid))
        _log(db, uid, "refund", credits=-charge["credits"], minutes=minutes, ref=job_id, note="คืนเครดิต งานไม่สำเร็จ")


# ---------------------------------------------------------------- ชำระเงิน (ซื้อเครดิตเติม หรือแพ็กเกจ)
def _start_payment(uid: str, amount: int, credits: int = 0, plan_id: Optional[str] = None) -> dict:
    """PAYMENT_PROVIDER=mock จ่ายสำเร็จทันที (ใช้ทดสอบ) ยังไม่ได้เชื่อมช่องทางชำระเงินจริง"""
    provider = settings.payment_provider
    if provider != "mock":
        raise AccountError(503, "ยังไม่ได้เชื่อมช่องทางชำระเงิน ติดต่อผู้ดูแลเพื่อเติมเครดิต")
    tid = secrets.token_hex(8)
    with _tx() as db:
        db.execute("INSERT INTO topups (id, user_id, amount, provider, status, created_at, credits, plan_id) "
                   "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)", (tid, uid, amount, provider, time.time(), credits, plan_id))
    mark_paid(tid)
    return {"id": tid, "status": "paid", "amount": amount}


def buy_credits(uid: str, credits: int) -> dict:
    if not TOPUP_MIN <= credits <= TOPUP_MAX:
        raise AccountError(400, f"ซื้อได้ครั้งละ {TOPUP_MIN:,}–{TOPUP_MAX:,} เครดิต")
    return _start_payment(uid, credits * CREDIT_PRICE, credits=credits)


def subscribe(uid: str, plan_id: str) -> dict:
    p = plan(plan_id)
    if p is None:
        raise AccountError(404, "ไม่พบแพ็กเกจนี้")
    return _start_payment(uid, p.price, plan_id=p.id)


def mark_paid(topup_id: str) -> None:
    """ช่องทางชำระเงินแจ้งว่าจ่ายแล้ว (webhook) ให้เครดิตหรือเริ่มแพ็กเกจครั้งเดียวต่อรายการ"""
    with _tx() as db:
        t = db.execute("SELECT * FROM topups WHERE id = ?", (topup_id,)).fetchone()
        if t is None or t["status"] == "paid":
            return
        db.execute("UPDATE topups SET status = 'paid', paid_at = ? WHERE id = ?", (time.time(), topup_id))
        p = plan(t["plan_id"]) if t["plan_id"] else None
        if p:
            _activate(db, t["user_id"], p, "subscribe", t["amount"], f"แพ็กเกจ{p.name} {p.minutes} เครดิต")
        else:
            db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (t["credits"], t["user_id"]))
            _log(db, t["user_id"], "topup", credits=t["credits"], amount=t["amount"], ref=topup_id,
                 note=f"ซื้อ {t['credits']:,} เครดิต ผ่าน {t['provider']}")
