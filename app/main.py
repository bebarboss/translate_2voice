"""Dubbing API — ส่งคลิปต่างประเทศเข้ามา ได้คลิปพากย์ไทยหรืออังกฤษกลับไป"""
import hashlib
import hmac
import logging
import math
import mimetypes
import os
import re
import shutil
import subprocess
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import runtime_settings
from .config import settings
from .jobs import ACTIVE, JobStore, Worker
from .schemas import (Gender, Job, JobCreated, JobOptionsUpdate, JobStatus, LibraryVoice, LibraryVoiceUpdate,
                      RuntimeSettings, RuntimeSettingsUpdate, SpeakerVoice, Utterance, UtteranceEdit,
                      UtteranceSplit, VoiceStatus, VoiceSuggestion)
from .voice_library import VoiceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"} | ALLOWED_EXT
STEM_NAME = re.compile(r"^(vocals|bgm|dub_voice|final_audio|speaker_\d{2})$")
EDITABLE = (JobStatus.awaiting_review, JobStatus.done, JobStatus.failed, JobStatus.cancelled)

store = JobStore(settings.data_dir)
voice_store = VoiceStore(settings.data_dir)
worker = Worker(store, voice_store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker.start()
    yield


app = FastAPI(
    title="Dubbing API",
    version="2.0.0",
    description="แยกเสียง → แยกผู้พูด → ถอดเสียง → แปลด้วย Typhoon → พากย์ด้วย F5-TTS → รวมวิดีโอ",
    lifespan=lifespan,
)

# หน้าเว็บ Next.js เรียกผ่าน proxy ของตัวเองอยู่แล้ว CORS จำเป็นเฉพาะตอนเรียกจากเบราว์เซอร์ตรง ๆ
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "API key ไม่ถูกต้อง (ส่งใน header X-API-Key)")


def _valid_upload_token(token: str) -> bool:
    """ตั๋วอัปโหลด "<หมดอายุ unix>.<hmac>" ที่หน้าเว็บออกให้เบราว์เซอร์ (web/app/api/upload-ticket)
    ให้อัปโหลดไฟล์ตรงมาที่ API ได้โดยไม่เห็นคีย์จริง"""
    exp, _, sig = token.partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    expected = hmac.new(settings.api_key.encode(), f"upload:{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def require_key_or_upload_token(x_api_key: Optional[str] = Header(default=None),
                                x_upload_token: Optional[str] = Header(default=None)) -> None:
    if settings.api_key and x_upload_token and _valid_upload_token(x_upload_token):
        return
    require_key(x_api_key)


def get_job_or_404(job_id: str) -> Job:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "ไม่พบงานนี้")
    return job


def file_or_404(path: Path, media_type: str, filename: str) -> FileResponse:
    if not path.exists():
        raise HTTPException(404, "ยังไม่มีไฟล์นี้ งานอาจยังไม่เสร็จ")
    return FileResponse(path, media_type=media_type, filename=filename)


async def save_upload(file: UploadFile, dest: Path, owner_dir: Path) -> None:
    """สตรีมไฟล์ลงดิสก์ทีละ 1 MB เกินขนาดที่ตั้งไว้ลบทั้งโฟลเดอร์ทิ้ง"""
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                shutil.rmtree(owner_dir, ignore_errors=True)
                raise HTTPException(413, f"ไฟล์ใหญ่เกิน {settings.max_upload_mb} MB")
            out.write(chunk)


def out_name(job: Job, ext: str) -> str:
    return f"{Path(job.filename).stem}_{job.target_lang}{ext}"


def srt_path(job_id: str) -> Path:
    d = store.dir(job_id)
    return d / "subtitles.srt" if (d / "subtitles.srt").exists() else d / "subtitles_th.srt"


