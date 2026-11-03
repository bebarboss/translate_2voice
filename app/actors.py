"""นักพากย์: สมัครเอง (ผู้ดูแลอนุมัติ) ยอมรับหนังสือยินยอม PDPA และสิทธิ์ใช้เสียง แล้วอัดเสียงเข้าคลัง (ผู้ดูแลตรวจฟังก่อน)
ทุกครั้งที่งานพากย์เสร็จ บันทึกว่าเสียงของนักพากย์ถูกใช้กี่วินาที ใช้คำนวณค่าตอบแทนรายเดือน

เก็บในฐานข้อมูลเดียวกับบัญชีผู้ใช้ (data/accounts.db) ตัวไฟล์เสียงอยู่ในคลังเสียงตามปกติ (voice_library.py)
- actors: ข้อมูลนักพากย์ สถานะ pending / approved / rejected / withdrawn
- actor_consents: ทุกครั้งที่กดยอมรับ (เวอร์ชันหนังสือ แฮชข้อความ เวลา IP เบราว์เซอร์) และเวลาที่ถอน
- actor_voices: เสียงในคลังที่นักพากย์อัด สถานะตรวจ pending / approved / rejected
- actor_moods: เสียงอารมณ์ที่นักพากย์อัดเพิ่ม ตรวจแยกทีละอารมณ์ (เสียงหลักที่ผ่านแล้วไม่ต้องรอตรวจใหม่)
  อารมณ์ที่ไม่มีแถวในตารางนี้ (อัดก่อนมีการตรวจแยก) ถือตามสถานะของเสียงหลัก
- voice_usage: งาน × เสียง = วินาทีของเสียงพากย์ในผลงานรอบล่าสุดของงานนั้น (พากย์ใหม่ = แทนค่าเดิม ไม่นับซ้ำ)
- actor_payouts: การจ่ายค่าตอบแทนแต่ละครั้ง ยอดค้างจ่าย = ค่าตอบแทนตามการใช้งานของเดือน − ที่จ่ายแล้ว
  amount = ยอดก่อนหักภาษี, wht = ภาษีหัก ณ ที่จ่าย (โอนจริง = amount − wht) และสำเนาชื่อ เลขผู้เสียภาษี ที่อยู่ ณ วันจ่าย
- actor_payment: ข้อมูลรับเงินของนักพากย์ (ชื่อผู้รับเงิน เลขประจำตัวผู้เสียภาษี ที่อยู่ บัญชีธนาคาร)
นักพากย์ใช้เสียงตัวเองพากย์งานของตัวเอง ไม่นับเป็นค่าตอบแทน
"""
import hashlib
import json
import logging
import re
import time
from typing import Optional

from .accounts import AccountError, _read, _tx
from .config import settings

log = logging.getLogger("dubbing.actors")

CONSENT_VERSION = "2026-11-03.3"
# ข้อที่ต้องติ๊กทีละข้อ (บันทึกว่ายอมรับข้อไหน) ต้องครบทุกข้อถึงจะสมัครหรือส่งเสียงได้
CONSENT_ITEMS = {
    "biometric": "ข้าพเจ้ายินยอมโดยชัดแจ้งให้เก็บและใช้เสียงและลายเสียงของข้าพเจ้า (ข้อมูลชีวภาพ) ตามวัตถุประสงค์ในหนังสือนี้",
    "transfer": "ข้าพเจ้ายินยอมให้ส่งเสียงและข้อมูลของข้าพเจ้าไปประมวลผลกับผู้ให้บริการในต่างประเทศตามข้อ 4",
    "license": "ข้าพเจ้าอนุญาตให้ผู้ใช้ในระบบใช้เสียงของข้าพเจ้าสร้างและเผยแพร่งานพากย์ และรับรองว่าเสียงที่ส่งเป็นเสียงของข้าพเจ้าเอง",
    "age": "ข้าพเจ้ามีอายุ 20 ปีบริบูรณ์ขึ้นไป หรือผู้ใช้อำนาจปกครองได้อ่านและยินยอมตามหนังสือนี้ด้วยแล้ว",
}
TZ = 7 * 3600  # เดือนของค่าตอบแทนนับตามเวลาไทย

