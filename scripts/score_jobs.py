"""คะแนนงานจริงจากไฟล์ใน data/jobs (ต้นฉบับ vs ผลถอด/พากย์) — ไม่ใช้คนแก้บท

  python scripts/score_jobs.py
  python scripts/score_jobs.py --job 00b6a90e5e2d
  python scripts/score_jobs.py --limit 30 --json
  python scripts/score_jobs.py --write --nudge
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app import job_metrics, knobs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="คะแนน job จาก vocals/transcript/tts/recheck")
    p.add_argument("--jobs-dir", type=Path, default=settings.data_dir / "jobs")
    p.add_argument("--job", default="", help="คะแนน job เดียว")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true", help="เขียน metrics.json ลงแต่ละ job")
    p.add_argument("--nudge", action="store_true", help="ขยับ knobs จากสถิติรวม")
    args = p.parse_args()

    if args.job:
        d = args.jobs_dir / args.job
        if not d.exists():
            print(f"ไม่พบ job {args.job}", file=sys.stderr)
            return 2
        rows = [job_metrics.score_job(d, dub_check_min=knobs.get("dub_check_min", settings.dub_check_min))]
        if args.write:
            job_metrics.write_metrics(d, rows[0])
    else:
        rows = job_metrics.scan_jobs(args.jobs_dir, limit=args.limit)
        if args.write:
            for r in rows:
                if r.get("error"):
                    continue
                job_metrics.write_metrics(args.jobs_dir / r["job_id"], r)

    nudged = None
    if args.nudge:
        nudged = knobs.nudge_from_metrics(rows)

    def _mean(vals):
        return round(sum(vals) / len(vals), 4) if vals else None

    coverages = [
        float(r["speech_coverage"]["coverage"])
        for r in rows
        if (r.get("speech_coverage") or {}).get("coverage") is not None
    ]
    dubs = [
        float(r["dub_match"]["mean"])
        for r in rows
        if (r.get("dub_match") or {}).get("mean") is not None
    ]
    lengths = [
        float(r["length_vs_source"]["score"])
        for r in rows
        if (r.get("length_vs_source") or {}).get("score") is not None
    ]
    def _col(key, field="score"):
        return [
            float(r[key][field])
            for r in rows
            if isinstance(r.get(key), dict) and r[key].get(field) is not None
        ]

    translates = _col("translate_fidelity")
    prosodies = _col("prosody_match")
    lips = _col("lip_overflow")
    terms = _col("term_consistency")
    speakers = _col("speaker_confusion")
    overalls = [float(r["overall"]) for r in rows if r.get("overall") is not None]
    summary = {
        "n": len(rows),
        "mean_coverage": _mean(coverages),
        "mean_dub_match": _mean(dubs),
        "mean_length": _mean(lengths),
        "mean_translate": _mean(translates),
        "mean_prosody": _mean(prosodies),
        "mean_lip": _mean(lips),
        "mean_terms": _mean(terms),
        "mean_speaker": _mean(speakers),
        "mean_overall": _mean(overalls),
        "needs_heal": sum(1 for r in rows if r.get("needs_asr_heal")),
        "knobs": knobs.load()["values"],
        "nudged": bool(nudged),
        "jobs": rows,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"jobs={summary['n']}  cov={summary['mean_coverage']}  "
            f"len={summary['mean_length']}  tr={summary['mean_translate']}  "
            f"prosody={summary['mean_prosody']}  lip={summary['mean_lip']}  "
            f"terms={summary['mean_terms']}  spk={summary['mean_speaker']}  "
            f"overall={summary['mean_overall']}  heal={summary['needs_heal']}"
        )
        for r in rows:
            cov = (r.get("speech_coverage") or {}).get("coverage")
            length = (r.get("length_vs_source") or {}).get("score")
            tr = (r.get("translate_fidelity") or {}).get("score")
            pro = (r.get("prosody_match") or {}).get("score")
            lip = (r.get("lip_overflow") or {}).get("score")
            term = (r.get("term_consistency") or {}).get("score")
            spk = (r.get("speaker_confusion") or {}).get("score")
            ov = (r.get("lip_overflow") or {}).get("overflow_lines")
            heal = " HEAL" if r.get("needs_asr_heal") else ""
            err = f" err={r['error']}" if r.get("error") else ""
            print(
                f"  {r.get('job_id')} o={r.get('overall')} "
                f"cov={cov} len={length} tr={tr} pro={pro} lip={lip}(ov={ov}) "
                f"term={term} spk={spk}{heal}{err}"
            )
        if nudged:
            print(f"knobs nudged → {knobs.load()['values']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