def video_for_download(job: Job, with_subs: bool) -> Path:
    from .pipeline import runner, subs
    d = store.dir(job.id)
    if not with_subs:
        return d / "output.mp4"
    if not subs.burned_matches(d, runner.effective_style(job)):
        raise HTTPException(409, "ยังไม่มีวิดีโอฝังซับตามรูปแบบล่าสุด เรียก POST /jobs/{id}/render ก่อน")
    return d / "output_subs.mp4"


# ---------------------------------------------------------------- ระบบ
@app.get("/health")
def health():
    return {"status": "ok", "mock": settings.mock_pipeline, "queued": worker.queue.qsize()}


def _gpu_name() -> Optional[str]:
    if settings.worker == "modal" and not settings.mock_pipeline:
        return "Modal L4 (24 GB)"
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return f"{props.name} ({props.total_memory / 1024 ** 3:.0f} GB)"
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            return out.splitlines()[0] if out else None
        except (OSError, subprocess.SubprocessError):
            return None
    return None


@app.get("/system", dependencies=[Depends(require_key)])
def system_info():
    """ข้อมูลเครื่องประมวลผล ใช้แสดงในหน้าตั้งค่า"""
    jobs = store.all()
    return {
        "mock": settings.mock_pipeline,
        "gpu": _gpu_name(),
        "device": settings.device,
        "models": {
            "separation": settings.demucs_model,
            "diarization": settings.diarization_model,
            "transcription": f"whisper {settings.whisper_model}",
            "translation": settings.typhoon_model,
            "tts_th": f"F5-TTS Thai {settings.f5_model}",
            "tts_en": settings.f5_en_model,
        },
        "keys": {"hf_token": bool(settings.hf_token), "typhoon": bool(settings.typhoon_api_key)},
        "queue": {
            "running": worker.current,
            "queued": sum(1 for j in jobs if j.status == JobStatus.queued),
        },
        "limits": {"max_upload_mb": settings.max_upload_mb, "max_url_minutes": settings.max_url_minutes},
    }


@app.get("/settings", response_model=RuntimeSettings, dependencies=[Depends(require_key)])
def get_settings():
    return runtime_settings.get()


@app.put("/settings", response_model=RuntimeSettings, dependencies=[Depends(require_key)])
def put_settings(patch: RuntimeSettingsUpdate):
    """ค่าใหม่มีผลกับการพากย์รอบถัดไป ถ้าเปลี่ยนความเร็วหรือคุณภาพเสียง จะพากย์ใหม่ทุกประโยค"""
    return runtime_settings.update(patch)


@app.get("/fonts", dependencies=[Depends(require_key)])
def fonts():
    """ฟอนต์ที่ติดตั้งในเครื่องเซิร์ฟเวอร์ ใช้ฝังซับได้"""
    from .pipeline.subs import list_fonts
    return list_fonts()


