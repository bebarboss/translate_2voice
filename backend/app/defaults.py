"""ค่าคอนฟิกที่ไม่ใช่ความลับ — แก้ที่นี่ ไม่ใส่ใน .env

ความลับ / ค่าที่ขึ้นกับเครื่องหรือโดเมน ยังอยู่ใน .env (ดู .env.example)
"""

# ---------- ระบบ ----------
MAX_UPLOAD_MB = 95  # Cloudflare Tunnel รับได้ครั้งละไม่เกิน ~100 MB
MAX_URL_MINUTES = 60.0
BACKUP_HOURS = 24
BACKUP_KEEP = 14
NOTIFY_MIN_SECONDS = 120
MOCK_DELAY = 0.6
WATERMARK_TEXT = "Pakdee"

# ---------- Worker / คิว ----------
WORKER = "modal"  # local | modal — ทับด้วย WORKER ใน .env ได้ถ้าเครื่องนี้ใช้ GPU เอง
MODAL_APP = "dubbing-gpu"
MODAL_MAX_JOBS = 4
MODAL_TTS_BATCH = 40
ANALYZE_CHUNK_SEC = 480.0
ANALYZE_CHUNK_OVERLAP_SEC = 10.0
ANALYZE_CHUNK_MIN_SEC = 720.0
ANALYZE_FAST = True
ANALYZE_FAST_WHISPER = "medium"
LIGHT_WORKERS = 2
USER_MAX_JOBS = 2
USER_MAX_QUEUED = 10

# ---------- โมเดล ----------
SEPARATOR = "roformer"
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
SEPARATOR_OVERLAP = 2
DENOISE_MODEL = "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt"
DEMUCS_MODEL = "htdemucs"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
WHISPER_MODEL = "large-v3"
WHISPER_COMPUTE_TYPE = "int8_float16"
WHISPER_VAD_THRESHOLD = 0.35
WHISPER_VAD_MIN_SPEECH_MS = 100
WHISPER_VAD_MIN_SILENCE_MS = 400
WHISPER_VAD_SPEECH_PAD_MS = 600
WHISPER_FILL_GAP_SEC = 0.4
AUTO_HEAL_ASR = True
AUTO_KNOBS = True

TYPHOON_BASE_URL = "https://api.opentyphoon.ai/v1"
TYPHOON_MODEL = "typhoon-v2.5-30b-a3b-instruct"
TYPHOON_TEMPERATURE = 0.4
TYPHOON_REASONING_EFFORT = ""  # เช่น none สำหรับบางผู้ให้บริการ
TYPHOON_TRANSLATE_MODEL = "scb10x/typhoon-translate1.5-4b"
TRANSLATE_BATCH_SIZE = 20
TRANSLATE_EN_LOCAL = False

F5_MODEL = "v2"
F5_EN_MODEL = "F5TTS_v1_Base"
F5_FP32 = False  # ทับด้วย F5_FP32=1 ใน .env ถ้าเป็น GTX 16xx

# ---------- แปล / ประมวลผลบท ----------
FIT_TOLERANCE = 1.1
FIT_MIN_RATIO = 0.7
FIT_SLACK = 0.0
STORY_ANALYSIS = True
STORY_CONTENT_TYPE = True
TRANSLATE_NEIGHBORS = True
FIT_NEIGHBORS = True
TRANSLATE_REVIEW = True
LIP_SYNC_SAME_LANG = True
TRANSCRIPT_GATE = True
AI_FIX_SUSPECTS = True
AI_DUB_JUDGE = True
AI_FILL_EMPTY = True
AI_NATURALIZE = True
AI_SPEAK_LATIN = True

# ---------- ผู้พูด / overlap / dub check ----------
DIAR_REFINE = True
DIAR_EXCLUSIVE = True
DIAR_MERGE_SIM = 0.65
OVERLAP_RECOVER = True
RETRANSCRIBE_NOISY = True
MIN_COVERAGE_SYNTHESIZE = 0.70
TURN_SPLIT = True
TURN_SPLIT_SIM = 0.4
VOICE_MAX_INPUT_MIN = 60
DUB_CHECK = True
DUB_CHECK_MIN = 0.6
DUB_CHECK_RETRIES = 2

# ---------- บัญชี / แพ็กเกจ (ราคาใน config._DEFAULT_BILLING_PLANS) ----------
CREDIT_PRICE_SATANG = 700
CREDIT_PACKS = (10, 30, 60, 100)
PLAN_CREDIT_ROLLOVER = 1
ACTOR_RATE_SATANG_PER_MIN = 200
ACTOR_WHT_PERCENT = 3.0
ACTOR_WHT_MIN_SATANG = 100_000
ACTOR_INCOME_TYPE = "40(2)"
TYPHOON_OCR_MODEL = "typhoon-ocr"
SLIP_MAX_MB = 8
SLIP_MAX_AGE_HOURS = 72

# ---------- R2 (เปิด/ปิดและชื่อ bucket ตั้งใน .env; พฤติกรรมเริ่มต้น) ----------
R2_PURGE_LOCAL = False
