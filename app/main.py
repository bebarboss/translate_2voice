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

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import accounts, runtime_settings, supabase_db
from .account_api import router as account_router
from .config import settings
from .jobs import ACTIVE, JobStore, Worker
from .schemas import (Gender, Job, JobCreated, JobOptionsUpdate, JobStatus, LibraryVoice, LineDuplicate, LibraryVoiceUpdate, Mood,
                      Retranslate, RuntimeSettings, RuntimeSettingsUpdate, SpeakerRename, SpeakerToLibrary, SpeakerVoice, Utterance, UtteranceEdit,
                      UtteranceSplit, VoiceMood, VoiceMoodUpdate, VoiceStatus, VoiceSuggestion)
from .voice_library import VoiceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma"} | ALLOWED_EXT
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


@app.exception_handler(supabase_db.DBError)
def _db_error(_: Request, exc: supabase_db.DBError):
    logging.getLogger("dubbing.db").error("Supabase: %s", exc)
    return JSONResponse({"detail": "บันทึกลงฐานข้อมูลไม่ได้ชั่วคราว ลองใหม่อีกครั้ง"}, status_code=503)


def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "API key ไม่ถูกต้อง (ส่งใน header X-API-Key)")


def _upload_ticket(token: str) -> Optional[str]:
    """ตั๋วอัปโหลด "<หมดอายุ unix>.<hmac>" หรือ "<หมดอายุ>.<id ผู้ใช้>.<hmac>" ที่หน้าเว็บออกให้เบราว์เซอร์
    (web/app/api/upload-ticket) ให้อัปโหลดไฟล์ตรงมาที่ API ได้โดยไม่เห็นคีย์จริง
    คืน id ผู้ใช้ ("" = ตั๋วไม่ระบุผู้ใช้) หรือ None ถ้าตั๋วใช้ไม่ได้"""
    parts = token.split(".")
    if len(parts) not in (2, 3) or not settings.api_key:
        return None
    exp, uid, sig = parts if len(parts) == 3 else (parts[0], "", parts[1])
    if not exp.isdigit() or int(exp) < time.time():
        return None
    msg = f"upload:{exp}:{uid}" if uid else f"upload:{exp}"
    expected = hmac.new(settings.api_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return uid if hmac.compare_digest(sig, expected) else None


def require_key_or_upload_token(x_api_key: Optional[str] = Header(default=None),
                                x_upload_token: Optional[str] = Header(default=None)) -> None:
    if x_upload_token and _upload_ticket(x_upload_token) is not None:
        return
    require_key(x_api_key)


OPEN_PATHS = ("/health", "/auth/", "/billing/plans", "/docs", "/openapi.json", "/redoc")
ADMIN_WRITES = ("/settings", "/voices")  # เปิดระบบบัญชีแล้ว คลังเสียงและค่าตั้งระบบแก้ได้เฉพาะผู้ดูแล


def access_guard(request: Request, x_user_token: Optional[str] = Header(default=None),
                 x_upload_token: Optional[str] = Header(default=None)) -> None:
    """เปิด AUTH_ENABLED แล้ว: หาผู้ใช้จาก token ทุกคำขอ ต้องล็อกอิน และเข้าถึงได้เฉพาะงานของตัวเอง
    ปิดอยู่: ไม่ทำอะไร ระบบทำงานเหมือนเดิม"""
    request.state.user = None
    if not accounts.auth_enabled():
        return
    user = accounts.user_by_token(x_user_token)
    if user is None and x_upload_token:
        uid = _upload_ticket(x_upload_token)
        user = accounts.user_by_id(uid) if uid else None
    request.state.user = user
    path = request.url.path
    if path.startswith(OPEN_PATHS):
        return
    if user is None:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบ")
    if accounts.is_admin(user):
        return
    job_id = request.path_params.get("job_id")
    if job_id:
        job = store.get(job_id)
        if job is not None and job.owner != user["id"]:
            raise HTTPException(404, "ไม่พบงานนี้")
    if path.startswith(("/admin", "/system")) or (
            path.startswith(ADMIN_WRITES) and request.method not in ("GET", "HEAD")):
        raise HTTPException(403, "เฉพาะผู้ดูแลระบบ")


# ใช้กับทุกเส้นทาง (ต้องเพิ่มก่อนประกาศเส้นทางแรก)
app.router.dependencies.append(Depends(access_guard))


def current_user_id(request: Request) -> Optional[str]:
    user = getattr(request.state, "user", None)
    return user["id"] if user is not None else None


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


app.include_router(account_router, dependencies=[Depends(require_key)])


# ---------------------------------------------------------------- ระบบ
@app.get("/health")
def health():
    return {"status": "ok", "mock": settings.mock_pipeline, "queued": worker.pending_count()}


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
            "running_jobs": worker.running(),
            "queued": sum(1 for j in jobs if j.status == JobStatus.queued),
            "slots": worker.threads,
            "light_slots": settings.light_workers,
            "user_max_jobs": settings.user_max_jobs,
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
    request: Request,
    file: Optional[UploadFile] = File(None, description="ไฟล์วิดีโอต้นฉบับ (ส่งอย่างใดอย่างหนึ่งกับ url)"),
    url: Optional[str] = Form(None, description="ลิงก์คลิป YouTube, TikTok, Facebook, Bilibili ฯลฯ"),
    source_lang: Optional[str] = Form(None, description="รหัสภาษาต้นฉบับ เช่น zh, en, ko, ja ว่างไว้ = ตรวจอัตโนมัติ"),
    target_lang: Optional[str] = Form(None, description="ภาษาพากย์ th หรือ en ว่างไว้ = ค่าเริ่มต้น"),
    num_speakers: Optional[int] = Form(None, ge=1, le=20, description="จำนวนตัวละคร ถ้ารู้ ช่วยให้แยกผู้พูดแม่นขึ้น"),
    review: Optional[bool] = Form(None, description="true = หยุดรอให้ตรวจแก้บทก่อนพากย์"),
    burn_subs: Optional[bool] = Form(None, description="true = ฝังซับลงวิดีโอด้วย"),
    genre: str = Form("", max_length=80, description="แนวเรื่อง เช่น การ์ตูนเด็ก ละครจีนโบราณ ช่วยเลือกสรรพนามตอนแปล"),
    glossary: str = Form("", max_length=2000, description="ชื่อเฉพาะและคำแปล บรรทัดละคำ เช่น ドラえもん = โดราเอมอน"),
    library: bool = Form(False, description="true = คลิปสำหรับเก็บเสียงเข้าคลัง (รับไฟล์เสียงได้) แยกผู้พูดและถอดเสียงแล้วหยุดรอ ไม่แปลไม่พากย์"),
):
    owner = current_user_id(request)
    _check_quota(owner)
    if owner:
        try:
            accounts.can_start(owner)
        except accounts.AccountError as e:
            raise HTTPException(e.status, str(e))
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
        allowed = AUDIO_EXT if library else ALLOWED_EXT
        if ext not in allowed:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, f"รองรับเฉพาะไฟล์ {', '.join(sorted(allowed))}")
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
        review=True if library else rs.default_review if review is None else review,
        burn_subs=False if library else rs.default_burn_subs if burn_subs is None else burn_subs,
        library=library,
        genre=genre.strip(),
        glossary=glossary.strip(),
        owner=owner,
    ))
    worker.submit(job.id, "analyze")
    return JobCreated(id=job.id, status=JobStatus.queued)


