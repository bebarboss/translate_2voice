"""ความยินยอมของผู้ใช้: ข้อกำหนดการใช้งาน และนโยบายความเป็นส่วนตัว (PDPA) ต้องยอมรับก่อนใช้งาน, รับข่าวสาร (ไม่บังคับ)

ทุกครั้งที่กดยอมรับหรือเปลี่ยนใจ บันทึกเป็นแถวใหม่ใน user_consents (data/accounts.db) พร้อมเวอร์ชัน แฮชข้อความ
เวลา IP และเบราว์เซอร์ ไม่แก้แถวเดิม เป็นหลักฐานได้ว่าผู้ใช้ยอมรับข้อความฉบับไหนเมื่อไร
แก้ข้อความแล้วเปลี่ยน *_VERSION: ผู้ใช้ทุกคนต้องกดยอมรับฉบับใหม่ก่อนใช้งานต่อ (main.access_guard)
ร่างนี้ควรให้ทนายตรวจก่อนเปิดใช้จริง ชื่อและช่องทางติดต่อผู้ให้บริการตั้งที่ PDPA_CONTROLLER_NAME / PDPA_CONTROLLER_CONTACT
"""
import hashlib
import threading
import time
from typing import Optional

from .accounts import AccountError, _read, _tx
from .config import settings

_STATUS_TTL = 45.0
_status_cache: dict[str, tuple[float, dict]] = {}
_status_lock = threading.Lock()

TERMS_VERSION = "2026-11-07"
PRIVACY_VERSION = "2026-11-07"

TERMS = """ข้อกำหนดการใช้งาน Pakdee (ฉบับ {version})

ผู้ให้บริการ: {controller} ติดต่อ: {contact}

1. บริการ
Pakdee แปลและพากย์เสียงคลิปวิดีโอหรือเสียงด้วยระบบปัญญาประดิษฐ์ (AI) ผลงานที่ได้อาจแปลผิด ออกเสียงผิด หรือเสียงไม่เหมือนต้นฉบับ ผู้ใช้ควรตรวจก่อนนำไปใช้หรือเผยแพร่

2. สิทธิ์ในเนื้อหาที่อัปโหลด
ผู้ใช้รับรองว่าเป็นเจ้าของ หรือได้รับอนุญาตจากเจ้าของลิขสิทธิ์ของคลิป เสียง และไทม์ไลน์ที่อัปโหลดหรือส่งลิงก์ ให้นำมาแปล พากย์ และดัดแปลงได้ ผู้ใช้เป็นผู้รับผิดชอบหากมีการละเมิดลิขสิทธิ์หรือสิทธิ์อื่นของบุคคลภายนอก

3. เสียงของบุคคล
ระบบใช้เสียงของคนในคลิปเป็นตัวอย่างสร้างเสียงพากย์ ผู้ใช้ต้องได้รับอนุญาตจากเจ้าของเสียงเมื่อการใช้นั้นต้องได้รับอนุญาตตามกฎหมาย ห้ามใช้บริการเลียนเสียงบุคคลเพื่อหลอกลวง แอบอ้าง ทำให้เสียชื่อเสียง หรือสร้างเนื้อหาที่ผิดกฎหมาย

4. สิ่งที่ห้ามทำ
ห้ามอัปโหลดหรือสร้างเนื้อหาที่ผิดกฎหมาย ลามกอนาจาร ยุยงให้เกิดความรุนแรง หรือละเมิดความเป็นส่วนตัวของผู้อื่น ห้ามพยายามเข้าถึงระบบหรือข้อมูลของผู้ใช้อื่นโดยไม่ได้รับอนุญาต ผู้ให้บริการระงับบัญชีและลบเนื้อหาที่ฝ่าฝืนได้

5. ผลงาน
ผลงานพากย์ที่สร้างเป็นของผู้ใช้ ภายใต้สิทธิ์ของเจ้าของเนื้อหาต้นฉบับ ผู้ให้บริการไม่นำคลิปหรือผลงานของผู้ใช้ไปเผยแพร่ ไม่ใช้เสียงของคนในคลิปของผู้ใช้กับงานของผู้ใช้อื่น และไม่นำไปฝึกโมเดล AI เว้นแต่ผู้ใช้บันทึกเสียงนั้นลงคลังเสียงของระบบเอง

6. เครดิตและการชำระเงิน
เครดิตคิดตามความยาวคลิป ตัดเมื่อเริ่มวิเคราะห์งาน งานที่ระบบทำไม่สำเร็จคืนเครดิตให้อัตโนมัติ เครดิตที่ซื้อแล้วไม่คืนเป็นเงิน เว้นแต่กฎหมายกำหนด แพ็กเกจรายเดือนหมดอายุตามรอบ

7. ความรับผิด
ให้บริการตามสภาพที่เป็นอยู่ ผู้ให้บริการไม่รับผิดต่อความเสียหายทางอ้อมจากการใช้ผลงาน และรับผิดไม่เกินค่าบริการที่ผู้ใช้ชำระในสามเดือนล่าสุด เท่าที่กฎหมายอนุญาต

8. การเปลี่ยนแปลง
ผู้ให้บริการแก้ไขข้อกำหนดนี้ได้ ฉบับใหม่ผู้ใช้ต้องกดยอมรับก่อนใช้งานต่อ ข้อกำหนดนี้ใช้กฎหมายไทย"""

