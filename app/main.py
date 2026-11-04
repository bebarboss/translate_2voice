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
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import accounts, actors, backup, consent, memory, notify, projects, quality, runtime_settings, supabase_db
from .account_api import require_admin, require_user, router as account_router
from .config import settings
from .jobs import ACTIVE, JobStore, Worker
from .schemas import (Gender, Job, JobCreated, JobOptionsUpdate, JobStatus, LibraryVoice, LineDuplicate, LibraryVoiceUpdate, Mood, Project, TargetLang,
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
    backup.start()
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


OPEN_PATHS = ("/health", "/auth/", "/legal", "/billing/plans", "/docs", "/openapi.json", "/redoc")
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
    # ล็อกอินครั้งแรก: กรอกข้อมูลเบื้องต้นและยอมรับข้อกำหนดก่อน (PUT /auth/profile, POST /auth/consent อยู่ใน OPEN_PATHS)
    if not accounts.profile_complete(user):
        raise HTTPException(428, "กรุณากรอกข้อมูลเบื้องต้นก่อนใช้งาน")
    if not accounts.consent_current(user):
        raise HTTPException(428, "ข้อกำหนดการใช้งานหรือนโยบายความเป็นส่วนตัวมีฉบับใหม่ กรุณายอมรับก่อนใช้งานต่อ")
    job_id = request.path_params.get("job_id")
    if job_id:
        job = store.get(job_id)
        if job is not None and job.owner != user["id"]:
            raise HTTPException(404, "ไม่พบงานนี้")
    project_id = request.path_params.get("project_id")
    if project_id:
        proj = projects.get_store().get(project_id)
        if proj is not None and proj.owner != user["id"]:
            raise HTTPException(404, "ไม่พบโปรเจกต์นี้")
    voice_id = request.path_params.get("voice_id")
    if voice_id and voice_id in hidden_voices(request):
        raise HTTPException(404, "ไม่พบเสียงนี้ในคลัง")
    if path.startswith(("/admin", "/system")) or (
            path.startswith(ADMIN_WRITES) and request.method not in ("GET", "HEAD")):
        raise HTTPException(403, "เฉพาะผู้ดูแลระบบ")


# ใช้กับทุกเส้นทาง (ต้องเพิ่มก่อนประกาศเส้นทางแรก)
app.router.dependencies.append(Depends(access_guard))


def hidden_voices(request: Request) -> set[str]:
    """เสียงของนักพากย์ที่ผู้ดูแลยังไม่อนุมัติ: ซ่อนจากทุกคน ยกเว้นผู้ดูแลและนักพากย์เจ้าของเสียง"""
    user = getattr(request.state, "user", None)
    if user is None or accounts.is_admin(user):
        return set()
    return {v for v, a in actors.voice_actors().items() if a["review"] != "approved" and a["user_id"] != user["id"]}


def with_actor(v: LibraryVoice, info: Optional[dict], show_pending: bool = True,
               moods_info: Optional[dict] = None) -> LibraryVoice:
    """เติมชื่อนักพากย์และสถานะตรวจของเสียงหลักและเสียงอารมณ์ (ไม่เก็บกับเสียง)
    show_pending=False: ซ่อนเสียงอารมณ์ที่ยังไม่ผ่านการตรวจ (ผู้ใช้ทั่วไปที่ไม่ใช่เจ้าของเสียง)"""
    if info is None:
        return v
    reviews = (moods_info if moods_info is not None else actors.mood_reviews()).get(v.id, {})
    moods = []
    for m in v.moods:
        r = reviews.get(m.mood, {"review": info["review"], "note": ""})
        if show_pending or r["review"] == "approved":
            moods.append(m.model_copy(update={"review": r["review"], "review_note": r["note"]}))
    return v.model_copy(update={"actor": info["stage_name"], "review": info["review"], "review_note": info["note"],
                                "moods": moods})


def sees_pending(request: Request, info: Optional[dict]) -> bool:
    """เห็นเสียงอารมณ์ที่ยังไม่ผ่านการตรวจได้ไหม: ปิดระบบบัญชี ผู้ดูแล หรือนักพากย์เจ้าของเสียง"""
    user = getattr(request.state, "user", None)
    return user is None or accounts.is_admin(user) or (info is not None and info["user_id"] == user["id"])


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
    project_id: Optional[str] = Form(None, description="ส่งเข้าโปรเจกต์ จับคู่ตัวละคร ชื่อเฉพาะ และเสียงพากย์ตามที่โปรเจกต์จำไว้"),
):
    owner = current_user_id(request)
    project = None
    if project_id:
        project = projects.get_store().get(project_id)
        if project is None or (owner and project.owner != owner and not accounts.is_admin(request.state.user)):
            raise HTTPException(404, "ไม่พบโปรเจกต์นี้")
    _check_quota(owner)
    if owner:
        try:
            accounts.can_start(owner)
        except accounts.AccountError as e:
            raise HTTPException(e.status, str(e))
    rs = runtime_settings.get()
    target = (target_lang or (project.target_lang if project else "") or rs.default_target_lang).strip().lower()
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
        project_id=project.id if project and not library else None,
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
    quality.forget_job(job_id)
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
            # ความยาวคลิปในเบราว์เซอร์อาจยาวกว่าที่ ffprobe วัดได้เล็กน้อย ลากบล็อกไปท้ายคลิปแล้วเกิน → ดึงกลับมาที่ท้ายคลิป
            if job.duration and job.duration < end <= job.duration + 2:
                end = round(job.duration, 3)
            # 1e-6: ทศนิยมจากการลากขอบให้สั้นสุด 0.2 วินาทีพอดี (เช่น 19.793 - 19.593 = 0.19999...)
            if end - start < 0.2 - 1e-6 or start < 0 or (job.duration and end > job.duration + 0.05):
                raise HTTPException(400, f"เวลาของประโยคที่ {fmt_clock(u.start)} ไม่ถูกต้อง ({start:.2f}–{end:.2f} วินาที) "
                                         "ต้องยาวอย่างน้อย 0.2 วินาทีและอยู่ในคลิป")
            moved |= (start, end) != (u.start, u.end)
            u.start, u.end = start, end
    _save_lines(job, utterances, moved)
    return utterances


def fmt_clock(sec: float) -> str:
    """เวลาแบบที่หน้าเว็บแสดง (นาที:วินาที.ทศนิยม) ใช้ในข้อความแจ้งผู้ใช้"""
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


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
def get_job_voices(job_id: str, request: Request):
    """เสียงที่เลือกไว้และเสียงในคลังที่แนะนำ (ใกล้ที่สุดก่อน) ของแต่ละตัวละคร
    ครั้งแรกต้องวัดเสียงตัวละครบน CPU ใช้เวลาราวสิบวินาที หลังจากนั้นใช้ค่าที่เก็บไว้"""
    from .pipeline import library

    job = get_job_or_404(job_id)
    utterances = store.load_transcript(job_id)
    if not utterances:
        raise HTTPException(409, "งานนี้ยังไม่มีบท ต้องรอขั้นแยกผู้พูดเสร็จก่อน")
    profiles = library.speaker_profiles(store.dir(job_id), utterances)
    hidden = hidden_voices(request)
    ready = [v for v in voice_store.all() if v.status == VoiceStatus.ready and v.id not in hidden]
    embs = {v.id: voice_store.embedding(v.id) for v in ready}
    blocked = actors.blocked_moods()
    mood_bonus = {v.id: 0.01 * min(5, sum(m.status == VoiceStatus.ready and (v.id, m.mood) not in blocked for m in v.moods))
                  for v in ready}
    out = []
    for speaker in job.speakers:
        p = profiles.get(speaker)
        hz = round(float(2 ** (p.pitch / 12)), 1) if p is not None and math.isfinite(p.pitch) else None
        suggestions = []
        if p is not None:
            suggestions = sorted((VoiceSuggestion(voice_id=v.id, score=library.closeness(p, v.pitch_hz, embs[v.id]))
                                  for v in ready), key=lambda s: s.score + mood_bonus.get(s.voice_id, 0), reverse=True)
        out.append(SpeakerVoice(speaker=speaker, voice_id=job.voice_map.get(speaker), pitch_hz=hz,
                                gender=library.guess_gender(hz), suggestions=suggestions))
    return out