CONSENT_TEXT = """หนังสือให้ความยินยอมเก็บและใช้ข้อมูลเสียง และอนุญาตให้ใช้เสียง (เวอร์ชัน {version})

ผู้ควบคุมข้อมูลส่วนบุคคล: {controller} ติดต่อ: {contact}

1. ข้อมูลที่เก็บ
เสียงที่ท่านอัดหรืออัปโหลด ข้อความที่ถอดจากเสียง ลักษณะเฉพาะของเสียง (ลายเสียงที่คำนวณจากเสียงของท่าน) ชื่อในวงการ ชื่อและอีเมลของบัญชี ช่องทางติดต่อ ประวัติการใช้งานเสียงเพื่อคำนวณค่าตอบแทน และข้อมูลสำหรับรับค่าตอบแทน (ชื่อผู้รับเงิน เลขประจำตัวผู้เสียภาษี ที่อยู่ และบัญชีธนาคาร)

2. วัตถุประสงค์
ใช้เสียงของท่านเป็นเสียงตัวอย่างให้ระบบปัญญาประดิษฐ์สร้างเสียงพากย์ภาษาไทยหรือภาษาอื่นในงานของผู้ใช้ระบบ แสดงชื่อในวงการของท่านคู่กับเสียง และคำนวณค่าตอบแทน

3. ความยินยอมโดยชัดแจ้ง
ลายเสียงอาจเป็นข้อมูลชีวภาพซึ่งเป็นข้อมูลส่วนบุคคลประเภทพิเศษตามมาตรา 26 แห่งพระราชบัญญัติคุ้มครองข้อมูลส่วนบุคคล พ.ศ. 2562 การกดยอมรับคือการให้ความยินยอมโดยชัดแจ้ง ท่านไม่จำเป็นต้องให้ความยินยอม แต่หากไม่ให้ จะส่งเสียงเข้าคลังไม่ได้

4. การส่งข้อมูลไปต่างประเทศ
ระบบประมวลผลเสียงบนเซิร์ฟเวอร์ของผู้ให้บริการคลาวด์ในสหรัฐอเมริกา (Modal) และอาจเก็บข้อมูลบนผู้ให้บริการฐานข้อมูลคลาวด์ (Supabase) ประเทศปลายทางอาจมีมาตรฐานการคุ้มครองข้อมูลแตกต่างจากประเทศไทย

5. สิทธิ์ใช้เสียง
ท่านอนุญาตแบบไม่ผูกขาดให้ผู้ให้บริการและผู้ใช้ทุกคนในระบบใช้เสียงของท่านสร้างงานพากย์ และเผยแพร่งานพากย์นั้นได้ ท่านยังเป็นเจ้าของเสียงของท่าน และใช้เสียงของท่านที่อื่นได้ตามปกติ ท่านรับรองว่าเสียงที่ส่งเป็นเสียงของท่านเอง

6. ค่าตอบแทน
คิดตามความยาวเสียงพากย์ที่สร้างจากเสียงของท่านในงานของผู้ใช้คนอื่น อัตรา {rate} บาทต่อนาที สรุปยอดรายเดือน อัตรานี้อาจเปลี่ยนได้โดยแจ้งล่วงหน้า ผู้ให้บริการหักภาษี ณ ที่จ่ายตามที่กฎหมายกำหนด{wht} และใช้ชื่อ เลขประจำตัวผู้เสียภาษี และที่อยู่ของท่านยื่นแบบภาษีและออกหนังสือรับรองการหักภาษีให้ท่าน

7. ระยะเวลาเก็บ
เก็บจนกว่าท่านจะถอนความยินยอม เมื่อถอน ระบบลบเสียง ไฟล์ และลายเสียงของท่านออกจากคลังทันที ผลงานพากย์ที่ผู้ใช้สร้างเสร็จก่อนถอนไม่ถูกลบ ประวัติการใช้งานและการจ่ายค่าตอบแทน รวมถึงชื่อ เลขประจำตัวผู้เสียภาษี และที่อยู่ในรายการที่จ่ายแล้ว เก็บไว้ตามที่กฎหมายบัญชีและภาษีกำหนด เลขบัญชีธนาคารลบเมื่อปิดบัญชี

8. สิทธิ์ของท่าน
ท่านมีสิทธิ์ขอเข้าถึง ขอสำเนา ขอแก้ไข ขอลบ ขอระงับการใช้ คัดค้าน และถอนความยินยอมเมื่อใดก็ได้ (กดถอนได้ที่หน้านักพากย์) การถอนไม่กระทบการใช้ที่เกิดขึ้นก่อนถอน และท่านร้องเรียนต่อสำนักงานคณะกรรมการคุ้มครองข้อมูลส่วนบุคคล (สคส.) ได้

9. ผู้เยาว์
ผู้ที่อายุยังไม่ถึง 20 ปีบริบูรณ์ ต้องให้ผู้ใช้อำนาจปกครองอ่านและยินยอมตามหนังสือนี้ด้วย ผู้ให้บริการอาจขอหลักฐานการยินยอมของผู้ใช้อำนาจปกครองก่อนอนุมัติ

10. การบันทึกความยินยอม
ระบบบันทึกเวอร์ชันของหนังสือนี้ ข้อที่ท่านยอมรับ เวลา IP และเบราว์เซอร์ทุกครั้งที่ท่านกดยอมรับหรือถอนความยินยอม เป็นหลักฐาน"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS actors (
  user_id TEXT PRIMARY KEY, stage_name TEXT NOT NULL, gender TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
  contact TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL, reviewed_at REAL, reviewed_by TEXT);
CREATE TABLE IF NOT EXISTS actor_consents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, version TEXT NOT NULL, text_hash TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '', accepted_at REAL NOT NULL, withdrawn_at REAL);
CREATE INDEX IF NOT EXISTS actor_consents_user ON actor_consents(user_id, id);
CREATE TABLE IF NOT EXISTS actor_voices (
  voice_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, review TEXT NOT NULL DEFAULT 'pending',
  note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, reviewed_at REAL, reviewed_by TEXT);
CREATE INDEX IF NOT EXISTS actor_voices_user ON actor_voices(user_id);
CREATE TABLE IF NOT EXISTS voice_usage (
  job_id TEXT NOT NULL, voice_id TEXT NOT NULL, actor_id TEXT NOT NULL, user_id TEXT NOT NULL DEFAULT '',
  job_name TEXT NOT NULL DEFAULT '', seconds REAL NOT NULL, lines INTEGER NOT NULL, month TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (job_id, voice_id));
CREATE INDEX IF NOT EXISTS voice_usage_actor ON voice_usage(actor_id, month);
CREATE TABLE IF NOT EXISTS actor_payouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL, month TEXT NOT NULL, amount INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT '', paid_by TEXT NOT NULL, paid_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS actor_payouts_actor ON actor_payouts(actor_id, month);
CREATE TABLE IF NOT EXISTS actor_moods (
  voice_id TEXT NOT NULL, mood TEXT NOT NULL, review TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL, reviewed_at REAL, reviewed_by TEXT, PRIMARY KEY (voice_id, mood));
CREATE TABLE IF NOT EXISTS actor_payment (
  user_id TEXT PRIMARY KEY, payee_name TEXT NOT NULL, tax_id TEXT NOT NULL, address TEXT NOT NULL,
  bank TEXT NOT NULL, account_no TEXT NOT NULL, account_name TEXT NOT NULL, updated_at REAL NOT NULL);
"""
_ready = False