PRIVACY = """นโยบายความเป็นส่วนตัว Pakdee (ฉบับ {version})

ผู้ควบคุมข้อมูลส่วนบุคคล: {controller} ติดต่อ: {contact}

1. ข้อมูลที่เก็บ
- บัญชี: อีเมลและชื่อจากบัญชี Google
- ข้อมูลเบื้องต้นที่ท่านกรอก: ชื่อ-นามสกุล เบอร์โทร ประเภทผู้ใช้ ชื่อบริษัท และลักษณะงาน
- เนื้อหาที่อัปโหลด: คลิป เสียง ไทม์ไลน์ บทที่ถอดและแปล และผลงานพากย์
- การใช้งานและการเงิน: ประวัติงาน เครดิต การซื้อ และข้อมูลบัตรที่ผู้ให้บริการชำระเงินเก็บแทน (ระบบไม่เก็บเลขบัตร)
- ข้อมูลทางเทคนิค: IP เบราว์เซอร์ และเวลาที่กดยอมรับเอกสารนี้

2. วัตถุประสงค์และฐานทางกฎหมาย
- ให้บริการแปลและพากย์ตามที่ท่านสั่ง จัดการบัญชี เครดิต และการชำระเงิน (สัญญา)
- ติดต่อเรื่องบัญชี งาน และการชำระเงิน ป้องกันการใช้งานผิดกฎหมาย ทำบัญชีและภาษี (ประโยชน์โดยชอบด้วยกฎหมาย และหน้าที่ตามกฎหมาย)
- ส่งข่าวสารและโปรโมชัน เฉพาะเมื่อท่านเลือกรับ (ความยินยอม ถอนได้ตลอดเวลา)

3. เสียงของบุคคลในคลิป
ระบบวิเคราะห์เสียงในคลิปเพื่อแยกผู้พูดและใช้เป็นตัวอย่างพากย์ งานนั้นเท่านั้น ลักษณะเสียงที่คำนวณได้ไม่ใช้ระบุตัวบุคคล และไม่ใช้กับงานของผู้ใช้อื่น

4. ผู้ประมวลผลข้อมูลและการส่งข้อมูลไปต่างประเทศ
ข้อมูลบางส่วนถูกส่งไปประมวลผลกับผู้ให้บริการในต่างประเทศ (ส่วนใหญ่สหรัฐอเมริกา) ตามความจำเป็นของบริการ ได้แก่ Google (เข้าสู่ระบบ และแปลบทด้วย Gemini), Modal (ประมวลผลเสียงบนการ์ดจอ), Vercel (เว็บไซต์), Supabase (ฐานข้อมูล), Cloudflare (เชื่อมต่อเครือข่าย) และผู้ให้บริการชำระเงิน ผู้ให้บริการเหล่านี้ประมวลผลตามคำสั่งเท่านั้น ประเทศปลายทางอาจมีมาตรฐานคุ้มครองข้อมูลต่างจากประเทศไทย

5. ระยะเวลาเก็บ
- คลิปและผลงาน: จนกว่าท่านจะลบงาน หรือปิดบัญชี
- ข้อมูลบัญชีและข้อมูลเบื้องต้น: ตลอดที่มีบัญชี
- ประวัติการเงิน: ตามระยะเวลาที่กฎหมายบัญชีและภาษีกำหนด
- หลักฐานการยอมรับเอกสาร: ตลอดที่มีบัญชี และหลังปิดบัญชีตามอายุความที่กฎหมายกำหนด

6. สิทธิ์ของท่าน
ท่านขอเข้าถึง ขอสำเนา ขอแก้ไข ขอลบ ขอโอนย้าย ขอระงับการใช้ และคัดค้านการประมวลผลข้อมูลได้ ถอนความยินยอมรับข่าวสารได้ที่หน้าบัญชี ติดต่อตามช่องทางข้างต้น และร้องเรียนต่อสำนักงานคณะกรรมการคุ้มครองข้อมูลส่วนบุคคล (สคส.) ได้

7. ความปลอดภัย
ข้อมูลส่งผ่านการเชื่อมต่อที่เข้ารหัส เข้าถึงได้เฉพาะเจ้าของบัญชีและผู้ดูแลระบบที่จำเป็น หากเกิดเหตุข้อมูลรั่วไหลที่มีความเสี่ยง จะแจ้ง สคส. และท่านตามที่กฎหมายกำหนด"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_consents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, kind TEXT NOT NULL, version TEXT NOT NULL,
  text_hash TEXT NOT NULL DEFAULT '', accepted INTEGER NOT NULL, ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS user_consents_user ON user_consents(user_id, kind, id);
"""
_ready = False