@app.get("/jobs", response_model=list[Job], dependencies=[Depends(require_key)])
def list_jobs(request: Request):
    user = getattr(request.state, "user", None)
    jobs = store.all()
    if user is not None and not accounts.is_admin(user):
        jobs = [j for j in jobs if j.owner == user["id"]]
    pos = worker.positions()
    return [_with_position(j, pos) for j in jobs]


@app.get("/jobs/{job_id}", response_model=Job, dependencies=[Depends(require_key)])
def get_job(job_id: str):
    return _with_position(get_job_or_404(job_id), worker.positions())


def _with_position(job: Job, positions: dict[str, int]) -> Job:
    """งานที่รอคิว ใส่ลำดับคิวให้หน้าเว็บแสดง (ไม่ได้บันทึกลงไฟล์งาน)"""
    if job.status == JobStatus.queued and job.id in positions:
        return job.model_copy(update={"queue_position": positions[job.id]})
    return job


def _check_quota(owner: Optional[str]) -> None:
    """ผู้ใช้หนึ่งคนมีงานรอคิวรวมที่กำลังรันได้ไม่เกิน USER_MAX_QUEUED งาน กันคนเดียวส่งงานรัวจนคนอื่นรอนาน"""
    limit = settings.user_max_queued
    if owner and limit > 0 and worker.queued_by(owner) >= limit:
        raise HTTPException(429, f"มีงานรอคิวหรือกำลังทำอยู่ {limit} งานแล้ว รอให้งานเดิมเสร็จก่อนแล้วค่อยส่งเพิ่ม")


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
    _check_quota(job.owner)
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
    """แก้บทพากย์ ป้ายผู้พูด หรือเวลาเริ่ม/จบทีละประโยค แล้วเรียก POST /jobs/{id}/synthesize เพื่อพากย์"""
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
        if edit.take is not None:
            u.take = edit.take
        if edit.mood is not None:
            u.mood = edit.mood
        if edit.start is not None or edit.end is not None:
            start = round(edit.start if edit.start is not None else u.start, 3)
            end = round(edit.end if edit.end is not None else u.end, 3)
            if end - start < 0.2 or (job.duration and end > job.duration + 0.05):
                raise HTTPException(400, f"เวลาของประโยค id={edit.id} ไม่ถูกต้อง ต้องยาวอย่างน้อย 0.2 วินาทีและอยู่ในคลิป")
            moved |= (start, end) != (u.start, u.end)
            u.start, u.end = start, end
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


