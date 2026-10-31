"""บัญชีผู้ใช้ กระเป๋าเงิน และแพ็กเกจ เก็บใน data/accounts.db (SQLite)

ยังไม่เปิดใช้งาน: AUTH_ENABLED=1 เปิดระบบล็อกอิน (ทุกคำขอต้องล็อกอิน เห็นเฉพาะงานของตัวเอง)
BILLING_ENABLED=1 เปิดกระเป๋าเงินและแพ็กเกจ (ตัดนาทีเมื่อเริ่มวิเคราะห์งาน) ต้องเปิดคู่กับ AUTH_ENABLED

เงินเก็บเป็นสตางค์ (จำนวนเต็ม) นาทีพากย์ตัดจากแพ็กเกจก่อน ที่เหลือหักจากกระเป๋าตามราคาต่อนาที
ทุกการเปลี่ยนยอดลงสมุดบัญชี (ledger) ref ของการตัดและคืนนาทีเป็น id งาน กันตัดซ้ำ
"""
import hashlib
import hmac
import math
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .config import settings

SESSION_DAYS = 30
MIN_PASSWORD = 8
TOPUP_MIN, TOPUP_MAX = 100_00, 50_000_00  # สตางค์


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price: int  # สตางค์ต่อรอบ
    minutes: int  # นาทีพากย์ต่อรอบ
    days: int = 30


# ราคาตั้งต้น ปรับได้ก่อนเปิดใช้งานจริง
PLANS = [
    Plan("starter", "เริ่มต้น", 299_00, 30),
    Plan("pro", "มือโปร", 990_00, 120),
    Plan("studio", "สตูดิโอ", 2_990_00, 400),
]
PAYG_PER_MINUTE = 15_00  # ไม่มีแพ็กเกจหรือนาทีในแพ็กเกจหมด หักจากกระเป๋านาทีละเท่านี้


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
    return _conn


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


# ---------------------------------------------------------------- ผู้ใช้และการล็อกอิน
def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def _check_password(password: str, stored: str) -> bool:
    _, salt, _ = stored.split("$")
    return hmac.compare_digest(_hash_password(password, bytes.fromhex(salt)), stored)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_admin(email: str) -> bool:
    return email.lower() in settings.admin_emails


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "admin": is_admin(row["email"]),
            "balance": row["balance"]}


def signup(email: str, password: str, name: str) -> dict:
    email = email.strip().lower()
    if "@" not in email or len(email) > 200:
        raise AccountError(400, "อีเมลไม่ถูกต้อง")
    if len(password) < MIN_PASSWORD:
        raise AccountError(400, f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD} ตัว")
    with _tx() as db:
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AccountError(409, "อีเมลนี้สมัครไว้แล้ว เข้าสู่ระบบแทนได้เลย")
        uid = secrets.token_hex(8)
        db.execute("INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                   (uid, email, name.strip() or email.split("@")[0], _hash_password(password), time.time()))
    return login(email, password)


def login(email: str, password: str) -> dict:
    """คืน {token, user} token ส่งกลับมาใน header X-User-Token (หน้าเว็บเก็บไว้ในคุกกี้ httpOnly)"""
    rows = _read("SELECT * FROM users WHERE email = ?", email.strip().lower())
    if not rows or not _check_password(password, rows[0]["pw_hash"]):
        raise AccountError(401, "อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    token = secrets.token_urlsafe(32)
    with _tx() as db:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                   (_token_hash(token), rows[0]["id"], time.time() + SESSION_DAYS * 86400))
    return {"token": token, "user": public_user(rows[0])}


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


def change_password(uid: str, old: str, new: str) -> None:
    u = user_by_id(uid)
    if u is None or not _check_password(old, u["pw_hash"]):
        raise AccountError(400, "รหัสผ่านเดิมไม่ถูกต้อง")
    if len(new) < MIN_PASSWORD:
        raise AccountError(400, f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD} ตัว")
    with _tx() as db:
        db.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (_hash_password(new), uid))


def all_users() -> list[dict]:
    return [public_user(r) for r in _read("SELECT * FROM users ORDER BY created_at DESC")]


# ---------------------------------------------------------------- กระเป๋าเงินและแพ็กเกจ
def _log(db, uid: str, kind: str, amount: int = 0, minutes: int = 0, ref: Optional[str] = None, note: str = ""):
    db.execute("INSERT INTO ledger (user_id, kind, amount, minutes, ref, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (uid, kind, amount, minutes, ref, note, time.time()))


def _subscription(db, uid: str) -> Optional[sqlite3.Row]:
    row = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (uid,)).fetchone()
    return row if row and row["expires_at"] > time.time() else None


def wallet(uid: str) -> dict:
    with _lock:
        db = _db()
        u = db.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()
        sub = _subscription(db, uid)
        ledger = db.execute("SELECT kind, amount, minutes, ref, note, created_at FROM ledger WHERE user_id = ? "
                            "ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    return {
        "balance": u["balance"] if u else 0,
        "subscription": dict(sub) if sub else None,
        "payg_per_minute": PAYG_PER_MINUTE,
        "ledger": [dict(r) for r in ledger],
    }


def credit(uid: str, amount: int, kind: str = "topup", ref: Optional[str] = None, note: str = "") -> None:
    """เติมเงินเข้ากระเป๋า (ชำระเงินสำเร็จ หรือผู้ดูแลปรับยอด)"""
    with _tx() as db:
        if db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, uid)).rowcount != 1:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        _log(db, uid, kind, amount, ref=ref, note=note)