@app.put("/jobs/{job_id}/voices", response_model=Job, dependencies=[Depends(require_key)])
def set_job_voices(job_id: str, choice: dict[str, Optional[str]], request: Request):
    """เลือกเสียงจากคลังให้ตัวละคร {"speaker_01": "<id เสียง>", "speaker_02": null}
    null = กลับไปใช้เสียงต้นฉบับ ตัวละครที่ไม่ได้ส่งมาคงค่าเดิม มีผลตอนพากย์รอบถัดไป"""
    job = get_job_or_404(job_id)
    if job.status not in EDITABLE:
        raise HTTPException(409, "เปลี่ยนเสียงได้เมื่องานไม่ได้กำลังทำงานอยู่เท่านั้น")
    voice_map = dict(job.voice_map)
    hidden = hidden_voices(request)
    for speaker, voice_id in choice.items():
        if speaker not in job.speakers:
            raise HTTPException(400, f"ไม่รู้จักผู้พูด {speaker} มีแค่ {job.speakers}")
        if voice_id is None:
            voice_map.pop(speaker, None)
            continue
        v = voice_store.get(voice_id) if voice_id not in hidden else None
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
def list_voices(request: Request):
    info, hidden, moods = actors.voice_actors(), hidden_voices(request), actors.mood_reviews()
    return [with_actor(v, info.get(v.id), sees_pending(request, info.get(v.id)), moods)
            for v in voice_store.all() if v.id not in hidden]


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
def get_voice(voice_id: str, request: Request):
    info = actors.voice_actors().get(voice_id)
    return with_actor(get_voice_or_404(voice_id), info, sees_pending(request, info))


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
    actors.remove_voice(voice_id)


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
    actors.remove_mood(voice_id, mood)
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
def get_voice_mood_audio(voice_id: str, mood: Mood, request: Request):
    v, _ = get_mood_or_404(voice_id, mood)
    info = actors.voice_actors().get(voice_id)
    if (voice_id, mood) in actors.blocked_moods() and not sees_pending(request, info):
        raise HTTPException(404, "ไม่พบเสียงอารมณ์นี้")
    return file_or_404(voice_store.ref_path(voice_id, mood), "audio/wav", f"{v.name}-{mood}.wav")


# ---------------------------------------------------------------- ไทม์ไลน์จากโปรแกรมตัดต่อ (timeline/)
class TrackSetup(BaseModel):
    index: int = Field(..., ge=1, description="ลำดับแทร็กเสียง (A1 = 1)")
    enabled: Optional[bool] = Field(None, description="false = ไม่ใช่บทพูด (เพลง เสียงประกอบ) ไม่ถอดไม่พากย์ แต่ใส่ในเสียงรวม")
    speaker_name: Optional[str] = Field(None, max_length=40, description="ชื่อผู้พูด หลายแทร็กชื่อเดียวกัน = คนเดียวกัน")
    voice_id: Optional[str] = Field(None, description="เสียงในคลังที่ใช้พากย์ ว่าง = ใช้เสียงต้นฉบับของแทร็กเป็นตัวอย่าง")


class TimelineSetup(BaseModel):
    tracks: list[TrackSetup]


def _timeline_job(job_id: str, setup: bool = False):
    from .timeline import model as tl_model
    job = get_job_or_404(job_id)
    if not job.timeline:
        raise HTTPException(404, "งานนี้ไม่ใช่งานไทม์ไลน์")
    if setup and job.stage != "timeline_setup":
        raise HTTPException(409, "เริ่มถอดเสียงไปแล้ว ตั้งค่าแทร็กไม่ได้ (แก้ผู้พูดของแต่ละประโยคในหน้าตรวจบทแทน)")
    return job, tl_model.load(store.dir(job_id))


def _timeline_out(job: Job, info) -> dict:
    from .timeline import timecode as tc
    from .timeline.model import dumps
    out = dumps(info)
    out["fps"] = round(info.fps, 3)
    out["start_tc"] = tc.to_timecode(info.start, info.rate, info.drop_frame)
    out["duration_tc"] = tc.to_timecode(info.duration, info.rate, info.drop_frame)
    for t in out["tracks"]:
        t["speaker_name"] = job.speaker_names.get(t["speaker"], "")
        t["voice_id"] = job.voice_map.get(t["speaker"])
        for c in t["clips"]:
            c["start_tc"] = tc.to_timecode(info.start + c["start"], info.rate, info.drop_frame)
            c["end_tc"] = tc.to_timecode(info.start + c["end"], info.rate, info.drop_frame)
    return {"job": job.model_dump(mode="json"), "timeline": out}


@app.post("/timeline", status_code=201, dependencies=[Depends(require_key_or_upload_token)])
async def import_timeline(
    request: Request,
    file: UploadFile = File(..., description="ไฟล์ไทม์ไลน์ (.xml .fcpxml .edl .otio) หรือ zip ที่มีไทม์ไลน์และไฟล์สื่อ"),
    media: list[UploadFile] = File([], description="ไฟล์เสียง/วิดีโอที่ไทม์ไลน์อ้างถึง (ส่งได้หลายไฟล์ หรือรวมใน zip)"),
    fps: Optional[float] = Form(None, gt=0, le=120, description="อัตราเฟรม จำเป็นสำหรับ EDL ที่ไม่ได้บอกไว้"),
    drop_frame: Optional[bool] = Form(None, description="บังคับ drop-frame (ไม่ส่ง = ดูจากไฟล์)"),
    timeline_name: Optional[str] = Form(None, description="ชื่อไฟล์ไทม์ไลน์ใน zip เมื่อมีหลายไฟล์"),
    source_lang: Optional[str] = Form(None, description="ภาษาต้นฉบับ ว่าง = ตรวจอัตโนมัติ"),
    target_lang: str = Form("th"),
    genre: str = Form("", max_length=80),
    glossary: str = Form("", max_length=2000),
    review: bool = Form(True, description="true = หยุดรอตรวจบทก่อนพากย์"),
    start: bool = Form(False, description="true = ไฟล์สื่อครบแล้วเริ่มถอดเสียงเลย (ตั้งค่าแทร็กแบบเริ่มต้น)"),
):
    """นำเข้าไทม์ไลน์ อ่านแทร็กเสียง คลิป และไฟล์ที่อ้างถึง คืนรายชื่อไฟล์ที่ขาด (missing)
    ขั้นต่อไป: อัปโหลดไฟล์ที่ขาด (POST /jobs/{id}/timeline/media) → ตั้งผู้พูดและเสียง (PUT /jobs/{id}/timeline)
    → เริ่ม (POST /jobs/{id}/timeline/start)"""
    from .timeline import importer, model as tl_model

    owner = current_user_id(request)
    if target_lang not in ("th", "en"):
        raise HTTPException(400, "ภาษาพากย์ต้องเป็น th หรือ en")
    job_id = store.new_id()
    job_dir = store.dir(job_id)
    base = job_dir / "timeline"
    (base / "media").mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "timeline").name
    try:
        if name.lower().endswith(".zip"):
            tmp = job_dir / "upload.zip"
            await save_upload(file, tmp, job_dir)
            files = importer.extract_zip(tmp, base, settings.max_upload_mb * 2**20 * 4)
            tmp.unlink(missing_ok=True)
            tl_path = importer.find_timeline(files, timeline_name)
        else:
            if Path(name).suffix.lower() not in importer.TIMELINE_EXT:
                raise importer.TimelineError(f"รองรับ {', '.join(sorted(importer.TIMELINE_EXT))} หรือ .zip")
            tl_path = base / name
            await save_upload(file, tl_path, job_dir)
        for m in media:
            if m.filename:
                await save_upload(m, base / "media" / Path(m.filename).name, job_dir)
        _, info = importer.read(tl_path, fps, drop_frame)
        info.source = str(tl_path.relative_to(base)).replace("\\", "/")
        importer.resolve_media(info, base, exclude=tl_path)
    except importer.TimelineError as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, str(e))
    tl_model.save(job_dir, info)
    job = store.add(Job(id=job_id, filename=name, timeline=True, source_lang=(source_lang or "").strip().lower() or None,
                        target_lang=target_lang, review=review, genre=genre.strip(), glossary=glossary.strip(),
                        owner=owner, speakers=info.speakers(),
                        speaker_names={t.speaker: t.name for t in info.dialogue()}))
    job = store.update(job_id, status=JobStatus.awaiting_review, stage="timeline_setup")
    if start and not info.missing:
        return start_timeline(job_id, request)
    return _timeline_out(job, info)