@app.post("/jobs/{job_id}/transcript/{line_id}/duplicate", response_model=list[Utterance],
          dependencies=[Depends(require_key)])
def duplicate_line(job_id: str, line_id: int, body: LineDuplicate):
    """ทำสำเนาประโยค (บท อารมณ์ ความยาว) ให้ตัวละครอื่นหรือที่เวลาอื่น
    ใช้ตอนสองคนพูดพร้อมกันแต่ถอดเสียงได้แค่คนเดียว: วางสำเนาซ้อนเวลาเดิมให้อีกตัวละคร แล้วแก้บท
    ตัวละครเดียวกันวางทับช่วงที่ตัวเองพูดอยู่แล้วไม่ได้ (คนเดียวพูดทับตัวเองไม่ได้)"""
    job, utterances = _editable_lines(job_id)
    src = next((u for u in utterances if u.id == line_id), None)
    if src is None:
        raise HTTPException(404, f"ไม่พบประโยค id={line_id}")
    speaker = body.speaker or src.speaker
    if speaker not in job.speakers:
        raise HTTPException(404, f"ไม่รู้จักผู้พูด {speaker}")
    start = round(src.start if body.start is None else body.start, 3)
    end = round(start + src.duration, 3)
    if job.duration and end > job.duration + 0.05:
        start, end = round(max(0.0, job.duration - src.duration), 3), round(job.duration, 3)
    if any(u.speaker == speaker and min(end, u.end) - max(start, u.start) > 0.1 for u in utterances):
        raise HTTPException(409, "ตัวละครนี้มีประโยคช่วงเวลานี้อยู่แล้ว คนเดียวพูดทับตัวเองไม่ได้ "
                                 "วางให้ตัวละครอื่น หรือเลื่อนหัวอ่านไปช่วงที่ว่างก่อน")
    new = src.model_copy(update={"id": max(u.id for u in utterances) + 1, "speaker": speaker,
                                 "start": start, "end": end, "take": 0})
    utterances = sorted(utterances + [new], key=lambda u: u.start)
    _save_lines(job, utterances, True)
    return utterances


@app.delete("/jobs/{job_id}/transcript/{line_id}", response_model=list[Utterance],
            dependencies=[Depends(require_key)])
