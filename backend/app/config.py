"""ค่าตั้งค่าระบบ

ความลับและค่าที่ขึ้นกับเครื่อง/โดเมน → .env
ค่าคอนฟิกทั่วไป → defaults.py + audio_constants.py
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import audio_constants as audio
from . import defaults as d

# backend/app/config.py → รากโปรเจกต์ (มี .env, data/)
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
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


# แพ็กเกจเริ่มต้น (ทับด้วย BILLING_PLANS เป็น JSON ได้) — ราคาเป็นสตางค์
_DEFAULT_BILLING_PLANS: list[dict[str, Any]] = [
    {
        "id": "trial", "name": "ทดลอง", "price": 0, "minutes": 2, "days": 30,
        "max_clip_minutes": 2, "voices": "standard", "timeline": False, "watermark": True,
        "free_once": True,
        "features": [
            "ฟรี 2 เครดิต ครั้งเดียวต่อบัญชี",
            "คลิปยาวสุด 2 นาที",
            "เสียง Standard (ที่แอดมินเพิ่ม)",
            "ดาวน์โหลดมีลายน้ำ",
        ],
    },
    {
        "id": "starter", "name": "เริ่มต้น", "price": 299_00, "minutes": 60, "days": 30,
        "max_clip_minutes": 30, "voices": "all", "timeline": False, "watermark": False,
        "free_once": False,
        "features": [
            "60 เครดิต / 30 วัน",
            "คลิปยาวสุด 30 นาที",
            "เลือกเสียงได้ทั้งหมด",
            "ไม่มีลายน้ำ",
        ],
    },
    {
        "id": "pro", "name": "มือโปร", "price": 990_00, "minutes": 220, "days": 30,
        "max_clip_minutes": 60, "voices": "all", "timeline": False, "watermark": False,
        "free_once": False,
        "available": False,
        "features": [
            "220 เครดิต / 30 วัน",
            "คลิปยาวสุด 60 นาที",
            "เลือกเสียงได้ทั้งหมด",
            "นำเข้าไทม์ไลน์ (อยู่ระหว่างพัฒนา)",
        ],
    },
]


def _billing_plans() -> list[dict[str, Any]]:
    raw = _env("BILLING_PLANS")
    if not raw:
        return list(_DEFAULT_BILLING_PLANS)
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise RuntimeError("BILLING_PLANS ต้องเป็น JSON array ของแพ็กเกจ")
    return data


@dataclass(frozen=True)
class Settings:
    # ----- จาก .env (ความลับ / เครื่อง / โดเมน) -----
    data_dir: Path = Path(_env("DATA_DIR") or str(_REPO_ROOT / "data")).resolve()
    api_key: str = _env("API_KEY")
    backup_dir: Path = Path(
        _env("BACKUP_DIR") or str(Path(_env("DATA_DIR") or str(_REPO_ROOT / "data")) / "backups")
    ).resolve()
    smtp_host: str = _env("SMTP_HOST")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str = _env("SMTP_USER")
    smtp_password: str = _env("SMTP_PASSWORD")
    mail_from: str = _env("MAIL_FROM")
    web_url: str = _env("WEB_URL")
    mock_pipeline: bool = _bool("MOCK_PIPELINE")
    device: str = _env("DEVICE", "cuda")
    low_vram: bool = _bool("LOW_VRAM")
    # postgres = Postgres บน VPS/local | files = JSON ในเครื่อง
    # ค่า supabase ยังรับได้ชั่วคราว (ชื่อเก่า)
    db_backend: str = _env("DB_BACKEND", "postgres").lower()
    # DATABASE_URL ชื่อหลัก; SUPABASE_DB_URL = ชื่อเก่าที่ยังอ่านได้
    supabase_db_url: str = _env("DATABASE_URL") or _env("SUPABASE_DB_URL")
    auth_enabled: bool = _bool("AUTH_ENABLED", True)
    billing_enabled: bool = _bool("BILLING_ENABLED", True)
    # Swagger / ReDoc / openapi.json — ปิดเป็นค่าเริ่มต้น เพื่อไม่ให้ schema หลุดบน production
    # เปิดเฉพาะเครื่องพัฒนา: API_DOCS_ENABLED=1
    api_docs_enabled: bool = _bool("API_DOCS_ENABLED", False)
    google_client_id: str = _env("GOOGLE_CLIENT_ID")
    admin_emails: tuple = tuple(e.strip().lower() for e in _env("ADMIN_EMAILS").split(",") if e.strip())
    payment_provider: str = _env("PAYMENT_PROVIDER").lower()
    payee_name: str = _env("PAYEE_NAME")
    payee_bank: str = _env("PAYEE_BANK")
    payee_account: str = _env("PAYEE_ACCOUNT")
    stripe_secret_key: str = _env("STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = _env("STRIPE_WEBHOOK_SECRET")
    stripe_publishable_key: str = _env("STRIPE_PUBLISHABLE_KEY")
    controller_name: str = _env("PDPA_CONTROLLER_NAME", "[ชื่อผู้ให้บริการ]")
    controller_contact: str = _env("PDPA_CONTROLLER_CONTACT", "[อีเมลหรือช่องทางติดต่อ]")
    worker: str = _env("WORKER", d.WORKER).lower()
    hf_token: str = _env("HF_TOKEN")
    typhoon_api_key: str = _env("TYPHOON_API_KEY")
    typhoon_base_url: str = _env("TYPHOON_BASE_URL", d.TYPHOON_BASE_URL)
    typhoon_model: str = _env("TYPHOON_MODEL", d.TYPHOON_MODEL)
    typhoon_reasoning_effort: str = _env("TYPHOON_REASONING_EFFORT", d.TYPHOON_REASONING_EFFORT)
    f5_cache_dir: str = _env("F5_CACHE_DIR")
    f5_fp32: bool = _bool("F5_FP32", d.F5_FP32)
    fonts_dir: str = _env("FONTS_DIR")
    r2_enabled: bool = _bool("R2_ENABLED")
    r2_account_id: str = _env("R2_ACCOUNT_ID")
    r2_access_key_id: str = _env("R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = _env("R2_SECRET_ACCESS_KEY")
    r2_bucket: str = _env("R2_BUCKET")
    r2_endpoint: str = _env("R2_ENDPOINT")
    r2_purge_local: bool = _bool("R2_PURGE_LOCAL", d.R2_PURGE_LOCAL)
    free_retention_days: int = d.FREE_RETENTION_DAYS

    # ----- จาก defaults.py / audio_constants.py -----
    backup_hours: int = d.BACKUP_HOURS
    backup_keep: int = d.BACKUP_KEEP
    notify_min_seconds: int = d.NOTIFY_MIN_SECONDS
    max_upload_mb: int = d.MAX_UPLOAD_MB
    mock_delay: float = d.MOCK_DELAY
    typhoon_ocr_model: str = d.TYPHOON_OCR_MODEL
    slip_max_mb: int = d.SLIP_MAX_MB
    slip_max_age_hours: int = d.SLIP_MAX_AGE_HOURS
    credit_price_satang: int = d.CREDIT_PRICE_SATANG
    credit_packs: tuple = d.CREDIT_PACKS
    plan_credit_rollover: int = d.PLAN_CREDIT_ROLLOVER
    watermark_text: str = d.WATERMARK_TEXT
    actor_rate: int = d.ACTOR_RATE_SATANG_PER_MIN
    actor_wht_percent: float = d.ACTOR_WHT_PERCENT
    actor_wht_min: int = d.ACTOR_WHT_MIN_SATANG
    actor_income_type: str = d.ACTOR_INCOME_TYPE
    modal_app: str = d.MODAL_APP
    modal_max_jobs: int = d.MODAL_MAX_JOBS
    modal_tts_batch: int = d.MODAL_TTS_BATCH
    analyze_chunk_sec: float = d.ANALYZE_CHUNK_SEC
    analyze_chunk_overlap_sec: float = d.ANALYZE_CHUNK_OVERLAP_SEC
    analyze_chunk_min_sec: float = d.ANALYZE_CHUNK_MIN_SEC
    analyze_fast: bool = d.ANALYZE_FAST
    analyze_fast_whisper: str = d.ANALYZE_FAST_WHISPER
    light_workers: int = d.LIGHT_WORKERS
    user_max_jobs: int = d.USER_MAX_JOBS
    user_max_queued: int = d.USER_MAX_QUEUED
    separator: str = d.SEPARATOR
    separator_model: str = d.SEPARATOR_MODEL
    denoise_model: str = d.DENOISE_MODEL
    separator_overlap: int = d.SEPARATOR_OVERLAP
    demucs_model: str = d.DEMUCS_MODEL
    diarization_model: str = d.DIARIZATION_MODEL
    whisper_model: str = d.WHISPER_MODEL
    whisper_compute_type: str = d.WHISPER_COMPUTE_TYPE
    whisper_vad_threshold: float = d.WHISPER_VAD_THRESHOLD
    whisper_vad_min_speech_ms: int = d.WHISPER_VAD_MIN_SPEECH_MS
    whisper_vad_min_silence_ms: int = d.WHISPER_VAD_MIN_SILENCE_MS
    whisper_vad_speech_pad_ms: int = d.WHISPER_VAD_SPEECH_PAD_MS
    whisper_fill_gap_sec: float = d.WHISPER_FILL_GAP_SEC
    auto_heal_asr: bool = d.AUTO_HEAL_ASR
    auto_knobs: bool = d.AUTO_KNOBS
    typhoon_temperature: float = d.TYPHOON_TEMPERATURE
    translate_batch_size: int = d.TRANSLATE_BATCH_SIZE
    translate_en_local: bool = d.TRANSLATE_EN_LOCAL
    typhoon_translate_model: str = d.TYPHOON_TRANSLATE_MODEL
    f5_model: str = d.F5_MODEL
    f5_steps: int = audio.F5_STEPS
    f5_cfg: float = audio.F5_CFG
    f5_speed: float = audio.F5_SPEED
    ref_min_sec: float = audio.REF_MIN_SEC
    ref_max_sec: float = audio.REF_MAX_SEC
    ref_min_quality: float = audio.REF_MIN_QUALITY
    f5_en_model: str = d.F5_EN_MODEL
    en_words_per_sec: float = audio.EN_WORDS_PER_SEC
    max_url_minutes: float = d.MAX_URL_MINUTES
    max_line_sec: float = audio.MAX_LINE_SEC
    thai_chars_per_sec: float = audio.THAI_CHARS_PER_SEC
    max_speedup: float = audio.MAX_SPEEDUP
    fit_tolerance: float = d.FIT_TOLERANCE
    fit_min_ratio: float = d.FIT_MIN_RATIO
    fit_slack: float = d.FIT_SLACK
    story_analysis: bool = d.STORY_ANALYSIS
    story_content_type: bool = d.STORY_CONTENT_TYPE
    translate_neighbors: bool = d.TRANSLATE_NEIGHBORS
    fit_neighbors: bool = d.FIT_NEIGHBORS
    translate_review: bool = d.TRANSLATE_REVIEW
    pause_match: bool = audio.PAUSE_MATCH
    min_pause_sec: float = audio.MIN_PAUSE_SEC
    pause_pack: bool = audio.PAUSE_PACK
    pause_pack_min_sec: float = audio.PAUSE_PACK_MIN_SEC
    pause_pack_max_sec: float = audio.PAUSE_PACK_MAX_SEC
    pause_pack_ratio: float = audio.PAUSE_PACK_RATIO
    lip_sync_same_lang: bool = d.LIP_SYNC_SAME_LANG
    transcript_gate: bool = d.TRANSCRIPT_GATE
    ai_fix_suspects: bool = d.AI_FIX_SUSPECTS
    ai_dub_judge: bool = d.AI_DUB_JUDGE
    ai_fill_empty: bool = d.AI_FILL_EMPTY
    ai_naturalize: bool = d.AI_NATURALIZE
    ai_speak_latin: bool = d.AI_SPEAK_LATIN
    nonspeech_gain: float = audio.NONSPEECH_GAIN
    breath_keep: bool = audio.BREATH_KEEP
    voice_match: bool = audio.VOICE_MATCH
    voice_min_sim: float = audio.VOICE_MIN_SIM
    voice_max_pitch_diff: float = audio.VOICE_MAX_PITCH_DIFF
    voice_split_pitch: float = audio.VOICE_SPLIT_PITCH
    voice_profile_min_sec: float = audio.VOICE_PROFILE_MIN_SEC
    diar_refine: bool = d.DIAR_REFINE
    diar_exclusive: bool = d.DIAR_EXCLUSIVE
    overlap_recover: bool = d.OVERLAP_RECOVER
    retranscribe_noisy: bool = d.RETRANSCRIBE_NOISY
    min_coverage_synthesize: float = d.MIN_COVERAGE_SYNTHESIZE
    turn_split: bool = d.TURN_SPLIT
    turn_split_sim: float = d.TURN_SPLIT_SIM
    voice_max_input_min: int = d.VOICE_MAX_INPUT_MIN
    second_denoise: bool = d.SECOND_DENOISE
    diar_merge_sim: float = d.DIAR_MERGE_SIM
    voice_drift: float = audio.VOICE_DRIFT
    voice_retries: int = audio.VOICE_RETRIES
    dub_check: bool = d.DUB_CHECK
    dub_check_min: float = d.DUB_CHECK_MIN
    dub_check_retries: int = d.DUB_CHECK_RETRIES
    emotion_match: bool = audio.EMOTION_MATCH
    ref_emotion_weight: float = audio.REF_EMOTION_WEIGHT
    loudness_match: bool = audio.LOUDNESS_MATCH
    loudness_max_boost: float = audio.LOUDNESS_MAX_BOOST
    loudness_max_cut: float = audio.LOUDNESS_MAX_CUT
    room_reverb: float = audio.ROOM_REVERB
    room_rt60: float = audio.ROOM_RT60
    max_slowdown: float = audio.MAX_SLOWDOWN
    thai_syllables_per_sec: float = audio.THAI_SYLLABLES_PER_SEC
    prosody_match: bool = audio.PROSODY_MATCH
    prosody_max_shift: float = audio.PROSODY_MAX_SHIFT
    prosody_max_range: float = audio.PROSODY_MAX_RANGE
    voice_gain: float = audio.VOICE_GAIN
    bgm_gain: float = audio.BGM_GAIN


settings = Settings()


def fastapi_docs_kwargs(enabled: bool) -> dict[str, str | None]:
    """เส้นทางเอกสาร API ให้ FastAPI

    None = ไม่ลงทะเบียนเส้นทางนั้น เลยตอบ 404
    เปิดด้วย API_DOCS_ENABLED ตอนพัฒนา ค่าเริ่มต้นปิด
    """
    if enabled:
        return {
            "docs_url": "/docs",
            "redoc_url": "/redoc",
            "openapi_url": "/openapi.json",
        }
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def using_postgres() -> bool:
    """True เมื่อเก็บบัญชี/งานบน Postgres (ไม่ใช่โหมด files)"""
    backend = settings.db_backend
    if backend == "supabase":  # ชื่อเก่า
        backend = "postgres"
    return backend == "postgres" and bool((settings.supabase_db_url or "").strip())


def billing_plan_dicts() -> list[dict[str, Any]]:
    return _billing_plans()
