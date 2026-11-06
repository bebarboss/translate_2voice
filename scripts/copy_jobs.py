"""สร้างตาราง studio.jobs / transcripts / projects แล้วคัดลอกจาก data/jobs และ data/projects

    python scripts/copy_jobs.py            # นับไฟล์
    python scripts/copy_jobs.py --apply    # สร้างตาราง + นำเข้า (TRUNCATE ตารางงานก่อน)
ต้องตั้ง SUPABASE_DB_URL และมี psycopg
ไฟล์มีเดียใน data/jobs/<id>/ ไม่ถูกย้าย
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from app.config import settings  # noqa: E402
from app.pgstore import _dsn  # noqa: E402
from app.schemas import Job, Project, Utterance, now  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
SQL_FILE = "20261107010000_studio_jobs.sql"


def _statements(text: str):
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            yield "\n".join(buf)
            buf = []


def _ts(dt) -> float:
    return float(dt.timestamp()) if hasattr(dt, "timestamp") else float(dt)


def main(apply: bool) -> None:
    jobs_dir = settings.data_dir / "jobs"
    projects_dir = settings.data_dir / "projects"
    job_files = sorted(jobs_dir.glob("*/job.json")) if jobs_dir.exists() else []
    project_files = sorted(projects_dir.glob("*.json")) if projects_dir.exists() else []
    print(f"jobs {len(job_files)}  projects {len(project_files)}")
    tr_n = utt_n = 0
    for jf in job_files:
        tp = jf.parent / "transcript.json"
        if tp.exists():
            tr_n += 1
            utt_n += len(json.loads(tp.read_text(encoding="utf-8")))
    print(f"transcripts {tr_n}  utterances {utt_n}")
    if not apply:
        print("ยังไม่เขียน ใส่ --apply เพื่อสร้างตารางและคัดลอก")
        return

    with psycopg.connect(_dsn(), row_factory=dict_row, connect_timeout=20) as conn:
        for statement in _statements((ROOT / SQL_FILE).read_text(encoding="utf-8")):
            conn.execute(statement)
        conn.commit()
        conn.execute("SET search_path TO studio")
        # ลบ transcript ก่อน (FK) แล้วค่อยงาน / โปรเจกต์
        conn.execute("TRUNCATE transcripts, jobs, projects")
        conn.commit()

        ok_jobs = ok_tr = ok_proj = 0
        for jf in job_files:
            try:
                job = Job.model_validate_json(jf.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print("skip job", jf.parent.name, e)
                continue
            doc = job.model_dump(mode="json", exclude={"queue_position"})
            conn.execute(
                """INSERT INTO jobs (id, owner, status, created_at, updated_at, doc)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (job.id, job.owner,
                 job.status.value if hasattr(job.status, "value") else str(job.status),
                 _ts(job.created_at), _ts(job.updated_at), Jsonb(doc)),
            )
            ok_jobs += 1
            tp = jf.parent / "transcript.json"
            if tp.exists():
                try:
                    rows = [Utterance.model_validate(u).model_dump(mode="json")
                            for u in json.loads(tp.read_text(encoding="utf-8"))]
                except Exception as e:  # noqa: BLE001
                    print("skip transcript", job.id, e)
                    continue
                conn.execute(
                    """INSERT INTO transcripts (job_id, utterances, updated_at)
                       VALUES (%s, %s, %s)""",
                    (job.id, Jsonb(rows), _ts(now())),
                )
                ok_tr += 1
        for pf in project_files:
            try:
                p = Project.model_validate_json(pf.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print("skip project", pf.name, e)
                continue
            conn.execute(
                """INSERT INTO projects (id, owner, updated_at, doc)
                   VALUES (%s, %s, %s, %s)""",
                (p.id, p.owner, _ts(p.updated_at), Jsonb(p.model_dump(mode="json"))),
            )
            ok_proj += 1
        conn.commit()
        print(f"wrote jobs={ok_jobs} transcripts={ok_tr} projects={ok_proj}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