@app.get("/jobs/{job_id}/timeline", dependencies=[Depends(require_key)])
def get_timeline(job_id: str):
    """แทร็ก คลิป (timecode ตามไทม์ไลน์) ผู้พูด เสียงที่เลือก และไฟล์ที่ยังขาด"""
    job, info = _timeline_job(job_id)
    return _timeline_out(job, info)


@app.post("/jobs/{job_id}/timeline/media", dependencies=[Depends(require_key_or_upload_token)])
async def add_timeline_media(job_id: str, files: list[UploadFile] = File(..., description="ไฟล์สื่อที่ขาด (หรือ zip)")):
    """อัปโหลดไฟล์สื่อที่ไทม์ไลน์อ้างถึงเพิ่ม แล้วจับคู่ใหม่ คืนรายชื่อที่ยังขาด"""
    from .timeline import importer, model as tl_model
    job, info = _timeline_job(job_id, setup=True)
    job_dir = store.dir(job_id)
    base = job_dir / "timeline"
    dest = base / "media"
    for f in files:
        name = Path(f.filename or "").name
        if not name:
            continue
        if name.lower().endswith(".zip"):
            tmp = job_dir / "upload.zip"
            await save_upload(f, tmp, job_dir / "_none")
            try:
                importer.extract_zip(tmp, dest, settings.max_upload_mb * 2**20 * 4)
            except importer.TimelineError as e:
                raise HTTPException(400, str(e))
            finally:
                tmp.unlink(missing_ok=True)
        else:
            await save_upload(f, dest / name, job_dir / "_none")
    importer.resolve_media(info, base, exclude=base / info.source)
    tl_model.save(job_dir, info)
    return _timeline_out(job, info)


@app.put("/jobs/{job_id}/timeline", dependencies=[Depends(require_key)])
def setup_timeline(job_id: str, body: TimelineSetup, request: Request):
    """ตั้งค่าแทร็ก: เปิด/ปิด (บทพูดหรือไม่) ชื่อผู้พูด (ชื่อเดียวกัน = คนเดียวกัน) และเสียงพากย์จากคลัง
    แทร็กที่ไม่ได้ส่งมาคงค่าเดิม"""
    from .timeline import model as tl_model
    job, info = _timeline_job(job_id, setup=True)
    by_index = {t.index: t for t in info.tracks}
    names = {t.speaker: job.speaker_names.get(t.speaker) or t.name for t in info.tracks if t.speaker}
    voices = dict(job.voice_map)
    wanted_name: dict[int, str] = {t.index: names.get(t.speaker, t.name) for t in info.tracks}
    wanted_voice: dict[int, Optional[str]] = {t.index: voices.get(t.speaker) for t in info.tracks}
    hidden = hidden_voices(request)
    for s in body.tracks:
        t = by_index.get(s.index)
        if t is None or not t.clips:
            raise HTTPException(400, f"ไม่มีแทร็กเสียง A{s.index} หรือแทร็กนี้ไม่มีคลิป")
        if s.enabled is not None:
            t.enabled = s.enabled
        if s.speaker_name is not None and s.speaker_name.strip():
            wanted_name[t.index] = s.speaker_name.strip()
        if s.voice_id is not None:
            if s.voice_id:
                v = voice_store.get(s.voice_id) if s.voice_id not in hidden else None
                if v is None or v.status != VoiceStatus.ready:
                    raise HTTPException(400, f"เสียง {s.voice_id} ไม่มีในคลังหรือยังเตรียมไม่เสร็จ")
            wanted_voice[t.index] = s.voice_id or None
    # ชื่อเดียวกัน = ผู้พูดคนเดียวกัน เรียงตามลำดับแทร็ก
    ids: dict[str, str] = {}
    speaker_names, voice_map = {}, {}
    for t in info.tracks:
        if not t.clips:
            continue
        label = wanted_name[t.index]
        t.speaker = ids.setdefault(label, f"speaker_{len(ids) + 1:02d}")
        speaker_names[t.speaker] = label
        if t.enabled and wanted_voice[t.index]:
            voice_map[t.speaker] = wanted_voice[t.index]
    if not info.dialogue():
        raise HTTPException(400, "ต้องเปิดอย่างน้อยหนึ่งแทร็กเป็นบทพูด")
    tl_model.save(store.dir(job_id), info)
    job = store.update(job_id, speakers=info.speakers(), speaker_names=speaker_names, voice_map=voice_map)
    return _timeline_out(job, info)


@app.post("/jobs/{job_id}/timeline/start", response_model=JobCreated, status_code=202, dependencies=[Depends(require_key)])
def start_timeline(job_id: str, request: Request):
    """เริ่มถอดเสียงทีละแทร็ก แปล (และพากย์ต่อเลยถ้าไม่ได้ขอตรวจบท)"""
    job, info = _timeline_job(job_id, setup=True)
    if info.missing:
        raise HTTPException(409, "ไฟล์สื่อยังไม่ครบ: " + ", ".join(info.missing))
    if not info.dialogue():
        raise HTTPException(400, "ต้องเปิดอย่างน้อยหนึ่งแทร็กเป็นบทพูด")
    owner = current_user_id(request)
    _check_quota(owner)
    if owner:
        try:
            accounts.can_start(owner)
        except accounts.AccountError as e:
            raise HTTPException(e.status, str(e))
    store.update(job_id, status=JobStatus.queued, stage="queued", progress=0.0, error=None)
    worker.submit(job_id, "analyze")
    return JobCreated(id=job_id, status=JobStatus.queued)


