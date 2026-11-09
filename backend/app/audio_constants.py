"""ค่าปรับเสียงพากย์ / ผสมเสียง — แก้ที่ไฟล์นี้ ไม่ใส่ใน .env

ค่าที่หน้าเว็บยังปรับได้ (voice_gain, bgm_gain, max_speedup, f5_steps)
ใช้ตัวเลขเหล่านี้เป็นค่าเริ่มต้น แล้ว runtime_settings ทับตามที่บันทึก
"""

# --- F5-TTS คุณภาพพากย์ ---
F5_STEPS = 32          # มากขึ้น = ชัดขึ้นแต่ช้าลง
F5_CFG = 2.0
F5_SPEED = 1.0

# --- เสียงตัวอย่าง (ref) ---
REF_MIN_SEC = 2.0
REF_MAX_SEC = 10.0
REF_MIN_QUALITY = 2.3  # PESQ ประมาณ; ต่ำกว่านี้ยืมท่อนสะอาดกว่า; 0 = ปิด
REF_EMOTION_WEIGHT = 0.5

# --- จังหวะ / ความยาวบท ---
MAX_LINE_SEC = 8.0
THAI_CHARS_PER_SEC = 11.0
THAI_SYLLABLES_PER_SEC = 5.5
EN_WORDS_PER_SEC = 2.6
MAX_SPEEDUP = 1.35
MAX_SLOWDOWN = 1.05

# --- หยุดกลางประโยค ---
PAUSE_MATCH = True
MIN_PAUSE_SEC = 0.3
PAUSE_PACK = True
PAUSE_PACK_MIN_SEC = 0.08
PAUSE_PACK_MAX_SEC = 0.28
PAUSE_PACK_RATIO = 0.35

# --- เสียงนอกบท / หายใจ ---
NONSPEECH_GAIN = 1.0
BREATH_KEEP = True

# --- จับคู่เสียงตัวละคร ---
VOICE_MATCH = True
VOICE_MIN_SIM = 0.2
VOICE_MAX_PITCH_DIFF = 6.0
VOICE_SPLIT_PITCH = 7.0
VOICE_DRIFT = 4.0
VOICE_RETRIES = 1

# --- อารมณ์ / ความดัง / ห้อง ---
EMOTION_MATCH = True
LOUDNESS_MATCH = True
LOUDNESS_MAX_BOOST = 6.0   # dB
LOUDNESS_MAX_CUT = 10.0    # dB
ROOM_REVERB = 0.2          # 0 = แห้ง
ROOM_RT60 = 0.4            # วินาที

# --- Prosody (ปิดไว้: PSOLA มักทำให้เสียงแตก) ---
PROSODY_MATCH = False
PROSODY_MAX_SHIFT = 4.0    # เซมิโทน
PROSODY_MAX_RANGE = 1.6

# --- ระดับผสมสุดท้าย (ค่าเริ่มต้นหน้าตั้งค่า) ---
VOICE_GAIN = 1.0
BGM_GAIN = 1.0
