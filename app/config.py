"""ค่าตั้งค่าทั้งหมดของระบบ อ่านจาก environment variables หรือไฟล์ .env"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    # ระบบทั่วไป
    data_dir: Path = Path(_env("DATA_DIR", "data")).resolve()
    api_key: str = _env("API_KEY")  # ว่างไว้ = ไม่ต้องใช้คีย์
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 500)
    mock_pipeline: bool = _bool("MOCK_PIPELINE")  # ทดสอบ API โดยไม่โหลดโมเดลจริง
    device: str = _env("DEVICE", "cuda")
    low_vram: bool = _bool("LOW_VRAM")  # การ์ดจอเล็ก: ปล่อยโมเดลทิ้งหลังใช้แต่ละขั้น ไม่โหลดค้างพร้อมกัน

    # แยกเสียงพูดกับเพลง (Demucs)
    demucs_model: str = _env("DEMUCS_MODEL", "htdemucs")

    # แยกผู้พูด (pyannote)
    hf_token: str = _env("HF_TOKEN")
    diarization_model: str = _env("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")

    # ถอดเสียง (faster-whisper)
    whisper_model: str = _env("WHISPER_MODEL", "large-v3")
    whisper_compute_type: str = _env("WHISPER_COMPUTE_TYPE", "float16")

    # แปลภาษา (Typhoon)
    typhoon_api_key: str = _env("TYPHOON_API_KEY")
    typhoon_base_url: str = _env("TYPHOON_BASE_URL", "https://api.opentyphoon.ai/v1")
    typhoon_model: str = _env("TYPHOON_MODEL", "typhoon-v2.5-30b-a3b-instruct")
    typhoon_temperature: float = _float("TYPHOON_TEMPERATURE", 0.4)
    translate_batch_size: int = _int("TRANSLATE_BATCH_SIZE", 20)
    translate_en_local: bool = _bool("TRANSLATE_EN_LOCAL")  # ใช้ Typhoon Translate บนเครื่องกับคลิปภาษาอังกฤษ
    typhoon_translate_model: str = _env("TYPHOON_TRANSLATE_MODEL", "scb10x/typhoon-translate1.5-4b")

    # พากย์เสียง (F5-TTS ภาษาไทย)
    f5_model: str = _env("F5_MODEL", "v2")  # v2 พูดชัดกว่าและมีเสียงตัวอย่างหลุดมาต้นคลิปน้อยกว่า v1
    f5_cache_dir: str = _env("F5_CACHE_DIR")  # ที่เก็บโมเดลพากย์ไทย (ว่าง = แคช Hugging Face ปกติ)
    f5_steps: int = _int("F5_STEPS", 32)
    f5_cfg: float = _float("F5_CFG", 2.0)
    f5_speed: float = _float("F5_SPEED", 1.0)
    f5_fp32: bool = _bool("F5_FP32")  # การ์ดตระกูล GTX 16xx คำนวณ float16 แล้วได้ NaN (เสียงเงียบ) ต้องเปิด
    ref_min_sec: float = _float("REF_MIN_SEC", 2.0)
    ref_max_sec: float = _float("REF_MAX_SEC", 10.0)
    # เสียงตัวอย่างต้องสะอาดอย่างน้อยเท่านี้ (PESQ ประมาณ 1–4.5) ไม่งั้นใช้ท่อนที่สะอาดกว่าของตัวละครเดียวกัน 0 = ปิด
    ref_min_quality: float = _float("REF_MIN_QUALITY", 2.3)

    # พากย์ภาษาอังกฤษ (F5-TTS รุ่นหลัก)
    f5_en_model: str = _env("F5_EN_MODEL", "F5TTS_v1_Base")
    en_words_per_sec: float = _float("EN_WORDS_PER_SEC", 2.6)

    # รับลิงก์คลิป (yt-dlp)
    max_url_minutes: float = _float("MAX_URL_MINUTES", 60)

    # ซับไตเติล: โฟลเดอร์ฟอนต์เพิ่มเติม (นอกจากฟอนต์ที่ติดตั้งในเครื่อง)
    fonts_dir: str = _env("FONTS_DIR")

    # จังหวะเวลาและการผสมเสียง
    max_line_sec: float = _float("MAX_LINE_SEC", 8.0)  # ตัดประโยคยาวกว่านี้ ให้แต่ละประโยคใช้เสียงตัวเองเป็นตัวอย่างได้
    thai_chars_per_sec: float = _float("THAI_CHARS_PER_SEC", 11.0)
    max_speedup: float = _float("MAX_SPEEDUP", 1.35)
    pause_match: bool = _bool("PAUSE_MATCH", True)  # เว้นจังหวะหยุดกลางประโยคตามต้นฉบับ (pauses.py)
    min_pause_sec: float = _float("MIN_PAUSE_SEC", 0.3)  # ช่วงเงียบสั้นกว่านี้ไม่นับเป็นจังหวะหยุด
    # ความดังของเสียงร้อง กรี๊ด อุทานจากต้นฉบับในช่วงที่ไม่มีบท (0 = ตัดทิ้ง)
    nonspeech_gain: float = _float("NONSPEECH_GAIN", 1.0)
    # กันเสียงพากย์ผิดคน (voices.py): ยืมเสียงตัวอย่างและรวมประโยคเฉพาะท่อนที่เสียงเข้ากัน
    voice_match: bool = _bool("VOICE_MATCH", True)
    voice_min_sim: float = _float("VOICE_MIN_SIM", 0.2)  # ลายเสียงคล้ายกันอย่างน้อยเท่านี้ (−1 ถึง 1)
    voice_max_pitch_diff: float = _float("VOICE_MAX_PITCH_DIFF", 6.0)  # ระดับเสียงต่างได้ไม่เกินกี่เซมิโทน
    voice_split_pitch: float = _float("VOICE_SPLIT_PITCH", 7.0)  # แยกผู้พูดเมื่อเสียงสองกลุ่มห่างกันเกินกี่เซมิโทน
    # เสียงพากย์หลุดจากเสียงตัวอย่างเกินกี่เซมิโทนให้พากย์ใหม่ และลองใหม่ได้กี่รอบ (0 = ไม่ลอง)
    voice_drift: float = _float("VOICE_DRIFT", 4.0)
    voice_retries: int = _int("VOICE_RETRIES", 1)
    # อารมณ์ตามต้นฉบับ (emotion.py): เลือกเสียงตัวอย่างที่ตื่นเต้นพอ ๆ กัน และขยายขีดเร่ง/ยืดตามอารมณ์
    emotion_match: bool = _bool("EMOTION_MATCH", True)
    ref_emotion_weight: float = _float("REF_EMOTION_WEIGHT", 0.5)
    # ความดังของเสียงพากย์ตามนักแสดง (ตะโกนดัง กระซิบเบา) ปรับขึ้นลงได้ไม่เกินกี่ dB
    loudness_match: bool = _bool("LOUDNESS_MATCH", True)
    loudness_max_boost: float = _float("LOUDNESS_MAX_BOOST", 6.0)
    loudness_max_cut: float = _float("LOUDNESS_MAX_CUT", 10.0)
    # เสียงก้องของห้องให้เสียงพากย์ (TTS แห้งเกินไป ฟังลอยไม่เข้ากับฉาก) 0 = ไม่ใส่
    room_reverb: float = _float("ROOM_REVERB", 0.2)
    room_rt60: float = _float("ROOM_RT60", 0.4)  # วินาทีที่เสียงก้องจางหาย ห้องเล็ก 0.3 ห้องโถง 1.0+
    max_slowdown: float = _float("MAX_SLOWDOWN", 1.2)  # ยืดเสียงพากย์ให้เต็มฉากได้ช้าสุดกี่เท่าของความเร็วปกติ
    # ปรับระดับและการขึ้นลงของเสียงพากย์ตามต้นฉบับ (prosody.py) ปิดไว้ก่อน: PSOLA ทำให้เสียงแตก
    # และคลิปที่มีเพลงปนวัดระดับเสียงต้นฉบับผิด (ทดสอบแล้ว PESQ ตกจาก 3.2 เหลือ 2.6)
    prosody_match: bool = _bool("PROSODY_MATCH")
    prosody_max_shift: float = _float("PROSODY_MAX_SHIFT", 4.0)  # เซมิโทน
    prosody_max_range: float = _float("PROSODY_MAX_RANGE", 1.6)  # เท่า
    voice_gain: float = _float("VOICE_GAIN", 1.0)
    bgm_gain: float = _float("BGM_GAIN", 1.0)


settings = Settings()
