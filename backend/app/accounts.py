"""บัญชีผู้ใช้ เครดิต และแพ็กเกจ
DB_BACKEND=postgres เก็บใน schema studio บน Postgres (pgstore.py, ต้องมี DATABASE_URL)
ไม่งั้นเก็บใน data/accounts.db (SQLite)

AUTH_ENABLED=1 เปิดระบบล็อกอิน (ทุกคำขอต้องล็อกอิน เห็นเฉพาะงานของตัวเอง) สมัครและเข้าสู่ระบบด้วยบัญชี Google
(GOOGLE_CLIENT_ID) เท่านั้น ไม่มีรหัสผ่าน
BILLING_ENABLED=1 เปิดเครดิตและแพ็กเกจ (ตัดเครดิตเมื่อเริ่มวิเคราะห์งาน) ต้องเปิดคู่กับ AUTH_ENABLED
ผู้ดูแลระบบ (ADMIN_EMAILS) พากย์ได้ไม่จำกัด ไม่ถูกตัดเครดิต
PAYMENT_PROVIDER=slip ให้ผู้ใช้โอนตามยอดแล้วแนบสลิป Typhoon OCR อ่านยอด (slip_ocr.py) ตรงจึงเติมให้
ไม่ตรงหรืออ่านไม่ได้เข้าคิวผู้ดูแล  PAYMENT_PROVIDER=mock เติมทันทีสำหรับทดสอบ
PAYMENT_PROVIDER=stripe เปิด Stripe Checkout (stripe_pay.py) แล้ว webhook เรียก mark_paid

1 เครดิต = คลิป 1 นาที คิดตามความยาวจริงละเอียดถึงทศนิยม 2 ตำแหน่ง (ปัดขึ้น) มีสองแบบ:
- เครดิตแพ็กเกจ (subscriptions.minutes_left) ได้จากแพ็กเกจรายเดือน หมดอายุพร้อมแพ็กเกจ ใช้ก่อน
- เครดิตเติม (users.credits) ซื้อเพิ่มหรือผู้ดูแลให้ ไม่หมดอายุ
เงินเก็บเป็นสตางค์ (จำนวนเต็ม) ใช้แค่ตอนชำระเงิน
ในฐานข้อมูลเก็บเครดิตเป็นหน่วยย่อย (1 เครดิต = UNIT = 100 หน่วย) เป็นจำนวนเต็ม แปลงเป็นทศนิยมตอนส่งออกเท่านั้น
ทุกการเปลี่ยนยอดลงสมุดบัญชี (ledger) ref ของการตัดและคืนเครดิตเป็น id งาน กันตัดซ้ำ
"""
import hashlib
import json
import logging
import math
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from .config import settings, using_postgres
from .slip_ocr import SlipOcrError, image_mime, read_slip, verdict

log = logging.getLogger("dubbing.accounts")

SESSION_DAYS = 30
TOPUP_MIN, TOPUP_MAX = 5, 2000  # ซื้อเครดิตเติมได้ครั้งละกี่เครดิต
# แคช session ในหน่วยความจำ — ทุกคำขอเคยยิง Postgres (~0.6s จากไทย→EU) แค่เช็คว่าล็อกอินอยู่
_SESSION_TTL = 45.0
_session_cache: dict[str, tuple[float, Optional[dict]]] = {}
_session_cache_lock = threading.Lock()


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price: int  # สตางค์ต่อรอบ (0 = ฟรี)
    minutes: int  # เครดิตต่อรอบ (1 เครดิต = 1 นาที)
    days: int = 30
    max_clip_minutes: float = 60.0
    voices: str = "all"  # standard = เฉพาะเสียงที่แอดมินเพิ่ม (ไม่ใช่นักพากย์), all = ทุกเสียง
    timeline: bool = False
    watermark: bool = False
    free_once: bool = False  # รับได้ครั้งเดียวต่อบัญชี โดยไม่ต้องชำระ
    available: bool = True  # False = ปิดขายชั่วคราว (เช่น อยู่ระหว่างพัฒนา)
    features: tuple = ()

    def public_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "price": self.price, "minutes": self.minutes,
            "days": self.days, "max_clip_minutes": self.max_clip_minutes, "voices": self.voices,
            "timeline": self.timeline, "watermark": self.watermark, "free_once": self.free_once,
            "available": self.available, "features": list(self.features),
        }


def _load_plans() -> list[Plan]:
    from .config import billing_plan_dicts
    out: list[Plan] = []
    for raw in billing_plan_dicts():
        feats = raw.get("features") or []
        out.append(Plan(
            id=str(raw["id"]), name=str(raw["name"]), price=int(raw["price"]),
            minutes=int(raw["minutes"]), days=int(raw.get("days", 30)),
            max_clip_minutes=float(raw.get("max_clip_minutes", 60)),
            voices=str(raw.get("voices", "all")),
            timeline=bool(raw.get("timeline", False)),
            watermark=bool(raw.get("watermark", False)),
            free_once=bool(raw.get("free_once", False)),
            available=bool(raw.get("available", True)),
            features=tuple(str(x) for x in feats),
        ))
    return out


PLANS = _load_plans()
CREDIT_PRICE = settings.credit_price_satang
CREDIT_PACKS = settings.credit_packs
UNIT = 100  # หน่วยย่อยต่อ 1 เครดิต (คิดละเอียด 0.01 เครดิต)
CARD_BONUS = 0  # เลิกโบนัสผูกบัตร — ใช้แพ็กทดลองแทน
VOICE_APPROVE_BONUS = 5  # เครดิตเติมเมื่อเสียงนักพากย์ถูกอนุมัติขึ้นคลัง (ครั้งแรกต่อเสียง)
# แพ็กเกจเก่าที่ยังมีใน subscriptions → ใช้สิทธิ์เทียบเท่าแพ็กใหม่
_LEGACY_PLAN_FEATURES = {"studio": "pro"}


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


def _feature_plan(plan_id: Optional[str]) -> Optional[Plan]:
    """แผนสำหรับอ่านสิทธิ์ (รวมแม็ปแพ็กเก่า เช่น studio → pro)"""
    if not plan_id:
        return None
    p = plan(plan_id)
    if p:
        return p
    mapped = _LEGACY_PLAN_FEATURES.get(plan_id)
    return plan(mapped) if mapped else None


def trial_claimed(uid: str) -> bool:
    """เคยรับแพ็กทดลองแล้วหรือยัง (ledger kind=trial หรือเคยเป็น trial)"""
    rows = _read(
        "SELECT 1 AS ok FROM ledger WHERE user_id = ? AND (kind = 'trial' OR (kind IN ('subscribe','adjust') AND ref = 'trial')) LIMIT 1",
        uid)
    if rows:
        return True
    rows = _read("SELECT 1 AS ok FROM subscriptions WHERE user_id = ? AND plan_id = 'trial' LIMIT 1", uid)
    return bool(rows)


def entitlements(uid: Optional[str]) -> dict:
    """สิทธิ์ตามแพ็กเกจปัจจุบัน (แอดมิน = ไม่จำกัด)"""
    base = {
        "plan_id": None, "plan_name": None, "max_clip_minutes": 0.0,
        "voices": "none", "timeline": False, "watermark": True,
        "can_topup": False, "trial_available": False, "has_plan": False,
    }
    if not billing_enabled() or not uid:
        return {**base, "max_clip_minutes": 60.0, "voices": "all", "timeline": True, "watermark": False}
    with _lock:
        db = _db()
        u = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            return base
        if is_admin(u):
            return {
                "plan_id": "admin", "plan_name": "ผู้ดูแล", "max_clip_minutes": 24 * 60,
                "voices": "all", "timeline": True, "watermark": False,
                "can_topup": True, "trial_available": False, "has_plan": True,
            }
        sub = _subscription(db, uid)
        claimed = bool(db.execute(
            "SELECT 1 FROM ledger WHERE user_id = ? AND (kind = 'trial' OR ref = 'trial') LIMIT 1",
            (uid,)).fetchone())
    if sub is None:
        return {**base, "trial_available": not claimed}
    fp = _feature_plan(sub["plan_id"]) or Plan(
        id=sub["plan_id"], name=sub["plan_id"], price=0, minutes=0,
        max_clip_minutes=30, voices="all", timeline=False, watermark=False)
    return {
        "plan_id": sub["plan_id"], "plan_name": fp.name,
        "max_clip_minutes": float(fp.max_clip_minutes),
        "voices": fp.voices, "timeline": bool(fp.timeline), "watermark": bool(fp.watermark),
        "can_topup": True, "trial_available": False, "has_plan": True,
    }


