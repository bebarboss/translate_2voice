"""สรุป data/corrections/*.jsonl เป็น candidate สำหรับใส่ชุดทอง

  python scripts/export_gold_candidates.py
  python scripts/export_gold_candidates.py --day 20261109 --limit 30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gold import export_correction_candidates  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--day", default="", help="YYYYMMDD ว่าง = ทุกวัน")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--kind", default="", help="กรองเช่น target,time,source")
    args = p.parse_args()
    rows = export_correction_candidates(args.day or None, limit=max(1, args.limit * 3))
    if args.kind:
        rows = [r for r in rows if args.kind in (r.get("kind") or "")]
    rows = rows[: args.limit]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"# {len(rows)} candidates", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