@app.get("/jobs/{job_id}/timeline/export", dependencies=[Depends(require_key)])
def export_timeline(job_id: str, formats: str = "xml,fcpxml,stems,mix,srt", media_dir: Optional[str] = None):
    """zip สำหรับนำกลับเข้าโปรแกรมตัดต่อ formats เลือกได้: xml (Premiere/Resolve), fcpxml (Resolve/Final Cut Pro),
    stems (WAV แยกผู้พูด), mix (เสียงรวม), srt — มี README เสมอ
    media_dir: โฟลเดอร์บนเครื่องผู้ตัดต่อที่จะวางไฟล์เสียงพากย์ ไม่ส่ง = TH_dub ข้างไฟล์เสียงเดิม"""
    from .timeline import exporter
    job, info = _timeline_job(job_id)
    if job.status != JobStatus.done:
        raise HTTPException(409, "ยังพากย์ไม่เสร็จ")
    chosen = tuple(f.strip() for f in formats.split(",") if f.strip())
    try:
        z = exporter.build(store.dir(job_id), info, store.load_transcript(job_id), job.speaker_names, chosen,
                           (media_dir or "").strip() or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return FileResponse(z, media_type="application/zip", filename=z.name)



# ---------------------------------------------------------------- โปรเจกต์ (projects.py)
class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    genre: str = Field("", max_length=120)
    glossary: str = Field("", max_length=4000)
    speech_style: str = Field("", max_length=400)
    target_lang: TargetLang = "th"


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    genre: Optional[str] = Field(None, max_length=120)
    glossary: Optional[str] = Field(None, max_length=4000)
    speech_style: Optional[str] = Field(None, max_length=400)
    target_lang: Optional[TargetLang] = None


class CharacterPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    gender: Optional[str] = Field(None, max_length=10)
    role: Optional[str] = Field(None, max_length=200)
    self: Optional[str] = Field(None, max_length=40)
    addresses: Optional[str] = Field(None, max_length=120)
    voice_id: Optional[str] = Field(None, max_length=40, description="ว่าง = เลียนเสียงต้นฉบับ")


class JobProject(BaseModel):
    project_id: Optional[str] = Field(None, description="null = เอางานออกจากโปรเจกต์")


class ProjectSync(BaseModel):
    """ผู้พูด → id ตัวละครในโปรเจกต์ที่จะบันทึกทับ, "new" = ตัวละครใหม่, "skip" = ไม่บันทึก
    ไม่ส่งผู้พูดไหน ใช้ผลจับคู่ที่มั่นใจ (หรือสร้างตัวใหม่ถ้าตั้งชื่อไว้)"""
    mapping: dict[str, str] = Field(default_factory=dict)
    settings: bool = Field(False, description="true = บันทึกแนวเรื่อง ชื่อเฉพาะ และระดับภาษาของงานนี้เป็นค่าของโปรเจกต์ด้วย")


def get_project_or_404(project_id: str):
    p = projects.get_store().get(project_id)
    if p is None:
        raise HTTPException(404, "ไม่พบโปรเจกต์นี้")
    return p


def _own_projects(request: Request) -> list:
    user = getattr(request.state, "user", None)
    items = projects.get_store().all()
    return items if user is None or accounts.is_admin(user) else [p for p in items if p.owner == user["id"]]


def _episodes(project_id: str) -> list[Job]:
    return [j for j in store.all() if j.project_id == project_id]


@app.get("/projects", dependencies=[Depends(require_key)])
def list_projects(request: Request):
    """โปรเจกต์ของผู้ใช้ (ใหม่ก่อน) พร้อมจำนวนตอน"""
    counts: dict[str, int] = {}
    for j in store.all():
        if j.project_id:
            counts[j.project_id] = counts.get(j.project_id, 0) + 1
    return [projects.public(p, counts.get(p.id, 0)) for p in _own_projects(request)]


@app.post("/projects", status_code=201, dependencies=[Depends(require_key)])
def create_project(body: ProjectIn, request: Request):
    p = Project(id=projects.ProjectStore.new_id(), owner=current_user_id(request), name=body.name.strip(),
                genre=body.genre.strip(), glossary=body.glossary.strip(), speech_style=body.speech_style.strip(),
                target_lang=body.target_lang)
    return projects.public(projects.get_store().add(p))


@app.get("/projects/{project_id}", dependencies=[Depends(require_key)])
def get_project(project_id: str):
    """โปรเจกต์พร้อมตอนทั้งหมด (ใหม่ก่อน)"""
    p = get_project_or_404(project_id)
    eps = _episodes(project_id)
    return {**projects.public(p, len(eps)), "jobs": [j.model_dump(mode="json") for j in eps]}


@app.patch("/projects/{project_id}", dependencies=[Depends(require_key)])
def update_project(project_id: str, body: ProjectPatch):
    p = get_project_or_404(project_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(p, k, v.strip() if isinstance(v, str) else v)
    return projects.public(projects.get_store().save(p), len(_episodes(project_id)))


@app.delete("/projects/{project_id}", status_code=204, dependencies=[Depends(require_key)])
def delete_project(project_id: str):
    """ลบโปรเจกต์ งานในโปรเจกต์ยังอยู่ (แค่ไม่อยู่ในโปรเจกต์แล้ว)"""
    get_project_or_404(project_id)
    for j in _episodes(project_id):
        store.update(j.id, project_id=None, project_matches={})
    memory.forget_projects([project_id])
    projects.get_store().delete(project_id)


@app.get("/projects/{project_id}/memory", dependencies=[Depends(require_key)])
def project_memory(project_id: str, limit: int = 200):
    """ความจำคำแปล: จำนวนบรรทัดที่จำไว้ และบทที่ผู้ใช้แก้ล่าสุด (ใช้เป็นตัวอย่างตอนแปลตอนถัดไป)"""
    get_project_or_404(project_id)
    return memory.listing(project_id, max(1, min(limit, 500)))


@app.delete("/projects/{project_id}/memory/{memory_id}", status_code=204, dependencies=[Depends(require_key)])
def delete_memory_line(project_id: str, memory_id: int):
    """ลบบทที่จำผิดออก (ตอนถัดไปจะไม่ใช้เป็นตัวอย่าง)"""
    get_project_or_404(project_id)
    memory.delete(project_id, memory_id)


@app.delete("/projects/{project_id}/memory", status_code=204, dependencies=[Depends(require_key)])
def clear_memory(project_id: str):
    get_project_or_404(project_id)
    memory.delete(project_id)


@app.patch("/projects/{project_id}/characters/{char_id}", dependencies=[Depends(require_key)])
def update_character(project_id: str, char_id: str, body: CharacterPatch, request: Request):
    """แก้ตัวละครของโปรเจกต์ (ชื่อ ข้อมูลให้ผู้แปล เสียงพากย์) มีผลกับงานที่ส่งเข้ามาหลังจากนี้"""
    p = get_project_or_404(project_id)
    c = next((x for x in p.characters if x.id == char_id), None)
    if c is None:
        raise HTTPException(404, "ไม่พบตัวละครนี้")
    fields = body.model_dump(exclude_unset=True)
    if "voice_id" in fields:
        vid = fields.pop("voice_id") or None
        if vid and (voice_store.get(vid) is None or vid in hidden_voices(request)):
            raise HTTPException(400, "ไม่พบเสียงนี้ในคลัง")
        c.voice_id = vid
    for k, v in fields.items():
        if v is not None:
            setattr(c, k, v.strip())
    return projects.public(projects.get_store().save(p), len(_episodes(project_id)))


@app.delete("/projects/{project_id}/characters/{char_id}", dependencies=[Depends(require_key)])
def delete_character(project_id: str, char_id: str):
    p = get_project_or_404(project_id)
    p.characters = [x for x in p.characters if x.id != char_id]
    return projects.public(projects.get_store().save(p), len(_episodes(project_id)))


@app.put("/jobs/{job_id}/project", response_model=Job, dependencies=[Depends(require_key)])
def set_job_project(job_id: str, body: JobProject, request: Request):
    """ย้ายงานเข้าหรือออกจากโปรเจกต์ งานที่แยกผู้พูดแล้วจับคู่ตัวละครให้ทันที (ตั้งชื่อและเสียงเฉพาะที่มั่นใจ)"""
    job = get_job_or_404(job_id)
    if body.project_id:
        p = get_project_or_404(body.project_id)
        user = getattr(request.state, "user", None)
        if user is not None and not accounts.is_admin(user) and p.owner != user["id"]:
            raise HTTPException(404, "ไม่พบโปรเจกต์นี้")
    job = store.update(job_id, project_id=body.project_id or None, project_matches={})
    utterances = store.load_transcript(job_id)
    if job.project_id and utterances and job.status not in ACTIVE:
        from .pipeline import runner
        job, _ = runner._apply_project(store, job_id, utterances)
    return job


@app.post("/jobs/{job_id}/project/sync", dependencies=[Depends(require_key)])
def sync_job_project(job_id: str, body: ProjectSync):
    """บันทึกตัวละครของงานนี้เข้าโปรเจกต์: ชื่อ เสียงพากย์ ข้อมูลจากการวิเคราะห์เรื่อง และลายเสียง (ใช้จับคู่ตอนถัดไป)"""
    job = get_job_or_404(job_id)
    if not job.project_id:
        raise HTTPException(409, "งานนี้ไม่ได้อยู่ในโปรเจกต์")
    p = get_project_or_404(job.project_id)
    utterances = store.load_transcript(job_id)
    if not utterances:
        raise HTTPException(409, "งานนี้ยังไม่มีบท ต้องรอแยกผู้พูดเสร็จก่อน")
    from .pipeline import library
    prof = library.speaker_profiles(store.dir(job_id), utterances)
    info = {c["speaker"]: c for c in (job.story or {}).get("characters", [])}
    matches = {s: dict(m) for s, m in (job.project_matches or {}).items()}
    ids = {c.id for c in p.characters}
    saved = 0
    for s in job.speakers:
        choice = body.mapping.get(s)
        if choice is None:
            m = matches.get(s)
            choice = m["character"] if m and (m.get("sure") or m.get("confirmed")) else ("new" if job.speaker_names.get(s) else "skip")
        if choice == "skip":
            continue
        if choice != "new" and choice not in ids:
            raise HTTPException(400, f"ไม่พบตัวละคร {choice} ในโปรเจกต์")
        name = job.speaker_names.get(s) or (info.get(s) or {}).get("name") or s
        c = projects.learn(p, s, None if choice == "new" else choice, name, job.voice_map.get(s), prof.get(s), info.get(s))
        ids.add(c.id)
        matches[s] = {"character": c.id, "name": c.name, "score": (matches.get(s) or {}).get("score"), "sure": True, "confirmed": True}
        saved += 1
    if body.settings:
        p.genre = job.genre or (job.story or {}).get("genre") or p.genre
        p.glossary = job.glossary or "\n".join((job.story or {}).get("glossary") or []) or p.glossary
        p.speech_style = (job.story or {}).get("register") or p.speech_style
    projects.get_store().save(p)
    job = store.update(job_id, project_matches=matches)
    try:  # บทของงานนี้เข้าความจำคำแปลด้วย ตอนถัดไปจะได้ใช้สำนวนที่แก้ไว้
        memory.record_job(job, utterances, store.dir(job_id))
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("translation memory save failed for job %s: %s", job_id, e)
    return {"saved": saved, "project": projects.public(projects.get_store().get(p.id), len(_episodes(p.id))),
            "job": job.model_dump(mode="json")}

# ---------------------------------------------------------------- นักพากย์ (actors.py)
class ActorApply(BaseModel):
    stage_name: str = Field(..., min_length=1, max_length=60)
    gender: Gender = ""
    bio: str = Field("", max_length=1000)
    contact: str = Field("", max_length=200)
    consent_version: str = Field(..., max_length=20, description="เวอร์ชันหนังสือยินยอมที่อ่านและกดยอมรับ")
    consent_items: list[str] = Field(default_factory=list, max_length=10, description="ข้อที่ติ๊กยอมรับ (ต้องครบทุกข้อ)")


class ConsentAccept(BaseModel):
    version: str = Field(..., max_length=20)
    items: list[str] = Field(default_factory=list, max_length=10)


class Review(BaseModel):
    approve: bool
    note: str = Field("", max_length=300)


class ActorPayment(BaseModel):
    payee_name: str = Field(..., max_length=100, description="ชื่อ-นามสกุลผู้รับเงินตามบัตรประชาชน")
    tax_id: str = Field(..., max_length=20, description="เลขประจำตัวผู้เสียภาษี / เลขบัตรประชาชน 13 หลัก")
    address: str = Field(..., max_length=300, description="ที่อยู่ตามบัตรประชาชน")
    bank: str = Field(..., max_length=40)
    account_no: str = Field(..., max_length=30, description="เลขบัญชี หรือเบอร์/เลขพร้อมเพย์")
    account_name: str = Field(..., max_length=100)


class Payout(BaseModel):
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    note: str = Field("", max_length=200)


def _actor_fail(e: accounts.AccountError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _client(request: Request) -> tuple[str, str]:
    """IP และเบราว์เซอร์ของผู้กดยอมรับ (หน้าเว็บส่งต่อมาใน x-client-ip / x-client-ua)"""
    ip = request.headers.get("x-client-ip") or (request.client.host if request.client else "")
    return ip, request.headers.get("x-client-ua") or request.headers.get("user-agent") or ""


def _approved_actor(user) -> dict:
    a = actors.actor(user["id"])
    if a is None or a["status"] != "approved":
        raise HTTPException(403, "ต้องเป็นนักพากย์ที่ผู้ดูแลอนุมัติแล้ว")
    if not actors.has_consent(user["id"]):
        raise HTTPException(409, "หนังสือยินยอมมีเวอร์ชันใหม่ กดยอมรับก่อนส่งเสียง")
    return a


def _own_voice(user, voice_id: str) -> LibraryVoice:
    info = actors.voice_actors().get(voice_id)
    if info is None or info["user_id"] != user["id"]:
        raise HTTPException(404, "ไม่พบเสียงนี้")
    return with_actor(get_voice_or_404(voice_id), info)


@app.get("/legal/actor", dependencies=[Depends(require_key)])
def actor_consent():
    """หนังสือยินยอม PDPA และสิทธิ์ใช้เสียงของนักพากย์ฉบับปัจจุบัน และข้อที่ต้องติ๊ก (อ่านได้โดยไม่ต้องล็อกอิน)"""
    return actors.document()


@app.get("/actor/me", dependencies=[Depends(require_key)])
def actor_me(user=Depends(require_user)):
    """สถานะนักพากย์ของผู้ใช้ ความยินยอม เสียงที่ส่ง และยอดค่าตอบแทนย้อนหลัง 6 เดือน"""
    info = actors.voice_actors()
    voices = [with_actor(v, info[v.id]) for v in voice_store.all()
              if v.id in info and info[v.id]["user_id"] == user["id"]]
    c = actors.consent(user["id"])
    return {"actor": actors.actor(user["id"]),
            "consent": {"version": c["version"], "accepted_at": c["accepted_at"]} if c else None,
            "consent_current": actors.has_consent(user["id"]), "consent_version": actors.CONSENT_VERSION,
            "rate": settings.actor_rate, "voices": [v.model_dump(mode="json") for v in voices],
            "payment": actors.payment_out(user["id"]), "banks": actors.BANKS,
            "wht": {"percent": settings.actor_wht_percent, "min": settings.actor_wht_min},
            "usage": actors.summary(user["id"]), "payouts": actors.payouts(user["id"]),
            "mood_usage": actors.mood_usage(user["id"])}


@app.post("/actor/apply", dependencies=[Depends(require_key)])
def actor_apply(body: ActorApply, request: Request, user=Depends(require_user)):
    """สมัครเป็นนักพากย์พร้อมยอมรับหนังสือยินยอม รอผู้ดูแลอนุมัติ"""
    try:
        a = actors.apply(user["id"], body.stage_name.strip(), body.gender, body.bio.strip(), body.contact.strip(),
                         body.consent_version, body.consent_items, *_client(request))
    except accounts.AccountError as e:
        raise _actor_fail(e)
    notify.actor_applied(user["id"], a["stage_name"])
    return a


@app.post("/actor/consent", status_code=204, dependencies=[Depends(require_key)])
def actor_accept(body: ConsentAccept, request: Request, user=Depends(require_user)):
    """ยอมรับหนังสือยินยอมเวอร์ชันใหม่"""
    try:
        actors.accept_consent(user["id"], body.version, body.items, *_client(request))
    except accounts.AccountError as e:
        raise _actor_fail(e)


@app.get("/actor/usage", dependencies=[Depends(require_key)])
def actor_usage(month: str, user=Depends(require_user)):
    """รายการงานที่ใช้เสียงของนักพากย์ในเดือนนั้น (YYYY-MM)"""
    return actors.usage_rows(user["id"], month)


@app.post("/actor/voices", response_model=LibraryVoice, status_code=202, dependencies=[Depends(require_key)])
async def actor_record(
    file: UploadFile = File(..., description="เสียงที่อัดจากเบราว์เซอร์ (webm/m4a) หรือไฟล์เสียง"),
    voice_id: Optional[str] = Form(None, description="ว่าง = เสียงใหม่, มีค่า = อัดแทนเสียงหลัก หรือเพิ่มเสียงอารมณ์ของเสียงนั้น"),
    mood: Optional[Mood] = Form(None),
    denoise: bool = Form(True),
    user=Depends(require_user),
):
    """นักพากย์ส่งเสียงเข้าคลัง เตรียมเสียงเหมือนอัปโหลดทั่วไป แล้วรอผู้ดูแลตรวจฟังก่อนผู้อื่นจะเห็น"""
    a = _approved_actor(user)
    ext = Path(file.filename or "").suffix.lower() or ".webm"
    if ext not in AUDIO_EXT:
        raise HTTPException(400, f"รองรับเฉพาะไฟล์ {', '.join(sorted(AUDIO_EXT))}")
    label = f"อัดโดย {a['stage_name']}"
    if voice_id:
        v = _own_voice(user, voice_id)
        busy = next((m for m in v.moods if m.mood == mood), None) if mood else v
        if busy and busy.status == VoiceStatus.processing and busy.stage != "queued":
            raise HTTPException(409, "กำลังเตรียมเสียงนี้อยู่ รอให้เสร็จก่อน")
        if mood:
            voice_store.delete_mood(voice_id, mood)
            d = voice_store.mood_dir(voice_id, mood)
            d.mkdir(parents=True, exist_ok=True)
            await save_upload(file, d / f"original{ext}", d)
            voice_store.set_mood(voice_id, VoiceMood(mood=mood, filename=label, denoise=denoise))
        else:
            d = voice_store.dir(voice_id)
            for old in d.glob("original.*"):
                old.unlink(missing_ok=True)
            await save_upload(file, d / f"original{ext}", d / "_none")  # เกินขนาดไม่ลบทั้งเสียง
            voice_store.update(voice_id, status=VoiceStatus.processing, stage="queued", error=None,
                               filename=label, source_url=None, denoise=denoise)
        if mood:
            actors.add_mood(voice_id, mood)
        else:
            actors.resubmit_voice(voice_id)
        worker.submit_voice(voice_id, mood or "")
        out = _own_voice(user, voice_id)
        notify.actor_voice_submitted(user["id"], f"{out.name} ({mood})" if mood else out.name)
        return out
    if mood:
        raise HTTPException(400, "อัดเสียงหลักก่อน แล้วค่อยเพิ่มเสียงอารมณ์")
    voice_id = voice_store.new_id()
    d = voice_store.dir(voice_id)
    d.mkdir(parents=True, exist_ok=True)
    await save_upload(file, d / f"original{ext}", d)
    voice_store.add(LibraryVoice(id=voice_id, name=a["stage_name"], gender=a["gender"], description=a["bio"],
                                 categories=["นักพากย์"], filename=label, denoise=denoise))
    actors.add_voice(voice_id, user["id"])
    worker.submit_voice(voice_id)
    notify.actor_voice_submitted(user["id"], a["stage_name"])
    return _own_voice(user, voice_id)


@app.delete("/actor/voices/{voice_id}", status_code=204, dependencies=[Depends(require_key)])
def actor_delete_voice(voice_id: str, user=Depends(require_user)):
    v = _own_voice(user, voice_id)
    if any(x.status == VoiceStatus.processing and x.stage != "queued" for x in [v, *v.moods]):
        raise HTTPException(409, "กำลังเตรียมเสียงนี้อยู่ รอให้เสร็จก่อนแล้วค่อยลบ")
    voice_store.delete(voice_id)
    actors.remove_voice(voice_id)


@app.put("/actor/payment", dependencies=[Depends(require_key)])
def actor_payment(body: ActorPayment, user=Depends(require_user)):
    """ข้อมูลรับค่าตอบแทน: ชื่อผู้รับเงิน เลขผู้เสียภาษี ที่อยู่ และบัญชีธนาคาร (ต้องมีก่อนผู้ดูแลบันทึกการจ่าย)"""
    try:
        return actors.save_payment(user["id"], body.payee_name, body.tax_id, body.address, body.bank,
                                   body.account_no, body.account_name)
    except accounts.AccountError as e:
        raise _actor_fail(e)


@app.post("/actor/withdraw", status_code=204, dependencies=[Depends(require_key)])
def actor_withdraw(user=Depends(require_user)):
    """ถอนความยินยอม: ลบเสียงทั้งหมดของนักพากย์ออกจากคลังทันที"""
    try:
        ids = actors.withdraw(user["id"])
    except accounts.AccountError as e:
        raise _actor_fail(e)
    for voice_id in ids:
        voice_store.delete(voice_id)


class CloseAccount(BaseModel):
    confirm: str = Field(..., max_length=200, description="พิมพ์อีเมลของบัญชีเพื่อยืนยัน")


@app.get("/auth/export", dependencies=[Depends(require_key)])
def export_my_data(user=Depends(require_user)):
    """สำเนาข้อมูลทั้งหมดของผู้ใช้เป็นไฟล์ JSON (สิทธิ์ขอสำเนาและโอนย้ายข้อมูลตาม PDPA)
    มีบัญชี ความยินยอม เครดิต งานพร้อมบท และข้อมูลนักพากย์ ไฟล์คลิปและเสียงดาวน์โหลดได้จากหน้างานแต่ละงาน"""
    uid = user["id"]
    try:
        out = accounts.export_data(uid)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))
    jobs = []
    for j in store.all():
        if j.owner == uid:
            lines = [u.model_dump(mode="json", include={"id", "start", "end", "speaker", "source", "target", "mood"})
                     for u in store.load_transcript(j.id)]
            jobs.append({**j.model_dump(mode="json", exclude={"input_path", "queue_position"}), "transcript": lines})
    mine = {v for v, a in actors.voice_actors().items() if a["user_id"] == uid}
    out.update(consents=consent.history(uid), jobs=jobs, actor=actors.export_data(uid),
               actor_voices=[v.model_dump(mode="json") for v in voice_store.all() if v.id in mine],
               exported_at=time.time())
    return JSONResponse(out, headers={"Content-Disposition": f'attachment; filename="my-data-{uid}.json"'})


@app.post("/auth/close", status_code=204, dependencies=[Depends(require_key)])
def close_my_account(body: CloseAccount, user=Depends(require_user)):
    """ปิดบัญชีและลบข้อมูล (สิทธิ์ขอลบข้อมูลตาม PDPA): งานและไฟล์ทั้งหมด เสียงนักพากย์ ข้อมูลส่วนตัว และเครดิตที่เหลือ
    ประวัติการเงินเก็บไว้ตามกฎหมายโดยไม่มีชื่อ อีเมล หรือเบอร์โทร ย้อนกลับไม่ได้"""
    uid = user["id"]
    if body.confirm.strip().lower() != user["email"].lower():
        raise HTTPException(400, "พิมพ์อีเมลของบัญชีให้ตรงเพื่อยืนยัน")
    if accounts.is_owner(user["email"]):
        raise HTTPException(409, "บัญชีผู้ดูแลหลัก (ADMIN_EMAILS) ปิดไม่ได้ เอาอีเมลออกจาก ADMIN_EMAILS ก่อน")
    jobs = [j for j in store.all() if j.owner == uid]
    if any(j.status in ACTIVE for j in jobs):
        raise HTTPException(409, "มีงานที่กำลังทำหรือรอคิวอยู่ กดยกเลิกงานก่อนแล้วค่อยปิดบัญชี")
    due = actors.due_total(uid)
    if due > 0:
        raise HTTPException(409, f"มีค่าตอบแทนนักพากย์ค้างจ่าย {due / 100:,.2f} บาท ติดต่อผู้ดูแลให้จ่ายก่อนปิดบัญชี")
    mine = [v for v, a in actors.voice_actors().items() if a["user_id"] == uid]
    if any(v and v.status == VoiceStatus.processing and v.stage != "queued" for v in map(voice_store.get, mine)):
        raise HTTPException(409, "กำลังเตรียมเสียงของคุณอยู่ รอให้เสร็จก่อนแล้วค่อยปิดบัญชี")
    for voice_id in actors.forget(uid):
        voice_store.delete(voice_id)
    for j in jobs:
        store.delete(j.id)
    consent.forget(uid)
    quality.forget_owner(uid)
    own = [p.id for p in projects.get_store().all() if p.owner == uid]
    memory.forget_projects(own)
    for pid in own:
        projects.get_store().delete(pid)
    try:
        accounts.close_account(uid)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))
    logging.getLogger(__name__).info("account %s closed (%d jobs)", uid, len(jobs))


