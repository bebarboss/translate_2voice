"""อ่าน/เขียนงาน บท และโปรเจกต์บน Postgres (schema studio) เมื่อ DB_BACKEND=supabase

ไฟล์มีเดียยังอยู่ที่ data/jobs/<id>/ เหมือนเดิม ตารางนี้แทนเฉพาะ job.json / transcript.json / projects/*.json
"""
from __future__ import annotations

import json
import threading
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .pgstore import _dsn
from .schemas import Job, Project, Utterance, now

_local = threading.local()


def _conn() -> psycopg.Connection:
    raw = getattr(_local, "conn", None)
    if raw is None or raw.closed:
        raw = psycopg.connect(_dsn(), autocommit=False, row_factory=dict_row, connect_timeout=15)
        raw.execute("SET search_path TO studio")
        raw.commit()
        _local.conn = raw
    return raw


def _ts(dt) -> float:
    return float(dt.timestamp()) if hasattr(dt, "timestamp") else float(dt)


def job_doc(job: Job) -> dict:
    return job.model_dump(mode="json", exclude={"queue_position"})


def project_doc(p: Project) -> dict:
    return p.model_dump(mode="json")


def load_jobs() -> list[Job]:
    cur = _conn().execute("SELECT doc FROM jobs")
    rows = cur.fetchall()
    _conn().commit()
    out: list[Job] = []
    for r in rows:
        try:
            out.append(Job.model_validate(r["doc"]))
        except Exception:
            continue
    return out


def upsert_job(job: Job) -> None:
    doc = job_doc(job)
    _conn().execute(
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
    _conn().commit()


def delete_job(job_id: str) -> None:
    _conn().execute("DELETE FROM jobs WHERE id = %s", (job_id,))
    _conn().commit()


def save_transcript(job_id: str, utterances: list[Utterance]) -> None:
    data = [u.model_dump(mode="json") for u in utterances]
    _conn().execute(
        """INSERT INTO transcripts (job_id, utterances, updated_at)
           VALUES (%s, %s, %s)
           ON CONFLICT (job_id) DO UPDATE SET
             utterances = EXCLUDED.utterances,
             updated_at = EXCLUDED.updated_at""",
        (job_id, Jsonb(data), _ts(now())),
    )
    _conn().commit()


def load_transcript(job_id: str) -> Optional[list[Utterance]]:
    """None = ยังไม่มีแถวในฐาน (ให้เรียกฝั่งไฟล์ต่อได้) [] = มีแถวแต่บทว่าง"""
    cur = _conn().execute("SELECT utterances FROM transcripts WHERE job_id = %s", (job_id,))
    row = cur.fetchone()
    _conn().commit()
    if row is None:
        return None
    return [Utterance.model_validate(u) for u in (row["utterances"] or [])]


def delete_transcript(job_id: str) -> None:
    _conn().execute("DELETE FROM transcripts WHERE job_id = %s", (job_id,))
    _conn().commit()


def load_projects() -> list[Project]:
    cur = _conn().execute("SELECT doc FROM projects")
    rows = cur.fetchall()
    _conn().commit()
    out: list[Project] = []
    for r in rows:
        try:
            out.append(Project.model_validate(r["doc"]))
        except Exception:
            continue
    return out


def upsert_project(p: Project) -> None:
    doc = project_doc(p)
    _conn().execute(
        """INSERT INTO projects (id, owner, updated_at, doc)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET
             owner = EXCLUDED.owner,
             updated_at = EXCLUDED.updated_at,
             doc = EXCLUDED.doc""",
        (p.id, p.owner, _ts(p.updated_at), Jsonb(doc)),
    )
    _conn().commit()


def delete_project(pid: str) -> None:
    _conn().execute("DELETE FROM projects WHERE id = %s", (pid,))
    _conn().commit()
