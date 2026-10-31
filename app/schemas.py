"""โครงสร้างข้อมูลที่ API รับและส่ง"""
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


TargetLang = Literal["th", "en"]
# อารมณ์ของเสียงตัวอย่างเพิ่มเติมในคลัง ("" = เสียงปกติ คือเสียงตัวอย่างหลักของเสียงนั้น)
Mood = Literal["angry", "sad", "happy", "whisper", "scared"]
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
    take: int = 0  # รอบที่ผู้ใช้กดสุ่มเสียงพากย์ใหม่ (0 = รอบแรก)
    mood: str = ""  # อารมณ์ที่เลือกให้ประโยคนี้ ใช้เสียงตัวอย่างอารมณ์นั้นของเสียงในคลัง ("" = ปกติ)
    ref_reading: str = ""  # เลิกใช้แล้ว (ตอนนี้ tts.romanize สร้างคำอ่านเอง) เก็บไว้ให้อ่านไฟล์งานเก่าได้

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class UtteranceEdit(BaseModel):
    id: int
    target: Optional[str] = Field(None, validation_alias=AliasChoices("target", "thai"))
    speaker: Optional[str] = None
    take: Optional[int] = Field(None, ge=0, le=99)
    mood: Optional[Literal["", "angry", "sad", "happy", "whisper", "scared"]] = None
    start: Optional[float] = Field(None, ge=0)  # เวลาในคลิป (วินาที) ใช้ขยับช่วงที่ระบบจับเวลาเพี้ยน
    end: Optional[float] = Field(None, ge=0)


class UtteranceSplit(BaseModel):
    at: Optional[float] = Field(None, description="เวลาในคลิปที่ท่อนหลังเริ่ม (วินาที)")
    pos: Optional[int] = Field(None, ge=1, description="ตำแหน่งตัวอักษรในบทพากย์ที่ท่อนหลังเริ่ม")


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
    # ผู้พูด → id เสียงในคลังที่เลือกให้พากย์ ผู้พูดที่ไม่มีในนี้ใช้เสียงต้นฉบับของตัวเองเป็นตัวอย่าง
    voice_map: dict[str, str] = Field(default_factory=dict)
    duration: Optional[float] = None
    synth_stats: Optional[SynthStats] = None
    owner: Optional[str] = None  # id ผู้ใช้ที่สร้างงาน (เมื่อเปิดระบบบัญชี accounts.py)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class JobCreated(BaseModel):
    id: str
    status: JobStatus


class JobOptionsUpdate(BaseModel):
    burn_subs: Optional[bool] = None
    sub_style: Optional[SubtitleStyle] = None


# ---------------------------------------------------------------- คลังเสียง
Gender = Literal["male", "female", ""]  # "" = ไม่ระบุ (ระบบเดาจากระดับเสียงให้)


class VoiceStatus(str, Enum):
    processing = "processing"  # รอคิวหรือกำลังทำความสะอาด ตัดท่อน ถอดข้อความ
    ready = "ready"
    failed = "failed"


class VoiceMood(BaseModel):
    """เสียงตัวอย่างอารมณ์หนึ่งของเสียงในคลัง (คนพากย์คนเดียวกับเสียงหลัก) เก็บใน data/voices/<id>/moods/<mood>/"""
    mood: Mood
    status: VoiceStatus = VoiceStatus.processing
    stage: str = "queued"
    error: Optional[str] = None
    filename: str = ""
    text: str = ""
    duration: Optional[float] = None
    quality: Optional[float] = None


class LibraryVoice(BaseModel):
    """เสียงภาษาไทยในคลัง ใช้เป็นเสียงตัวอย่างให้ F5-TTS พากย์ตัวละครแทนเสียงต้นฉบับ"""
    id: str
    name: str
    gender: Gender = ""
    tone: str = ""  # โทนเสียง เช่น ทุ้มลึก นุ่มนวล สดใส
    status: VoiceStatus = VoiceStatus.processing
    stage: str = "queued"
    error: Optional[str] = None
    filename: str = ""  # ชื่อไฟล์ที่อัปโหลด
    text: str = ""  # ข้อความที่พูดในเสียงตัวอย่าง ต้องตรงกับเสียงจริง F5-TTS ถึงจะพากย์ไม่เพี้ยน
    duration: Optional[float] = None  # ความยาวเสียงตัวอย่าง (วินาที)
    pitch_hz: Optional[float] = None  # ระดับเสียงกลาง
    quality: Optional[float] = None  # ความสะอาด (ประมาณ PESQ 1–4.5)
    moods: list[VoiceMood] = Field(default_factory=list)  # เสียงตัวอย่างอารมณ์อื่น ๆ
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class LibraryVoiceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    gender: Optional[Gender] = None
    tone: Optional[str] = Field(None, max_length=80)
    text: Optional[str] = Field(None, min_length=1)


class VoiceMoodUpdate(BaseModel):
    text: str = Field(..., min_length=1)


class VoiceSuggestion(BaseModel):
    voice_id: str
    score: float  # ความใกล้เคียง 0–1


class SpeakerVoice(BaseModel):
    """เสียงที่เลือกและเสียงแนะนำของตัวละครหนึ่งตัว"""
    speaker: str
    voice_id: Optional[str] = None  # None = ใช้เสียงต้นฉบับ
    pitch_hz: Optional[float] = None
    gender: Gender = ""  # เดาจากระดับเสียง
    suggestions: list[VoiceSuggestion] = Field(default_factory=list)  # ใกล้ที่สุดก่อน


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
