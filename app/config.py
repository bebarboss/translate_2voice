"""ค่าตั้งค่าทั้งหมดของระบบ อ่านจาก environment variables หรือไฟล์ .env"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


# แพ็กเกจเริ่มต้น (ทับด้วย BILLING_PLANS เป็น JSON ได้) — ราคาเป็นสตางค์
_DEFAULT_BILLING_PLANS: list[dict[str, Any]] = [
    {
        "id": "trial", "name": "ทดลอง", "price": 0, "minutes": 5, "days": 30,
        "max_clip_minutes": 2, "voices": "standard", "timeline": False, "watermark": True,
        "free_once": True,
        "features": [
            "ฟรี 5 เครดิต ครั้งเดียวต่อบัญชี",
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
        # ปิดขายชั่วคราว — นำเข้าไทม์ไลน์ยังพัฒนาอยู่
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


def _credit_packs() -> tuple[int, ...]:
    raw = _env("CREDIT_PACKS", "10,30,60,100")
    return tuple(int(x.strip()) for x in raw.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    # ระบบทั่วไป
    data_dir: Path = Path(_env("DATA_DIR", "data")).resolve()
    api_key: str = _env("API_KEY")  # ว่างไว้ = ไม่ต้องใช้คีย์
    # สำรองข้อมูลอัตโนมัติ (backup.py): ปลายทาง ทุกกี่ชั่วโมง (0 = ปิด) และเก็บกี่ชุดล่าสุด
    backup_dir: Path = Path(_env("BACKUP_DIR") or Path(_env("DATA_DIR", "data")) / "backups").resolve()
    backup_hours: int = _int("BACKUP_HOURS", 24)
    backup_keep: int = _int("BACKUP_KEEP", 14)
    # อีเมลแจ้งเตือน (notify.py) ผ่าน SMTP ไม่ตั้ง SMTP_HOST / MAIL_FROM = ไม่ส่ง พอร์ต 465 = SSL, อื่น ๆ = STARTTLS
    smtp_host: str = _env("SMTP_HOST")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str = _env("SMTP_USER")
    smtp_password: str = _env("SMTP_PASSWORD")
    mail_from: str = _env("MAIL_FROM")
    web_url: str = _env("WEB_URL")  # ที่อยู่หน้าเว็บ ใช้ทำลิงก์ในอีเมล เช่น https://<โปรเจกต์>.vercel.app
    notify_min_seconds: int = _int("NOTIFY_MIN_SECONDS", 120)  # งานที่เสร็จเร็วกว่านี้ไม่ส่งอีเมล
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 500)
    mock_pipeline: bool = _bool("MOCK_PIPELINE")  # ทดสอบ API โดยไม่โหลดโมเดลจริง
    device: str = _env("DEVICE", "cuda")
    low_vram: bool = _bool("LOW_VRAM")  # การ์ดจอเล็ก: ปล่อยโมเดลทิ้งหลังใช้แต่ละขั้น ไม่โหลดค้างพร้อมกัน
    # ที่เก็บข้อมูล: files = ไฟล์ JSON ใน data/ (เดิม), supabase = ฐานข้อมูล Supabase
    # ย้ายแล้ว: ค่าตั้งระบบ คลังเสียง ความจำคำแปล และบัญชี (schema studio ผ่าน SUPABASE_DB_URL)
    # งานและโปรเจกต์ยังเป็นไฟล์ JSON ค่าตั้งกับคลังเสียงยังเขียนไฟล์สำรองไว้ด้วย
    db_backend: str = _env("DB_BACKEND", "files").lower()
    supabase_url: str = _env("SUPABASE_URL")
    # คีย์เซิร์ฟเวอร์: แบบเดิม (JWT service_role) หรือแบบใหม่ (sb_secret_...)
    supabase_key: str = _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_SECRET_KEY")
    supabase_db_url: str = _env("SUPABASE_DB_URL")  # Postgres โดยตรง สำหรับบัญชี/งาน/โปรเจกต์ (schema studio)

    # บัญชีผู้ใช้และการเก็บเงิน (accounts.py) ยังไม่เปิดใช้งาน
    auth_enabled: bool = _bool("AUTH_ENABLED")  # ต้องล็อกอิน แต่ละคนเห็นเฉพาะงานของตัวเอง
    billing_enabled: bool = _bool("BILLING_ENABLED")  # กระเป๋าเงิน แพ็กเกจ และตัดนาทีต่องาน (ต้องเปิด AUTH_ENABLED ด้วย)
    google_client_id: str = _env("GOOGLE_CLIENT_ID")  # OAuth Client ID (Web) สำหรับปุ่มเข้าสู่ระบบด้วย Google
    admin_emails: tuple = tuple(e.strip().lower() for e in _env("ADMIN_EMAILS").split(",") if e.strip())
    payment_provider: str = _env("PAYMENT_PROVIDER").lower()  # ว่าง/mock/slip/stripe
    # บัญชีรับโอนเมื่อ PAYMENT_PROVIDER=slip (เลขบัญชีอย่างน้อย 8 หลัก ใช้ตรวจว่าสลิปโอนมาบัญชีนี้)
    payee_name: str = _env("PAYEE_NAME")
    payee_bank: str = _env("PAYEE_BANK")
    payee_account: str = _env("PAYEE_ACCOUNT")
    typhoon_ocr_model: str = _env("TYPHOON_OCR_MODEL", "typhoon-ocr")
    slip_max_mb: int = _int("SLIP_MAX_MB", 8)
    slip_max_age_hours: int = _int("SLIP_MAX_AGE_HOURS", 72)  # สลิปที่อ่านวันเวลาได้และเก่ากว่านี้ไม่เติมอัตโนมัติ
    # Stripe Checkout (https://docs.stripe.com/keys): secret + webhook signing secret อยู่ฝั่งเซิร์ฟเวอร์เท่านั้น
    stripe_secret_key: str = _env("STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = _env("STRIPE_WEBHOOK_SECRET")
    stripe_publishable_key: str = _env("STRIPE_PUBLISHABLE_KEY")  # ไม่จำเป็นสำหรับ Checkout แบบ redirect
    # แพ็กเกจและเครดิต (accounts.py / BILLING_PLANS) — ราคาเครดิตเติมเป็นสตางค์
    credit_price_satang: int = _int("CREDIT_PRICE_SATANG", 700)  # 7 บาท/เครดิต
    credit_packs: tuple = _credit_packs()
    plan_credit_rollover: int = _int("PLAN_CREDIT_ROLLOVER", 1)  # ทบเครดิตแพ็กเกจได้ไม่เกินกี่รอบของแพ็กใหม่
    watermark_text: str = _env("WATERMARK_TEXT", "Pakdee")
    # นักพากย์ (actors.py): ค่าตอบแทนต่อนาทีที่เสียงถูกใช้พากย์ (สตางค์) และผู้ควบคุมข้อมูลในหนังสือยินยอม PDPA
    actor_rate: int = _int("ACTOR_RATE_SATANG_PER_MIN", 200)
    # ภาษีหัก ณ ที่จ่ายค่าตอบแทนนักพากย์: กี่เปอร์เซ็นต์ (0 = ไม่หัก) หักเมื่อจ่ายครั้งละตั้งแต่กี่สตางค์ และประเภทเงินได้ในรายงาน
    # ค่าเริ่มต้นเป็นแนวปฏิบัติทั่วไปกับฟรีแลนซ์ ตรวจกับนักบัญชีก่อนใช้จริง
    actor_wht_percent: float = float(_env("ACTOR_WHT_PERCENT", "3"))
    actor_wht_min: int = _int("ACTOR_WHT_MIN_SATANG", 100_000)
    actor_income_type: str = _env("ACTOR_INCOME_TYPE", "40(2)")
    controller_name: str = _env("PDPA_CONTROLLER_NAME", "[ชื่อผู้ให้บริการ]")
    controller_contact: str = _env("PDPA_CONTROLLER_CONTACT", "[อีเมลหรือช่องทางติดต่อ]")

    # ที่รันขั้นที่ใช้การ์ดจอ (pipeline/gpu.py): local = เครื่องนี้, modal = Modal GPU L4 (ไฟล์งานยังอยู่ใน data/)
    worker: str = _env("WORKER", "local").lower()
    modal_app: str = _env("MODAL_APP", "dubbing-gpu")  # ชื่อแอปที่ modal deploy ไว้ (ตรงกับ modal_app.py)
    modal_max_jobs: int = _int("MODAL_MAX_JOBS", 4)  # จำนวนงานที่ส่ง Modal พร้อมกันได้
    modal_tts_batch: int = _int("MODAL_TTS_BATCH", 40)  # ประโยคต่อชุดที่ส่งพากย์ (หลายชุดรันพร้อมกันคนละ GPU)
    # คิวงานหลายผู้ใช้ (jobs.Worker)
    light_workers: int = _int("LIGHT_WORKERS", 2)  # งานเบา (ฝังซับ แปลใหม่) รันพร้อมกันได้กี่งาน แยกจากงานหนัก
    user_max_jobs: int = _int("USER_MAX_JOBS", 2)  # ผู้ใช้หนึ่งคนรันงานหนักพร้อมกันได้กี่งาน (0 = ไม่จำกัด)
    user_max_queued: int = _int("USER_MAX_QUEUED", 10)  # ผู้ใช้หนึ่งคนมีงานรอคิวรวมที่กำลังรันได้กี่งาน (0 = ไม่จำกัด)

    # แยกเสียงพูดกับเพลง: roformer (BS-RoFormer ผ่าน audio-separator ได้เสียงพูดสะอาดกว่ามาก) หรือ demucs
    # roformer โหลดไม่ได้หรือแยกไม่สำเร็จ จะใช้ Demucs แทนอัตโนมัติ
    separator: str = _env("SEPARATOR", "roformer")
    separator_model: str = _env("SEPARATOR_MODEL", "model_bs_roformer_ep_317_sdr_12.9755.ckpt")
    # ลดเสียงรบกวนในเสียงคลัง (เลือกได้ตอนเพิ่มเสียง) ใช้หลังแยกเพลง: Mel-Roformer-Denoise ผ่าน audio-separator ชุดเดิม
    denoise_model: str = _env("DENOISE_MODEL", "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt")
    # จำนวนหน้าต่างที่ซ้อนกันตอนแยก (ค่าเริ่มต้นของไลบรารีคือ 8 ช้ามาก 2 เร็วกว่าราว 4 เท่า คุณภาพต่างกันน้อยมาก)
    separator_overlap: int = _int("SEPARATOR_OVERLAP", 2)
    demucs_model: str = _env("DEMUCS_MODEL", "htdemucs")

    # แยกผู้พูด (pyannote)
    hf_token: str = _env("HF_TOKEN")
    # community-1 (pyannote 4) นับจำนวนคนแม่นกว่า 3.1 มาก โดยเฉพาะคลิปที่มีเพลงประกอบ ถ้าโหลดไม่ได้จะใช้ 3.1 แทน
    diarization_model: str = _env("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")

    # ถอดเสียง (faster-whisper)
    whisper_model: str = _env("WHISPER_MODEL", "large-v3")
    whisper_compute_type: str = _env("WHISPER_COMPUTE_TYPE", "float16")

    # แปลภาษา (Typhoon)
    typhoon_api_key: str = _env("TYPHOON_API_KEY")
    typhoon_base_url: str = _env("TYPHOON_BASE_URL", "https://api.opentyphoon.ai/v1")
    typhoon_model: str = _env("TYPHOON_MODEL", "typhoon-v2.5-30b-a3b-instruct")
    typhoon_temperature: float = _float("TYPHOON_TEMPERATURE", 0.4)
    # ใช้ผู้ให้บริการอื่นที่เรียกแบบ OpenAI ได้ (เช่น Gemini: base_url .../v1beta/openai/) รุ่นที่คิดก่อนตอบ
    # ควรตั้ง none ไม่งั้นการคิดกินโควตาความยาวคำตอบจน JSON ขาด (ว่าง = ไม่ส่งค่านี้)
    typhoon_reasoning_effort: str = _env("TYPHOON_REASONING_EFFORT", "")
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
    # ย่อบทตั้งแต่ตอนแปล ถ้าคาดว่าต้องพูดเร็วกว่าปกติเกินเท่านี้ (1.1 = ยอมเร็วขึ้น 10%) ไม่รอให้ต้องเร่งเสียงจนรีบ
    fit_tolerance: float = _float("FIT_TOLERANCE", 1.1)
    # บทที่คาดว่าพูดได้ไม่ถึงสัดส่วนนี้ของเวลาที่ตัวละครพูดจริง ให้ Typhoon ขยายบทให้เต็มเวลาขึ้น
    # (เสียงพากย์จบก่อนปากหยุดขยับ ดูไม่ตรงภาพ) 0 = ไม่ขยาย
    fit_min_ratio: float = _float("FIT_MIN_RATIO", 0.6)
    # นับช่วงเงียบหลังประโยคเป็นเวลาพูดได้อีกไม่เกินกี่วินาที ตอนคิดความยาวบท (0 = ใช้แค่ช่วงที่นักแสดงพูด
    # เพราะตอนพากย์ยังบีบเสียงให้พอดีช่วงที่นักแสดงพูด ถ้าเผื่อตรงนี้เสียงจะเร็วขึ้นแทน)
    fit_slack: float = _float("FIT_SLACK", 0.0)
    story_analysis: bool = _bool("STORY_ANALYSIS", True)  # อ่านบททั้งเรื่องก่อนแปล สรุปแนวเรื่อง ตัวละคร ชื่อเฉพาะ (translate.analyze_story)
    story_content_type: bool = _bool("STORY_CONTENT_TYPE", True)  # ให้ขั้นอ่านบทบอกประเภทคลิป: เรื่องต่อเนื่อง หรือทีเซอร์/รวมฉาก
    translate_neighbors: bool = _bool("TRANSLATE_NEIGHBORS", True)  # ส่งประโยคก่อนหน้า 3 และถัดไป 2 ไปดูบริบทตอนแปล (ปิด = บทแปลก่อนหน้า 6 ท่อนแบบเดิม)
    fit_neighbors: bool = _bool("FIT_NEIGHBORS", True)  # ส่งบทข้างเคียงไปด้วยตอนย่อหรือขยายบท ให้ความหมายยังเชื่อมกัน
    # ตรวจหลังแปล: เรื่องต่อเนื่องแปลใหม่บรรทัดที่ไม่ต่อกัน (ไม่เกิน 2 รอบ) ทีเซอร์ตรวจชื่อและศัพท์แล้วติดป้าย "ควรตรวจ" อย่างเดียว
    translate_review: bool = _bool("TRANSLATE_REVIEW", True)
    pause_match: bool = _bool("PAUSE_MATCH", True)  # เว้นจังหวะหยุดกลางประโยคตามต้นฉบับ (pauses.py)
    min_pause_sec: float = _float("MIN_PAUSE_SEC", 0.3)  # ช่วงเงียบสั้นกว่านี้ไม่นับเป็นจังหวะหยุด
    # ความดังของเสียงร้อง กรี๊ด อุทานจากต้นฉบับในช่วงที่ไม่มีบท (0 = ตัดทิ้ง)
    nonspeech_gain: float = _float("NONSPEECH_GAIN", 1.0)
    breath_keep: bool = _bool("BREATH_KEEP", True)  # ใส่เสียงหายใจของนักแสดงในช่วงหยุดกลางประโยค
    # กันเสียงพากย์ผิดคน (voices.py): ยืมเสียงตัวอย่างและรวมประโยคเฉพาะท่อนที่เสียงเข้ากัน
    voice_match: bool = _bool("VOICE_MATCH", True)
    voice_min_sim: float = _float("VOICE_MIN_SIM", 0.2)  # ลายเสียงคล้ายกันอย่างน้อยเท่านี้ (−1 ถึง 1)
    voice_max_pitch_diff: float = _float("VOICE_MAX_PITCH_DIFF", 6.0)  # ระดับเสียงต่างได้ไม่เกินกี่เซมิโทน
    voice_split_pitch: float = _float("VOICE_SPLIT_PITCH", 7.0)  # แยกผู้พูดเมื่อเสียงสองกลุ่มห่างกันเกินกี่เซมิโทน
    # ไม่ได้ระบุจำนวนคน → จัดกลุ่มผู้พูดใหม่ทีละประโยคจากลายเสียง หาจำนวนคนเอง (voices.cluster_lines)
    diar_refine: bool = _bool("DIAR_REFINE", True)
    diar_exclusive: bool = _bool("DIAR_EXCLUSIVE", True)  # ให้คำเป็นของผู้พูดตามช่วงแบบ exclusive ของ pyannote
    # ช่วงที่สองคนพูดพร้อมกัน แยกเสียงแล้วถอดคำพูดของคนที่ถูกกลบเป็นประโยคแยก (overlap.py)
    overlap_recover: bool = _bool("OVERLAP_RECOVER", True)
    # ถอดรอบสองจากเสียงต้นฉบับ (มีเพลง) เฉพาะช่วงที่ถอดไม่มั่นใจ ไม่มีคำ หรือเพลงดังทับ (transcribe.recheck_noisy)
    retranscribe_noisy: bool = _bool("RETRANSCRIBE_NOISY", False)
    # สองคนพูดต่อกันแต่ระบบแยกผู้พูดรวมเป็นท่อนเดียว (เสียงคล้ายกัน เช่น การ์ตูน): ให้ Typhoon/Gemini อ่านบทแล้วเสนอจุดเปลี่ยนคน
    # ตัดจริงเฉพาะจุดที่ลายเสียงสองฝั่งคล้ายกันต่ำกว่า TURN_SPLIT_SIM แล้วจัดกลุ่มผู้พูดใหม่ (turns.py)
    turn_split: bool = _bool("TURN_SPLIT", True)
    turn_split_sim: float = _float("TURN_SPLIT_SIM", 0.4)
    # เพิ่มเสียงเข้าคลัง: ประเมินไฟล์ที่อัปโหลดได้ยาวสุดกี่นาที (0 = ทั้งไฟล์ไม่จำกัด)
    voice_max_input_min: int = _int("VOICE_MAX_INPUT_MIN", 60)
    # ผู้พูดสองคนที่ลายเสียงคล้ายกันเกินนี้ (และระดับเสียงใกล้กัน) ถือเป็นคนเดียว คนต่างกันมักได้ไม่เกิน 0.5
    diar_merge_sim: float = _float("DIAR_MERGE_SIM", 0.65)
    # เสียงพากย์หลุดจากเสียงตัวอย่างเกินกี่เซมิโทนให้พากย์ใหม่ และลองใหม่ได้กี่รอบ (0 = ไม่ลอง)
    voice_drift: float = _float("VOICE_DRIFT", 4.0)
    voice_retries: int = _int("VOICE_RETRIES", 1)
    # ตรวจเสียงพากย์: ถอดเสียงพากย์กลับด้วย Whisper เทียบกับบท ตรงกันไม่ถึง DUB_CHECK_MIN (0–1) ให้พากย์ใหม่
    # ได้ DUB_CHECK_RETRIES รอบ เก็บรอบที่ตรงที่สุด ยังไม่ผ่านก็ติดป้าย "ควรฟัง" ในหน้าผลงาน
    dub_check: bool = _bool("DUB_CHECK", True)
    dub_check_min: float = _float("DUB_CHECK_MIN", 0.6)
    dub_check_retries: int = _int("DUB_CHECK_RETRIES", 2)
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
    # ยืดเสียงพากย์ให้เต็มฉากได้ช้าสุดกี่เท่าของความเร็วปกติ ยืดมากแล้วเสียงยานหรือพูดคำซ้ำ บทสั้นปล่อยเงียบท้ายดีกว่า
    max_slowdown: float = _float("MAX_SLOWDOWN", 1.05)
    thai_syllables_per_sec: float = _float("THAI_SYLLABLES_PER_SEC", 5.5)  # ความเร็วพูดปกติของเสียงพากย์ไทย
    # ปรับระดับและการขึ้นลงของเสียงพากย์ตามต้นฉบับ (prosody.py) ปิดไว้ก่อน: PSOLA ทำให้เสียงแตก
    # และคลิปที่มีเพลงปนวัดระดับเสียงต้นฉบับผิด (ทดสอบแล้ว PESQ ตกจาก 3.2 เหลือ 2.6)
    prosody_match: bool = _bool("PROSODY_MATCH")
    prosody_max_shift: float = _float("PROSODY_MAX_SHIFT", 4.0)  # เซมิโทน
    prosody_max_range: float = _float("PROSODY_MAX_RANGE", 1.6)  # เท่า
    voice_gain: float = _float("VOICE_GAIN", 1.0)
    bgm_gain: float = _float("BGM_GAIN", 1.0)


settings = Settings()


def billing_plan_dicts() -> list[dict[str, Any]]:
    """รายการแพ็กเกจจาก BILLING_PLANS หรือค่าเริ่มต้นในไฟล์นี้"""
    return _billing_plans()