def delete_line(job_id: str, line_id: int):
    """ลบประโยค (เช่นประโยคที่วางผิด หรือเสียงที่ไม่ต้องพากย์) ช่วงนั้นจะไม่มีเสียงพากย์"""
    job, utterances = _editable_lines(job_id)
    if not any(u.id == line_id for u in utterances):
        raise HTTPException(404, f"ไม่พบประโยค id={line_id}")
    if len(utterances) == 1:
        raise HTTPException(400, "ต้องเหลืออย่างน้อยหนึ่งประโยค")
    utterances = [u for u in utterances if u.id != line_id]
    _save_lines(job, utterances, True)
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


@app.patch("/jobs/{job_id}/speakers/{speaker}", response_model=Job, dependencies=[Depends(require_key)])
def rename_speaker(job_id: str, speaker: str, body: SpeakerRename):
    """ตั้งชื่อตัวละคร ใช้แสดงในหน้าเว็บอย่างเดียว ไม่กระทบเสียงพากย์ จึงแก้ได้ทุกเมื่อ"""
    job = get_job_or_404(job_id)
    if speaker not in job.speakers:
        raise HTTPException(404, f"ไม่รู้จักผู้พูด {speaker}")
    name = " ".join(body.name.split())
    names = {s: n for s, n in job.speaker_names.items() if s != speaker}
    if name:
        names[speaker] = name
    return store.update(job_id, speaker_names=names)


LIBRARY_GAP = 0.4  # เว้นเงียบระหว่างประโยคที่ต่อกัน ให้ขั้นเตรียมเสียงแบ่งท่อนตรงช่วงหยุดได้


@app.get("/jobs/{job_id}/lines/quality", dependencies=[Depends(require_key)])
def line_quality(job_id: str) -> dict[str, Optional[float]]:
    """id ประโยค → คะแนนความสะอาดของเสียงต้นฉบับ (1–4.5 ยิ่งสูงยิ่งไม่มีเพลงทับ) ที่วัดไว้ตอนวิเคราะห์
    ประโยคที่แยกหรือแก้เวลาภายหลังไม่มีคะแนน"""
    from .pipeline import gpu

    get_job_or_404(job_id)
    saved = gpu.saved_lines(store.dir(job_id), store.load_transcript(job_id)) or {}
    return {str(i): x.get("quality") for i, x in saved.items()}


@app.post("/jobs/{job_id}/speakers/{speaker}/library", response_model=LibraryVoice, status_code=202,
          dependencies=[Depends(require_key)])