@app.get("/admin/backups", dependencies=[Depends(require_key)])
def admin_backups(_=Depends(require_admin)):
    """ไฟล์สำรองข้อมูลที่มี (ใหม่ก่อน) และตั้งค่าปัจจุบัน"""
    return {"dir": str(settings.backup_dir), "hours": settings.backup_hours, "keep": settings.backup_keep,
            "backups": backup.list_backups()}


@app.get("/admin/quality", dependencies=[Depends(require_key)])
def admin_quality(days: int = 30, _=Depends(require_admin)):
    """สัดส่วนบรรทัดที่ผู้ใช้แก้จากที่ AI ทำ (คำแปล ผู้พูด เวลา) รวม รายสัปดาห์ และแยกคู่ภาษา"""
    return quality.summary(max(1, min(days, 365)))


@app.get("/admin/quality/lines", dependencies=[Depends(require_key)])
def admin_quality_lines(days: int = 30, kind: str = "", limit: int = 50, _=Depends(require_admin)):
    """บรรทัดที่ผู้ใช้แก้ล่าสุด kind = text / speaker / time"""
    if kind not in ("", "text", "speaker", "time"):
        raise HTTPException(422, "kind ต้องเป็น text, speaker หรือ time")
    return quality.edited_lines(max(1, min(days, 365)), kind, max(1, min(limit, 500)))


