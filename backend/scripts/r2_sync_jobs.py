"""อัปไฟล์สื่องาน done ที่ค้างบนดิสก์ขึ้น Cloudflare R2

  python scripts/r2_sync_jobs.py
  python scripts/r2_sync_jobs.py --job 5317c27fff91
  python scripts/r2_sync_jobs.py --purge
  python scripts/r2_sync_jobs.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import object_store  # noqa: E402
from app.config import settings  # noqa: E402
from app.schemas import JobStatus  # noqa: E402


def _job_status(job_dir: Path) -> str:
    meta = job_dir / "job.json"
    if not meta.exists():
        return ""
    try:
        return str(json.loads(meta.read_text(encoding="utf-8")).get("status") or "")
    except (OSError, json.JSONDecodeError, TypeError):
        return ""


def main() -> int:
    p = argparse.ArgumentParser(description="อัปสื่องาน done ขึ้น R2")
    p.add_argument("--jobs-dir", type=Path, default=settings.data_dir / "jobs")
    p.add_argument("--job", default="", help="อัป job เดียว")
    p.add_argument("--purge", action="store_true", help="ลบสื่อ local หลังอัปสำเร็จ (ทับ R2_PURGE_LOCAL)")
    p.add_argument("--dry-run", action="store_true", help="แสดงรายการที่จะอัป โดยไม่ส่งขึ้น R2")
    p.add_argument("--all-status", action="store_true", help="อัปทุกโฟลเดอร์ที่มีสื่อ ไม่จำกัด status=done")
    args = p.parse_args()

    if not args.dry_run and not object_store.enabled():
        print("R2 ยังไม่พร้อม — ตั้ง R2_ENABLED=1 และคีย์ bucket ใน .env", file=sys.stderr)
        return 2

    if args.job:
        dirs = [args.jobs_dir / args.job]
    else:
        dirs = sorted(d for d in args.jobs_dir.iterdir() if d.is_dir()) if args.jobs_dir.is_dir() else []

    ok = 0
    skipped = 0
    for d in dirs:
        if not d.is_dir():
            print(f"ไม่พบ {d}", file=sys.stderr)
            return 2
        status = _job_status(d)
        if not args.all_status and status and status != JobStatus.done.value:
            skipped += 1
            continue
        media = object_store.iter_media_files(d)
        if not media:
            skipped += 1
            continue
        if args.dry_run:
            print(f"{d.name}: would upload {len(media)} files (status={status or '?'})")
            for f in media:
                print(f"  {f.relative_to(d).as_posix()}")
            ok += 1
            continue
        keys = object_store.upload_job_media(d, purge=args.purge)
        print(f"{d.name}: uploaded/kept {len(keys)} objects")
        ok += 1

    print(f"done: {ok} jobs, skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