def speaker_to_library(job_id: str, speaker: str, body: SpeakerToLibrary, request: Request):
    """บันทึกเสียงของตัวละครนี้ลงคลัง: ต่อเสียงพูด (แยกเพลงออกแล้ว) ของประโยคที่เลือก (ไม่เลือก = ทุกประโยค)
    ข้ามประโยคที่คนอื่นพูดทับ แล้วเตรียมเสียงเหมือนอัปโหลดเอง (เลือกท่อนที่ชัดที่สุด ถอดข้อความ วัดเสียง)
    target: new = เสียงใหม่, replace = แทนเสียงตัวอย่างของ voice_id (ชื่อและรายละเอียดเดิม), mood = เสียงอารมณ์ของ voice_id"""
    import numpy as np
    import soundfile as sf

    # คลังเสียงใช้ร่วมกันทั้งระบบ แก้ได้เฉพาะผู้ดูแลเหมือน /voices (ADMIN_WRITES)
    user = getattr(request.state, "user", None)
    if accounts.auth_enabled() and (user is None or not accounts.is_admin(user)):
        raise HTTPException(403, "บันทึกลงคลังเสียงได้เฉพาะผู้ดูแลระบบ")
    job, utterances = _editable_lines(job_id)
    if speaker not in job.speakers:
        raise HTTPException(404, f"ไม่รู้จักผู้พูด {speaker}")
    lang = job.detected_lang or job.source_lang
    if lang and lang != "th":
        raise HTTPException(400, "เสียงในคลังต้องเป็นภาษาไทย (ระบบพากย์ใช้ข้อความที่พูดในเสียงตัวอย่างกำกับ) คลิปนี้เป็นภาษาอื่น")
    target = None
    if body.target == "new":
        if not body.name.strip():
            raise HTTPException(400, "ต้องตั้งชื่อเสียง")
    else:
        target = get_voice_or_404(body.voice_id or "")
        if body.target == "mood" and not body.mood:
            raise HTTPException(400, "ต้องเลือกอารมณ์")
        busy = next((m for m in target.moods if m.mood == body.mood), None) if body.target == "mood" else target
        if busy and busy.status == VoiceStatus.processing and busy.stage != "queued":
            raise HTTPException(409, "กำลังเตรียมเสียงนี้อยู่ รอให้เสร็จก่อน")
    vocals = store.dir(job_id) / "vocals.wav"
    if not vocals.exists():
        raise HTTPException(409, "ไม่พบเสียงพูดที่แยกไว้ของงานนี้")
    others = [u for u in utterances if u.speaker != speaker]
    picked = set(body.lines) if body.lines is not None else None
    own = [u for u in utterances if u.speaker == speaker and (picked is None or u.id in picked)
           and not any(min(u.end, o.end) - max(u.start, o.start) > 0.2 for o in others)]
    speech = sum(u.duration for u in own)
    if speech < 3:
        raise HTTPException(400, f"ประโยคที่เลือก (ไม่นับช่วงที่คนอื่นพูดทับ) ยาวรวม {speech:.1f} วินาที ต้องมีอย่างน้อย 3 วินาที")
    sr = sf.info(vocals).samplerate
    parts = []
    for u in own:
        seg, _ = sf.read(vocals, start=int(u.start * sr), stop=int(u.end * sr), dtype="float32")
        parts += [seg.mean(axis=1) if seg.ndim > 1 else seg, np.zeros(int(LIBRARY_GAP * sr), dtype=np.float32)]
    clip = np.concatenate(parts)
    label = f"{job.filename} · {job.speaker_names.get(speaker) or speaker}"

    if body.target == "mood":
        voice_store.delete_mood(target.id, body.mood)
        d = voice_store.mood_dir(target.id, body.mood)
        d.mkdir(parents=True, exist_ok=True)
        sf.write(d / "original.wav", clip, sr)
        v = voice_store.set_mood(target.id, VoiceMood(mood=body.mood, filename=label, denoise=body.denoise))
        worker.submit_voice(target.id, body.mood)
        return v
    if body.target == "replace":
        d = voice_store.dir(target.id)
        for old in d.glob("original.*"):
            old.unlink(missing_ok=True)
        sf.write(d / "original.wav", clip, sr)
        v = voice_store.update(target.id, status=VoiceStatus.processing, stage="queued", error=None,
                               filename=label, source_url=None, denoise=body.denoise)
        worker.submit_voice(target.id)
    else:
        voice_id = voice_store.new_id()
        d = voice_store.dir(voice_id)
        d.mkdir(parents=True, exist_ok=True)
        sf.write(d / "original.wav", clip, sr)
        v = voice_store.add(LibraryVoice(id=voice_id, name=body.name.strip(), gender=body.gender, tone=body.tone.strip(),
                                         description=body.description.strip(), categories=_clean_categories(body.categories),
                                         filename=label, denoise=body.denoise))
        worker.submit_voice(voice_id)
    store.update(job_id, saved_voices={**job.saved_voices, speaker: v.id})
    return v


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
    names = {s: n for s, n in job.speaker_names.items() if s != speaker}
    job = store.update(job_id, speakers=speakers, voice_map=voice_map, speaker_names=names)
    _save_lines(job, utterances, True)
    return job


@app.post("/jobs/{job_id}/retranslate", response_model=JobCreated, status_code=202,
          dependencies=[Depends(require_key)])