def subscribe(uid: str, plan_id: str) -> dict:
    """ซื้อแพ็กเกจด้วยเงินในกระเป๋า นาทีที่เหลือของรอบเดิมไม่ทบ แพ็กเกจใหม่เริ่มนับวันนี้"""
    p = plan(plan_id)
    if p is None:
        raise AccountError(404, "ไม่พบแพ็กเกจนี้")
    with _tx() as db:
        u = db.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        if u["balance"] < p.price:
            raise AccountError(402, f"เงินในกระเป๋าไม่พอ ต้องการ {p.price / 100:,.0f} บาท เติมเงินก่อน")
        now = time.time()
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (p.price, uid))
        db.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?, ?, ?, ?)",
                   (uid, p.id, p.minutes, now, now + p.days * 86400))
        _log(db, uid, "subscribe", -p.price, p.minutes, ref=p.id, note=f"แพ็กเกจ{p.name} {p.minutes} นาที")
    return wallet(uid)


def job_minutes(seconds: float) -> int:
    return max(1, math.ceil(seconds / 60))


def can_start(uid: str) -> None:
    """เช็กก่อนรับงาน: มีนาทีในแพ็กเกจหรือเงินพออย่างน้อยหนึ่งนาที (ยังไม่รู้ความยาวคลิปจากลิงก์)"""
    if not billing_enabled():
        return
    with _lock:
        db = _db()
        sub = _subscription(db, uid)
        u = db.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()
    if (sub and sub["minutes_left"] > 0) or (u and u["balance"] >= PAYG_PER_MINUTE):
        return
    raise AccountError(402, "นาทีพากย์หมด ซื้อแพ็กเกจหรือเติมเงินก่อนส่งงาน")


def charge_job(uid: str, job_id: str, seconds: float) -> None:
    """ตัดนาทีของงานเมื่อรู้ความยาวคลิป (ต้นขั้นวิเคราะห์) ตัดครั้งเดียวต่องาน พากย์ซ้ำหรือแก้บทไม่ตัดเพิ่ม"""
    if not billing_enabled():
        return
    need = job_minutes(seconds)
    with _tx() as db:
        if db.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'charge' AND ref = ?",
                      (uid, job_id)).fetchone():
            return
        sub = _subscription(db, uid)
        from_plan = min(need, sub["minutes_left"]) if sub else 0
        rest = need - from_plan
        cost = rest * PAYG_PER_MINUTE
        balance = db.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()["balance"]
        if cost > balance:
            raise AccountError(402, f"คลิปนี้ยาว {need} นาที นาทีในแพ็กเกจและเงินในกระเป๋าไม่พอ "
                                    f"(ขาด {(cost - balance) / 100:,.0f} บาท)")
        if from_plan:
            db.execute("UPDATE subscriptions SET minutes_left = minutes_left - ? WHERE user_id = ?", (from_plan, uid))
        if cost:
            db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (cost, uid))
        _log(db, uid, "charge", -cost, -from_plan, ref=job_id,
             note=f"งานพากย์ {need} นาที" + (f" (แพ็กเกจ {from_plan} นาที)" if from_plan else ""))


def refund_job(uid: str, job_id: str) -> None:
    """คืนนาทีและเงินของงานที่วิเคราะห์ไม่สำเร็จ (ครั้งเดียวต่องาน)"""
    with _tx() as db:
        charge = db.execute("SELECT amount, minutes FROM ledger WHERE user_id = ? AND kind = 'charge' AND ref = ?",
                            (uid, job_id)).fetchone()
        if charge is None or db.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'refund' AND ref = ?",
                                        (uid, job_id)).fetchone():
            return
        if charge["minutes"] and _subscription(db, uid):
            db.execute("UPDATE subscriptions SET minutes_left = minutes_left + ? WHERE user_id = ?",
                       (-charge["minutes"], uid))
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (-charge["amount"], uid))
        _log(db, uid, "refund", -charge["amount"], -charge["minutes"], ref=job_id, note="คืนนาที งานไม่สำเร็จ")


# ---------------------------------------------------------------- เติมเงิน
def create_topup(uid: str, amount: int) -> dict:
    """เริ่มเติมเงิน PAYMENT_PROVIDER=mock เติมทันที (ใช้ทดสอบ) ยังไม่ได้เชื่อมช่องทางชำระเงินจริง"""
    if not TOPUP_MIN <= amount <= TOPUP_MAX:
        raise AccountError(400, f"เติมได้ครั้งละ {TOPUP_MIN // 100:,}–{TOPUP_MAX // 100:,} บาท")
    provider = settings.payment_provider
    if provider != "mock":
        raise AccountError(503, "ยังไม่ได้เชื่อมช่องทางชำระเงิน")
    tid = secrets.token_hex(8)
    with _tx() as db:
        db.execute("INSERT INTO topups VALUES (?, ?, ?, ?, 'pending', ?, NULL)", (tid, uid, amount, provider, time.time()))
    mark_paid(tid)
    return {"id": tid, "status": "paid", "amount": amount}


def mark_paid(topup_id: str) -> None:
    """ช่องทางชำระเงินแจ้งว่าจ่ายแล้ว (webhook) เติมเงินครั้งเดียวต่อรายการ"""
    with _tx() as db:
        t = db.execute("SELECT * FROM topups WHERE id = ?", (topup_id,)).fetchone()
        if t is None or t["status"] == "paid":
            return
        db.execute("UPDATE topups SET status = 'paid', paid_at = ? WHERE id = ?", (time.time(), topup_id))
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (t["amount"], t["user_id"]))
        _log(db, t["user_id"], "topup", t["amount"], ref=topup_id, note=f"เติมเงินผ่าน {t['provider']}")
