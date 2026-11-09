"""รันประเมินงานรายวันด้วยมือ (backfill / ทดสอบ)

  python scripts/run_daily_metrics.py
  python scripts/run_daily_metrics.py --date 2026-11-09
  python scripts/run_daily_metrics.py --date 2026-11-09 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import daily_metrics  # noqa: E402
from app.daily_metrics import BKK  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="ประเมินงาน done ในวันนั้น แล้วเก็บลง DB")
    p.add_argument("--date", default="", help="YYYY-MM-DD (ค่าเริ่มต้น = วันนี้ตามกรุงเทพ)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.date:
        day = date.fromisoformat(args.date)
    else:
        day = datetime.now(BKK).date()

    result = daily_metrics.run_for_date(day)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"run_date={result.get('run_date')} n_jobs={result.get('n_jobs')} "
            f"overall={result.get('mean_overall')} heal={result.get('needs_heal')} "
            f"worst={result.get('worst_job_id') or '-'}"
        )
        if result.get("db_error"):
            print(f"db_error={result['db_error']}", file=sys.stderr)
        if result.get("db_skipped"):
            print("db_skipped=true (ตั้ง DB_BACKEND=supabase เพื่อเก็บลงฐานข้อมูล)")
        top = (result.get("summary") or {}).get("top_issues") or []
        for issue in top[:10]:
            print(f"  issue: {issue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
