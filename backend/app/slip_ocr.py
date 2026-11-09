"""อ่านสลิปโอนเงินด้วย Typhoon OCR แล้วตัดสินว่าเติมเครดิตอัตโนมัติได้หรือต้องให้ผู้ดูแลตรวจ

ขั้นแรกเรียกโมเดล typhoon-ocr ให้ถอดข้อความทั้งใบ (รูปแบบที่โมเดลถูกสอน: JSON คีย์ natural_text)
ขั้นสองให้โมเดลข้อความดึงยอด วันเวลา เลขอ้างอิง และบัญชีผู้รับ เป็น JSON
ยอดจากป้าย "จำนวนเงิน" ในข้อความใช้ตรวจซ้ำ ถ้าสองทางไม่ตรงกันจะไม่เติมอัตโนมัติ
"""
import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

import requests

from .config import settings

OCR_PROMPT = (
    "Extract all text from this document image as if reading it naturally. "
    "Keep the reading order. Render tables as HTML. "
    'Return a JSON object with a single key "natural_text" whose value is the transcription. '
    "Do not add commentary."
)

EXTRACT_PROMPT = """จากข้อความสลิปโอนเงินด้านล่าง ตอบเป็น JSON เท่านั้น ไม่มีคำอธิบาย
คีย์:
- amount_baht: ยอดเงินที่โอนครั้งนี้ (ตัวเลข) หรือ null ถ้าไม่เห็น
- transferred_at: วันเวลาที่โอน รูปแบบ YYYY-MM-DD HH:MM หรือ null
- ref: เลขอ้างอิงรายการ หรือ null
- payer: ชื่อผู้โอน หรือ null
- payee: ชื่อผู้รับ หรือ null
- payee_account: เลขบัญชีหรือพร้อมเพย์ของผู้รับ เป็นตัวเลขล้วน หรือ null
อย่าเดา ถ้าไม่เห็นในข้อความให้ใส่ null

ข้อความ:
"""

_THAI_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}


class SlipOcrError(Exception):
    """อ่านสลิปไม่ได้ (คีย์ไม่ตั้ง โควตาเต็ม หรือบริการตอบผิด) รายการยังเก็บไว้ให้ผู้ดูแลตรวจ"""


@dataclass
class SlipRead:
    text: str
    amount: Optional[int]  # สตางค์ ที่เชื่อได้ (null ถ้าอ่านไม่ได้หรือสองทางขัดกัน)
    conflict: bool
    ref: Optional[str] = None
    payer: Optional[str] = None
    payee: Optional[str] = None
    payee_account: Optional[str] = None
    transferred_at: Optional[str] = None
    when: Optional[float] = None  # unix ถ้าแปลงวันเวลาได้

    def public(self) -> dict:
        return {
            "amount": self.amount, "ref": self.ref, "payer": self.payer, "payee": self.payee,
            "payee_account": self.payee_account, "transferred_at": self.transferred_at,
        }


