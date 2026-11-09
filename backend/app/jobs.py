"""เก็บสถานะงาน และคิวงาน (การ์ดจอใบเดียวรันทีละงาน โหมด modal รันพร้อมกันได้หลายงาน)

เมื่อ DB_BACKEND=postgres เมตาดาต้างานและบทอยู่บน Postgres (schema studio)
โฟลเดอร์ data/jobs/<id>/ ยังเก็บไฟล์มีเดีย (อินพุต tts ผลลัพธ์) เหมือนเดิม
"""
import json
import logging
import shutil
import threading
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Optional

from .config import settings, using_postgres
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
        self._pg = using_postgres()
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._cancel: set[str] = set()
        self._load()

    # ---------- โหลดและบันทึก ----------
    def _load(self) -> None:
        jobs: list[Job] = []
        from_files = True
        if self._pg:
            from . import jobstore_pg
            try:
                log.info("โหลดงานจาก Postgres…")
                jobs = jobstore_pg.load_jobs()
                from_files = False
                log.info("โหลดงานจาก Postgres ได้ %s งาน", len(jobs))
            except Exception:
                log.exception("โหลดงานจาก Postgres ไม่ได้ ลองจากไฟล์ในเครื่อง")
        if from_files:
            for job_file in self.root.glob("*/job.json"):
                try:
                    jobs.append(Job.model_validate_json(job_file.read_text(encoding="utf-8")))
                except Exception:
                    log.warning("skip broken job file %s", job_file)
        for job in jobs:
            changed = False
            if job.status == JobStatus.running:  # งานที่รอคิวอยู่ Worker.start เอาเข้าคิวต่อให้
                job.status = JobStatus.failed
                job.error = "เซิร์ฟเวอร์รีสตาร์ตระหว่างทำงาน กดลองใหม่ได้เลย"
                changed = True
            # งานที่สร้างบนเครื่องอื่น (เช่น Windows แล้วย้ายมารันใน Docker) เก็บ path เดิมไว้ ชี้กลับมาที่โฟลเดอร์งานนี้
            if job.input_path and not Path(job.input_path).exists():
                local = self.dir(job.id) / PureWindowsPath(job.input_path).name
                if local.exists():
                    job.input_path = str(local)
                    changed = True
            if changed:
                # เขียนไฟล์ของงานเดียวไม่ได้ (ไฟล์ถูกล็อกฝั่ง Windows ฯลฯ) ต้องไม่ทำให้ API เปิดไม่ขึ้นทั้งระบบ
                # สถานะใหม่ยังอยู่ในหน่วยความจำ และจะถูกเขียนลงไฟล์อีกครั้งเมื่องานนี้เปลี่ยนสถานะ
                try:
                    self._write(job)
                except OSError as e:
                    log.warning("could not update job %s at startup: %s", job.id, e)
            self._jobs[job.id] = job

    def _write(self, job: Job) -> None:
        if self._pg:
            from . import jobstore_pg
            jobstore_pg.upsert_job(job)
            return
        self.dir(job.id).mkdir(parents=True, exist_ok=True)
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
            if self._pg:
                from . import jobstore_pg
                try:
                    jobstore_pg.delete_job(job_id)
                except Exception:
                    log.exception("ลบงาน %s จาก Supabase ไม่สำเร็จ", job_id)
            try:
                from . import object_store
                object_store.delete_prefix(job_id)
            except Exception:
                log.exception("ลบงาน %s จาก R2 ไม่สำเร็จ", job_id)
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
        if self._pg:
            from . import jobstore_pg
            jobstore_pg.save_transcript(job_id, utterances)
            return
        data = [u.model_dump() for u in utterances]
        _atomic_write(self.transcript_path(job_id), json.dumps(data, ensure_ascii=False, indent=2))

    def load_transcript(self, job_id: str) -> list[Utterance]:
        if self._pg:
            from . import jobstore_pg
            rows = jobstore_pg.load_transcript(job_id)
            if rows is not None:
                return rows
        path = self.transcript_path(job_id)
        if not path.exists():
            return []
        return [Utterance.model_validate(u) for u in json.loads(path.read_text(encoding="utf-8"))]


HEAVY = "gpu"  # สายงานหนัก: วิเคราะห์ พากย์ (และเตรียมเสียงในคลังเมื่อใช้การ์ดจอเครื่องนี้)
LIGHT = "light"  # สายงานเบา: ฝังซับ แปลใหม่ (ไม่ใช้การ์ดจอ หรือส่งไปการ์ดจอบน Modal) ไม่ต้องรอหลังงานหนัก


@dataclass
class Task:
    job_id: str  # งาน หรือ "voice_id:mood" ของเสียงในคลัง
    phase: str
    owner: Optional[str]
    seq: int  # ลำดับที่เข้าคิว