def _init() -> None:
    global _ready
    if not _ready:
        from .accounts import _db, _lock
        with _lock:
            db = _db()
            db.executescript(SCHEMA)
            if "items" not in {r["name"] for r in db.execute("PRAGMA table_info(actor_consents)")}:
                db.execute("ALTER TABLE actor_consents ADD COLUMN items TEXT NOT NULL DEFAULT ''")
            if "moods" not in {r["name"] for r in db.execute("PRAGMA table_info(voice_usage)")}:
                # จำนวนประโยคที่ใช้เสียงอารมณ์แต่ละแบบ (JSON {อารมณ์: ประโยค}) แสดงให้นักพากย์เห็นว่าอารมณ์ไหนถูกใช้
                db.execute("ALTER TABLE voice_usage ADD COLUMN moods TEXT NOT NULL DEFAULT '{}'")
            if "wht" not in {r["name"] for r in db.execute("PRAGMA table_info(actor_payouts)")}:
                db.execute("ALTER TABLE actor_payouts ADD COLUMN wht INTEGER NOT NULL DEFAULT 0")
                for col in ("payee_name", "tax_id", "address"):
                    db.execute(f"ALTER TABLE actor_payouts ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        _ready = True


def month_of(ts: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts + TZ))


def consent_text() -> str:
    wht = (f" (ปัจจุบันร้อยละ {settings.actor_wht_percent:g} เมื่อจ่ายครั้งละตั้งแต่ {settings.actor_wht_min / 100:,.0f} บาท)"
           if settings.actor_wht_percent > 0 else "")
    return CONSENT_TEXT.format(version=CONSENT_VERSION, controller=settings.controller_name,
                               contact=settings.controller_contact, rate=f"{settings.actor_rate / 100:,.2f}", wht=wht)


def amount_of(seconds: float) -> int:
    """วินาที → ค่าตอบแทน (สตางค์ ปัดลง)"""
    return int(seconds / 60 * settings.actor_rate)


def wht_of(amount: int) -> int:
    """ภาษีหัก ณ ที่จ่ายของการจ่ายครั้งหนึ่ง (สตางค์ ปัดลง) ไม่ถึงขั้นต่ำ = ไม่หัก"""
    if settings.actor_wht_percent <= 0 or amount < settings.actor_wht_min:
        return 0
    return int(amount * settings.actor_wht_percent / 100)


# ---------------------------------------------------------------- ข้อมูลรับเงิน
BANKS = ("ธนาคารกรุงเทพ", "ธนาคารกสิกรไทย", "ธนาคารกรุงไทย", "ธนาคารทหารไทยธนชาต", "ธนาคารไทยพาณิชย์",
         "ธนาคารกรุงศรีอยุธยา", "ธนาคารเกียรตินาคินภัทร", "ธนาคารซีไอเอ็มบี ไทย", "ธนาคารยูโอบี",
         "ธนาคารแลนด์ แอนด์ เฮ้าส์", "ธนาคารออมสิน", "ธนาคารอาคารสงเคราะห์", "ธ.ก.ส.", "พร้อมเพย์")


