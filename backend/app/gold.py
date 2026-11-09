"""ชุดคลิปทอง + คะแนนถอดเสียง/ซ่อม + บันทึกการแก้จาก Review

ใช้วัดผลหลังปรับ VAD / repair / พรอมต์ โดยไม่ต้อง fine-tune โมเดลก่อน
"""
from __future__ import annotations

import json
import logging
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from .config import settings
from .schemas import Utterance

log = logging.getLogger("dubbing.gold")

# รากชุดทองใน repo (ไม่ใช่ data/ ที่ gitignore)
ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "gold"


def corrections_dir() -> Path:
    path = settings.data_dir / "corrections"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _letters(text: str) -> str:
    text = unicodedata.normalize("NFC", (text or "").lower())
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LMN")


def text_score(expected: str, got: str) -> float:
    """ความคล้ายข้อความ 0–1 (ตัดวรรคตอน)"""
    a, b = _letters(expected), _letters(got)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def coverage(expected_segs: list[dict], got: list[Utterance], *, overlap_ratio: float = 0.35) -> dict:
    """recall ของช่วงทอง: คาดหวังถูกคลุมด้วยท่อนที่ได้มาแค่ไหน"""
    if not expected_segs:
        return {"n": 0, "hit": 0, "recall": 1.0, "missed": []}
    hit, missed = 0, []
    for seg in expected_segs:
        a, b = float(seg["start"]), float(seg["end"])
        dur = max(1e-3, b - a)
        need = (seg.get("text") or "").strip()
        best_ov, best_txt = 0.0, ""
        for u in got:
            ov = max(0.0, min(b, u.end) - max(a, u.start))
            if ov > best_ov:
                best_ov = ov
                best_txt = (u.source or u.target or "").strip()
        covered = best_ov / dur >= overlap_ratio
        text_ok = True
        if need and covered:
            # ท่อนสั้น (ตะโกน) อนุญาตคะแนนต่ำกว่า
            min_score = 0.35 if len(_letters(need)) <= 6 else 0.55
            text_ok = text_score(need, best_txt) >= min_score
        if covered and text_ok:
            hit += 1
        else:
            missed.append({
                "start": a, "end": b, "text": need,
                "overlap": round(best_ov, 3), "got": best_txt[:80],
            })
    n = len(expected_segs)
    return {"n": n, "hit": hit, "recall": round(hit / n, 4) if n else 1.0, "missed": missed}


def load_case(path: Path) -> dict[str, Any]:
    """โหลดหนึ่งเคสทอง: meta + expected + ไฟล์เสริม"""
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    case = {"id": path.name, "path": path, "meta": meta, "expected": expected}
    for name in ("words.json", "turns.json", "utterances.json", "got.json"):
        f = path / name
        if f.exists():
            case[name.replace(".json", "")] = json.loads(f.read_text(encoding="utf-8"))
    audio = path / "audio.wav"
    if audio.exists():
        case["audio"] = audio
    return case


def list_cases(root: Path = ROOT, *, tag: Optional[str] = None) -> list[Path]:
    if not root.exists():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "meta.json").exists()):
        if tag:
            tags = json.loads((d / "meta.json").read_text(encoding="utf-8")).get("tags") or []
            if tag not in tags:
                continue
        out.append(d)
    return out


def _words_from_json(rows: list[dict]):
    from .pipeline.common import Word
    return [Word(float(r["start"]), float(r["end"]), r.get("text") or r.get("word") or "",
                 int(r.get("segment", 0))) for r in rows]


def _turns_from_json(rows: list[dict]):
    from .pipeline.common import Turn
    return [Turn(float(r["start"]), float(r["end"]), r.get("speaker") or "speaker_01") for r in rows]


def _utts_from_json(rows: list[dict]) -> list[Utterance]:
    return [Utterance.model_validate(r) for r in rows]


def run_repair_case(case: dict) -> list[Utterance]:
    """รัน repair บน words/utterances ของเคส (โหมดออฟไลน์ ไม่เรียก Whisper)"""
    from .pipeline.repair import repair_transcript

    words = _words_from_json(case.get("words") or [])
    turns = _turns_from_json(case.get("turns") or [{"start": 0, "end": 999, "speaker": "speaker_01"}])
    utts = _utts_from_json(case.get("utterances") or [])
    lang = (case["meta"].get("language") or "th")
    fixed, _, _ = repair_transcript(utts, words, turns, lang)
    return fixed