class Worker:
    """จัดคิวงานหลายงาน หลายผู้ใช้

    phase: analyze (ดาวน์โหลด/แยกเสียง/ถอดเสียง/แปล), synthesize (พากย์และรวมวิดีโอ),
    render (ฝังซับลงวิดีโอใหม่อย่างเดียว), translate (แปลบทใหม่จากบทถอดเสียงเดิม), voice (เตรียมเสียงในคลัง)

    แบ่งเป็นสองสาย แต่ละสายมีเธรดของตัวเอง งานเบาจึงไม่ต้องรองานวิเคราะห์ยาว ๆ
    - สายงานหนัก (HEAVY): WORKER=local รันทีละงาน (การ์ดจอใบเดียว) WORKER=modal รันพร้อมกันได้ MODAL_MAX_JOBS งาน
    - สายงานเบา (LIGHT): LIGHT_WORKERS งานพร้อมกัน
    เลือกงานถัดไปแบบวนตามผู้ใช้: คนที่มีงานรันอยู่น้อยที่สุดได้ก่อน เท่ากันใช้งานที่เข้าคิวก่อน
    ผู้ใช้หนึ่งคนรันงานหนักพร้อมกันได้ไม่เกิน USER_MAX_JOBS งาน (งานที่ไม่มีเจ้าของ = ระบบบัญชีปิดอยู่ ไม่จำกัด)
    """

    def __init__(self, store: JobStore, voices=None, threads: Optional[int] = None):
        self.store = store
        self.voices = voices  # VoiceStore
        self.remote = settings.worker == "modal" and not settings.mock_pipeline
        self.threads = threads or (max(1, settings.modal_max_jobs) if self.remote else 1)
        self._cond = threading.Condition()
        self._pending: list[Task] = []
        self._running: dict[str, Task] = {}  # ชื่อเธรด → งานที่กำลังรัน
        self._seq = 0

    # ---------- สถานะคิว ----------
    @property
    def current(self) -> Optional[str]:
        """งานที่กำลังรันอยู่ (ถ้ารันหลายงาน คืนงานแรก)"""
        with self._cond:
            return next((t.job_id for t in self._running.values() if t.phase != "voice"), None)

    def running(self) -> list[str]:
        with self._cond:
            return [t.job_id for t in self._running.values() if t.phase != "voice"]

    def pending_count(self) -> int:
        with self._cond:
            return len(self._pending)

    def _pool(self, phase: str) -> str:
        if phase in ("render", "translate"):
            return LIGHT
        if phase == "voice":  # โหมด modal เตรียมเสียงบนการ์ดจอของ Modal เอง ไม่แย่งช่องงานหนัก
            return LIGHT if self.remote else HEAVY
        return HEAVY

    def _order(self, pool: str) -> list[Task]:
        """ลำดับที่น่าจะได้รัน: วนตามผู้ใช้ (งานที่ 1 ของทุกคน แล้วงานที่ 2 ของทุกคน ...) แต่ละรอบเรียงตามเวลาเข้าคิว"""
        rank: dict[Optional[str], int] = defaultdict(int)
        keyed = []
        for t in sorted((t for t in self._pending if self._pool(t.phase) == pool), key=lambda t: t.seq):
            keyed.append(((rank[t.owner], t.seq), t))
            rank[t.owner] += 1
        return [t for _, t in sorted(keyed, key=lambda x: x[0])]

    def positions(self) -> dict[str, int]:
        """งานที่รอคิว → ลำดับคิว (1 = ได้รันเป็นงานถัดไปในสายนั้น)"""
        with self._cond:
            out = {}
            for pool in (HEAVY, LIGHT):
                for i, t in enumerate(self._order(pool)):
                    out[t.job_id] = i + 1
            return out

    def queued_by(self, owner: str) -> int:
        """จำนวนงานของผู้ใช้นี้ที่รอคิวหรือกำลังรัน (ใช้จำกัดไม่ให้คนเดียวส่งงานรัว ๆ)"""
        with self._cond:
            return sum(1 for t in [*self._pending, *self._running.values()] if t.owner == owner and t.phase != "voice")

    # ---------- รับงาน ----------
    def start(self) -> None:
        # งานที่รอคิวอยู่ตอนปิดเซิร์ฟเวอร์ (ยังไม่ได้เริ่ม) เข้าคิวต่อตามลำดับเดิม
        waiting = {t.job_id for t in self._pending}
        for job in sorted((j for j in self.store.all() if j.status == JobStatus.queued and j.id not in waiting),
                          key=lambda j: j.updated_at):
            log.info("requeue %s (%s)", job.id, job.phase)
            self._put(job.id, job.phase, job.owner)
        pools = [HEAVY] * self.threads + [LIGHT] * max(1, settings.light_workers)
        for n, pool in enumerate(pools):
            threading.Thread(target=self.run, args=(pool,), daemon=True, name=f"dubbing-{pool}-{n}").start()

    def _put(self, job_id: str, phase: str, owner: Optional[str]) -> None:
        with self._cond:
            self._pending = [t for t in self._pending if t.job_id != job_id]  # ส่งซ้ำ = ใช้คำขอล่าสุด
            self._seq += 1
            self._pending.append(Task(job_id, phase, owner, self._seq))
            self._cond.notify_all()

    def submit(self, job_id: str, phase: str) -> None:
        self.store.clear_cancel(job_id)
        job = self.store.update(job_id, status=JobStatus.queued, stage="queued", phase=phase, error=None)
        self._put(job_id, phase, job.owner)

    def submit_voice(self, voice_id: str, mood: str = "") -> None:
        self._put(f"{voice_id}:{mood}" if mood else voice_id, "voice", None)

    def _next(self, pool: str) -> Optional[Task]:
        """งานถัดไปของสายนี้ (เรียกขณะถือ _cond) ข้ามงานที่ถูกยกเลิกหรือลบระหว่างรอ"""
        busy: dict[Optional[str], int] = defaultdict(int)
        for t in self._running.values():
            if self._pool(t.phase) == HEAVY:
                busy[t.owner] += 1
        cap = settings.user_max_jobs
        best = None
        for t in list(self._pending):
            if self._pool(t.phase) != pool:
                continue
            if t.phase != "voice":
                job = self.store.get(t.job_id)
                if job is None or job.status != JobStatus.queued:
                    self._pending.remove(t)
                    continue
            if pool == HEAVY and cap > 0 and t.owner and busy[t.owner] >= cap:
                continue
            key = (busy[t.owner], t.seq)
            if best is None or key < best[0]:
                best = (key, t)
        if best is None:
            return None
        self._pending.remove(best[1])
        return best[1]

    def run(self, pool: str = HEAVY) -> None:
        name = threading.current_thread().name
        while True:
            with self._cond:
                task = self._next(pool)
                while task is None:
                    self._cond.wait()
                    task = self._next(pool)
                self._running[name] = task
            try:
                self._execute(task.job_id, task.phase)
            finally:
                with self._cond:
                    self._running.pop(name, None)
                    self._cond.notify_all()  # ช่องว่างแล้ว ผู้ใช้ที่ติดเพดานอาจได้คิวต่อ

    def _archive_r2(self, job_id: str) -> None:
        """หลังงาน done: อัปสื่อขึ้น R2 (และ purge ตาม R2_PURGE_LOCAL) — ล้มไม่ทำให้งานล้ม"""
        try:
            from . import object_store
            object_store.archive_after_done(self.store.dir(job_id))
        except Exception:  # noqa: BLE001
            log.exception("r2 archive after done failed for %s", job_id)

    def _execute(self, job_id: str, phase: str) -> None:
        from .pipeline import library, runner
        started = time.time()
        event = ""  # อีเมลแจ้งผู้ใช้หลังงานจบ (notify.py) แปลบทใหม่เร็ว ไม่แจ้ง
        try:
            if phase == "voice":
                voice_id, _, mood = job_id.partition(":")
                library.prepare(self.voices, voice_id, mood or None)
                return
            job = self.store.get(job_id)
            if job is None or job.status != JobStatus.queued:  # ถูกลบหรือถูกยกเลิกระหว่างรอคิว
                return
            self.store.update(job_id, status=JobStatus.running)
            if phase == "render":
                runner.run_render(self.store, job_id)
                self.store.update(job_id, status=JobStatus.done, stage="done", progress=1.0)
                event = "done"
                self._archive_r2(job_id)
                return
            if phase == "translate":  # แปลบทใหม่ แล้วรอให้ตรวจก่อนพากย์ใหม่เสมอ
                runner.run_translate(self.store, job_id)
                self.store.update(job_id, status=JobStatus.awaiting_review, stage="awaiting_review")
                return
            if phase == "analyze":
                runner.run_analyze(self.store, job_id)
                job = self.store.get(job_id)
                if job and job.review:
                    self.store.update(job_id, status=JobStatus.awaiting_review, stage="awaiting_review")
                    event = "review"
                    return
                self.store.update(job_id, phase="synthesize")
            runner.run_synthesize(self.store, job_id, self.voices)
            self.store.update(job_id, status=JobStatus.done, stage="done", progress=1.0)
            event = "done"
            self._archive_r2(job_id)
        except Cancelled:
            log.info("job %s cancelled", job_id)
            if self.store.get(job_id):
                self.store.update(job_id, status=JobStatus.cancelled, stage="cancelled", error=None)
        except Exception as exc:  # noqa: BLE001
            log.error("job %s failed:\n%s", job_id, traceback.format_exc())
            job = self.store.get(job_id)
            if job and phase != "voice":
                self.store.update(job_id, status=JobStatus.failed, error=str(exc)[:2000])
                event = "failed"
                if phase == "analyze" and job.owner:  # วิเคราะห์ไม่สำเร็จ คืนนาทีที่ตัดไป
                    from . import accounts
                    accounts.refund_job(job.owner, job_id)
        finally:
            if phase != "voice":
                self.store.clear_cancel(job_id)
            if event:
                try:
                    from . import notify
                    notify.job_event(job_id, event, time.time() - started)
                except Exception:  # noqa: BLE001
                    log.exception("notify job %s failed", job_id)
