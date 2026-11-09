"""คะแนนชุดคลิปทอง — วัด ASR/repair เทียบ expected

ตัวอย่าง:
  python scripts/score_gold.py
  python scripts/score_gold.py --tag shout
  python scripts/score_gold.py --case shout_orphan_th
  python scripts/score_gold.py --live
  python scripts/score_gold.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gold import ROOT as GOLD_ROOT, list_cases, load_case, score_all, score_case  # noqa: E402
from app.schemas import Utterance  # noqa: E402


def _live_transcribe(case: dict) -> list[Utterance]:
    """ถอดเสียงคลิปทองด้วย Whisper (ถ้ามี) — ใช้เวลาสัมพัทธ์ของคลิป + audio_offset"""
    audio = case.get("audio")
    if not audio or not Path(audio).exists():
        raise FileNotFoundError(f"{case['id']}: ไม่มี audio.wav สำหรับ --live")
    from app.pipeline import transcribe as tr
    from app.pipeline.common import Turn
    from app.pipeline.repair import repair_transcript

    lang = case["meta"].get("language") or None
    offset = float(case["meta"].get("audio_offset") or 0.0)
    words, detected = tr.transcribe(Path(audio), language=lang)
    lang = lang or detected or "th"
    # เลื่อนเวลาให้ตรงกับ expected ที่เป็นเวลาในคลิปต้นทาง
    if offset:
        words = [type(w)(w.start + offset, w.end + offset, w.text, w.segment) for w in words]
    turns = [Turn(0.0 + offset, 1e6 + offset, "speaker_01")]
    utts = tr.assign_speakers(words, turns, lang=lang) if words else []
    fixed, _, _ = repair_transcript(utts, words, turns, lang)
    return fixed


def main() -> int:
    p = argparse.ArgumentParser(description="คะแนนชุดคลิปทอง (gold fixtures)")
    p.add_argument("--root", type=Path, default=GOLD_ROOT)
    p.add_argument("--tag", default="", help="กรองแท็ก เช่น shout / child")
    p.add_argument("--case", default="", help="รันเคสเดียวตามชื่อโฟลเดอร์")
    p.add_argument("--live", action="store_true", help="ถอดเสียง audio.wav ด้วย Whisper")
    p.add_argument("--json", action="store_true", help="พิมพ์ผลเป็น JSON")
    args = p.parse_args()

    if args.case:
        paths = [args.root / args.case]
        if not (paths[0] / "meta.json").exists():
            print(f"ไม่พบเคส {args.case}", file=sys.stderr)
            return 2
    else:
        paths = list_cases(args.root, tag=args.tag or None)

    results = []
    for path in paths:
        case = load_case(path)
        got = None
        if args.live and case.get("audio"):
            try:
                got = _live_transcribe(case)
            except Exception as exc:
                results.append({
                    "id": case["id"], "pass": False, "error": str(exc),
                    "recall": 0.0, "tags": case["meta"].get("tags") or [],
                })
                continue
        results.append(score_case(case, got=got))

    summary = {
        "n": len(results),
        "passed": sum(1 for r in results if r.get("pass")),
        "failed": sum(1 for r in results if not r.get("pass")),
        "mean_recall": round(
            sum(r.get("recall", 0) for r in results) / len(results), 4
        ) if results else 1.0,
        "cases": results,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"gold: {summary['passed']}/{summary['n']} passed  mean_recall={summary['mean_recall']}")
        for r in results:
            mark = "OK" if r.get("pass") else "FAIL"
            err = f" err={r['error']}" if r.get("error") else ""
            miss = ""
            if r.get("missed"):
                miss = " missed=" + ";".join(
                    f"{m['start']}-{m['end']}:{m['text']}" for m in r["missed"][:3]
                )
            print(f"  [{mark}] {r['id']} recall={r.get('recall')} tags={r.get('tags')}{err}{miss}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    # กัน unused import เมื่อรัน --case อย่างเดียว
    _ = score_all
    raise SystemExit(main())