def retranslate(job_id: str, body: Retranslate):
    """แปลบทใหม่ทั้งหมดจากบทถอดเสียงเดิม ใช้แนวเรื่อง คำเฉพาะ และชื่อตัวละครที่ตั้งไว้ แล้วรอตรวจบท
    บทที่แก้เองไว้จะถูกแทน ตัวละคร เวลา และอารมณ์ของแต่ละประโยคคงเดิม"""
    job = get_job_or_404(job_id)
    if job.status in ACTIVE:
        raise HTTPException(409, "งานกำลังทำงานอยู่")
    if not store.load_transcript(job_id):
        raise HTTPException(409, "งานนี้ยังไม่มีบท ต้องรอขั้นถอดเสียงเสร็จก่อน")
    fields = {k: v.strip() for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        store.update(job_id, **fields)
    worker.submit(job_id, "translate")
    return JobCreated(id=job_id, status=JobStatus.queued)


@app.post("/jobs/{job_id}/synthesize", response_model=JobCreated, status_code=202,
          dependencies=[Depends(require_key)])
def synthesize(job_id: str):
    """พากย์ต่อหลังตรวจบท หรือพากย์ใหม่หลังแก้บท (พากย์ใหม่เฉพาะประโยคที่เปลี่ยน)"""
    job = get_job_or_404(job_id)
    if job.status in ACTIVE:
        raise HTTPException(409, "งานกำลังทำงานอยู่")
    if not store.load_transcript(job_id):
        raise HTTPException(409, "งานนี้ยังไม่มีบท ต้องรอขั้นแปลเสร็จก่อน")
    _check_quota(job.owner)
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


def _clean_categories(values: list[str]) -> list[str]:
    """ตัดช่องว่าง ตัดซ้ำ (คงลำดับ) ไม่เกิน 10 หมวด หมวดละไม่เกิน 30 ตัว"""
    out: list[str] = []
    for v in values:
        v = " ".join(v.split())[:30]
        if v and v not in out:
            out.append(v)
    return out[:10]


@app.get("/voices", response_model=list[LibraryVoice], dependencies=[Depends(require_key)])
def list_voices():
    return voice_store.all()


@app.post("/voices", response_model=LibraryVoice, status_code=202,
          dependencies=[Depends(require_key_or_upload_token)])
async def create_voice(
    file: Optional[UploadFile] = File(None, description="คลิปเสียงภาษาไทย (หรือวิดีโอ) ของเจ้าของเสียง ประเมินทั้งไฟล์ (ไม่เกิน VOICE_MAX_INPUT_MIN นาที)"),
    url: Optional[str] = Form(None, description="ลิงก์คลิปแทนไฟล์ (ส่งอย่างใดอย่างหนึ่ง)"),
    name: str = Form(..., min_length=1, max_length=80),
    gender: Gender = Form("", description="male, female หรือว่างไว้ให้ระบบเดาจากระดับเสียง"),
    tone: str = Form("", max_length=80, description="โทนเสียง เช่น ทุ้มลึก นุ่มนวล สดใส"),
    description: str = Form("", max_length=1000, description="รายละเอียด เช่น ประวัติคนพากย์ บทที่เหมาะ"),
    categories: list[str] = Form([], description="หมวดหมู่ ส่งได้หลายค่า เช่น ละคร หนัง การ์ตูน"),
    denoise: bool = Form(False, description="true = ลดเสียงรบกวนหลังแยกเพลง (เสียงมีซ่า ลม หรือเพลงหลงเหลือ)"),
):
    """อัปโหลดเสียงเข้าคลัง ระบบแยกเสียงรบกวน ประเมินทุกท่อนพูดในไฟล์ เลือกท่อนที่สะอาดที่สุดของเสียงหลัก 3–10 วินาที และถอดข้อความให้"""
    url = (url or "").strip()
    has_file = file is not None and bool(file.filename)
    if has_file == bool(url):
        raise HTTPException(400, "ส่งไฟล์หรือลิงก์อย่างใดอย่างหนึ่ง")
    if has_file:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in AUDIO_EXT:
            raise HTTPException(400, f"รองรับเฉพาะไฟล์ {', '.join(sorted(AUDIO_EXT))}")
    else:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(400, "ลิงก์ไม่ถูกต้อง ต้องขึ้นต้นด้วย http:// หรือ https://")
    voice_id = voice_store.new_id()
    d = voice_store.dir(voice_id)
    d.mkdir(parents=True, exist_ok=True)
    if has_file:  # ลิงก์ดาวน์โหลดตอนเตรียมเสียง (library.prepare) ไม่ให้คำขอนี้ค้าง
        await save_upload(file, d / f"original{ext}", d)
    v = voice_store.add(LibraryVoice(id=voice_id, name=name.strip(), gender=gender, tone=tone.strip(),
                                     description=description.strip(), categories=_clean_categories(categories),
                                     filename=file.filename if has_file else urlparse(url).netloc.replace("www.", ""),
                                     source_url=url or None, denoise=denoise))
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
    if fields.get("categories") is not None:
        fields["categories"] = _clean_categories(fields["categories"])
    return voice_store.update(voice_id, **fields)


@app.delete("/voices/{voice_id}", status_code=204, dependencies=[Depends(require_key)])
def delete_voice(voice_id: str):
    """ลบเสียงออกจากคลัง ตัวละครที่เลือกเสียงนี้ไว้จะกลับไปใช้เสียงต้นฉบับ"""
    v = get_voice_or_404(voice_id)
    if any(x.status == VoiceStatus.processing and x.stage != "queued" for x in [v, *v.moods]):
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


IMAGE_TYPES = {b"\xff\xd8\xff": (".jpg", "image/jpeg"), b"\x89PNG\r\n\x1a\n": (".png", "image/png")}
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def _image_type(head: bytes) -> Optional[tuple[str, str]]:
    """ดูชนิดรูปจากไบต์แรกของไฟล์ (ไม่เชื่อชื่อไฟล์หรือ content-type ที่ส่งมา)"""
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return next((t for magic, t in IMAGE_TYPES.items() if head.startswith(magic)), None)


@app.post("/voices/{voice_id}/image", response_model=LibraryVoice, dependencies=[Depends(require_key_or_upload_token)])
async def set_voice_image(voice_id: str, file: UploadFile = File(..., description="รูป JPG, PNG หรือ WEBP ไม่เกิน 2 MB")):
    """ตั้งรูปของเสียง (แทนรูปเดิม) หน้าเว็บย่อรูปให้เหลือไม่เกิน 512 px ก่อนส่ง"""
    get_voice_or_404(voice_id)
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "รูปใหญ่เกิน 2 MB")
    kind = _image_type(data[:16])
    if kind is None:
        raise HTTPException(400, "รองรับเฉพาะรูป JPG, PNG หรือ WEBP")
    d = voice_store.dir(voice_id)
    for old in d.glob("image.*"):
        old.unlink(missing_ok=True)
    (d / f"image{kind[0]}").write_bytes(data)
    return voice_store.update(voice_id, image=f"image{kind[0]}")


