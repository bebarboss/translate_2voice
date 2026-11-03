"""timecode และอัตราเฟรม: แปลงเฟรม ↔ วินาที ↔ HH:MM:SS:FF (drop-frame ใช้ ; คั่นเฟรม)

อัตรา NTSC (23.976, 29.97, 59.94) เก็บเป็นเศษส่วนจริง (24000/1001 ...) ไม่ใช่ทศนิยมที่ปัดแล้ว
OTIO เก็บ 29.97 เป็นทศนิยม ถ้าใช้ตรง ๆ คลิปยาวหนึ่งชั่วโมงเวลาคลาดราว 0.1 เฟรม
drop-frame: ข้ามเลขเฟรม 0 และ 1 (59.94 = 0–3) ทุกนาที ยกเว้นนาทีที่หารด้วย 10 ลงตัว เวลาจริงไม่ได้หายไป แค่เลขหายไป
"""
from fractions import Fraction

NTSC = {24: Fraction(24000, 1001), 30: Fraction(30000, 1001), 48: Fraction(48000, 1001), 60: Fraction(60000, 1001)}


def exact_rate(rate: float) -> Fraction:
    """29.97 → 30000/1001, 25 → 25"""
    for nominal, r in NTSC.items():
        if abs(rate - float(r)) < 0.005:
            return r
    return Fraction(rate).limit_denominator(1001)


def nominal(rate: Fraction) -> int:
    """เลขเฟรมต่อวินาทีที่ใช้นับ timecode (29.97 → 30)"""
    return round(float(rate))


def is_ntsc(rate: Fraction) -> bool:
    return rate.denominator == 1001


def can_drop(rate: Fraction) -> bool:
    return is_ntsc(rate) and nominal(rate) in (30, 60)


def _dropped(rate: Fraction) -> int:
    return 2 * nominal(rate) // 30  # 29.97 = 2 เฟรมต่อนาที, 59.94 = 4


def to_timecode(frames: int, rate: Fraction, drop: bool = False) -> str:
    fps = nominal(rate)
    sign = "-" if frames < 0 else ""
    frames = abs(int(frames))
    if drop and can_drop(rate):
        d = _dropped(rate)
        per_10min = fps * 600 - d * 9
        per_min = fps * 60 - d
        tens, rem = divmod(frames, per_10min)
        frames += d * 9 * tens + (d * ((rem - d) // per_min) if rem > d else 0)
    ff = frames % fps
    ss = frames // fps % 60
    mm = frames // (fps * 60) % 60
    hh = frames // (fps * 3600)
    sep = ";" if drop and can_drop(rate) else ":"
    return f"{sign}{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


def from_timecode(tc: str, rate: Fraction, drop: bool | None = None) -> int:
    """"01:00:00;02" → เลขเฟรม drop=None = ดูจากตัวคั่น (; หรือ . = drop-frame)"""
    tc = tc.strip()
    if drop is None:
        drop = ";" in tc or "." in tc
    hh, mm, ss, ff = (int(x) for x in tc.replace(";", ":").replace(".", ":").split(":"))
    fps = nominal(rate)
    frames = ((hh * 60 + mm) * 60 + ss) * fps + ff
    if drop and can_drop(rate):
        total_min = hh * 60 + mm
        frames -= _dropped(rate) * (total_min - total_min // 10)
    return frames


def seconds(frames: float, rate: Fraction) -> float:
    return float(Fraction(frames).limit_denominator(10**6) / rate)


def frames_at(sec: float, rate: Fraction) -> int:
    """วินาที → เฟรมที่ใกล้ที่สุด"""
    return round(Fraction(sec).limit_denominator(10**7) * rate)