def check_clip_duration(uid: Optional[str], seconds: float) -> None:
    """ตรวจความยาวคลิปตามสิทธิ์แพ็กเกจ เกินแล้วโยน 402 พร้อมข้อความอัปเกรด"""
    if not billing_enabled() or not uid:
        return
    ent = entitlements(uid)
    if ent.get("plan_id") == "admin":
        return
    max_m = float(ent.get("max_clip_minutes") or 0)
    if max_m <= 0:
        raise AccountError(402, "ยังไม่มีแพ็กเกจ รับทดลองฟรีหรือซื้อแพ็กเกจที่หน้าโปรโมชันก่อนส่งคลิป")
    if seconds > max_m * 60 + 0.5:
        length = f"{int(seconds // 60)}:{int(seconds % 60):02d}"
        raise AccountError(
            402,
            f"คลิปยาว {length} นาที เกินสิทธิ์แพ็กเกจ{ent.get('plan_name') or ''} "
            f"(ยาวสุด {max_m:g} นาที) อัปเกรดที่หน้าโปรโมชัน")


def require_timeline(uid: Optional[str]) -> None:
    """นำเข้าไทม์ไลน์ปิดชั่วคราว (อยู่ระหว่างพัฒนา) — แอดมินยังใช้ทดสอบได้"""
    if not billing_enabled() or not uid:
        return
    ent = entitlements(uid)
    if ent.get("plan_id") == "admin":
        return
    raise AccountError(503, "นำเข้าไทม์ไลน์อยู่ระหว่างพัฒนา ยังไม่เปิดให้ใช้")


def voice_allowed(uid: Optional[str], voice_id: str, actor_voice_ids: set[str],
                  ent: Optional[dict] = None, *, owner_id: Optional[str] = None,
                  actor_review: Optional[str] = None) -> bool:
    """แพ็กทดลอง (voices=standard) ใช้ได้เฉพาะเสียงที่แอดมินเพิ่ม ไม่ใช่เสียงนักพากย์
    เจ้าของเห็นและใช้เสียงตัวเองได้เสมอ (แม้ยังรอตรวจ)
    actor_review รับจาก list/เลือกเสียง แต่แพ็กทดลองไม่เปิดเสียงนักพากย์ถึงอนุมัติแล้ว
    ent = สิทธิ์ที่คำนวณไว้แล้ว (ส่งมาจาก list_voices เพื่อไม่ยิงฐานข้อมูลซ้ำทุกเสียง)"""
    _ = actor_review
    if not billing_enabled() or not uid:
        return True
    if owner_id and owner_id == uid:
        return True
    if ent is None:
        ent = entitlements(uid)
    if ent.get("voices") == "all" or ent.get("plan_id") == "admin":
        return True
    if ent.get("voices") == "standard":
        return voice_id not in actor_voice_ids
    return False


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
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, provider TEXT NOT NULL, ref TEXT NOT NULL, brand TEXT NOT NULL,
  last4 TEXT NOT NULL, exp_month INTEGER NOT NULL, exp_year INTEGER NOT NULL, fingerprint TEXT NOT NULL,
  created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS cards_user ON cards(user_id);
