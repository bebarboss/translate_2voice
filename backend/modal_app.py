"""ขั้นที่ใช้การ์ดจอบน Modal (GPU L4) ใช้คู่กับ WORKER=modal ใน .env

deploy: modal deploy modal_app.py   (ขั้นตอนเต็มอยู่ใน README หัวข้อ "ส่งขั้นที่ใช้การ์ดจอไปรันบน Modal")

- analyze_audio    : แยกเสียงพูด/เพลง (BS-RoFormer หรือ Demucs) → แยกผู้พูด (pyannote) → ถอดเสียง (faster-whisper)
                     หรือ preseparated=True ข้ามแยกเสียง/แยกคน (แทร็กไทม์ไลน์)
- synthesize_lines : พากย์ทีละช่วง (F5-TTS ไทย/อังกฤษ) โดยตัดเสียงตัวอย่างจาก vocals ที่ส่งมา
ทั้งสองตัวเรียก app/pipeline/gpu.py ชุดเดียวกับโหมด local รับส่งข้อมูลเป็น bytes (FLAC) และ JSON
ไฟล์ระหว่างทางอยู่ในโฟลเดอร์ชั่วคราวของ container เท่านั้น Volume "dubbing-models" เก็บแคชโมเดลอย่างเดียว
โมเดลโหลดตอนใช้ครั้งแรกแล้วค้างไว้ใน container จนกว่า container จะปิดตัว (scaledown_window)
"""
from pathlib import Path
from typing import Optional

import modal

ROOT = Path(__file__).parent
APP_NAME = "dubbing-gpu"  # ต้องตรงกับ MODAL_APP ใน .env
MODELS = "/model-cache"  # ที่ mount Volume ต้องว่างใน image (ห้ามตั้ง XDG_CACHE_HOME มาที่นี่ pip จะเขียนแคชตอนสร้าง image)
SITE = "/usr/local/lib/python3.11/site-packages"
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1", "libsamplerate0", "git", "build-essential")
    # PyTorch รุ่นเดียวกับ Dockerfile (CUDA 12.6)
    .pip_install("torch==2.14.1", "torchaudio==2.11.0", index_url=TORCH_INDEX)
    # แพ็กเกจของ requirements-ml.txt ตามรุ่นที่ล็อกไว้ใน constraints-docker.txt (pip freeze ของชุดที่ใช้ได้จริง)
    # ติดตั้งแบบ --no-deps เพราะ f5-tts-th ประกาศ numpy<=1.26.4 แต่ใช้กับ numpy 2.x ได้ pip ปกติจะแก้ dependency ไม่ผ่าน
    .add_local_file(ROOT / "constraints-docker.txt", "/tmp/constraints.txt", copy=True)
    .run_commands(
        "pip install --no-deps -r /tmp/constraints.txt",
        # torchcodec จาก PyPI สร้างกับ CUDA 13 ต้องใช้รุ่น cu126 ให้ตรงกับ PyTorch
        f"pip install --no-deps --force-reinstall torchcodec==0.17.0 --index-url {TORCH_INDEX}",
        # BS-RoFormer แยกเสียงพูด (audio.separate_vocals) ล็อกแพ็กเกจที่มีอยู่แล้วไว้ ให้ติดตั้งเฉพาะที่ขาด
        "pip install audio-separator==0.48.0 -c /tmp/constraints.txt",
        # audio-separator ดึง torchvision จาก PyPI (CUDA คนละรุ่นกับ torch) ทำให้ pyannote พัง ต้องใช้รุ่น cu126 ที่คู่กับ torch 2.14.1
        f"pip install --no-deps --force-reinstall torchvision==0.29.1 --index-url {TORCH_INDEX}",
    )
    .env({
        "PYTHONIOENCODING": "utf-8",
        "WORKER": "local",  # บน Modal รันโมเดลในเครื่องตัวเอง
        "DEVICE": "cuda",
        # แคชโมเดลทั้งหมดอยู่ใน Volume โหลดจากอินเทอร์เน็ตครั้งเดียว
        "HF_HOME": f"{MODELS}/hf",
        "TORCH_HOME": f"{MODELS}/torch",
        "PYTHAINLP_DATA_DIR": f"{MODELS}/pythainlp",
        # faster-whisper (CTranslate2) หา cuDNN/cuBLAS จากแพ็กเกจ nvidia-* ที่มากับ PyTorch
        "LD_LIBRARY_PATH": f"{SITE}/nvidia/cudnn/lib:{SITE}/nvidia/cublas/lib",
    })
    .add_local_python_source("app")
)

