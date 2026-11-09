"""ข้อมูลไทม์ไลน์ที่นำเข้า เก็บใน data/jobs/<id>/timeline.json"""
import json
from fractions import Fraction
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

Format = Literal["fcp_xml", "fcpx_xml", "edl", "otio"]
FILE = "timeline.json"


class TimelineClip(BaseModel):
    name: str
    media: str = ""  # ที่อยู่ไฟล์ตามที่ไทม์ไลน์อ้าง (path หรือ file:// URL)
    file: Optional[str] = None  # ไฟล์ที่หาเจอ (สัมพัทธ์กับโฟลเดอร์ timeline/ ของงาน) None = ไฟล์หาย
    start: int  # เฟรมบนไทม์ไลน์ นับจากต้นไทม์ไลน์ (ไม่รวม timecode เริ่ม)
    end: int  # ไม่รวมเฟรมนี้
    source_in: int  # เฟรมของต้นฉบับตามที่ไทม์ไลน์เขียน (อาจนับจาก timecode ของไฟล์)
    source_out: int
    media_start: Optional[int] = None  # timecode เริ่มของไฟล์ (เฟรม) ถ้าไทม์ไลน์บอก ใช้หักออกจาก source_in
    channel: Optional[int] = None  # ช่องเสียงของไฟล์ที่คลิปใช้ (1 = ซ้าย/ช่องแรก) None = รวมทุกช่อง


class TimelineTrack(BaseModel):
    index: int  # ลำดับแทร็กเสียง เริ่ม 1 (A1, A2, ...)
    name: str
    clips: list[TimelineClip] = Field(default_factory=list)
    speaker: str = ""  # ผู้พูดที่แทร็กนี้เป็น (หลายแทร็กเป็นคนเดียวกันได้)
    enabled: bool = True  # False = ไม่ใช่บทพูด (เพลง เสียงประกอบ) ไม่ถอดไม่พากย์ แต่ใส่ในเสียงรวม
    duplicate_of: Optional[int] = None  # แทร็กที่มีคลิปเหมือนแทร็กนี้ทุกคลิป (สเตอริโอแยกซ้าย/ขวา) ปิดไว้ให้ก่อน


class TimelineInfo(BaseModel):
    format: Format
    source: str  # ชื่อไฟล์ไทม์ไลน์
    name: str = ""
    rate_num: int
    rate_den: int = 1
    drop_frame: bool = False
    sample_rate: int = 48000
    start: int = 0  # timecode เริ่มของไทม์ไลน์ (เฟรม) เช่น 01:00:00:00
    duration: int  # ความยาวไทม์ไลน์ (เฟรม)
    tracks: list[TimelineTrack] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)  # ไฟล์สื่อที่ไทม์ไลน์อ้างแต่ไม่ได้อัปโหลดมา
    warnings: list[str] = Field(default_factory=list)

    @property
    def rate(self) -> Fraction:
        return Fraction(self.rate_num, self.rate_den)

    @property
    def fps(self) -> float:
        return float(self.rate)

    def sec(self, frames: float) -> float:
        return float(Fraction(frames).limit_denominator(10**6) / self.rate)

    @property
    def seconds(self) -> float:
        return self.sec(self.duration)

    def dialogue(self) -> list[TimelineTrack]:
        return [t for t in self.tracks if t.enabled and t.clips]

    def speakers(self) -> list[str]:
        return sorted({t.speaker for t in self.dialogue()})


def load(job_dir: Path) -> TimelineInfo:
    return TimelineInfo.model_validate_json((job_dir / FILE).read_text(encoding="utf-8"))


def save(job_dir: Path, info: TimelineInfo) -> None:
    from ..jobs import _atomic_write
    _atomic_write(job_dir / FILE, info.model_dump_json(indent=2))


def dumps(info: TimelineInfo) -> dict:
    return json.loads(info.model_dump_json())