def _init() -> None:
    global _ready
    if not _ready:
        from .accounts import _db, _lock
        with _lock:
            _db().executescript(SCHEMA)
        _ready = True


def _fill(text: str, version: str) -> str:
    return text.format(version=version, controller=settings.controller_name, contact=settings.controller_contact)


def documents() -> dict:
    return {"terms": {"version": TERMS_VERSION, "text": _fill(TERMS, TERMS_VERSION)},
            "privacy": {"version": PRIVACY_VERSION, "text": _fill(PRIVACY, PRIVACY_VERSION)}}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _latest(db, uid: str) -> dict[str, dict]:
    rows = db.execute("SELECT * FROM user_consents WHERE id IN (SELECT MAX(id) FROM user_consents WHERE user_id = ? "
                      "GROUP BY kind)", (uid,)).fetchall()
    return {r["kind"]: dict(r) for r in rows}


def status(uid: str) -> dict:
    """ยอมรับฉบับปัจจุบันครบไหม และค่าล่าสุดของแต่ละเรื่อง"""
    now = time.time()
    with _status_lock:
        hit = _status_cache.get(uid)
        if hit and hit[0] > now:
            return hit[1]
    _init()
    from .accounts import _db, _lock
    with _lock:
        last = _latest(_db(), uid)
    ok = lambda k, v: bool(last.get(k)) and last[k]["accepted"] == 1 and last[k]["version"] == v  # noqa: E731
    out = {"current": ok("terms", TERMS_VERSION) and ok("privacy", PRIVACY_VERSION),
           "marketing": bool(last.get("marketing")) and last["marketing"]["accepted"] == 1,
           "terms": last.get("terms") and {"version": last["terms"]["version"], "at": last["terms"]["created_at"]},
           "privacy": last.get("privacy") and {"version": last["privacy"]["version"], "at": last["privacy"]["created_at"]}}
    with _status_lock:
        _status_cache[uid] = (now + _STATUS_TTL, out)
    return out


def accept(uid: str, terms_version: str, privacy_version: str, marketing: Optional[bool], ip: str, ua: str) -> None:
    """ยอมรับข้อกำหนดและนโยบายฉบับปัจจุบัน (ต้องตรงเวอร์ชันที่ผู้ใช้เห็น) และตั้งค่ารับข่าวสาร (None = คงเดิม)"""
    with _status_lock:
        _status_cache.pop(uid, None)
    _init()
    if terms_version != TERMS_VERSION or privacy_version != PRIVACY_VERSION:
        raise AccountError(409, "ข้อกำหนดหรือนโยบายมีฉบับใหม่ โหลดหน้าใหม่แล้วอ่านอีกครั้ง")
    docs = documents()
    now = time.time()
    with _tx() as db:
        last = _latest(db, uid)
        rows = [("terms", TERMS_VERSION, _hash(docs["terms"]["text"]), 1),
                ("privacy", PRIVACY_VERSION, _hash(docs["privacy"]["text"]), 1)]
        before = bool(last.get("marketing")) and last["marketing"]["accepted"] == 1
        if marketing is not None and (marketing != before or "marketing" not in last):
            rows.append(("marketing", "1", "", int(marketing)))
        for kind, version, h, accepted in rows:
            prev = last.get(kind)
            if prev and prev["version"] == version and prev["accepted"] == accepted and kind != "marketing":
                continue  # ยอมรับฉบับนี้ไว้แล้ว ไม่บันทึกซ้ำ
            db.execute("INSERT INTO user_consents (user_id, kind, version, text_hash, accepted, ip, user_agent, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uid, kind, version, h, accepted, ip[:64], ua[:300], now))


def set_marketing(uid: str, on: bool, ip: str, ua: str) -> None:
    _init()
    with _tx() as db:
        db.execute("INSERT INTO user_consents (user_id, kind, version, accepted, ip, user_agent, created_at) "
                   "VALUES (?, 'marketing', '1', ?, ?, ?, ?)", (uid, int(on), ip[:64], ua[:300], time.time()))


def forget(uid: str) -> None:
    """ปิดบัญชี: ลบ IP และเบราว์เซอร์ออกจากประวัติ เหลือเวอร์ชันและเวลาที่ยอมรับ"""
    _init()
    with _tx() as db:
        db.execute("UPDATE user_consents SET ip = '', user_agent = '' WHERE user_id = ?", (uid,))


def history(uid: str) -> list[dict]:
    _init()
    return [dict(r) for r in _read("SELECT kind, version, accepted, ip, user_agent, created_at FROM user_consents "
                                   "WHERE user_id = ? ORDER BY id DESC", uid)]