"""


def _db():
    if using_postgres():
        from . import pgstore
        return pgstore.connect()
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
    from .pgstore import is_pg
    if is_pg(db):
        return  # schema studio สร้างครบจาก migration แล้ว และข้อมูลที่ย้ายมาคูณหน่วยย่อยไว้แล้ว
    cols = lambda t: {r["name"] for r in db.execute(f"PRAGMA table_info({t})")}
    if "credits" not in cols("users"):
        db.execute("ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        for u in db.execute("SELECT id, balance FROM users WHERE balance > 0").fetchall():
            n = u["balance"] // CREDIT_PRICE
            db.execute("UPDATE users SET credits = ?, balance = 0 WHERE id = ?", (n, u["id"]))
            db.execute("INSERT INTO ledger (user_id, kind, credits, note, created_at) VALUES (?, 'adjust', ?, ?, ?)",
                       (u["id"], n, f"แปลงเงิน {u['balance'] / 100:,.0f} บาทเป็นเครดิต", time.time()))
    if "admin" not in cols("users"):
        db.execute("ALTER TABLE users ADD COLUMN admin INTEGER NOT NULL DEFAULT 0")
    if db.execute("PRAGMA user_version").fetchone()[0] < 1:
        # เครดิตเป็นทศนิยมได้: ยอดเดิม (เครดิตเต็ม) คูณเป็นหน่วยย่อย topups.credits ยังเป็นเครดิตเต็มที่ซื้อ
        db.execute("BEGIN IMMEDIATE")
        db.execute(f"UPDATE users SET credits = credits * {UNIT}")
        db.execute(f"UPDATE subscriptions SET minutes_left = minutes_left * {UNIT}")
        db.execute(f"UPDATE ledger SET credits = credits * {UNIT}, minutes = minutes * {UNIT}")
        db.execute("PRAGMA user_version = 1")
        db.execute("COMMIT")
    if "credits" not in cols("topups"):
        db.execute("ALTER TABLE topups ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE topups ADD COLUMN plan_id TEXT")
    if "profile_at" not in cols("users"):  # ข้อมูลเบื้องต้นที่ผู้ใช้กรอกหลังล็อกอินครั้งแรก (save_profile)
        for col in ("full_name", "phone", "account_type", "company", "use_case"):
            db.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE users ADD COLUMN profile_at REAL")
    if "deleted_at" not in cols("users"):  # ปิดบัญชี (close_account): ลบข้อมูลส่วนตัวแล้ว เหลือแถวไว้ผูกกับสมุดบัญชี
        db.execute("ALTER TABLE users ADD COLUMN deleted_at REAL")
    if "notify_email" not in cols("users"):  # อีเมลแจ้งเมื่องานรอตรวจบท พากย์เสร็จ หรือล้มเหลว (notify.py)
        db.execute("ALTER TABLE users ADD COLUMN notify_email INTEGER NOT NULL DEFAULT 1")
    # สลิปโอน (PAYMENT_PROVIDER=slip): ไฟล์รูปอยู่ใน data/slips/ แฮชกันใช้สลิปเดิมซ้ำอยู่ใน slip_uses
    if "note" not in cols("topups"):
        db.execute("ALTER TABLE topups ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    for col in ("slip_hash", "ocr_text", "ocr_json"):
        if col not in cols("topups"):
            db.execute(f"ALTER TABLE topups ADD COLUMN {col} TEXT")
    if "ocr_amount" not in cols("topups"):
        db.execute("ALTER TABLE topups ADD COLUMN ocr_amount INTEGER")
    if "provider_ref" not in cols("topups"):  # Stripe Checkout Session id หรืออ้างอิงผู้ให้บริการ
        db.execute("ALTER TABLE topups ADD COLUMN provider_ref TEXT")
    db.execute("CREATE TABLE IF NOT EXISTS slip_uses ("
               "hash TEXT PRIMARY KEY, topup_id TEXT NOT NULL, created_at REAL NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS feedback ("
        "id TEXT PRIMARY KEY, user_id TEXT, email TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', "
        "category TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, job_id TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'open', admin_note TEXT NOT NULL DEFAULT '', "
        "created_at REAL NOT NULL, resolved_at REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS feedback_status_created ON feedback(status, created_at)")


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
    # อ่านขนานได้ผ่าน pool — ไม่รอ accounts._lock (กันหน้าเว็บยิงพร้อมกันแล้วคิว 10–20 วิ)
    if using_postgres():
        from . import pgstore
        with pgstore.borrow() as db:
            return db.execute(sql, args).fetchall()
    with _lock:
        return _db().execute(sql, args).fetchall()


# ---------------------------------------------------------------- ผู้ใช้และการล็อกอิน (บัญชี Google เท่านั้น)
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def credits_out(units: int) -> float:
    """หน่วยย่อย → เครดิต (ทศนิยม 2 ตำแหน่ง) สำหรับส่งออกทาง API"""
    return round(units / UNIT, 2)


def fmt_credits(units: int) -> str:
    """หน่วยย่อย → ข้อความ ทศนิยม 2 ตำแหน่งเสมอ เช่น 1.25, 3.00, 1,200.50"""
    return f"{units / UNIT:,.2f}"


def _sub_out(sub) -> Optional[dict]:
    return {**dict(sub), "minutes_left": credits_out(sub["minutes_left"])} if sub else None


def is_owner(email: str) -> bool:
    """ผู้ดูแลจาก ADMIN_EMAILS ถอดสิทธิ์ผ่านหน้าเว็บไม่ได้"""
    return email.lower() in settings.admin_emails


def is_admin(user: sqlite3.Row) -> bool:
    """ผู้ดูแลระบบ: อยู่ใน ADMIN_EMAILS หรือผู้ดูแลคนอื่นให้สิทธิ์ (users.admin)"""
    return is_owner(user["email"]) or bool(user["admin"])


def profile_complete(row: sqlite3.Row) -> bool:
    return row["profile_at"] is not None


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "admin": is_admin(row),
            "owner": is_owner(row["email"]), "credits": credits_out(row["credits"]),
            "profile_complete": profile_complete(row), **_consent_out(row["id"]), "notify_email": bool(row["notify_email"]),
            "profile": {k: row[k] for k in ("full_name", "phone", "account_type", "company", "use_case")}}


def _consent_out(uid: str) -> dict:
    from . import consent
    st = consent.status(uid)
    return {"consent_current": st["current"], "marketing": st["marketing"], "consent": {"terms": st["terms"], "privacy": st["privacy"]}}


def consent_current(row: sqlite3.Row) -> bool:
    from . import consent
    return consent.status(row["id"])["current"]


ACCOUNT_TYPES = ("personal", "creator", "business")
_PHONE = re.compile(r"^(0\d{8,9}|\+\d{8,15})$")


def save_profile(uid: str, name: str, full_name: str, phone: str, account_type: str, company: str,
                 use_case: str) -> dict:
    """ข้อมูลเบื้องต้นของผู้ใช้ (ต้องกรอกก่อนใช้งานครั้งแรก แก้ภายหลังได้) คืนข้อมูลผู้ใช้ล่าสุด"""
    full_name, company, use_case = " ".join(full_name.split()), company.strip(), use_case.strip()
    phone = re.sub(r"[\s\-().]", "", phone)
    if len(full_name) < 2:
        raise AccountError(400, "กรอกชื่อ-นามสกุล")
    if not _PHONE.match(phone):
        raise AccountError(400, "เบอร์โทรไม่ถูกต้อง เช่น 0812345678 หรือ +66812345678")
    if account_type not in ACCOUNT_TYPES:
        raise AccountError(400, "เลือกประเภทผู้ใช้")
    if account_type == "business" and not company:
        raise AccountError(400, "กรอกชื่อบริษัทหรือหน่วยงาน")
    with _tx() as db:
        db.execute("UPDATE users SET name = COALESCE(NULLIF(?, ''), name), full_name = ?, phone = ?, account_type = ?, "
                   "company = ?, use_case = ?, profile_at = COALESCE(profile_at, ?) WHERE id = ?",
                   (name.strip()[:80], full_name[:100], phone, account_type,
                    company[:120] if account_type == "business" else "", use_case[:300], time.time(), uid))
        row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None:
        raise AccountError(404, "ไม่พบผู้ใช้นี้")
    _drop_session_cache(user_id=uid)
    return public_user(row)


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


def _cache_session(token_hash: str, user: Optional[dict]) -> None:
    with _session_cache_lock:
        _session_cache[token_hash] = (time.time() + _SESSION_TTL, user)


def _drop_session_cache(token: Optional[str] = None, user_id: Optional[str] = None) -> None:
    with _session_cache_lock:
        if token:
            _session_cache.pop(_token_hash(token), None)
        if user_id:
            dead = [h for h, (_, u) in _session_cache.items() if u and u.get("id") == user_id]
            for h in dead:
                _session_cache.pop(h, None)


def logout(token: str) -> None:
    _drop_session_cache(token=token)
    with _tx() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_by_token(token: Optional[str]) -> Optional[sqlite3.Row]:
    if not token:
        return None
    h = _token_hash(token)
    now = time.time()
    with _session_cache_lock:
        hit = _session_cache.get(h)
        if hit and hit[0] > now:
            return hit[1]  # type: ignore[return-value]
    rows = _read("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                 "WHERE s.token_hash = ? AND s.expires_at > ?", h, now)
    user = dict(rows[0]) if rows else None
    _cache_session(h, user)
    return user  # type: ignore[return-value]


def user_by_id(uid: str) -> Optional[sqlite3.Row]:
    rows = _read("SELECT * FROM users WHERE id = ?", uid)
    return rows[0] if rows else None


def all_users() -> list[dict]:
    """สำหรับหน้าผู้ดูแล: ผู้ใช้ทุกคนพร้อมเครดิตและแพ็กเกจ"""
    with _lock:
        db = _db()
        rows = db.execute("SELECT * FROM users WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()
        return [{**public_user(r), "created_at": r["created_at"],
                 "subscription": _sub_out(_subscription(db, r["id"]))} for r in rows]


def set_admin(uid: str, admin: bool, by: sqlite3.Row) -> None:
    """ผู้ดูแลให้หรือถอดสิทธิ์ผู้ดูแลของคนอื่น ถอดผู้ดูแลจาก ADMIN_EMAILS หรือตัวเองไม่ได้ (กันไม่มีใครเหลือ)"""
    with _tx() as db:
        u = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        if u["id"] == by["id"]:
            raise AccountError(400, "เปลี่ยนสิทธิ์ของตัวเองไม่ได้")
        if not admin and is_owner(u["email"]):
            raise AccountError(400, "ผู้ดูแลหลัก (ADMIN_EMAILS) ถอดสิทธิ์ผ่านหน้าเว็บไม่ได้")
        db.execute("UPDATE users SET admin = ? WHERE id = ?", (int(admin), uid))
        _log(db, uid, "adjust", note=f"{'ให้' if admin else 'ถอด'}สิทธิ์ผู้ดูแลโดย {by['email']}")
    _drop_session_cache(user_id=uid)


# ---------------------------------------------------------------- เครดิตและแพ็กเกจ
def set_notify(uid: str, on: bool) -> dict:
    """เปิดหรือปิดอีเมลแจ้งเตือนงาน คืนข้อมูลผู้ใช้ล่าสุด"""
    with _tx() as db:
        db.execute("UPDATE users SET notify_email = ? WHERE id = ?", (int(on), uid))
        row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return public_user(row)


def export_data(uid: str) -> dict:
    """ข้อมูลบัญชีทั้งหมดของผู้ใช้ (สิทธิ์ขอสำเนาข้อมูลตาม PDPA) ไม่มีโทเคนเข้าสู่ระบบและรหัสอ้างอิงบัตรที่ผู้ให้บริการชำระเงิน"""
    with _lock:
        db = _db()
        u = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        q = lambda sql: [dict(r) for r in db.execute(sql, (uid,)).fetchall()]  # noqa: E731
        sub = q("SELECT plan_id, minutes_left, started_at, expires_at FROM subscriptions WHERE user_id = ?")
        ledger = q("SELECT kind, credits, minutes, amount, ref, note, created_at FROM ledger WHERE user_id = ? ORDER BY id")
        topups = q("SELECT id, amount, credits, plan_id, provider, status, created_at, paid_at FROM topups "
                   "WHERE user_id = ? ORDER BY created_at")
        cards = q("SELECT brand, last4, exp_month, exp_year, created_at FROM cards WHERE user_id = ? ORDER BY created_at")
    return {
        "account": {k: u[k] for k in ("id", "email", "name", "full_name", "phone", "account_type", "company",
                                      "use_case", "created_at", "profile_at", "notify_email")},
        "credits": credits_out(u["credits"]),
        "subscription": {**sub[0], "minutes_left": credits_out(sub[0]["minutes_left"])} if sub else None,
        "ledger": [{**r, "credits": credits_out(r["credits"]), "minutes": credits_out(r["minutes"])} for r in ledger],
        "topups": topups,
        "cards": cards,
    }


def close_account(uid: str) -> float:
    """ปิดบัญชี: ลบข้อมูลส่วนตัว เซสชัน แพ็กเกจ และบัตร เครดิตที่เหลือถูกยกเลิก (ไม่คืนเป็นเงิน)
    แถวผู้ใช้กับสมุดบัญชีและรายการชำระเงินยังเก็บไว้ตามกฎหมายบัญชีและภาษี แต่ไม่มีชื่อ อีเมล หรือเบอร์โทรแล้ว
    ล็อกอินด้วย Google อีเมลเดิมอีกครั้งจะได้บัญชีใหม่ คืนเครดิตที่ยกเลิก"""
    with _tx() as db:
        u = db.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (uid,)).fetchone()
        if u is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        if is_owner(u["email"]):
            raise AccountError(409, "บัญชีผู้ดูแลหลัก (ADMIN_EMAILS) ปิดไม่ได้ เอาอีเมลออกจาก ADMIN_EMAILS ก่อน")
        cards = db.execute("SELECT provider, ref FROM cards WHERE user_id = ?", (uid,)).fetchall()
        if u["credits"]:
            _log(db, uid, "closed", credits=-u["credits"], note="ปิดบัญชี เครดิตที่เหลือถูกยกเลิก")
        for t in ("sessions", "subscriptions", "cards"):
            db.execute(f"DELETE FROM {t} WHERE user_id = ?", (uid,))
        db.execute("UPDATE users SET email = ?, name = 'บัญชีที่ปิดแล้ว', pw_hash = '', credits = 0, admin = 0, "
                   "full_name = '', phone = '', account_type = '', company = '', use_case = '', deleted_at = ? "
                   "WHERE id = ?", (f"closed-{uid}@deleted.invalid", time.time(), uid))
    _drop_session_cache(user_id=uid)
    for c in cards:
        _detach_card(c["provider"], c["ref"])
    return credits_out(u["credits"])


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
        "credits": credits_out(u["credits"]) if u else 0,
        "subscription": _sub_out(sub),
        "credit_price": CREDIT_PRICE,
        "entitlements": entitlements(uid),
        "ledger": [{**dict(r), "credits": credits_out(r["credits"]), "minutes": credits_out(r["minutes"])}
                   for r in ledger],
    }


def credit(uid: str, credits: float, kind: str = "topup", amount: int = 0, ref: Optional[str] = None,
           note: str = "") -> None:
    """เพิ่ม (หรือหักถ้าติดลบ) เครดิตเติม (เป็นเครดิต ทศนิยมได้ 2 ตำแหน่ง): ชำระเงินสำเร็จ หรือผู้ดูแลให้"""
    credits = round(credits * UNIT)
    with _tx() as db:
        u = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        if u["credits"] + credits < 0:
            raise AccountError(400, f"หักได้ไม่เกิน {fmt_credits(u['credits'])} เครดิต")
        db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (credits, uid))
        _log(db, uid, kind, credits=credits, amount=amount, ref=ref, note=note)


def grant_voice_approve_bonus(uid: str, voice_id: str, voice_name: str = "") -> bool:
    """ให้ VOICE_APPROVE_BONUS เครดิตเติมเมื่อเสียงนักพากย์ถูกอนุมัติครั้งแรก
    กันซ้ำด้วย ledger kind=voice_bonus + ref=voice_id คืน True ถ้าเพิ่งให้"""
    if not billing_enabled() or VOICE_APPROVE_BONUS <= 0:
        return False
    units = VOICE_APPROVE_BONUS * UNIT
    label = voice_name.strip() or voice_id
    with _tx() as db:
        if db.execute(
            "SELECT 1 FROM ledger WHERE kind = 'voice_bonus' AND ref = ?", (voice_id,)
        ).fetchone():
            return False
        u = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None:
            return False
        db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (units, uid))
        _log(db, uid, "voice_bonus", credits=units, ref=voice_id,
             note=f"โบนัสอนุมัติเสียง “{label}” ขึ้นคลัง")
    return True


def _activate(db, uid: str, p: Plan, kind: str, amount: int, note: str) -> None:
    """เริ่มแพ็กเกจใหม่วันนี้ ทบเครดิตแพ็กเกจที่เหลือได้ตาม PLAN_CREDIT_ROLLOVER (หน่วย = รอบของแพ็กใหม่)"""
    now = time.time()
    prev = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (uid,)).fetchone()
    carry = 0
    cycles = max(0, int(settings.plan_credit_rollover))
    if prev and cycles > 0 and prev["minutes_left"] > 0:
        # ทบได้ไม่เกิน (เครดิตแพ็กใหม่ × จำนวนรอบ) — ค่าเริ่มต้น 1 รอบ
        carry = min(int(prev["minutes_left"]), p.minutes * UNIT * cycles)
    granted = p.minutes * UNIT + carry
    db.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?, ?, ?, ?)",
               (uid, p.id, granted, now, now + p.days * 86400))
    extra = f" ทบ {fmt_credits(carry)} จากรอบก่อน" if carry else ""
    _log(db, uid, kind, minutes=granted, amount=amount, ref=p.id, note=note + extra)


def promote_owner_media(uid: str) -> int:
    """หลังอัปเกรดแพ็กไม่มีลายน้ำ: ย้ายไฟล์งานจาก free/ ออก และล้าง expires_at
    วิดีโอที่เรนเดอร์มีลายน้ำแล้วยังมี watermark=True (ไฟล์เดิมไม่ลบลายน้ำ) คืนจำนวนงานที่แตะ"""
    if not uid or bool(entitlements(uid).get("watermark")):
        return 0
    try:
        from .main import store
        from . import object_store
    except Exception:  # noqa: BLE001
        log.exception("promote_owner_media import failed")
        return 0
    touched = 0
    for job in store.all():
        if job.owner != uid:
            continue
        if not job.expires_at and not job.watermark:
            continue
        try:
            object_store.promote_from_free(job.id, store.dir(job.id))
        except Exception:  # noqa: BLE001 ไม่ให้การชำระเงินล้มเพราะ R2
            log.exception("promote free media failed for job %s", job.id)
        if job.expires_at is not None:
            store.update(job.id, expires_at=None)
            touched += 1
        elif job.watermark:
            touched += 1
    return touched


def grant_plan(uid: str, plan_id: str, admin_email: str) -> None:
    """ผู้ดูแลให้แพ็กเกจโดยไม่ต้องชำระ (รับโอนนอกระบบ ชดเชย ฯลฯ)"""
    p = plan(plan_id)
    if p is None:
        raise AccountError(404, "ไม่พบแพ็กเกจนี้")
    with _tx() as db:
        if db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone() is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        _activate(db, uid, p, "adjust", 0, f"แพ็กเกจ{p.name} {p.minutes} เครดิต ให้โดย {admin_email}")
    if not p.watermark:
        promote_owner_media(uid)


def _exempt(db, uid: str) -> bool:
    """ผู้ดูแลระบบพากย์ได้ไม่จำกัด ไม่ต้องมีเครดิตหรือแพ็กเกจ"""
    u = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return u is not None and is_admin(u)


def job_credits(seconds: float) -> int:
    """เครดิตของงาน (หน่วยย่อย) ตามความยาวคลิปจริง ปัดขึ้นที่ 0.01 เครดิต"""
    return max(1, math.ceil(round(seconds / 60 * UNIT, 6)))


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
    if not sub and not trial_claimed(uid):
        raise AccountError(402, "ยังไม่มีแพ็กเกจ รับทดลองฟรีหรือซื้อแพ็กเกจที่หน้าโปรโมชันก่อนส่งงาน")
    raise AccountError(402, "เครดิตหมด ซื้อแพ็กเกจหรือเติมเครดิตที่หน้าโปรโมชัน")


def charge_job(uid: str, job_id: str, seconds: float) -> None:
    """ตัดเครดิตของงานเมื่อรู้ความยาวคลิป (ต้นขั้นวิเคราะห์) ตัดครั้งเดียวต่องานหลัก
    พากย์ซ้ำหลังเสร็จแล้วคิดแยกด้วย charge_redub (0.1 เครดิต/วิ ของบรรทัดที่แก้)"""
    if not billing_enabled():
        return
    check_clip_duration(uid, seconds)
    need = job_credits(seconds)
    length = f"{int(seconds // 60)}:{int(seconds % 60):02d}"
    with _tx() as db:
        if _exempt(db, uid) or db.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'charge' AND ref = ?",
                                          (uid, job_id)).fetchone():
            return
        sub = _subscription(db, uid)
        from_plan = min(need, sub["minutes_left"]) if sub else 0
        rest = need - from_plan
        have = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()["credits"]
        if rest > have:
            raise AccountError(402, f"คลิปนี้ยาว {length} นาที ใช้ {fmt_credits(need)} เครดิต แต่มีเพียง "
                                    f"{fmt_credits(from_plan + have)} เครดิต (ขาด {fmt_credits(rest - have)} เครดิต)")
        if from_plan:
            db.execute("UPDATE subscriptions SET minutes_left = minutes_left - ? WHERE user_id = ?", (from_plan, uid))
        if rest:
            db.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (rest, uid))
        _log(db, uid, "charge", credits=-rest, minutes=-from_plan, ref=job_id, note=f"งานพากย์ {length} นาที")


def refund_job(uid: str, job_id: str) -> None:
    """คืนเครดิตเมื่องานล้มเหลวเพราะระบบ (ครั้งเดียวต่องาน) เครดิตแพ็กเกจคืนเฉพาะถ้าแพ็กเกจยังไม่หมดอายุ"""
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
        _log(db, uid, "refund", credits=-charge["credits"], minutes=minutes, ref=job_id, note="คืนเครดิต งานล้มเหลวเพราะระบบ")


def quote_job(seconds: float) -> dict:
    """ประมาณเครดิตก่อนเริ่มงาน จากความยาวคลิป (วินาที)"""
    need = job_credits(max(0.0, seconds))
    return {
        "seconds": round(seconds, 2),
        "credits": need / UNIT,
        "credits_units": need,
        "note": "1 เครดิต ≈ 1 นาที (ปัดขึ้นที่ 0.01)",
    }


def quote_redub(edit_seconds: float, clip_seconds: float, free_flagged_seconds: float = 0.0) -> dict:
    """ประมาณเครดิตพากย์ซ้ำ: 0.1 เครดิตต่อวินาทีของบรรทัดที่แก้
    ฟรีได้ไม่เกิน 10% ของความยาวคลิป และบรรทัดที่ AI ติดธงฟรีเสมอ"""
    billable = max(0.0, edit_seconds - max(0.0, free_flagged_seconds))
    free_quota = max(0.0, clip_seconds) * 0.10
    charged_sec = max(0.0, billable - free_quota)
    # 0.1 เครดิตต่อวินาที → หน่วยย่อย = ceil(sec * 0.1 * UNIT)
    need = max(0, math.ceil(round(charged_sec * 0.1 * UNIT, 6))) if charged_sec > 0 else 0
    return {
        "edit_seconds": round(edit_seconds, 2),
        "free_flagged_seconds": round(free_flagged_seconds, 2),
        "free_quota_seconds": round(free_quota, 2),
        "charged_seconds": round(charged_sec, 2),
        "credits": need / UNIT,
        "credits_units": need,
        "free": need == 0,
    }


def charge_redub(uid: str, job_id: str, edit_seconds: float, clip_seconds: float,
                 free_flagged_seconds: float = 0.0) -> dict:
    """ตัดเครดิตพากย์ซ้ำ (ref = job_id:redub:<n>) คืนผล quote ที่ตัดจริง"""
    q = quote_redub(edit_seconds, clip_seconds, free_flagged_seconds)
    need = int(q["credits_units"])
    if not billing_enabled() or need <= 0:
        return q
    with _tx() as db:
        if _exempt(db, uid):
            return {**q, "charged": False, "exempt": True}
        # นับรอบพากย์ซ้ำจาก ledger เพื่อไม่ชน ref ของ charge งานหลัก
        n = db.execute(
            "SELECT COUNT(*) AS c FROM ledger WHERE user_id = ? AND kind = 'charge' AND ref LIKE ?",
            (uid, f"{job_id}:redub:%"),
        ).fetchone()["c"]
        ref = f"{job_id}:redub:{int(n) + 1}"
        sub = _subscription(db, uid)
        from_plan = min(need, sub["minutes_left"]) if sub else 0
        rest = need - from_plan
        have = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()["credits"]
        if rest > have:
            raise AccountError(
                402,
                f"พากย์ซ้ำครั้งนี้ใช้ {fmt_credits(need)} เครดิต แต่มีเพียง "
                f"{fmt_credits(from_plan + have)} เครดิต (ขาด {fmt_credits(rest - have)} เครดิต)",
            )
        if from_plan:
            db.execute("UPDATE subscriptions SET minutes_left = minutes_left - ? WHERE user_id = ?",
                       (from_plan, uid))
        if rest:
            db.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (rest, uid))
        _log(db, uid, "charge", credits=-rest, minutes=-from_plan, ref=ref,
             note=f"พากย์ซ้ำ {q['charged_seconds']:.1f} วินาที")
    return {**q, "charged": True, "ref": ref}


# ---------------------------------------------------------------- ชำระเงิน (ซื้อเครดิตเติม หรือแพ็กเกจ)
_SLIP_OPEN = ("pending", "rejected")  # แนบสลิปได้ตอนรอโอน และหลังผู้ดูแลไม่ผ่าน (ส่งรูปใหม่ได้)


def _payee() -> dict:
    return {"name": settings.payee_name, "bank": settings.payee_bank, "account": settings.payee_account}


def _order_out(row, email: str = "", name: str = "", admin: bool = False) -> dict:
    raw = {}
    if row["ocr_json"]:
        try:
            raw = json.loads(row["ocr_json"])
        except json.JSONDecodeError:
            raw = {}
    ocr = None
    if row["ocr_amount"] is not None or raw:
        ocr = {
            "amount": row["ocr_amount"], "ref": raw.get("ref"), "payer": raw.get("payer"),
            "payee": raw.get("payee"), "payee_account": raw.get("payee_account"),
            "transferred_at": raw.get("transferred_at"),
        }
    keys = row.keys() if hasattr(row, "keys") else []
    out = {
        "id": row["id"], "status": row["status"], "amount": row["amount"], "credits": row["credits"] or 0,
        "plan_id": row["plan_id"], "provider": row["provider"], "created_at": row["created_at"],
        "paid_at": row["paid_at"], "note": row["note"] or "", "has_slip": bool(row["slip_hash"]),
        "payee": _payee() if row["status"] != "paid" and row["provider"] == "slip" else None, "ocr": ocr,
        "checkout_url": None,
        "provider_ref": row["provider_ref"] if "provider_ref" in keys and row["provider_ref"] else None,
    }
    if admin:
        out["email"] = email
        out["name"] = name
        out["ocr_text"] = (row["ocr_text"] or "")[:4000]
    return out


def _fetch_order(topup_id: str, admin: bool = False) -> dict:
    with _lock:
        row = _db().execute(
            "SELECT t.*, u.email AS email, u.name AS user_name FROM topups t "
            "JOIN users u ON u.id = t.user_id WHERE t.id = ?", (topup_id,)).fetchone()
    if row is None:
        raise AccountError(404, "ไม่พบรายการนี้")
    return _order_out(row, row["email"], row["user_name"], admin=admin)


def _payment_label(credits: int, plan_id: Optional[str]) -> str:
    if plan_id:
        p = plan(plan_id)
        return f"แพ็กเกจ{p.name}" if p else f"แพ็กเกจ {plan_id}"
    return f"เครดิตเติม {credits:,} เครดิต"


def _start_payment(uid: str, amount: int, credits: int = 0, plan_id: Optional[str] = None) -> dict:
    """mock = จ่ายสำเร็จทันที  slip = รอโอนแนบสลิป  stripe = เปิด Checkout แล้ว webhook เติมเครดิต"""
    provider = settings.payment_provider
    if provider not in ("mock", "slip", "stripe"):
        raise AccountError(503, "ยังไม่ได้เชื่อมช่องทางชำระเงิน ติดต่อผู้ดูแลเพื่อเติมเครดิต")
    if provider == "slip" and len(re.sub(r"\D", "", settings.payee_account)) < 8:
        raise AccountError(503, "ยังไม่ได้ตั้งบัญชีรับโอน (PAYEE_ACCOUNT)")
    tid = secrets.token_hex(8)
    email = ""
    with _tx() as db:
        user = db.execute("SELECT email FROM users WHERE id = ? AND deleted_at IS NULL", (uid,)).fetchone()
        if user is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        email = user["email"] or ""
        db.execute(
            "INSERT INTO topups (id, user_id, amount, provider, status, created_at, credits, plan_id) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (tid, uid, amount, provider, time.time(), credits, plan_id))
    if provider == "mock":
        mark_paid(tid)
        return _fetch_order(tid)
    if provider == "stripe":
        from .stripe_pay import StripeError, create_checkout
        try:
            sid, url = create_checkout(
                topup_id=tid, user_id=uid, amount=amount, label=_payment_label(credits, plan_id),
                email=email)
        except StripeError as e:
            with _tx() as db:
                db.execute("UPDATE topups SET status = 'rejected', note = ? WHERE id = ?",
                           (str(e)[:300], tid))
            raise AccountError(e.status, str(e))
        with _tx() as db:
            db.execute("UPDATE topups SET provider_ref = ? WHERE id = ?", (sid, tid))
        order = _fetch_order(tid)
        order["checkout_url"] = url
        return order
    return _fetch_order(tid)


def fulfill_stripe(topup_id: str, *, session_id: str = "", amount_total=None, currency: str = "") -> None:
    """webhook ยืนยันแล้ว: ตรวจยอดแล้ว mark_paid (เรียกซ้ำได้)"""
    with _lock:
        row = _db().execute("SELECT * FROM topups WHERE id = ?", (topup_id,)).fetchone()
    if row is None:
        log = __import__("logging").getLogger("dubbing.stripe")
        log.warning("Stripe fulfill ไม่พบ topup %s", topup_id)
        return
    if row["status"] == "paid":
        return
    if row["provider"] != "stripe":
        raise AccountError(400, "รายการนี้ไม่ใช่ Stripe")
    if currency and currency != "thb":
        raise AccountError(400, "สกุลเงินไม่ตรง")
    if amount_total is not None and int(amount_total) != int(row["amount"]):
        raise AccountError(400, "ยอดเงินไม่ตรงกับรายการ")
    pref = row["provider_ref"] if "provider_ref" in row.keys() else None
    if session_id and pref and pref != session_id:
        raise AccountError(400, "รหัสเซสชัน Stripe ไม่ตรง")
    with _tx() as db:
        note = "ชำระผ่าน Stripe แล้ว เริ่มแพ็กเกจ" if row["plan_id"] else "ชำระผ่าน Stripe แล้ว"
        db.execute("UPDATE topups SET note = ? WHERE id = ? AND status != 'paid'", (note, topup_id))
        if session_id and not pref:
            db.execute("UPDATE topups SET provider_ref = ? WHERE id = ?", (session_id, topup_id))
    mark_paid(topup_id)


def confirm_stripe(uid: str, topup_id: str) -> dict:
    """หลังกลับจาก Checkout (?paid=): ถาม Stripe เองว่าจ่ายแล้วหรือยัง แล้วเติมเครดิต
    ใช้เมื่อ webhook มาไม่ถึงหรือลายเซ็นไม่ผ่าน"""
    import stripe
    with _lock:
        row = _db().execute("SELECT * FROM topups WHERE id = ? AND user_id = ?", (topup_id, uid)).fetchone()
    if row is None:
        raise AccountError(404, "ไม่พบรายการนี้")
    if row["status"] == "paid":
        return _fetch_order(topup_id)
    if row["provider"] != "stripe":
        raise AccountError(400, "รายการนี้ไม่ใช่ Stripe")
    sid = row["provider_ref"] if "provider_ref" in row.keys() else None
    if not sid:
        raise AccountError(409, "ยังไม่มีเซสชัน Stripe ของรายการนี้")
    if not settings.stripe_secret_key.strip():
        raise AccountError(503, "ยังไม่ได้ตั้ง STRIPE_SECRET_KEY")
    stripe.api_key = settings.stripe_secret_key
    try:
        session = stripe.checkout.Session.retrieve(sid)
    except stripe.StripeError as e:
        raise AccountError(502, "ถามสถานะ Stripe ไม่สำเร็จ") from e
    if getattr(session, "payment_status", None) != "paid":
        return _fetch_order(topup_id)
    fulfill_stripe(topup_id, session_id=sid, amount_total=getattr(session, "amount_total", None),
                   currency=(getattr(session, "currency", None) or ""))
    return _fetch_order(topup_id)


def user_payments(uid: str) -> list[dict]:
    rows = _read("SELECT * FROM topups WHERE user_id = ? ORDER BY created_at DESC LIMIT 30", uid)
    return [_order_out(r) for r in rows]


def _write_slip(uid: str, topup_id: str, data: bytes, mime: str, digest: str, slip, note: str) -> None:
    """เก็ปรูปและผลอ่าน ตั้งสถานะรอตรวจ แฮชซ้ำของรายการอื่นใช้ไม่ได้"""
    ext = ".jpg" if mime == "image/jpeg" else ".png"
    folder = Path(settings.data_dir) / "slips"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{topup_id}{ext}.part"
    dest = folder / f"{topup_id}{ext}"
    tmp.write_bytes(data)
    try:
        with _tx() as db:
            row = db.execute("SELECT status FROM topups WHERE id = ? AND user_id = ?", (topup_id, uid)).fetchone()
            if row is None:
                raise AccountError(404, "ไม่พบรายการนี้")
            if row["status"] not in _SLIP_OPEN:
                raise AccountError(409, "รายการนี้แนบสลิปเพิ่มไม่ได้")
            used = db.execute("SELECT topup_id FROM slip_uses WHERE hash = ?", (digest,)).fetchone()
            if used and used["topup_id"] != topup_id:
                raise AccountError(409, "สลิปนี้เคยใช้แล้ว")
            db.execute("INSERT OR IGNORE INTO slip_uses (hash, topup_id, created_at) VALUES (?, ?, ?)",
                       (digest, topup_id, time.time()))
            public = json.dumps(slip.public(), ensure_ascii=False) if slip else ""
            db.execute(
                "UPDATE topups SET slip_hash = ?, ocr_text = ?, ocr_amount = ?, ocr_json = ?, note = ?, status = 'review' "
                "WHERE id = ?",
                (digest, (slip.text if slip else "")[:8000], None if slip is None else slip.amount,
                 public, note[:500], topup_id))
        (folder / f"{topup_id}{'.png' if ext == '.jpg' else '.jpg'}").unlink(missing_ok=True)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def submit_slip(uid: str, topup_id: str, data: bytes) -> dict:
    """อ่านสลิปด้วย Typhoon OCR ยอดและบัญชีตรงแล้วเติมให้เลย ไม่ตรงหรืออ่านไม่ได้เข้าคิวผู้ดูแล"""
    mime = image_mime(data)
    if mime is None:
        raise AccountError(400, "รับเฉพาะรูปสลิป JPG หรือ PNG")
    if len(data) > max(1, settings.slip_max_mb) * 1024 * 1024:
        raise AccountError(400, f"รูปสลิปใหญ่เกิน {settings.slip_max_mb} MB")
    digest = hashlib.sha256(data).hexdigest()
    with _lock:
        db = _db()
        row = db.execute("SELECT * FROM topups WHERE id = ? AND user_id = ?", (topup_id, uid)).fetchone()
        used = db.execute("SELECT topup_id FROM slip_uses WHERE hash = ?", (digest,)).fetchone()
    if row is None:
        raise AccountError(404, "ไม่พบรายการนี้")
    if row["provider"] != "slip":
        raise AccountError(400, "รายการนี้ไม่ต้องแนบสลิป")
    if row["status"] not in _SLIP_OPEN:
        raise AccountError(409, "รายการนี้แนบสลิปเพิ่มไม่ได้")
    if used and used["topup_id"] != topup_id:
        raise AccountError(409, "สลิปนี้เคยใช้แล้ว")
    force_review = row["status"] == "rejected"
    try:
        slip = read_slip(data, mime)
        ok, note = verdict(row["amount"], slip, payee_account=settings.payee_account,
                           max_age_hours=settings.slip_max_age_hours)
    except SlipOcrError as exc:
        slip, ok, note = None, False, str(exc)
    if ok and force_review:
        note = "ส่งสลิปใหม่หลังไม่ผ่าน ยอดตรง รอผู้ดูแลตรวจอีกครั้ง"
    _write_slip(uid, topup_id, data, mime, digest, slip, note)
    if ok and not force_review:
        mark_paid(topup_id)
        done = "ยอดตรงกับสลิป เริ่มแพ็กเกจแล้ว" if row["plan_id"] else "ยอดตรงกับสลิป เติมเครดิตแล้ว"
        with _tx() as db:
            db.execute("UPDATE topups SET note = ? WHERE id = ? AND status = 'paid'", (done, topup_id))
    return _fetch_order(topup_id)


def admin_payments(status: str = "review") -> list[dict]:
    if status and status not in ("pending", "review", "paid", "rejected"):
        raise AccountError(400, "สถานะไม่ถูกต้อง")
    sql = ("SELECT t.*, u.email AS email, u.name AS user_name FROM topups t JOIN users u ON u.id = t.user_id ")
    if status:
        rows = _read(sql + "WHERE t.status = ? ORDER BY t.created_at DESC LIMIT 100", status)
    else:
        rows = _read(sql + "ORDER BY t.created_at DESC LIMIT 100")
    return [_order_out(r, r["email"], r["user_name"], admin=True) for r in rows]


def approve_payment(topup_id: str, admin_email: str) -> dict:
    """ผู้ดูแลยืนยันสลิปที่ระบบไม่กล้าเติมเอง"""
    with _lock:
        row = _db().execute("SELECT status, slip_hash FROM topups WHERE id = ?", (topup_id,)).fetchone()
    if row is None:
        raise AccountError(404, "ไม่พบรายการนี้")
    if row["status"] == "paid":
        raise AccountError(409, "รายการนี้เติมเครดิตไปแล้ว")
    if row["status"] != "review" or not row["slip_hash"]:
        raise AccountError(400, "รายการนี้ยังไม่มีสลิปให้ตรวจ")
    with _tx() as db:
        db.execute("UPDATE topups SET note = ? WHERE id = ? AND status = 'review'",
                   (f"ผู้ดูแล {admin_email} ตรวจสลิปแล้วอนุมัติ", topup_id))
    mark_paid(topup_id)
    return _fetch_order(topup_id, admin=True)


def reject_payment(topup_id: str, admin_email: str, note: str = "") -> dict:
    text = note.strip() or f"ผู้ดูแล {admin_email} ไม่ผ่านสลิป"
    with _tx() as db:
        row = db.execute("SELECT status FROM topups WHERE id = ?", (topup_id,)).fetchone()
        if row is None:
            raise AccountError(404, "ไม่พบรายการนี้")
        if row["status"] == "paid":
            raise AccountError(409, "รายการนี้เติมเครดิตไปแล้ว")
        if row["status"] != "review":
            raise AccountError(400, "รายการนี้ไม่อยู่ในคิวตรวจ")
        db.execute("UPDATE topups SET status = 'rejected', note = ? WHERE id = ?", (text[:300], topup_id))
    return _fetch_order(topup_id, admin=True)


def slip_file(topup_id: str, uid: str, admin: bool) -> tuple[Path, str, str]:
    """ไฟล์สลิปของเจ้าของรายการหรือผู้ดูแล"""
    with _lock:
        row = _db().execute("SELECT user_id FROM topups WHERE id = ?", (topup_id,)).fetchone()
    if row is None or (not admin and row["user_id"] != uid):
        raise AccountError(404, "ไม่พบสลิปนี้")
    folder = Path(settings.data_dir) / "slips"
    for ext, mime in ((".jpg", "image/jpeg"), (".png", "image/png")):
        path = folder / f"{topup_id}{ext}"
        if path.is_file():
            return path, mime, f"slip-{topup_id}{ext}"
    raise AccountError(404, "ยังไม่มีไฟล์สลิป")


def buy_credits(uid: str, credits: int) -> dict:
    if not TOPUP_MIN <= credits <= TOPUP_MAX:
        raise AccountError(400, f"ซื้อได้ครั้งละ {TOPUP_MIN:,}–{TOPUP_MAX:,} เครดิต")
    ent = entitlements(uid)
    if not ent.get("can_topup"):
        raise AccountError(402, "ซื้อเครดิตเติมได้เมื่อมีแพ็กเกจแล้ว รับทดลองหรือซื้อแพ็กเกจที่หน้าโปรโมชันก่อน")
    return _start_payment(uid, credits * CREDIT_PRICE, credits=credits)


def claim_trial(uid: str) -> dict:
    """รับแพ็กทดลองฟรี ครั้งเดียวต่อบัญชี"""
    p = plan("trial")
    if p is None or not p.free_once:
        raise AccountError(404, "ไม่มีแพ็กเกจทดลอง")
    with _tx() as db:
        if db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone() is None:
            raise AccountError(404, "ไม่พบผู้ใช้นี้")
        if db.execute(
            "SELECT 1 FROM ledger WHERE user_id = ? AND (kind = 'trial' OR ref = 'trial') LIMIT 1",
            (uid,),
        ).fetchone():
            raise AccountError(409, "บัญชีนี้รับแพ็กทดลองไปแล้ว")
        if _exempt(db, uid):
            raise AccountError(400, "บัญชีผู้ดูแลไม่ต้องใช้แพ็กทดลอง")
        _activate(db, uid, p, "trial", 0, f"แพ็กเกจ{p.name} {p.minutes} เครดิตฟรี")
        sub = db.execute("SELECT * FROM subscriptions WHERE user_id = ?", (uid,)).fetchone()
    # รูปแบบคล้าย PaymentOrder เพื่อหน้าเว็บเดิมที่เรียก /billing/subscribe แล้วมองหา status=paid
    return {
        "id": f"trial-{uid}",
        "status": "paid",
        "amount": 0,
        "credits": p.minutes,
        "plan_id": p.id,
        "provider": "trial",
        "created_at": time.time(),
        "paid_at": time.time(),
        "note": f"เริ่มแพ็กเกจ{p.name} ฟรี",
        "plan": p.public_dict(),
        "subscription": _sub_out(sub),
        "entitlements": entitlements(uid),
    }


def subscribe(uid: str, plan_id: str) -> dict:
    p = plan(plan_id)
    if p is None:
        raise AccountError(404, "ไม่พบแพ็กเกจนี้")
    if not p.available:
        raise AccountError(503, f"แพ็กเกจ{p.name}อยู่ระหว่างพัฒนา ยังไม่เปิดให้ซื้อ")
    if p.free_once or p.price <= 0:
        return claim_trial(uid)
    return _start_payment(uid, p.price, plan_id=p.id)


# ---------------------------------------------------------------- บัตรที่ผูกไว้
def _attach_card(uid: str, token: str) -> dict:
    """ผูกบัตรกับผู้ให้บริการชำระเงิน token มาจากสคริปต์ของผู้ให้บริการในหน้าเว็บ (เลขบัตรไม่ผ่านเซิร์ฟเวอร์เรา)
    คืน {ref, brand, last4, exp_month, exp_year, fingerprint} fingerprint เหมือนกันทุกครั้งที่ผูกบัตรใบเดิม
    PAYMENT_PROVIDER=mock รับ token "tok_mock_<เลขท้าย 4 ตัว>[_อะไรก็ได้]" (ทดสอบ) ยังไม่ได้เชื่อมผู้ให้บริการจริง"""
    if settings.payment_provider != "mock":
        raise AccountError(503, "ยังไม่ได้เชื่อมช่องทางชำระเงิน ผูกบัตรไม่ได้ตอนนี้")
    parts = token.split("_")
    if len(parts) < 3 or parts[:2] != ["tok", "mock"] or not (parts[2].isdigit() and len(parts[2]) == 4):
        raise AccountError(400, "ข้อมูลบัตรไม่ถูกต้อง")
    return {"ref": f"card_mock_{secrets.token_hex(6)}", "brand": "Visa", "last4": parts[2],
            "exp_month": 12, "exp_year": 2030, "fingerprint": f"mock:{token}"}


def _detach_card(provider: str, ref: str) -> None:
    """ลบบัตรที่ผู้ให้บริการ (mock ไม่ต้องทำอะไร)"""


def _public_card(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "brand", "last4", "exp_month", "exp_year", "created_at")}


def cards(uid: str) -> dict:
    """บัตรที่ผูกไว้ ยังรับเครดิตฟรีจากการผูกบัตรได้ไหม และผู้ให้บริการ (หน้าเว็บใช้เลือกฟอร์มผูกบัตร ว่าง = ยังไม่เชื่อม)"""
    with _lock:
        db = _db()
        rows = db.execute("SELECT * FROM cards WHERE user_id = ? ORDER BY created_at", (uid,)).fetchall()
        got = db.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'bonus'", (uid,)).fetchone()
    return {"cards": [_public_card(r) for r in rows], "bonus": CARD_BONUS, "bonus_available": got is None,
            "provider": settings.payment_provider}


def add_card(uid: str, token: str) -> dict:
    """ผูกบัตร ครั้งแรกได้ CARD_BONUS เครดิต (ถ้าผู้ใช้นี้ยังไม่เคยได้ และบัตรใบนี้ยังไม่เคยให้โบนัสกับใคร)"""
    info = _attach_card(uid, token)
    with _tx() as db:
        if db.execute("SELECT 1 FROM cards WHERE user_id = ? AND fingerprint = ?", (uid, info["fingerprint"])).fetchone():
            raise AccountError(409, "ผูกบัตรใบนี้ไว้แล้ว")
        cid = secrets.token_hex(8)
        db.execute("INSERT INTO cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (cid, uid, settings.payment_provider, info["ref"], info["brand"], info["last4"],
                    info["exp_month"], info["exp_year"], info["fingerprint"], time.time()))
        bonus = 0
        if not db.execute("SELECT 1 FROM ledger WHERE kind = 'bonus' AND (user_id = ? OR ref = ?)",
                          (uid, info["fingerprint"])).fetchone():
            bonus = CARD_BONUS
            db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (bonus * UNIT, uid))
            _log(db, uid, "bonus", credits=bonus * UNIT, ref=info["fingerprint"],
                 note=f"ผูกบัตร {info['brand']} ลงท้าย {info['last4']} ครั้งแรก")
        row = db.execute("SELECT * FROM cards WHERE id = ?", (cid,)).fetchone()
    return {"card": _public_card(row), "bonus": bonus}


def remove_card(uid: str, card_id: str) -> None:
    """ลบบัตร เครดิตฟรีที่ได้ไปแล้วไม่หัก แต่ผูกใหม่ก็ไม่ได้อีก"""
    with _tx() as db:
        row = db.execute("SELECT * FROM cards WHERE id = ? AND user_id = ?", (card_id, uid)).fetchone()
        if row is None:
            raise AccountError(404, "ไม่พบบัตรนี้")
        db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    _detach_card(row["provider"], row["ref"])


FEEDBACK_CATEGORIES = ("bug", "billing", "quality", "feature", "other")
_FEEDBACK_DDL = (
    "CREATE TABLE IF NOT EXISTS feedback ("
    "id TEXT PRIMARY KEY, user_id TEXT, email TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', "
    "category TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, job_id TEXT NOT NULL DEFAULT '', "
    "status TEXT NOT NULL DEFAULT 'open', admin_note TEXT NOT NULL DEFAULT '', "
    "created_at REAL NOT NULL, resolved_at REAL)"
)


def _ensure_feedback(db) -> None:
    db.execute(_FEEDBACK_DDL)
    try:
        db.execute("CREATE INDEX IF NOT EXISTS feedback_status_created ON feedback(status, created_at)")
    except Exception:
        pass


def _feedback_out(row) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "email": row["email"] or "", "name": row["name"] or "",
        "category": row["category"], "subject": row["subject"], "body": row["body"],
        "job_id": row["job_id"] or "", "status": row["status"], "admin_note": row["admin_note"] or "",
        "created_at": row["created_at"], "resolved_at": row["resolved_at"],
    }


def submit_feedback(uid: Optional[str], *, category: str, subject: str, body: str, job_id: str = "") -> dict:
    """ผู้ใช้แจ้งปัญหาหรือข้อเสนอแนะ"""
    cat = (category or "").strip()
    if cat not in FEEDBACK_CATEGORIES:
        raise AccountError(400, "เลือกประเภทปัญหาไม่ถูกต้อง")
    sub = (subject or "").strip()
    text = (body or "").strip()
    if len(sub) < 3:
        raise AccountError(400, "กรอกหัวข้อสั้น ๆ อย่างน้อย 3 ตัวอักษ")
    if len(text) < 10:
        raise AccountError(400, "อธิบายปัญหาอย่างน้อย 10 ตัวอักษ")
    if len(sub) > 120 or len(text) > 4000:
        raise AccountError(400, "ข้อความยาวเกินไป")
    jid = (job_id or "").strip()[:80]
    email, name = "", ""
    with _tx() as db:
        _ensure_feedback(db)
        if uid:
            u = db.execute("SELECT id, email, name FROM users WHERE id = ?", (uid,)).fetchone()
            if u is None:
                raise AccountError(404, "ไม่พบผู้ใช้นี้")
            email, name = u["email"] or "", u["name"] or ""
        fid = secrets.token_urlsafe(12)
        now = time.time()
        db.execute(
            "INSERT INTO feedback (id, user_id, email, name, category, subject, body, job_id, status, admin_note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', '', ?)",
            (fid, uid, email, name, cat, sub, text, jid, now),
        )
        row = db.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone()
    return _feedback_out(row)


def list_feedback(uid: str, *, mine: bool = False) -> list[dict]:
    """รายการแจ้งปัญหา — ของตัวเอง หรือทั้งหมดเมื่อเป็นผู้ดูแล"""
    with _lock:
        db = _db()
        _ensure_feedback(db)
        if mine:
            rows = db.execute(
                "SELECT * FROM feedback WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (uid,)
            ).fetchall()
        else:
            u = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            if u is None or not is_admin(u):
                raise AccountError(403, "เฉพาะผู้ดูแลระบบ")
            rows = db.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 100").fetchall()
    return [_feedback_out(r) for r in rows]


def resolve_feedback(fid: str, admin_email: str, *, status: str = "done", note: str = "") -> dict:
    """ผู้ดูแลปิดหรือเปิดรายงานใหม่"""
    if status not in ("open", "done"):
        raise AccountError(400, "สถานะไม่ถูกต้อง")
    with _tx() as db:
        _ensure_feedback(db)
        row = db.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone()
        if row is None:
            raise AccountError(404, "ไม่พบรายการนี้")
        resolved = time.time() if status == "done" else None
        note_text = (note or "").strip()[:500]
        if note_text:
            db.execute(
                "UPDATE feedback SET status = ?, resolved_at = ?, admin_note = ? WHERE id = ?",
                (status, resolved, note_text, fid),
            )
        else:
            db.execute(
                "UPDATE feedback SET status = ?, resolved_at = ? WHERE id = ?",
                (status, resolved, fid),
            )
        row = db.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone()
    return _feedback_out(row)


def mark_paid(topup_id: str) -> None:
    """ช่องทางชำระเงินแจ้งว่าจ่ายแล้ว (webhook) ให้เครดิตหรือเริ่มแพ็กเกจครั้งเดียวต่อรายการ"""
    promote_uid = None
    with _tx() as db:
        t = db.execute("SELECT * FROM topups WHERE id = ?", (topup_id,)).fetchone()
        if t is None or t["status"] == "paid":
            return
        db.execute("UPDATE topups SET status = 'paid', paid_at = ? WHERE id = ?", (time.time(), topup_id))
        p = plan(t["plan_id"]) if t["plan_id"] else None
        if p:
            _activate(db, t["user_id"], p, "subscribe", t["amount"], f"แพ็กเกจ{p.name} {p.minutes} เครดิต")
            if not p.watermark:
                promote_uid = t["user_id"]
        else:
            db.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (t["credits"] * UNIT, t["user_id"]))
            _log(db, t["user_id"], "topup", credits=t["credits"] * UNIT, amount=t["amount"], ref=topup_id,
                 note=f"ซื้อ {t['credits']:,} เครดิต ผ่าน {t['provider']}")
    if promote_uid:
        promote_owner_media(promote_uid)