# ---------------------------------------------------------------- สร้างงาน
@app.post("/jobs", response_model=JobCreated, status_code=202, dependencies=[Depends(require_key_or_upload_token)])
async def create_job(
    file: Optional[UploadFile] = File(None, description="ไฟล์วิดีโอต้นฉบับ (ส่งอย่างใดอย่างหนึ่งกับ url)"),
    url: Optional[str] = Form(None, description="ลิงก์คลิป YouTube, TikTok, Facebook, Bilibili ฯลฯ"),
    source_lang: Optional[str] = Form(None, description="รหัสภาษาต้นฉบับ เช่น zh, en, ko, ja ว่างไว้ = ตรวจอัตโนมัติ"),
    target_lang: Optional[str] = Form(None, description="ภาษาพากย์ th หรือ en ว่างไว้ = ค่าเริ่มต้น"),
    num_speakers: Optional[int] = Form(None, ge=1, le=20, description="จำนวนตัวละคร ถ้ารู้ ช่วยให้แยกผู้พูดแม่นขึ้น"),
    review: Optional[bool] = Form(None, description="true = หยุดรอให้ตรวจแก้บทก่อนพากย์"),
    burn_subs: Optional[bool] = Form(None, description="true = ฝังซับลงวิดีโอด้วย"),
):
    rs = runtime_settings.get()
    target = (target_lang or rs.default_target_lang).strip().lower()
    if target not in ("th", "en"):
        raise HTTPException(400, "ภาษาพากย์ต้องเป็น th หรือ en")
    url = (url or "").strip()
    has_file = file is not None and bool(file.filename)
    if has_file == bool(url):
        raise HTTPException(400, "ส่งไฟล์หรือลิงก์อย่างใดอย่างหนึ่ง")

    job_id = store.new_id()
    job_dir = store.dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path, filename = "", ""

    if has_file:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, f"รองรับเฉพาะไฟล์ {', '.join(sorted(ALLOWED_EXT))}")
        dest = job_dir / f"input{ext}"
        await save_upload(file, dest, job_dir)
        input_path, filename = str(dest), file.filename
    else:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "ลิงก์ไม่ถูกต้อง ต้องขึ้นต้นด้วย http:// หรือ https://")
        filename = f"{parsed.netloc.replace('www.', '')}.mp4"

    job = store.add(Job(
        id=job_id,
        filename=filename,
        input_path=input_path,
        source_url=url or None,
        source_lang=(source_lang or "").strip().lower() or None,
        target_lang=target,
        num_speakers=num_speakers,
        review=rs.default_review if review is None else review,
        burn_subs=rs.default_burn_subs if burn_subs is None else burn_subs,
    ))
    worker.submit(job.id, "analyze")
    return JobCreated(id=job.id, status=JobStatus.queued)


@app.get("/jobs", response_model=list[Job], dependencies=[Depends(require_key)])
def list_jobs():
    return store.all()


@app.get("/jobs/{job_id}", response_model=Job, dependencies=[Depends(require_key)])
def get_job(job_id: str):
    return get_job_or_404(job_id)


@app.delete("/jobs/{job_id}", status_code=204, dependencies=[Depends(require_key)])
def delete_job(job_id: str):
    job = get_job_or_404(job_id)
    if job.status in ACTIVE:
        raise HTTPException(409, "งานกำลังทำงานอยู่ กดยกเลิกก่อนแล้วค่อยลบ")
    store.delete(job_id)


@app.post("/jobs/{job_id}/cancel", response_model=Job, dependencies=[Depends(require_key)])
def cancel_job(job_id: str):
    """ยกเลิกงานที่รอคิวหรือกำลังทำ งานที่กำลังทำจะหยุดเมื่อจบขั้นย่อยปัจจุบัน"""
    job = get_job_or_404(job_id)
    if job.status not in ACTIVE:
        raise HTTPException(409, "งานนี้ไม่ได้กำลังทำงานอยู่")
    if job.status == JobStatus.queued:
        return store.update(job_id, status=JobStatus.cancelled, stage="cancelled")
    store.request_cancel(job_id)
    return store.update(job_id, stage="cancelling")


@app.post("/jobs/{job_id}/retry", response_model=JobCreated, status_code=202, dependencies=[Depends(require_key)])
def retry_job(job_id: str):
    """เริ่มใหม่จากขั้นใหญ่ที่ล้มเหลวหรือถูกยกเลิก"""
    job = get_job_or_404(job_id)
    if job.status not in (JobStatus.failed, JobStatus.cancelled):
        raise HTTPException(409, "ลองใหม่ได้เฉพาะงานที่ล้มเหลวหรือถูกยกเลิก")
    phase = job.phase
    if phase in ("synthesize", "render") and not store.load_transcript(job_id):
        phase = "analyze"
    if phase == "render" and not (store.dir(job_id) / "output.mp4").exists():
        phase = "synthesize"
    worker.submit(job_id, phase)
    return JobCreated(id=job_id, status=JobStatus.queued)