@app.get("/admin/quality/lines.csv", dependencies=[Depends(require_key)])
def admin_quality_csv(days: int = 90, kind: str = "", _=Depends(require_admin)):
    """ชุดทดสอบ: ต้นฉบับ บทของ AI และบทที่ผู้ใช้แก้ (ใช้วัดผลหลังปรับ prompt หรือเปลี่ยนโมเดล)"""
    if kind not in ("", "text", "speaker", "time"):
        raise HTTPException(422, "kind ต้องเป็น text, speaker หรือ time")
    import csv
    import io

    rows = quality.edited_lines(max(1, min(days, 365)), kind)
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["job_id", "line_id", "target_lang", "kinds", "source", "ai_target", "final_target", "ai_speaker", "final_speaker", "updated_at"]
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"content-disposition": "attachment; filename=quality-lines.csv"})


@app.post("/admin/backups", dependencies=[Depends(require_key)])
def admin_backup_now(_=Depends(require_admin)):
    """สำรองข้อมูลทันที"""
    out = backup.run()
    return {"name": out.name, "bytes": out.stat().st_size}


@app.get("/admin/actors", dependencies=[Depends(require_key)])
def admin_actors(_=Depends(require_admin)):
    return actors.all_actors()


@app.get("/admin/actors/{user_id}/consents", dependencies=[Depends(require_key)])
def admin_actor_consents(user_id: str, _=Depends(require_admin)):
    """ประวัติการกดยอมรับและถอนความยินยอมของนักพากย์ (หลักฐาน)"""
    return actors.consent_history(user_id)