def image_mime(data: bytes) -> Optional[str]:
    """รับเฉพาะ JPEG และ PNG ตามที่ Typhoon OCR รองรับ"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def baht_to_satang(value) -> Optional[int]:
    """บาท → สตางค์ ปัดที่สตางค์ ค่าที่ไม่ใช่ยอดโอน (ติดลบ ศูนย์ ใหญ่ผิดปกติ) คืน None"""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("บาท", "").replace("฿", "").strip()
    if not text or text.lower() == "null":
        return None
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0 or amount > Decimal("1000000"):
        return None
    return int(amount * 100)


def labeled_amount(text: str) -> Optional[int]:
    """ยอดจากป้ายจำนวนเงิน หรือยอดเดียวในใบที่ลงท้ายด้วยบาท หลายยอดที่ไม่ติดป้ายไม่เดา"""
    plain = re.sub(r"<[^>]+>", " ", text or "")
    labeled = re.search(
        r"(?:จำนวนเงิน|จํานวนเงิน|amount|transfer amount|ยอดเงิน|ยอดโอน).{0,48}?(\d[\d,]*\.\d{2})",
        plain, re.IGNORECASE | re.DOTALL)
    if labeled:
        return baht_to_satang(labeled.group(1))
    found: list[int] = []
    for match in re.finditer(r"(\d[\d,]*\.\d{2})\s*(?:บาท|THB|Baht)\b", plain, re.IGNORECASE):
        satang = baht_to_satang(match.group(1))
        if satang and satang not in found:
            found.append(satang)
    return found[0] if len(found) == 1 else None


def choose_amount(model: Optional[int], labeled: Optional[int]) -> tuple[Optional[int], bool]:
    """สองทางตรงกันใช้ค่านั้น ขัดกันให้คนตรวจ (conflict=True)"""
    if model and labeled and abs(model - labeled) > 1:
        return None, True
    return model or labeled, False


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def account_in_text(account: str, *parts: str) -> bool:
    """เลขบัญชีที่ตั้งไว้ (อย่างน้อย 8 หลัก) ต้องโผล่ในสลิป ทั้งแบบมีขีดและแบบติดกัน"""
    want = digits(account)
    if len(want) < 8:
        return False
    return want in digits(" ".join(parts))


def _year(number: int) -> Optional[int]:
    """ปี ค.ศ. 4 หลัก, ปี พ.ศ. 4 หลัก, หรือปี 2 หลัก (43 ขึ้นไป = พ.ศ. ย่อ เช่น 69 = 2569)"""
    if number >= 2400:
        return number - 543
    if number >= 1900:
        return number
    if 43 <= number <= 99:
        return number + 1957  # 2500 + yy - 543
    if 0 <= number <= 42:
        return 2000 + number
    return None


def parse_when(value: Optional[str]) -> Optional[float]:
    """วันเวลาบนสลิป → unix ตามนาฬิกาเครื่อง แปลงไม่ได้คืน None (ไม่ใช้เป็นเหตุปฏิเสธ)"""
    if not value:
        return None
    text = value.strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", text)
    if iso:
        year = _year(int(iso.group(1)))
        month, day = int(iso.group(2)), int(iso.group(3))
        hour = int(iso.group(4)) if iso.group(4) else 12
        minute = int(iso.group(5)) if iso.group(5) else 0
    else:
        months = "|".join(sorted((re.escape(name) for name in _THAI_MONTHS), key=len, reverse=True))
        match = re.search(
            rf"(\d{{1,2}})\s*(?:[/\-.]|\s)\s*(\d{{1,2}}|{months})\s*(?:[/\-.]|\s)\s*(\d{{2,4}})"
            rf"(?:\s+(\d{{1,2}})[:.](\d{{2}}))?",
            text)
        if not match:
            return None
        day = int(match.group(1))
        month_raw = match.group(2)
        month = int(month_raw) if month_raw.isdigit() else _THAI_MONTHS[month_raw]
        year = _year(int(match.group(3)))
        hour = int(match.group(4)) if match.group(4) else 12
        minute = int(match.group(5)) if match.group(5) else 0
    if year is None:
        return None
    try:
        return time.mktime(datetime(year, month, day, hour, minute).timetuple())
    except (OverflowError, ValueError):
        return None


def verdict(expected: int, slip: SlipRead, *, payee_account: str, max_age_hours: int,
            now: Optional[float] = None) -> tuple[bool, str]:
    """True = เติมหรือเริ่มแพ็กเกจได้เลย ยอดต้องตรงทุกสตางค์ และเลขบัญชีปลายทางต้องอยู่ในสลิป"""
    now = time.time() if now is None else now
    if slip.conflict:
        return False, "อ่านยอดจากสลิปได้สองค่าไม่ตรงกัน รอผู้ดูแลตรวจ"
    if not slip.amount:
        return False, "อ่านยอดเงินจากสลิปไม่ได้ รอผู้ดูแลตรวจ"
    if slip.amount != expected:
        return False, f"ยอดในสลิป {slip.amount / 100:,.2f} บาท ไม่ตรงกับยอดที่ต้องโอน {expected / 100:,.2f} บาท"
    if not account_in_text(payee_account, slip.text, slip.payee_account or ""):
        return False, "ไม่พบเลขบัญชีผู้รับในสลิป รอผู้ดูแลตรวจ"
    if slip.when is not None and slip.when > now + 26 * 3600:
        return False, "วันที่ในสลิปยังมาไม่ถึง รอผู้ดูแลตรวจ"
    if slip.when is not None and max_age_hours > 0 and now - slip.when > max_age_hours * 3600:
        return False, f"สลิปเก่ากว่า {max_age_hours} ชั่วโมง รอผู้ดูแลตรวจ"
    return True, "ยอดตรงกับสลิป"


def _loads_json(raw: str) -> Optional[dict]:
    text = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _opt_str(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _chat(model: str, messages: list, max_tokens: int) -> str:
    if not settings.typhoon_api_key:
        raise SlipOcrError("ยังไม่ได้ตั้ง TYPHOON_API_KEY จึงอ่านสลิปไม่ได้")
    try:
        response = requests.post(
            settings.typhoon_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {settings.typhoon_api_key}"},
            json={
                "model": model,
                "temperature": 0.1,
                "top_p": 0.6,
                "max_tokens": max_tokens,
                "repetition_penalty": 1.05,
                "messages": messages,
            },
            timeout=90,
        )
    except requests.RequestException as exc:
        raise SlipOcrError("เชื่อมต่อ Typhoon OCR ไม่ได้ ลองใหม่อีกครั้ง") from exc
    if response.status_code == 429:
        raise SlipOcrError("ระบบอ่านสลิปยุ่งอยู่ ลองใหม่ในอีกสักครู่")
    if response.status_code >= 400:
        raise SlipOcrError("อ่านสลิปไม่สำเร็จ")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SlipOcrError("อ่านสลิปไม่สำเร็จ") from exc
    return content or ""


def read_slip(image: bytes, mime: str) -> SlipRead:
    """ถอดข้อความจากรูปสลิป แล้วยอดที่เชื่อได้ (หรือ conflict ถ้าสองทางไม่ตรง)"""
    encoded = base64.b64encode(image).decode()
    raw = _chat(settings.typhoon_ocr_model, [{
        "role": "user",
        "content": [
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ],
    }], max_tokens=3000)
    parsed = _loads_json(raw)
    text = parsed.get("natural_text") if parsed and isinstance(parsed.get("natural_text"), str) else raw
    text = (text or "").strip()
    if not text:
        raise SlipOcrError("อ่านข้อความบนสลิปไม่ได้")
    fields: dict = {}
    try:
        extracted = _chat(settings.typhoon_model, [
            {"role": "user", "content": EXTRACT_PROMPT + text[:8000]},
        ], max_tokens=400)
        fields = _loads_json(extracted) or {}
    except SlipOcrError:
        fields = {}
    model_amount = baht_to_satang(fields.get("amount_baht"))
    amount, conflict = choose_amount(model_amount, labeled_amount(text))
    transferred = _opt_str(fields.get("transferred_at"))
    return SlipRead(
        text=text[:8000], amount=amount, conflict=conflict,
        ref=_opt_str(fields.get("ref")), payer=_opt_str(fields.get("payer")),
        payee=_opt_str(fields.get("payee")), payee_account=digits(fields.get("payee_account") or "") or None,
        transferred_at=transferred, when=parse_when(transferred),
    )
