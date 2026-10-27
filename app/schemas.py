"""โครงสร้างข้อมูลที่ API รับและส่ง"""
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


TargetLang = Literal["th", "en"]
SubPosition = Literal["bottom", "top"]


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_review = "awaiting_review"  # แปลเสร็จแล้ว รอคนตรวจบทก่อนพากย์
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class SubtitleStyle(BaseModel):
    """รูปแบบซับที่ฝังลงวิดีโอ font ว่าง = ใช้ฟอนต์เริ่มต้นตามภาษาพากย์"""
    font: str = ""
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str = Field("#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    size: int = Field(48, ge=16, le=120, description="ขนาดตัวอักษร อ้างอิงวิดีโอสูง 1080 px")
    position: SubPosition = "bottom"


class Utterance(BaseModel):
    """หนึ่งประโยคพูดของตัวละครหนึ่งตัว"""
    id: int
    speaker: str
    start: float
    end: float
    source: str  # ข้อความภาษาต้นฉบับ
    # บทพากย์ในภาษาปลายทาง (ไฟล์งานเก่าเก็บไว้ในชื่อ thai)
    target: str = Field("", validation_alias=AliasChoices("target", "thai"))
    ref_reading: str = ""  # เลิกใช้แล้ว (ตอนนี้ tts.romanize สร้างคำอ่านเอง) เก็บไว้ให้อ่านไฟล์งานเก่าได้

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class UtteranceEdit(BaseModel):
    id: int
    target: Optional[str] = Field(None, validation_alias=AliasChoices("target", "thai"))
    speaker: Optional[str] = None


class SynthStats(BaseModel):
    redubbed: int = 0  # ประโยคที่พากย์ใหม่รอบล่าสุด
    reused: int = 0  # ประโยคที่ใช้เสียงเดิม


class Job(BaseModel):
    id: str
    status: JobStatus = JobStatus.queued
    stage: str = "queued"
    progress: float = 0.0
    phase: str = "analyze"  # ขั้นใหญ่ที่สั่งรันล่าสุด: analyze | synthesize | render
    filename: str
    input_path: str = ""
    source_url: Optional[str] = None
    source_lang: Optional[str] = None  # None = ตรวจภาษาอัตโนมัติ
    detected_lang: Optional[str] = None
    target_lang: TargetLang = "th"
    num_speakers: Optional[int] = None
    review: bool = False
    burn_subs: bool = False
    sub_style: Optional[SubtitleStyle] = None  # None = ใช้ค่าเริ่มต้นจากหน้าตั้งค่า
    speakers: list[str] = Field(default_factory=list)
    duration: Optional[float] = None
    synth_stats: Optional[SynthStats] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class JobCreated(BaseModel):
    id: str
    status: JobStatus


class JobOptionsUpdate(BaseModel):
    burn_subs: Optional[bool] = None
    sub_style: Optional[SubtitleStyle] = None


class RuntimeSettings(BaseModel):
    """ค่าที่ปรับได้จากหน้าเว็บ เก็บไว้ใน data/settings.json"""
    # เสียงพากย์
    voice_gain: float = Field(1.0, ge=0.0, le=2.0)
    bgm_gain: float = Field(1.0, ge=0.0, le=2.0)
    max_speedup: float = Field(1.35, ge=1.0, le=2.0)
    f5_steps: int = Field(32, ge=8, le=64)
    # ค่าเริ่มต้นตอนส่งงาน
    default_target_lang: TargetLang = "th"
    default_review: bool = True
    default_burn_subs: bool = False
    # ซับไตเติล
    sub_font_th: str = "Noto Sans Thai"
    sub_font_en: str = "Noto Sans"
    sub_color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    sub_outline_color: str = Field("#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    sub_size: int = Field(48, ge=16, le=120)
    sub_position: SubPosition = "bottom"

    def default_style(self, target_lang: str) -> SubtitleStyle:
        return SubtitleStyle(
            font=self.sub_font_en if target_lang == "en" else self.sub_font_th,
            color=self.sub_color, outline_color=self.sub_outline_color,
            size=self.sub_size, position=self.sub_position)


class RuntimeSettingsUpdate(BaseModel):
    voice_gain: Optional[float] = Field(None, ge=0.0, le=2.0)
    bgm_gain: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_speedup: Optional[float] = Field(None, ge=1.0, le=2.0)
    f5_steps: Optional[int] = Field(None, ge=8, le=64)
    default_target_lang: Optional[TargetLang] = None
    default_review: Optional[bool] = None
    default_burn_subs: Optional[bool] = None
    sub_font_th: Optional[str] = None
    sub_font_en: Optional[str] = None
    sub_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sub_outline_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sub_size: Optional[int] = Field(None, ge=16, le=120)
    sub_position: Optional[SubPosition] = None