def valid_tax_id(tax_id: str) -> bool:
    """เลขประจำตัวผู้เสียภาษี / เลขบัตรประชาชน 13 หลัก ตรวจหลักสุดท้าย"""
    if not re.fullmatch(r"\d{13}", tax_id):
        return False
    s = sum(int(tax_id[i]) * (13 - i) for i in range(12))
    return (11 - s % 11) % 10 == int(tax_id[12])


def payment(uid: str) -> Optional[dict]:
    _init()
    rows = _read("SELECT * FROM actor_payment WHERE user_id = ?", uid)
    return dict(rows[0]) if rows else None


def _mask(s: str) -> str:
    return "•" * max(len(s) - 4, 0) + s[-4:]


def payment_out(uid: str) -> Optional[dict]:
    """ข้อมูลรับเงินสำหรับหน้านักพากย์ ปิดเลขผู้เสียภาษีและเลขบัญชีเหลือ 4 ตัวท้าย"""
    p = payment(uid)
    if p is None:
        return None
    return {**p, "tax_id": _mask(p["tax_id"]), "account_no": _mask(p["account_no"])}


def save_payment(uid: str, payee_name: str, tax_id: str, address: str, bank: str, account_no: str,
                 account_name: str) -> dict:
    _init()
    payee_name, address, account_name = " ".join(payee_name.split()), " ".join(address.split()), " ".join(account_name.split())
    tax_id, account_no = re.sub(r"[\s-]", "", tax_id), re.sub(r"[\s-]", "", account_no)
    if len(payee_name) < 2:
        raise AccountError(400, "กรอกชื่อ-นามสกุลผู้รับเงิน (ตามบัตรประชาชน)")
    if not valid_tax_id(tax_id):
        raise AccountError(400, "เลขประจำตัวผู้เสียภาษีหรือเลขบัตรประชาชนไม่ถูกต้อง (13 หลัก)")
    if len(address) < 10:
        raise AccountError(400, "กรอกที่อยู่ตามบัตรประชาชน (ใช้ออกหนังสือรับรองการหักภาษี)")
    if bank not in BANKS:
        raise AccountError(400, "เลือกธนาคาร")
    if not re.fullmatch(r"\d{10,15}", account_no):
        raise AccountError(400, "เลขบัญชีหรือพร้อมเพย์ต้องเป็นตัวเลข 10–15 หลัก")
    if len(account_name) < 2:
        raise AccountError(400, "กรอกชื่อบัญชี")
    with _tx() as db:
        if db.execute("SELECT 1 FROM actors WHERE user_id = ? AND status != 'withdrawn'", (uid,)).fetchone() is None:
            raise AccountError(404, "ยังไม่ได้สมัครเป็นนักพากย์")
        db.execute("INSERT OR REPLACE INTO actor_payment VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (uid, payee_name[:100], tax_id, address[:300], bank, account_no, account_name[:100], time.time()))
    return payment_out(uid)


# ---------------------------------------------------------------- นักพากย์และความยินยอม
def actor(uid: str) -> Optional[dict]:
    _init()
    rows = _read("SELECT * FROM actors WHERE user_id = ?", uid)
    return dict(rows[0]) if rows else None


def consent(uid: str) -> Optional[dict]:
    """ความยินยอมล่าสุดที่ยังไม่ถอน"""
    _init()
    rows = _read("SELECT * FROM actor_consents WHERE user_id = ? AND withdrawn_at IS NULL ORDER BY id DESC LIMIT 1", uid)
    return dict(rows[0]) if rows else None


def has_consent(uid: str) -> bool:
    c = consent(uid)
    return c is not None and c["version"] == CONSENT_VERSION


def document() -> dict:
    """หนังสือยินยอมฉบับปัจจุบัน ข้อที่ต้องติ๊ก และอัตราค่าตอบแทน (อ่านได้โดยไม่ต้องล็อกอิน)"""
    return {"version": CONSENT_VERSION, "text": consent_text(), "rate": settings.actor_rate,
            "items": [{"id": k, "text": v} for k, v in CONSENT_ITEMS.items()]}


def _accept(db, uid: str, version: str, items: list[str], ip: str, ua: str) -> None:
    if version != CONSENT_VERSION:
        raise AccountError(409, "หนังสือยินยอมมีเวอร์ชันใหม่ โหลดหน้าใหม่แล้วอ่านอีกครั้ง")
    missing = [k for k in CONSENT_ITEMS if k not in items]
    if missing:
        raise AccountError(400, "ต้องติ๊กยอมรับให้ครบทุกข้อ")
    # แฮชรวมข้อความหนังสือและทุกข้อที่ติ๊ก พิสูจน์ได้ว่ายอมรับข้อความฉบับไหน
    text = "\n".join([consent_text(), *CONSENT_ITEMS.values()])
    db.execute("INSERT INTO actor_consents (user_id, version, text_hash, items, ip, user_agent, accepted_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)",
               (uid, version, hashlib.sha256(text.encode()).hexdigest(), ",".join(CONSENT_ITEMS), ip[:64], ua[:300],
                time.time()))


def apply(uid: str, stage_name: str, gender: str, bio: str, contact: str, version: str, items: list[str],
          ip: str, ua: str) -> dict:
    """สมัคร (หรือสมัครใหม่หลังถูกปฏิเสธ/ถอนตัว) พร้อมยอมรับหนังสือยินยอม รอผู้ดูแลอนุมัติ"""
    _init()
    with _tx() as db:
        old = db.execute("SELECT status FROM actors WHERE user_id = ?", (uid,)).fetchone()
        if old is not None and old["status"] in ("pending", "approved"):
            raise AccountError(409, "สมัครไว้แล้ว")
        _accept(db, uid, version, items, ip, ua)
        db.execute("INSERT OR REPLACE INTO actors (user_id, stage_name, gender, bio, contact, status, created_at) "
                   "VALUES (?, ?, ?, ?, ?, 'pending', ?)", (uid, stage_name, gender, bio, contact, time.time()))
    return actor(uid)


def accept_consent(uid: str, version: str, items: list[str], ip: str, ua: str) -> None:
    """ยอมรับหนังสือยินยอมเวอร์ชันใหม่ (เวอร์ชันเก่าไม่ถอน แต่ส่งเสียงใหม่ไม่ได้จนกว่าจะยอมรับ)"""
    _init()
    with _tx() as db:
        if db.execute("SELECT 1 FROM actors WHERE user_id = ? AND status != 'withdrawn'", (uid,)).fetchone() is None:
            raise AccountError(404, "ยังไม่ได้สมัครเป็นนักพากย์")
        _accept(db, uid, version, items, ip, ua)


def review_actor(uid: str, approve: bool, note: str, by: str) -> None:
    _init()
    with _tx() as db:
        a = db.execute("SELECT status FROM actors WHERE user_id = ?", (uid,)).fetchone()
        if a is None or a["status"] == "withdrawn":
            raise AccountError(404, "ไม่พบนักพากย์นี้")
        db.execute("UPDATE actors SET status = ?, note = ?, reviewed_at = ?, reviewed_by = ? WHERE user_id = ?",
                   ("approved" if approve else "rejected", note, time.time(), by, uid))


def withdraw(uid: str) -> list[str]:
    """ถอนความยินยอม: คืน id เสียงทั้งหมดของนักพากย์ให้ผู้เรียกลบออกจากคลัง ประวัติการใช้และการจ่ายเงินยังเก็บไว้"""
    _init()
    with _tx() as db:
        if db.execute("SELECT 1 FROM actors WHERE user_id = ?", (uid,)).fetchone() is None:
            raise AccountError(404, "ยังไม่ได้สมัครเป็นนักพากย์")
        ids = [r["voice_id"] for r in db.execute("SELECT voice_id FROM actor_voices WHERE user_id = ?", (uid,))]
        db.execute("UPDATE actor_consents SET withdrawn_at = ? WHERE user_id = ? AND withdrawn_at IS NULL",
                   (time.time(), uid))
        db.execute("UPDATE actors SET status = 'withdrawn', note = '' WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM actor_voices WHERE user_id = ?", (uid,))
        if ids:
            db.execute(f"DELETE FROM actor_moods WHERE voice_id IN ({','.join('?' * len(ids))})", ids)
    return ids


def due_total(uid: str) -> int:
    """ค่าตอบแทนที่ยังค้างจ่ายรวมทุกเดือน (สตางค์)"""
    return sum(max(r["due"], 0) for r in report(None, uid))


def export_data(uid: str) -> Optional[dict]:
    """ข้อมูลนักพากย์ของผู้ใช้ (สำเนาตาม PDPA) None = ไม่เคยสมัคร"""
    a = actor(uid)
    if a is None:
        return None
    return {"actor": a, "payment": payment(uid), "consents": consent_history(uid),
            "voices": [dict(r) for r in _read("SELECT * FROM actor_voices WHERE user_id = ?", uid)],
            "usage": [dict(r) for r in _read("SELECT voice_id, seconds, lines, month, job_name, created_at, updated_at "
                                             "FROM voice_usage WHERE actor_id = ? ORDER BY updated_at", uid)],
            "earnings": report(None, uid), "payouts": payouts(uid)}


def forget(uid: str) -> list[str]:
    """ปิดบัญชี: ถอนความยินยอม ลบข้อมูลโปรไฟล์ IP และเบราว์เซอร์ คืน id เสียงให้ผู้เรียกลบออกจากคลัง
    ยอดใช้งานและการจ่ายเงินยังเก็บไว้ตามกฎหมายบัญชีและภาษี ชื่องานที่ผู้ใช้คนนี้สร้างในบันทึกการใช้เสียงถูกลบ"""
    _init()
    ids = withdraw(uid) if actor(uid) else []
    with _tx() as db:
        db.execute("UPDATE actors SET stage_name = '', bio = '', contact = '', note = '' WHERE user_id = ?", (uid,))
        db.execute("UPDATE actor_consents SET ip = '', user_agent = '' WHERE user_id = ?", (uid,))
        db.execute("UPDATE voice_usage SET job_name = '' WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM actor_payment WHERE user_id = ?", (uid,))
    return ids


def consent_history(uid: str) -> list[dict]:
    """ทุกครั้งที่กดยอมรับและถอน (ใหม่ก่อน) สำหรับผู้ดูแลและเจ้าของข้อมูล"""
    _init()
    return [dict(r) for r in _read("SELECT version, items, text_hash, ip, user_agent, accepted_at, withdrawn_at "
                                   "FROM actor_consents WHERE user_id = ? ORDER BY id DESC", uid)]


def all_actors() -> list[dict]:
    """สำหรับผู้ดูแล: นักพากย์ทุกคนพร้อมบัญชี ความยินยอมล่าสุด และจำนวนเสียง"""
    _init()
    rows = _read("SELECT a.*, u.email, u.name AS account_name, "
                 "(SELECT COUNT(*) FROM actor_voices v WHERE v.user_id = a.user_id) AS voices, "
                 "(SELECT COUNT(*) FROM actor_voices v WHERE v.user_id = a.user_id AND v.review = 'pending') AS pending, "
                 "(SELECT version FROM actor_consents c WHERE c.user_id = a.user_id AND c.withdrawn_at IS NULL "
                 " ORDER BY c.id DESC LIMIT 1) AS consent_version, "
                 "(SELECT accepted_at FROM actor_consents c WHERE c.user_id = a.user_id AND c.withdrawn_at IS NULL "
                 " ORDER BY c.id DESC LIMIT 1) AS consent_at "
                 "FROM actors a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.created_at DESC")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- เสียงของนักพากย์
def add_voice(voice_id: str, uid: str) -> None:
    _init()
    with _tx() as db:
        db.execute("INSERT INTO actor_voices (voice_id, user_id, created_at) VALUES (?, ?, ?)",
                   (voice_id, uid, time.time()))


def resubmit_voice(voice_id: str) -> None:
    """อัดเสียงใหม่หรือเพิ่มเสียงอารมณ์: กลับไปรอตรวจ"""
    _init()
    with _tx() as db:
        db.execute("UPDATE actor_voices SET review = 'pending', note = '' WHERE voice_id = ?", (voice_id,))


def remove_voice(voice_id: str) -> None:
    _init()
    with _tx() as db:
        db.execute("DELETE FROM actor_voices WHERE voice_id = ?", (voice_id,))
        db.execute("DELETE FROM actor_moods WHERE voice_id = ?", (voice_id,))


# ---------------------------------------------------------------- เสียงอารมณ์ (ตรวจแยกทีละอารมณ์)
def add_mood(voice_id: str, mood: str) -> None:
    """นักพากย์อัดเสียงอารมณ์ใหม่หรืออัดซ้ำ: อารมณ์นั้นรอตรวจ เสียงหลักและอารมณ์อื่นใช้ได้ตามเดิม"""
    _init()
    with _tx() as db:
        db.execute("INSERT INTO actor_moods (voice_id, mood, created_at) VALUES (?, ?, ?) "
                   "ON CONFLICT (voice_id, mood) DO UPDATE SET review = 'pending', note = '', created_at = excluded.created_at, "
                   "reviewed_at = NULL, reviewed_by = NULL", (voice_id, mood, time.time()))


def remove_mood(voice_id: str, mood: str) -> None:
    _init()
    with _tx() as db:
        db.execute("DELETE FROM actor_moods WHERE voice_id = ? AND mood = ?", (voice_id, mood))


def review_mood(voice_id: str, mood: str, approve: bool, note: str, by: str) -> None:
    _init()
    with _tx() as db:
        if db.execute("SELECT 1 FROM actor_voices WHERE voice_id = ?", (voice_id,)).fetchone() is None:
            raise AccountError(404, "ไม่ใช่เสียงของนักพากย์")
        db.execute("INSERT INTO actor_moods (voice_id, mood, review, note, created_at, reviewed_at, reviewed_by) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (voice_id, mood) DO UPDATE SET review = excluded.review, "
                   "note = excluded.note, reviewed_at = excluded.reviewed_at, reviewed_by = excluded.reviewed_by",
                   (voice_id, mood, "approved" if approve else "rejected", note, time.time(), time.time(), by))


def mood_reviews() -> dict[str, dict[str, dict]]:
    """id เสียง → อารมณ์ → {review, note} (เฉพาะอารมณ์ที่ตรวจแยก)"""
    _init()
    out: dict[str, dict[str, dict]] = {}
    for r in _read("SELECT voice_id, mood, review, note FROM actor_moods"):
        out.setdefault(r["voice_id"], {})[r["mood"]] = {"review": r["review"], "note": r["note"]}
    return out


def mood_review(voice_id: str, mood: str, voice_review: Optional[str] = None) -> Optional[str]:
    """สถานะตรวจของเสียงอารมณ์ (None = ไม่ใช่เสียงของนักพากย์) ไม่มีแถว = ตามเสียงหลัก"""
    info = voice_actors().get(voice_id)
    if info is None:
        return None
    m = mood_reviews().get(voice_id, {}).get(mood)
    return m["review"] if m else (voice_review or info["review"])


def blocked_moods() -> set[tuple[str, str]]:
    """(id เสียง, อารมณ์) ที่ยังไม่ผ่านการตรวจ ห้ามใช้พากย์งานของผู้ใช้ และซ่อนจากผู้ใช้คนอื่น"""
    _init()
    return {(r["voice_id"], r["mood"]) for r in _read("SELECT voice_id, mood FROM actor_moods WHERE review != 'approved'")}


def voice_actors() -> dict[str, dict]:
    """id เสียง → {user_id, stage_name, review, note} ของเสียงที่นักพากย์อัด"""
    _init()
    rows = _read("SELECT v.voice_id, v.user_id, v.review, v.note, a.stage_name FROM actor_voices v "
                 "JOIN actors a ON a.user_id = v.user_id")
    return {r["voice_id"]: dict(r) for r in rows}


def review_voice(voice_id: str, approve: bool, note: str, by: str) -> None:
    _init()
    with _tx() as db:
        if db.execute("SELECT 1 FROM actor_voices WHERE voice_id = ?", (voice_id,)).fetchone() is None:
            raise AccountError(404, "ไม่ใช่เสียงของนักพากย์")
        db.execute("UPDATE actor_voices SET review = ?, note = ?, reviewed_at = ?, reviewed_by = ? WHERE voice_id = ?",
                   ("approved" if approve else "rejected", note, time.time(), by, voice_id))


# ---------------------------------------------------------------- บันทึกการใช้เสียงและค่าตอบแทน
def record_usage(job_id: str, owner: Optional[str], job_name: str, usage: dict[str, tuple]) -> None:
    """งานพากย์เสร็จ: usage = id เสียง → (วินาทีเสียงพากย์, จำนวนประโยค[, {อารมณ์: ประโยค}]) ของรอบนี้ แทนค่ารอบก่อนของงานเดียวกัน
    เสียงที่รอบนี้ไม่ได้ใช้แล้ว (เปลี่ยนเป็นเสียงอื่น) ลบออก เวลาใช้ครั้งแรก (เดือน) คงเดิม"""
    _init()
    owners = voice_actors()
    now = time.time()
    with _tx() as db:
        keep = []
        for voice_id, (seconds, lines, *rest) in usage.items():
            moods = json.dumps(rest[0] if rest else {}, ensure_ascii=False)
            a = owners.get(voice_id)
            if a is None or seconds <= 0:
                continue
            keep.append(voice_id)
            db.execute("INSERT INTO voice_usage (job_id, voice_id, actor_id, user_id, job_name, seconds, lines, moods, month, "
                       "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                       "ON CONFLICT (job_id, voice_id) DO UPDATE SET seconds = excluded.seconds, "
                       "lines = excluded.lines, moods = excluded.moods, job_name = excluded.job_name, updated_at = excluded.updated_at",
                       (job_id, voice_id, a["user_id"], owner or "", job_name, round(seconds, 2), lines, moods,
                        month_of(now), now, now))
        db.execute(f"DELETE FROM voice_usage WHERE job_id = ? AND voice_id NOT IN ({','.join('?' * len(keep))})",
                   (job_id, *keep))
    if keep:
        log.info("job %s: actor voice usage %s", job_id, {v: usage[v] for v in keep})


def mood_usage(uid: str) -> dict[str, dict[str, int]]:
    """id เสียงของนักพากย์ → อารมณ์ ("" = ปกติ) → จำนวนประโยคที่ถูกใช้พากย์ (รวมทุกงาน รอบล่าสุดของแต่ละงาน)"""
    _init()
    out: dict[str, dict[str, int]] = {}
    for r in _read("SELECT voice_id, lines, moods FROM voice_usage WHERE actor_id = ?", uid):
        per = out.setdefault(r["voice_id"], {})
        moods = json.loads(r["moods"] or "{}")
        for m, n in moods.items():
            per[m] = per.get(m, 0) + n
        if not moods:  # งานที่บันทึกก่อนแยกอารมณ์ นับเป็นเสียงปกติ
            per[""] = per.get("", 0) + r["lines"]
    return out


def _payable(r) -> bool:
    return r["user_id"] != r["actor_id"]


def usage_rows(uid: str, month: str) -> list[dict]:
    """รายการใช้เสียงของนักพากย์ในเดือนนั้น (ใหม่ก่อน)"""
    _init()
    rows = _read("SELECT * FROM voice_usage WHERE actor_id = ? AND month = ? ORDER BY updated_at DESC", uid, month)
    return [{**dict(r), "payable": _payable(r), "amount": amount_of(r["seconds"]) if _payable(r) else 0}
            for r in rows]


def summary(uid: str, months: int = 6) -> list[dict]:
    """ยอดของนักพากย์คนเดียว ย้อนหลังหลายเดือน (ใหม่ก่อน) สำหรับหน้านักพากย์"""
    return report(None, uid)[:months]


def report(month: Optional[str], uid: Optional[str] = None) -> list[dict]:
    """ยอดรวมต่อ (นักพากย์ × เดือน): วินาทีที่คิดเงิน วินาทีที่ใช้เอง จำนวนงาน ค่าตอบแทน จ่ายแล้ว ค้างจ่าย"""
    _init()
    where, args = [], []
    if month:
        where.append("u.month = ?"), args.append(month)
    if uid:
        where.append("u.actor_id = ?"), args.append(uid)
    sql = ("SELECT u.actor_id, u.month, a.stage_name, us.email, "
           "SUM(CASE WHEN u.user_id != u.actor_id THEN u.seconds ELSE 0 END) AS seconds, "
           "SUM(CASE WHEN u.user_id = u.actor_id THEN u.seconds ELSE 0 END) AS self_seconds, "
           "COUNT(DISTINCT CASE WHEN u.user_id != u.actor_id THEN u.job_id END) AS jobs, "
           "COUNT(DISTINCT CASE WHEN u.user_id != u.actor_id THEN u.user_id END) AS users "
           ", (SELECT COUNT(*) FROM actor_payment p WHERE p.user_id = u.actor_id) AS payee "
           "FROM voice_usage u LEFT JOIN actors a ON a.user_id = u.actor_id LEFT JOIN users us ON us.id = u.actor_id "
           + (f"WHERE {' AND '.join(where)} " if where else "") +
           "GROUP BY u.actor_id, u.month ORDER BY u.month DESC, seconds DESC")
    paid = {(r["actor_id"], r["month"]): r["paid"] for r in
            _read("SELECT actor_id, month, SUM(amount) AS paid FROM actor_payouts GROUP BY actor_id, month")}
    out = []
    for r in _read(sql, *args):
        amount = amount_of(r["seconds"])
        p = paid.get((r["actor_id"], r["month"]), 0)
        due = amount - p
        out.append({**dict(r), "seconds": round(r["seconds"], 2), "self_seconds": round(r["self_seconds"], 2),
                    "amount": amount, "paid": p, "due": due, "payee": bool(r["payee"]),
                    "wht": wht_of(due) if due > 0 else 0})
    return out


def add_payout(uid: str, month: str, note: str, by: str) -> dict:
    """บันทึกว่าจ่ายยอดค้างของเดือนนั้นแล้ว (ยอดตามการใช้งานตอนกด) หักภาษี ณ ที่จ่าย และเก็บสำเนาข้อมูลผู้รับเงิน
    คืน {amount, wht, net} (สตางค์) net = ยอดที่ต้องโอน"""
    rows = report(month, uid)
    due = rows[0]["due"] if rows else 0
    if due <= 0:
        raise AccountError(409, "ไม่มียอดค้างจ่ายของเดือนนี้")
    p = payment(uid)
    if p is None:
        raise AccountError(409, "นักพากย์ยังไม่ได้กรอกข้อมูลรับเงิน (ชื่อ เลขผู้เสียภาษี ที่อยู่ บัญชี)")
    wht = wht_of(due)
    with _tx() as db:
        db.execute("INSERT INTO actor_payouts (actor_id, month, amount, wht, payee_name, tax_id, address, note, paid_by, "
                   "paid_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (uid, month, due, wht, p["payee_name"], p["tax_id"], p["address"], note, by, time.time()))
    return {"amount": due, "wht": wht, "net": due - wht}


def wht_rows(paid_month: str) -> list[dict]:
    """การจ่ายที่หักภาษีในเดือนที่จ่ายจริง (ตามเวลาไทย) สำหรับยื่นแบบหักภาษี ณ ที่จ่ายและออกหนังสือรับรอง"""
    _init()
    return [dict(r) for r in _read("SELECT * FROM actor_payouts ORDER BY paid_at") if month_of(r["paid_at"]) == paid_month]


def payouts(uid: Optional[str] = None) -> list[dict]:
    _init()
    if uid:
        return [dict(r) for r in _read("SELECT * FROM actor_payouts WHERE actor_id = ? ORDER BY id DESC", uid)]
    return [dict(r) for r in _read("SELECT * FROM actor_payouts ORDER BY id DESC")]