@app.delete("/voices/{voice_id}/image", response_model=LibraryVoice, dependencies=[Depends(require_key)])
def delete_voice_image(voice_id: str):
    get_voice_or_404(voice_id)
    for old in voice_store.dir(voice_id).glob("image.*"):
        old.unlink(missing_ok=True)
    return voice_store.update(voice_id, image="")


@app.get("/voices/{voice_id}/image", dependencies=[Depends(require_key)])
def get_voice_image(voice_id: str):
    v = get_voice_or_404(voice_id)
    path = voice_store.dir(voice_id) / v.image if v.image else None
    if path is None or not path.exists():
        raise HTTPException(404, "เสียงนี้ยังไม่มีรูป")
    media = next(t[1] for t in [*IMAGE_TYPES.values(), (".webp", "image/webp")] if t[0] == path.suffix)
    return FileResponse(path, media_type=media, headers={"X-Content-Type-Options": "nosniff",
                                                         "Cache-Control": "private, max-age=86400"})


def get_mood_or_404(voice_id: str, mood: str) -> tuple[LibraryVoice, VoiceMood]:
    v = get_voice_or_404(voice_id)
    m = next((x for x in v.moods if x.mood == mood), None)
    if m is None:
        raise HTTPException(404, "เสียงนี้ยังไม่มีอารมณ์นี้")
    return v, m