# โหลด torch ตอนเปิด container ก่อนรับงาน ถ้าไป import ระหว่างทำงานแล้วโดนสั่งยกเลิกกลางคัน
# torch จะค้างครึ่งเดียว งานถัดไปใน container เดียวกันจะพังด้วย SystemError
with image.imports():
    import torch  # noqa: F401

app = modal.App(APP_NAME, image=image)
models = modal.Volume.from_name("dubbing-models", create_if_missing=True)
keys = modal.Secret.from_name("dubbing-keys")  # HF_TOKEN
progress = modal.Dict.from_name("dubbing-progress", create_if_missing=True)  # gpu.PROGRESS_DICT

# L4 ถูกที่สุดแต่คิวเต็มบ่อย ไม่ว่างก็ใช้ A10G (24 GB เท่ากัน) แทน ไม่ต้องรอ
GPU = dict(gpu=["L4", "A10G"], secrets=[keys], volumes={MODELS: models},
           timeout=60 * 60,  # คลิป 60 นาทีใช้ราว 10–20 นาที เผื่อไว้
           # ว่างเกิน 3 นาทีค่อยปิด — คั่นขั้นแปลบน API แล้วยังได้ container เดิมตอน resplit/พากย์
           scaledown_window=180)


def _reporter(key: Optional[str]):
    """เขียนความคืบหน้า [ชื่อขั้น, ค่า] ให้ฝั่ง API อ่าน (gpu._run)"""
    def report(name: str, value: float) -> None:
        if key:
            try:
                progress[key] = [name, value]
            except Exception:  # noqa: BLE001  รายงานไม่ได้ไม่ควรทำให้งานล้ม
                pass
    return report


@app.function(cpu=4.0, memory=16384, **GPU)
def analyze_audio(audio_flac: bytes, source_lang: Optional[str], num_speakers: Optional[int],
                  config: Optional[dict] = None, progress_key: Optional[str] = None, voice_ref: bool = False,
                  denoise: bool = False, preseparated: bool = False) -> dict:
    """เสียงต้นฉบับ (FLAC mono 44.1 kHz) → {vocals_flac, bgm_flac, turns, words, detected_lang,
    utterances, speakers, features}
    voice_ref=True: เตรียมเสียงในคลัง → {ref_flac, text, pitch_hz, quality, emb} (denoise: ลดเสียงรบกวนหลังแยกเพลง)
    preseparated=True: แทร็กคนละคนจากไทม์ไลน์แล้ว — ข้ามแยกพูด/เพลงและแยกผู้พูด"""
    from app.pipeline import gpu

    gpu.apply_config(config)
    try:
        return gpu.serve_analyze(audio_flac, source_lang, num_speakers, _reporter(progress_key),
                                 voice_ref, denoise, preseparated=preseparated)
    finally:
        models.commit()


@app.function(cpu=2.0, memory=8192, **GPU)
def resplit_turns(audio_flac: bytes, utterances: list[dict], words: list[dict], proposals: dict,
                  lang: str, num_speakers: Optional[int], config: Optional[dict] = None,
                  progress_key: Optional[str] = None) -> dict:
    """ตัดท่อนตามจุดเปลี่ยนคนที่เสนอจากบท (ตรวจด้วยลายเสียง) จัดกลุ่มผู้พูดใหม่ และวัดค่าต่อท่อนใหม่ (turns.py)
    → {utterances, cuts, features}"""
    from app.pipeline import gpu

    gpu.apply_config(config)
    try:
        return gpu.serve_resplit(audio_flac, utterances, words, proposals, lang, num_speakers, _reporter(progress_key))
    finally:
        models.commit()


@app.function(cpu=2.0, memory=8192, **GPU)
def synthesize_lines(vocals_flac: bytes, lines: list[dict], steps: int, speed: float,
                     refs: Optional[dict] = None, config: Optional[dict] = None,
                     progress_key: Optional[str] = None) -> dict:
    """vocals (FLAC mono 24 kHz) + [{id, text, ref_start, ref_end, ref_text, target_lang, ...}] → {id: เสียง FLAC 24 kHz}
    refs: เสียงตัวอย่างจากคลัง {คีย์: FLAC} สำหรับประโยคที่มี "ref" แทน ref_start/ref_end"""
    from app.pipeline import gpu

    gpu.apply_config(config)
    try:
        return gpu.serve_synthesize(vocals_flac, lines, steps, speed, refs, _reporter(progress_key))
    finally:
        models.commit()
