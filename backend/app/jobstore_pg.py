"""อ่าน/เขียนงาน บท และโปรเจกต์บน Postgres (schema studio) เมื่อ DB_BACKEND=supabase

ไฟล์มีเดียยังอยู่ที่ data/jobs/<id>/ เหมือนเดิม ตารางนี้แทนเฉพาะ job.json / transcript.json / projects/*.json
ต้องใช้ db.execute (ไม่ใช่ db.raw) เพื่อให้ตั้ง search_path = studio ทุกครั้ง — transaction pooler สลับ backend ได้
"""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from .pgstore import borrow
from .schemas import Job, Project, Utterance, now


def _ts(dt) -> float:
    return float(dt.timestamp()) if hasattr(dt, "timestamp") else float(dt)


def job_doc(job: Job) -> dict:
    return job.model_dump(mode="json", exclude={"queue_position"})


def project_doc(p: Project) -> dict:
    return p.model_dump(mode="json")


def load_jobs() -> list[Job]:
    with borrow() as db:
        rows = db.execute("SELECT doc FROM jobs").fetchall()
    out: list[Job] = []
    for r in rows:
        try:
            out.append(Job.model_validate(r["doc"]))
        except Exception:
            continue
    return out


def upsert_job(job: Job) -> None:
    doc = job_doc(job)
    with borrow() as db:
        db.execute(
            """INSERT INTO jobs (id, owner, status, created_at, updated_at, doc)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                 owner = EXCLUDED.owner,
                 status = EXCLUDED.status,
                 updated_at = EXCLUDED.updated_at,
                 doc = EXCLUDED.doc""",
            (job.id, job.owner, job.status.value if hasattr(job.status, "value") else str(job.status),
             _ts(job.created_at), _ts(job.updated_at), Jsonb(doc)),
        )


def delete_job(job_id: str) -> None:
    with borrow() as db:
        db.execute("DELETE FROM jobs WHERE id = %s", (job_id,))


def save_transcript(job_id: str, utterances: list[Utterance]) -> None:
    data = [u.model_dump(mode="json") for u in utterances]
    with borrow() as db:
        db.execute(
            """INSERT INTO transcripts (job_id, utterances, updated_at)
               VALUES (%s, %s, %s)
               ON CONFLICT (job_id) DO UPDATE SET
                 utterances = EXCLUDED.utterances,
                 updated_at = EXCLUDED.updated_at""",
            (job_id, Jsonb(data), _ts(now())),
        )


def load_transcript(job_id: str) -> Optional[list[Utterance]]:
    """None = ยังไม่มีแถวในฐาน (ให้เรียกฝั่งไฟล์ต่อได้) [] = มีแถวแต่บทว่าง"""
    with borrow() as db:
        row = db.execute("SELECT utterances FROM transcripts WHERE job_id = %s", (job_id,)).fetchone()
    if row is None:
        return None
    return [Utterance.model_validate(u) for u in (row["utterances"] or [])]


def delete_transcript(job_id: str) -> None:
    with borrow() as db:
        db.execute("DELETE FROM transcripts WHERE job_id = %s", (job_id,))


def load_projects() -> list[Project]:
    with borrow() as db:
        rows = db.execute("SELECT doc FROM projects").fetchall()
    out: list[Project] = []
    for r in rows:
        try:
            out.append(Project.model_validate(r["doc"]))
        except Exception:
            continue
    return out


def upsert_project(p: Project) -> None:
    doc = project_doc(p)
    with borrow() as db:
        db.execute(
            """INSERT INTO projects (id, owner, updated_at, doc)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                 owner = EXCLUDED.owner,
                 updated_at = EXCLUDED.updated_at,
                 doc = EXCLUDED.doc""",
            (p.id, p.owner, _ts(p.updated_at), Jsonb(doc)),
        )


def delete_project(pid: str) -> None:
    with borrow() as db:
        db.execute("DELETE FROM projects WHERE id = %s", (pid,))