@app.post("/voices/{voice_id}/moods", response_model=LibraryVoice, status_code=202,
          dependencies=[Depends(require_key_or_upload_token)])
async def add_voice_mood(
    voice_id: str,
    file: UploadFile = File(..., description="คลิปเสียงของคนพากย์คนเดิม พูดด้วยอารมณ์นั้น"),
    mood: Mood = Form(...),
    denoise: bool = Form(False, description="true = ลดเสียงรบกวนหลังแยกเพลง"),
):
    """เพิ่ม (หรือแทน) เสียงตัวอย่างอารมณ์หนึ่ง ประโยคที่เลือกอารมณ์นี้จะพากย์จากเสียงตัวอย่างนี้แทนเสียงปกติ"""
    v = get_voice_or_404(voice_id)
    old = next((x for x in v.moods if x.mood == mood), None)
    if old and old.status == VoiceStatus.processing and old.stage != "queued":
        raise HTTPException(409, "กำลังเตรียมเสียงอารมณ์นี้อยู่ รอให้เสร็จก่อน")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(400, f"รองรับเฉพาะไฟล์ {', '.join(sorted(AUDIO_EXT))}")
    voice_store.delete_mood(voice_id, mood)
    d = voice_store.mood_dir(voice_id, mood)
    d.mkdir(parents=True, exist_ok=True)
    await save_upload(file, d / f"original{ext}", d)
    v = voice_store.set_mood(voice_id, VoiceMood(mood=mood, filename=file.filename or "", denoise=denoise))
    worker.submit_voice(voice_id, mood)
    return v


@app.patch("/voices/{voice_id}/moods/{mood}", response_model=LibraryVoice, dependencies=[Depends(require_key)])
def update_voice_mood(voice_id: str, mood: Mood, patch: VoiceMoodUpdate):
    """แก้ข้อความที่พูดในเสียงตัวอย่างอารมณ์นี้ (ถ้าถอดผิด)"""
    get_mood_or_404(voice_id, mood)
    voice_store.update_mood(voice_id, mood, text=patch.text.strip())
    return voice_store.get(voice_id)


@app.delete("/voices/{voice_id}/moods/{mood}", response_model=LibraryVoice, dependencies=[Depends(require_key)])
def delete_voice_mood(voice_id: str, mood: Mood):
    """ลบอารมณ์นี้ ประโยคที่เลือกอารมณ์นี้ไว้จะกลับไปใช้เสียงปกติ"""
    _, m = get_mood_or_404(voice_id, mood)
    if m.status == VoiceStatus.processing and m.stage != "queued":
        raise HTTPException(409, "กำลังเตรียมเสียงอารมณ์นี้อยู่ รอให้เสร็จก่อนแล้วค่อยลบ")
    voice_store.delete_mood(voice_id, mood)
    return voice_store.get(voice_id)


@app.post("/voices/{voice_id}/moods/{mood}/retry", response_model=LibraryVoice, status_code=202,
          dependencies=[Depends(require_key)])
def retry_voice_mood(voice_id: str, mood: Mood):
    _, m = get_mood_or_404(voice_id, mood)
    if m.status != VoiceStatus.failed:
        raise HTTPException(409, "ลองใหม่ได้เฉพาะเสียงที่เตรียมไม่สำเร็จ")
    if not any(voice_store.mood_dir(voice_id, mood).glob("original.*")):
        raise HTTPException(409, "ไม่พบไฟล์ต้นฉบับแล้ว ลบแล้วอัปโหลดใหม่")
    voice_store.update_mood(voice_id, mood, status=VoiceStatus.processing, stage="queued", error=None)
    worker.submit_voice(voice_id, mood)
    return voice_store.get(voice_id)


@app.get("/voices/{voice_id}/moods/{mood}/audio", dependencies=[Depends(require_key)])
def get_voice_mood_audio(voice_id: str, mood: Mood):
    v, _ = get_mood_or_404(voice_id, mood)
    return file_or_404(voice_store.ref_path(voice_id, mood), "audio/wav", f"{v.name}-{mood}.wav")


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
