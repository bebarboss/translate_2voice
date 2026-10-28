"""เก็บสถานะงาน และคิวงานที่รันทีละงาน (การ์ดจอใบเดียวรันพร้อมกันหลายงานไม่ไหว)"""
import json
import logging
import queue
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path, PureWindowsPath
from typing import Optional

from .schemas import Job, JobStatus, Utterance, now

log = logging.getLogger("dubbing.jobs")

ACTIVE = (JobStatus.queued, JobStatus.running)


class Cancelled(Exception):
    """ผู้ใช้กดยกเลิกงานระหว่างทำงาน"""


def _atomic_write(path: Path, text: str) -> None:
    """เขียนไฟล์ชั่วคราวแล้วสลับแทนของเดิม ไฟล์จะไม่ขาดครึ่งถ้าโปรแกรมตายกลางทาง

    บน Windows ถ้ามีโปรแกรมอื่นเปิดไฟล์ปลายทางค้างอยู่ชั่วครู่ (Defender สแกน, ตัวทำดัชนี, หน้าเว็บกำลังอ่าน)
    การสลับไฟล์จะได้ Access is denied จึงลองใหม่สักพักก่อนยอมแพ้
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


class JobStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._cancel: set[str] = set()
        self._load()

    # ---------- โหลดและบันทึก ----------
    def _load(self) -> None:
        for job_file in self.root.glob("*/job.json"):
            try:
                job = Job.model_validate_json(job_file.read_text(encoding="utf-8"))
            except Exception:
                log.warning("skip broken job file %s", job_file)
                continue
            if job.status in ACTIVE:
                job.status = JobStatus.failed
                job.error = "เซิร์ฟเวอร์รีสตาร์ตระหว่างทำงาน กดลองใหม่ได้เลย"
                self._write(job)
            # งานที่สร้างบนเครื่องอื่น (เช่น Windows แล้วย้ายมารันใน Docker) เก็บ path เดิมไว้ ชี้กลับมาที่โฟลเดอร์งานนี้
            if job.input_path and not Path(job.input_path).exists():
                local = job_file.parent / PureWindowsPath(job.input_path).name
                if local.exists():
                    job.input_path = str(local)
                    self._write(job)
            self._jobs[job.id] = job

    def _write(self, job: Job) -> None:
        _atomic_write(self.dir(job.id) / "job.json", job.model_dump_json(indent=2))

    # ---------- งาน ----------
    def dir(self, job_id: str) -> Path:
        return self.root / job_id

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def add(self, job: Job) -> Job:
        with self._lock:
            self.dir(job.id).mkdir(parents=True, exist_ok=True)
            self._jobs[job.id] = job
            self._write(job)
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def all(self) -> list[Job]:
        with self._lock:
            return sorted((j.model_copy(deep=True) for j in self._jobs.values()),
                          key=lambda j: j.created_at, reverse=True)

    def update(self, job_id: str, **fields) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = now()
            self._write(job)
            return job.model_copy(deep=True)

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._cancel.discard(job_id)
            shutil.rmtree(self.dir(job_id), ignore_errors=True)

    # ---------- ยกเลิก ----------
    def request_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel.add(job_id)

    def clear_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel.discard(job_id)

    def check_cancel(self, job_id: str) -> None:
        """เรียกระหว่างขั้นตอน ถ้าผู้ใช้กดยกเลิกจะหยุดงานตรงนั้น"""
        with self._lock:
            if job_id in self._cancel or job_id not in self._jobs:
                raise Cancelled()

    # ---------- บทพากย์ ----------
    def transcript_path(self, job_id: str) -> Path:
        return self.dir(job_id) / "transcript.json"

    def save_transcript(self, job_id: str, utterances: list[Utterance]) -> None:
        data = [u.model_dump() for u in utterances]
        _atomic_write(self.transcript_path(job_id), json.dumps(data, ensure_ascii=False, indent=2))

    def load_transcript(self, job_id: str) -> list[Utterance]:
        path = self.transcript_path(job_id)
        if not path.exists():
            return []
        return [Utterance.model_validate(u) for u in json.loads(path.read_text(encoding="utf-8"))]


class Worker(threading.Thread):
    """รับงานจากคิวทีละงาน

    phase: analyze (ดาวน์โหลด/แยกเสียง/ถอดเสียง/แปล), synthesize (พากย์และรวมวิดีโอ),
    render (ฝังซับลงวิดีโอใหม่อย่างเดียว), voice (เตรียมเสียงในคลัง ใช้การ์ดจอเหมือนกันจึงเข้าคิวเดียวกัน)
    """

    def __init__(self, store: JobStore, voices=None):
        super().__init__(daemon=True, name="dubbing-worker")
        self.store = store
        self.voices = voices  # VoiceStore
        self.queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.current: Optional[str] = None  # งานที่กำลังรันอยู่

    def submit(self, job_id: str, phase: str) -> None:
        self.store.clear_cancel(job_id)
        self.store.update(job_id, status=JobStatus.queued, stage="queued", phase=phase, error=None)
        self.queue.put((job_id, phase))

    def submit_voice(self, voice_id: str) -> None:
        self.queue.put((voice_id, "voice"))

    def run(self) -> None:
        from .pipeline import library, runner
        while True:
            job_id, phase = self.queue.get()
            try:
                if phase == "voice":
                    library.prepare(self.voices, job_id)
                    continue
                job = self.store.get(job_id)
                if job is None or job.status != JobStatus.queued:  # ถูกลบหรือถูกยกเลิกระหว่างรอคิว
                    continue
                self.current = job_id
                self.store.update(job_id, status=JobStatus.running)
                if phase == "render":
                    runner.run_render(self.store, job_id)
                    self.store.update(job_id, status=JobStatus.done, stage="done", progress=1.0)
                    continue
                if phase == "analyze":
                    runner.run_analyze(self.store, job_id)
                    job = self.store.get(job_id)
                    if job and job.review:
                        self.store.update(job_id, status=JobStatus.awaiting_review,
                                          stage="awaiting_review")
                        continue
                    self.store.update(job_id, phase="synthesize")
                runner.run_synthesize(self.store, job_id, self.voices)
                self.store.update(job_id, status=JobStatus.done, stage="done", progress=1.0)
            except Cancelled:
                log.info("job %s cancelled", job_id)
                if self.store.get(job_id):
                    self.store.update(job_id, status=JobStatus.cancelled, stage="cancelled", error=None)
            except Exception as exc:  # noqa: BLE001
                log.error("job %s failed:\n%s", job_id, traceback.format_exc())
                if self.store.get(job_id):
                    self.store.update(job_id, status=JobStatus.failed, error=str(exc)[:2000])
            finally:
                self.current = None
                self.store.clear_cancel(job_id)
                self.queue.task_done()