def score_case(case: dict, got: Optional[list[Utterance]] = None) -> dict:
    """คะแนนหนึ่งเคส — got ถ้าไม่ส่งจะใช้ got.json หรือรัน repair"""
    if got is None:
        if "got" in case:
            got = _utts_from_json(case["got"])
        elif case["meta"].get("mode", "repair") == "repair" and "utterances" in case:
            got = run_repair_case(case)
        elif case["meta"].get("job_ref"):
            got = _load_job_transcript(case["meta"]["job_ref"])
        else:
            got = []
    segs = case["expected"].get("segments") or []
    cov = coverage(segs, got)
    min_recall = float(case["expected"].get("min_recall", 0.8))
    tags = case["meta"].get("tags") or []
    return {
        "id": case["id"],
        "tags": tags,
        "mode": case["meta"].get("mode", "repair"),
        "n_got": len(got),
        "recall": cov["recall"],
        "hit": cov["hit"],
        "n_expected": cov["n"],
        "missed": cov["missed"],
        "pass": cov["recall"] >= min_recall,
        "min_recall": min_recall,
    }


def _load_job_transcript(job_id: str) -> list[Utterance]:
    path = settings.data_dir / "jobs" / job_id / "transcript.json"
    if not path.exists():
        return []
    return _utts_from_json(json.loads(path.read_text(encoding="utf-8")))


def score_all(root: Path = ROOT, *, tag: Optional[str] = None) -> dict:
    results = []
    for path in list_cases(root, tag=tag):
        case = load_case(path)
        results.append(score_case(case))
    n = len(results)
    passed = sum(1 for r in results if r["pass"])
    mean_recall = round(sum(r["recall"] for r in results) / n, 4) if n else 1.0
    return {
        "n": n, "passed": passed, "failed": n - passed,
        "mean_recall": mean_recall,
        "cases": results,
    }


def record_corrections(
    job_id: str,
    before: list[Utterance],
    after: list[Utterance],
    *,
    stage: str = "review",
) -> Optional[Path]:
    """บันทึก diff บทจาก Review เป็น candidate ชุดทอง (ไฟล์ JSONL รายวัน)"""
    by_before = {u.id: u for u in before}
    by_after = {u.id: u for u in after}
    rows: list[dict] = []
    now = time.time()

    for uid, old in by_before.items():
        new = by_after.get(uid)
        if new is None:
            rows.append({
                "ts": now, "job_id": job_id, "utterance_id": uid, "stage": stage, "kind": "removed",
                "before": _utt_snap(old), "after": None,
            })
            continue
        kinds = []
        if (old.source or "").strip() != (new.source or "").strip():
            kinds.append("source")
        if (old.target or "").strip() != (new.target or "").strip():
            kinds.append("target")
        if old.speaker != new.speaker:
            kinds.append("speaker")
        if abs(old.start - new.start) > 0.05 or abs(old.end - new.end) > 0.05:
            kinds.append("time")
        if kinds:
            rows.append({
                "ts": now, "job_id": job_id, "utterance_id": uid, "stage": stage,
                "kind": ",".join(kinds),
                "before": _utt_snap(old), "after": _utt_snap(new),
            })
    for uid, new in by_after.items():
        if uid not in by_before:
            rows.append({
                "ts": now, "job_id": job_id, "utterance_id": uid, "stage": stage, "kind": "added",
                "before": None, "after": _utt_snap(new),
            })
    if not rows:
        return None
    day = time.strftime("%Y%m%d", time.localtime(now))
    path = corrections_dir() / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    log.info("gold corrections: job=%s n=%d → %s", job_id, len(rows), path.name)
    return path


def _utt_snap(u: Utterance) -> dict:
    return {
        "id": u.id, "speaker": u.speaker, "start": u.start, "end": u.end,
        "source": u.source, "target": u.target,
    }


def export_correction_candidates(day: Optional[str] = None, *, limit: int = 50) -> list[dict]:
    """อ่าน corrections JSONL เป็นรายการ candidate (สำหรับคัดเข้าชุดทองมือ)"""
    d = corrections_dir()
    files = sorted(d.glob("*.jsonl"))
    if day:
        files = [p for p in files if p.stem == day]
    out: list[dict] = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= limit:
                return out
    return out