@app.patch("/jobs/{job_id}/options", response_model=Job, dependencies=[Depends(require_key)])
def update_options(job_id: str, patch: JobOptionsUpdate):
    """ตั้งค่าฝังซับและรูปแบบซับของงานนี้ ส่ง sub_style เป็น null เพื่อกลับไปใช้ค่าเริ่มต้น"""
    get_job_or_404(job_id)
    fields = patch.model_dump(exclude_unset=True)
    if "sub_style" in fields:
        fields["sub_style"] = patch.sub_style
    return store.update(job_id, **fields)


@app.post("/jobs/{job_id}/render", response_model=JobCreated, status_code=202, dependencies=[Depends(require_key)])
def render(job_id: str):
    """ฝังซับลงวิดีโอใหม่ตามรูปแบบล่าสุด (ไม่ต้องพากย์ใหม่)"""
    job = get_job_or_404(job_id)
    if job.status != JobStatus.done or not (store.dir(job_id) / "output.mp4").exists():
        raise HTTPException(409, "ฝังซับได้เมื่อพากย์เสร็จแล้วเท่านั้น")
    worker.submit(job_id, "render")
    return JobCreated(id=job_id, status=JobStatus.queued)


# ---------------------------------------------------------------- บทพากย์
@app.get("/jobs/{job_id}/transcript", response_model=list[Utterance], dependencies=[Depends(require_key)])
def get_transcript(job_id: str):
    get_job_or_404(job_id)
    return store.load_transcript(job_id)


@app.put("/jobs/{job_id}/transcript", response_model=list[Utterance], dependencies=[Depends(require_key)])
def edit_transcript(job_id: str, edits: list[UtteranceEdit]):
    """แก้บทพากย์หรือป้ายผู้พูดทีละประโยค แล้วเรียก POST /jobs/{id}/synthesize เพื่อพากย์"""
    job = get_job_or_404(job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, "แก้บทได้เมื่องานไม่ได้กำลังทำงานอยู่เท่านั้น")
    utterances = store.load_transcript(job_id)
    if not utterances:
        raise HTTPException(409, "งานนี้ยังไม่มีบท")
    by_id = {u.id: u for u in utterances}
    moved = False
    for edit in edits:
        u = by_id.get(edit.id)
        if u is None:
            raise HTTPException(400, f"ไม่พบประโยค id={edit.id}")
        if edit.target is not None:
            u.target = edit.target.strip()
        if edit.speaker is not None:
            if edit.speaker not in job.speakers:
                raise HTTPException(400, f"ไม่รู้จักผู้พูด {edit.speaker} มีแค่ {job.speakers}")
            moved |= u.speaker != edit.speaker
            u.speaker = edit.speaker
    _save_lines(job, utterances, moved)
    return utterances


def _editable_lines(job_id: str) -> tuple[Job, list[Utterance]]:
    job = get_job_or_404(job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, "แก้บทได้เมื่องานไม่ได้กำลังทำงานอยู่เท่านั้น")
    utterances = sorted(store.load_transcript(job_id), key=lambda u: u.start)
    if not utterances:
        raise HTTPException(409, "งานนี้ยังไม่มีบท")
    return job, utterances


def _save_lines(job: Job, utterances: list[Utterance], moved: bool) -> None:
    """บันทึกบท ถ้าช่วงพูดของตัวละครเปลี่ยน สร้างเสียงแยกรายคนใหม่ (ปุ่มฟังเสียงแยก และเสียงตัวอย่างตอนเลือกเสียง)"""
    from .transcript_edit import export_stems

    store.save_transcript(job.id, utterances)
    if moved:
        export_stems(store.dir(job.id), utterances, job.speakers)


@app.post("/jobs/{job_id}/transcript/{line_id}/split", response_model=list[Utterance],
          dependencies=[Depends(require_key)])