@app.post("/admin/actors/{user_id}/review", status_code=204, dependencies=[Depends(require_key)])
def admin_review_actor(user_id: str, body: Review, admin=Depends(require_admin)):
    """อนุมัติหรือปฏิเสธผู้สมัคร (ปฏิเสธแล้วสมัครใหม่ได้)"""
    try:
        actors.review_actor(user_id, body.approve, body.note.strip(), admin["email"])
    except accounts.AccountError as e:
        raise _actor_fail(e)
    notify.actor_reviewed(user_id, body.approve, body.note.strip())


@app.get("/admin/actor-voices", response_model=list[LibraryVoice], dependencies=[Depends(require_key)])
def admin_actor_voices(_=Depends(require_admin)):
    """เสียงทั้งหมดที่นักพากย์ส่ง (รอตรวจขึ้นก่อน)"""
    info, moods = actors.voice_actors(), actors.mood_reviews()
    out = [with_actor(v, info[v.id], True, moods) for v in voice_store.all() if v.id in info]
    pending = lambda v: v.review == "pending" or any(m.review == "pending" for m in v.moods)  # noqa: E731
    return sorted(out, key=lambda v: not pending(v))


@app.post("/admin/actor-voices/{voice_id}/review", status_code=204, dependencies=[Depends(require_key)])
def admin_review_voice(voice_id: str, body: Review, admin=Depends(require_admin)):
    """อนุมัติให้เสียงขึ้นคลัง (ทุกคนเลือกใช้ได้) หรือให้นักพากย์อัดใหม่พร้อมเหตุผล"""
    v = get_voice_or_404(voice_id)
    if body.approve and v.status != VoiceStatus.ready:
        raise HTTPException(409, "เสียงยังเตรียมไม่เสร็จหรือเตรียมไม่สำเร็จ")
    try:
        actors.review_voice(voice_id, body.approve, body.note.strip(), admin["email"])
    except accounts.AccountError as e:
        raise _actor_fail(e)
    owner = actors.voice_actors().get(voice_id)
    if owner:
        notify.voice_reviewed(owner["user_id"], v.name, body.approve, body.note.strip())