def split_line(job_id: str, line_id: int, body: UtteranceSplit):
    """แยกประโยคเป็นสองท่อน เช่น สองคนพูดต่อกันแต่ถูกรวมเป็นท่อนเดียว แล้วเปลี่ยนตัวละครของท่อนหลังได้
    ระบุ at (วินาทีในคลิป) หรือ pos (ตำแหน่งตัวอักษรในบทพากย์) หรือทั้งสองอย่าง ค่าที่ไม่ระบุหาจากเวลาของแต่ละคำ"""
    from .pipeline.runner import _load_words
    from .transcript_edit import split

    job, utterances = _editable_lines(job_id)
    i = next((k for k, u in enumerate(utterances) if u.id == line_id), None)
    if i is None:
        raise HTTPException(404, f"ไม่พบประโยค id={line_id}")
    u = utterances[i]
    if body.pos is not None and not 0 < body.pos < len(u.target.strip()):
        raise HTTPException(400, "ตำแหน่งที่แยกต้องอยู่กลางบท ไม่ใช่หัวหรือท้าย")
    try:
        a, b = split(u, max(x.id for x in utterances) + 1, body.at, body.pos, _load_words(store.dir(job_id)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    utterances[i:i + 1] = [a, b]
    _save_lines(job, utterances, False)
    return utterances


@app.post("/jobs/{job_id}/transcript/{line_id}/merge", response_model=list[Utterance],
          dependencies=[Depends(require_key)])
def merge_line(job_id: str, line_id: int):
    """รวมประโยคนี้กับประโยคถัดไป ใช้ตัวละครของประโยคนี้"""
    from .transcript_edit import merge

    job, utterances = _editable_lines(job_id)
    i = next((k for k, u in enumerate(utterances) if u.id == line_id), None)
    if i is None:
        raise HTTPException(404, f"ไม่พบประโยค id={line_id}")
    if i + 1 == len(utterances):
        raise HTTPException(400, "เป็นประโยคสุดท้าย ไม่มีประโยคถัดไปให้รวม")
    moved = utterances[i + 1].speaker != utterances[i].speaker
    utterances[i:i + 2] = [merge(utterances[i], utterances[i + 1])]
    _save_lines(job, utterances, moved)
    return utterances


# ---------------------------------------------------------------- ตัวละคร
@app.post("/jobs/{job_id}/speakers", response_model=Job, dependencies=[Depends(require_key)])
def add_speaker(job_id: str):
    """เพิ่มตัวละครใหม่ (ระบบแยกผู้พูดรวมสองคนเป็นคนเดียว) แล้วย้ายประโยคไปให้ด้วย PUT /jobs/{id}/transcript"""
    job, _ = _editable_lines(job_id)
    n = max((int(s.split("_")[-1]) for s in job.speakers if re.fullmatch(r"speaker_\d{2}", s)), default=0) + 1
    if n > 99:
        raise HTTPException(400, "ตัวละครเต็มแล้ว")
    return store.update(job_id, speakers=job.speakers + [f"speaker_{n:02d}"])


@app.delete("/jobs/{job_id}/speakers/{speaker}", response_model=Job, dependencies=[Depends(require_key)])
def remove_speaker(job_id: str, speaker: str, into: Optional[str] = None):
    """ลบตัวละคร (ระบบแยกคนเดียวเป็นสองตัวละคร) ประโยคของตัวละครนี้ย้ายไปให้ into"""
    job, utterances = _editable_lines(job_id)
    if speaker not in job.speakers:
        raise HTTPException(404, f"ไม่รู้จักผู้พูด {speaker}")
    if len(job.speakers) == 1:
        raise HTTPException(400, "ต้องเหลือตัวละครอย่างน้อยหนึ่งตัว")
    own = [u for u in utterances if u.speaker == speaker]
    if own and (into is None or into == speaker or into not in job.speakers):
        raise HTTPException(400, f"ตัวละครนี้มี {len(own)} ประโยค ต้องเลือกตัวละครที่จะรับประโยคไป (into)")
    for u in own:
        u.speaker = into
    speakers = [s for s in job.speakers if s != speaker]
    voice_map = {s: v for s, v in job.voice_map.items() if s != speaker}
    job = store.update(job_id, speakers=speakers, voice_map=voice_map)
    _save_lines(job, utterances, True)
    return job


@app.post("/jobs/{job_id}/synthesize", response_model=JobCreated, status_code=202,
          dependencies=[Depends(require_key)])
def synthesize(job_id: str):
    """พากย์ต่อหลังตรวจบท หรือพากย์ใหม่หลังแก้บท (พากย์ใหม่เฉพาะประโยคที่เปลี่ยน)"""
    job = get_job_or_404(job_id)
    if job.status in ACTIVE:
        raise HTTPException(409, "งานกำลังทำงานอยู่")
    if not store.load_transcript(job_id):
        raise HTTPException(409, "งานนี้ยังไม่มีบท ต้องรอขั้นแปลเสร็จก่อน")
    worker.submit(job_id, "synthesize")
    return JobCreated(id=job_id, status=JobStatus.queued)


# ---------------------------------------------------------------- เสียงของตัวละคร
@app.get("/jobs/{job_id}/voices", response_model=list[SpeakerVoice], dependencies=[Depends(require_key)])
def get_job_voices(job_id: str):
    """เสียงที่เลือกไว้และเสียงในคลังที่แนะนำ (ใกล้ที่สุดก่อน) ของแต่ละตัวละคร
    ครั้งแรกต้องวัดเสียงตัวละครบน CPU ใช้เวลาราวสิบวินาที หลังจากนั้นใช้ค่าที่เก็บไว้"""
    from .pipeline import library

    job = get_job_or_404(job_id)
    utterances = store.load_transcript(job_id)
    if not utterances:
        raise HTTPException(409, "งานนี้ยังไม่มีบท ต้องรอขั้นแยกผู้พูดเสร็จก่อน")
    profiles = library.speaker_profiles(store.dir(job_id), utterances)
    ready = [v for v in voice_store.all() if v.status == VoiceStatus.ready]
    embs = {v.id: voice_store.embedding(v.id) for v in ready}
    out = []
    for speaker in job.speakers:
        p = profiles.get(speaker)
        hz = round(float(2 ** (p.pitch / 12)), 1) if p is not None and math.isfinite(p.pitch) else None
        suggestions = []
        if p is not None:
            suggestions = sorted((VoiceSuggestion(voice_id=v.id, score=library.closeness(p, v.pitch_hz, embs[v.id]))
                                  for v in ready), key=lambda s: s.score, reverse=True)
        out.append(SpeakerVoice(speaker=speaker, voice_id=job.voice_map.get(speaker), pitch_hz=hz,
                                gender=library.guess_gender(hz), suggestions=suggestions))
    return out


@app.put("/jobs/{job_id}/voices", response_model=Job, dependencies=[Depends(require_key)])
def set_job_voices(job_id: str, choice: dict[str, Optional[str]]):
    """เลือกเสียงจากคลังให้ตัวละคร {"speaker_01": "<id เสียง>", "speaker_02": null}
    null = กลับไปใช้เสียงต้นฉบับ ตัวละครที่ไม่ได้ส่งมาคงค่าเดิม มีผลตอนพากย์รอบถัดไป"""
    job = get_job_or_404(job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, "เปลี่ยนเสียงได้เมื่องานไม่ได้กำลังทำงานอยู่เท่านั้น")
    voice_map = dict(job.voice_map)
    for speaker, voice_id in choice.items():
        if speaker not in job.speakers:
            raise HTTPException(400, f"ไม่รู้จักผู้พูด {speaker} มีแค่ {job.speakers}")
        if voice_id is None:
            voice_map.pop(speaker, None)
            continue
        v = voice_store.get(voice_id)
        if v is None or v.status != VoiceStatus.ready:
            raise HTTPException(400, f"เสียง {voice_id} ไม่มีในคลังหรือยังเตรียมไม่เสร็จ")
        voice_map[speaker] = voice_id
    return store.update(job_id, voice_map=voice_map)


# ---------------------------------------------------------------- คลังเสียง
def get_voice_or_404(voice_id: str) -> LibraryVoice:
    v = voice_store.get(voice_id)
    if not v:
        raise HTTPException(404, "ไม่พบเสียงนี้ในคลัง")
    return v


@app.get("/voices", response_model=list[LibraryVoice], dependencies=[Depends(require_key)])
def list_voices():
    return voice_store.all()


@app.post("/voices", response_model=LibraryVoice, status_code=202,
          dependencies=[Depends(require_key_or_upload_token)])
async def create_voice(
    file: UploadFile = File(..., description="คลิปเสียงภาษาไทย (หรือวิดีโอ) ของเจ้าของเสียง ใช้แค่ 5 นาทีแรก"),
    name: str = Form(..., min_length=1, max_length=80),
    gender: Gender = Form("", description="male, female หรือว่างไว้ให้ระบบเดาจากระดับเสียง"),
    tone: str = Form("", max_length=80, description="โทนเสียง เช่น ทุ้มลึก นุ่มนวล สดใส"),
):
    """อัปโหลดเสียงเข้าคลัง ระบบจะแยกเสียงรบกวน ตัดท่อนพูดที่สะอาดที่สุด 3–10 วินาที และถอดข้อความให้"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(400, f"รองรับเฉพาะไฟล์ {', '.join(sorted(AUDIO_EXT))}")
    voice_id = voice_store.new_id()
    d = voice_store.dir(voice_id)
    d.mkdir(parents=True, exist_ok=True)
    await save_upload(file, d / f"original{ext}", d)
    v = voice_store.add(LibraryVoice(id=voice_id, name=name.strip(), gender=gender, tone=tone.strip(),
                                     filename=file.filename or ""))
    worker.submit_voice(voice_id)
    return v


@app.get("/voices/{voice_id}", response_model=LibraryVoice, dependencies=[Depends(require_key)])
def get_voice(voice_id: str):
    return get_voice_or_404(voice_id)


@app.patch("/voices/{voice_id}", response_model=LibraryVoice, dependencies=[Depends(require_key)])
def update_voice(voice_id: str, patch: LibraryVoiceUpdate):
    """แก้ชื่อ เพศ โทนเสียง หรือข้อความที่พูดในเสียงตัวอย่าง (ถ้าถอดผิด แก้ให้ตรงเสียงจริงจะพากย์ได้ชัดขึ้น)
    งานที่ใช้เสียงนี้จะพากย์ตัวละครนั้นใหม่ทุกประโยคเมื่อข้อความเปลี่ยน"""
    get_voice_or_404(voice_id)
    fields = {k: v.strip() if isinstance(v, str) else v for k, v in patch.model_dump(exclude_unset=True).items()}
    return voice_store.update(voice_id, **fields)


@app.delete("/voices/{voice_id}", status_code=204, dependencies=[Depends(require_key)])
def delete_voice(voice_id: str):
    """ลบเสียงออกจากคลัง ตัวละครที่เลือกเสียงนี้ไว้จะกลับไปใช้เสียงต้นฉบับ"""
    v = get_voice_or_404(voice_id)
    if v.status == VoiceStatus.processing and v.stage != "queued":
        raise HTTPException(409, "กำลังเตรียมเสียงนี้อยู่ รอให้เสร็จก่อนแล้วค่อยลบ")
    voice_store.delete(voice_id)


@app.post("/voices/{voice_id}/retry", response_model=LibraryVoice, status_code=202,
          dependencies=[Depends(require_key)])
def retry_voice(voice_id: str):
    v = get_voice_or_404(voice_id)
    if v.status != VoiceStatus.failed:
        raise HTTPException(409, "ลองใหม่ได้เฉพาะเสียงที่เตรียมไม่สำเร็จ")
    if not any(voice_store.dir(voice_id).glob("original.*")):
        raise HTTPException(409, "ไม่พบไฟล์ต้นฉบับแล้ว ลบแล้วอัปโหลดใหม่")
    v = voice_store.update(voice_id, status=VoiceStatus.processing, stage="queued", error=None)
    worker.submit_voice(voice_id)
    return v


@app.get("/voices/{voice_id}/audio", dependencies=[Depends(require_key)])
def get_voice_audio(voice_id: str):
    """เสียงตัวอย่างที่ทำความสะอาดและตัดแล้ว (ใช้ปุ่มฟังตัวอย่าง)"""
    v = get_voice_or_404(voice_id)
    return file_or_404(voice_store.ref_path(voice_id), "audio/wav", f"{v.name}.wav")


# ---------------------------------------------------------------- ไฟล์
@app.get("/jobs/{job_id}/result", dependencies=[Depends(require_key)])
def get_result(job_id: str, subs: bool = False):
    """วิดีโอพากย์แล้ว subs=true = รุ่นฝังซับ"""
    job = get_job_or_404(job_id)
    return file_or_404(video_for_download(job, subs), "video/mp4", out_name(job, ".mp4"))


@app.get("/jobs/{job_id}/export", dependencies=[Depends(require_key)])
def export(job_id: str, subs: bool = False):
    """ไฟล์ zip ที่มีวิดีโอกับซับ .srt เสมอ"""
    job = get_job_or_404(job_id)
    video = video_for_download(job, subs)
    srt = srt_path(job_id)
    if not video.exists() or not srt.exists():
        raise HTTPException(404, "ยังไม่มีไฟล์ งานอาจยังไม่เสร็จ")
    zip_path = store.dir(job_id) / ("export_subs.zip" if subs else "export.zip")
    if not zip_path.exists() or zip_path.stat().st_mtime < max(video.stat().st_mtime, srt.stat().st_mtime):
        tmp = zip_path.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w") as z:
            z.write(video, out_name(job, ".mp4"), compress_type=zipfile.ZIP_STORED)
            z.write(srt, out_name(job, ".srt"), compress_type=zipfile.ZIP_DEFLATED)
        tmp.replace(zip_path)
    return FileResponse(zip_path, media_type="application/zip", filename=out_name(job, ".zip"))


@app.get("/jobs/{job_id}/source", dependencies=[Depends(require_key)])
def get_source(job_id: str):
    """คลิปต้นฉบับ ใช้เปิดในหน้าตรวจบท"""
    job = get_job_or_404(job_id)
    if not job.input_path:
        raise HTTPException(404, "ยังดาวน์โหลดคลิปไม่เสร็จ")
    path = Path(job.input_path)
    media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return file_or_404(path, media_type, job.filename)


@app.get("/jobs/{job_id}/subtitles", dependencies=[Depends(require_key)])
def get_subtitles(job_id: str):
    job = get_job_or_404(job_id)
    return file_or_404(srt_path(job_id), "application/x-subrip", out_name(job, ".srt"))


@app.get("/jobs/{job_id}/stems", dependencies=[Depends(require_key)])
def list_stems(job_id: str):
    """เลเยอร์เสียงที่แยกได้: vocals, bgm, speaker_01.. (เสียงของแต่ละคน), dub_voice, final_audio"""
    get_job_or_404(job_id)
    d = store.dir(job_id)
    files = list(d.glob("*.wav")) + list((d / "stems").glob("*.wav"))
    return sorted(f.stem for f in files if STEM_NAME.match(f.stem))


@app.get("/jobs/{job_id}/stems/{name}", dependencies=[Depends(require_key)])
def get_stem(job_id: str, name: str):
    get_job_or_404(job_id)
    if not STEM_NAME.match(name):
        raise HTTPException(400, "ชื่อเลเยอร์ไม่ถูกต้อง")
    d = store.dir(job_id)
    path = d / "stems" / f"{name}.wav" if name.startswith("speaker_") else d / f"{name}.wav"
    return file_or_404(path, "audio/wav", f"{job_id}_{name}.wav")