@app.post("/admin/actor-voices/{voice_id}/moods/{mood}/review", status_code=204, dependencies=[Depends(require_key)])
def admin_review_mood(voice_id: str, mood: Mood, body: Review, admin=Depends(require_admin)):
    """อนุมัติหรือส่งกลับเสียงอารมณ์ทีละอารมณ์ (เสียงหลักไม่เปลี่ยนสถานะ)"""
    v, m = get_mood_or_404(voice_id, mood)
    if body.approve and m.status != VoiceStatus.ready:
        raise HTTPException(409, "เสียงอารมณ์นี้ยังเตรียมไม่เสร็จหรือเตรียมไม่สำเร็จ")
    try:
        actors.review_mood(voice_id, mood, body.approve, body.note.strip(), admin["email"])
    except accounts.AccountError as e:
        raise _actor_fail(e)
    owner = actors.voice_actors().get(voice_id)
    if owner:
        notify.voice_reviewed(owner["user_id"], f"{v.name} ({mood})", body.approve, body.note.strip())


@app.get("/admin/actor-usage", dependencies=[Depends(require_key)])
def admin_actor_usage(month: Optional[str] = None, _=Depends(require_admin)):
    """ยอดใช้เสียงและค่าตอบแทนต่อนักพากย์ต่อเดือน (ไม่ส่ง month = ทุกเดือน) จำนวนเงินเป็นสตางค์
    wht = ภาษีหัก ณ ที่จ่ายถ้าจ่ายยอดค้างตอนนี้, payee = นักพากย์กรอกข้อมูลรับเงินแล้ว"""
    return {"rate": settings.actor_rate, "rows": actors.report(month), "payouts": actors.payouts(),
            "wht": {"percent": settings.actor_wht_percent, "min": settings.actor_wht_min}}


@app.get("/admin/actors/{user_id}/payment", dependencies=[Depends(require_key)])
def admin_actor_payment(user_id: str, _=Depends(require_admin)):
    """ข้อมูลรับเงินเต็มของนักพากย์ (สำหรับโอนเงินและออกหนังสือรับรองการหักภาษี)"""
    p = actors.payment(user_id)
    if p is None:
        raise HTTPException(404, "นักพากย์ยังไม่ได้กรอกข้อมูลรับเงิน")
    return p


@app.get("/admin/actor-wht-csv", dependencies=[Depends(require_key)])
def admin_actor_wht_csv(month: str, _=Depends(require_admin)):
    """รายการหักภาษี ณ ที่จ่ายของการจ่ายในเดือนนั้น (นับตามวันที่จ่ายจริง) สำหรับยื่นแบบและออกหนังสือรับรอง"""
    import csv
    import io

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "month ต้องเป็น YYYY-MM")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ลำดับ", "เลขประจำตัวผู้เสียภาษี", "ชื่อผู้มีเงินได้", "ที่อยู่", "วันที่จ่าย", "ประเภทเงินได้",
                "อัตราภาษี (%)", "จำนวนเงินที่จ่าย", "ภาษีที่หัก", "โอนจริง", "ค่าตอบแทนเดือน", "หมายเหตุ"])
    for i, p in enumerate(actors.wht_rows(month), 1):
        day = time.strftime("%d/%m/%Y", time.gmtime(p["paid_at"] + actors.TZ))
        rate = f"{settings.actor_wht_percent:g}" if p["wht"] else "0"
        w.writerow([i, p["tax_id"], p["payee_name"], p["address"], day, settings.actor_income_type, rate,
                    f"{p['amount'] / 100:.2f}", f"{p['wht'] / 100:.2f}", f"{(p['amount'] - p['wht']) / 100:.2f}",
                    p["month"], p["note"]])
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"content-disposition": f"attachment; filename=actor-wht-{month}.csv"})


@app.get("/admin/actor-usage/{user_id}", dependencies=[Depends(require_key)])
def admin_actor_usage_rows(user_id: str, month: str, _=Depends(require_admin)):
    return actors.usage_rows(user_id, month)


@app.get("/admin/actor-usage-csv", dependencies=[Depends(require_key)])
def admin_actor_usage_csv(month: str, _=Depends(require_admin)):
    """รายการใช้เสียงทุกงานของเดือนนั้น สำหรับทำบัญชี"""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["เดือน", "นักพากย์", "อีเมล", "งาน", "ชื่อไฟล์", "ผู้ใช้", "เสียง", "ประโยค", "วินาที", "คิดเงิน", "บาท"])
    for r in actors.report(month):
        for u in actors.usage_rows(r["actor_id"], month):
            w.writerow([month, r["stage_name"], r["email"], u["job_id"], u["job_name"], u["user_id"], u["voice_id"],
                        u["lines"], u["seconds"], "ใช่" if u["payable"] else "ใช้เอง", f"{u['amount'] / 100:.2f}"])
    name = f"actor-usage-{month}.csv"
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"content-disposition": f"attachment; filename={name}"})


@app.post("/admin/actor-payouts/{user_id}", dependencies=[Depends(require_key)])
def admin_payout(user_id: str, body: Payout, admin=Depends(require_admin)):
    """บันทึกว่าจ่ายค่าตอบแทนยอดค้างของเดือนนั้นแล้ว"""
    try:
        out = actors.add_payout(user_id, body.month, body.note.strip(), admin["email"])
    except accounts.AccountError as e:
        raise _actor_fail(e)
    notify.actor_paid(user_id, body.month, out["amount"], out["wht"])
    return out


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


@app.get("/jobs/{job_id}/thumb", dependencies=[Depends(require_key)])
def get_thumb(job_id: str):
    """ภาพตัวอย่างของคลิป (เฟรมราววินาทีที่ 1 กว้าง 480 px) สร้างครั้งแรกแล้วเก็บไว้ งานที่เป็นไฟล์เสียงล้วนไม่มีภาพ (404)"""
    job = get_job_or_404(job_id)
    out = store.dir(job_id) / "thumb.jpg"
    src = Path(job.input_path) if job.input_path else None
    if not out.exists():
        if src is None or not src.exists() or src.suffix.lower() not in ALLOWED_EXT:
            raise HTTPException(404, "งานนี้ไม่มีภาพ")
        at = min(1.0, (job.duration or 3) / 3)
        tmp = out.with_suffix(".part.jpg")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=480:-2", "-q:v", "5", str(tmp)], capture_output=True, timeout=60)
        if r.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise HTTPException(404, "สร้างภาพตัวอย่างไม่ได้")
        tmp.replace(out)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


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
