"""ประเมินงานที่พากย์เสร็จในวันนั้น แล้วเก็บคะแนนลง Supabase

รันอัตโนมัติทุก 23:59 Asia/Bangkok จาก lifespan ของ API
หรือมือ: python scripts/run_daily_metrics.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from . import job_metrics, knobs, supabase_db as sdb
from .config import settings
from .schemas import JobStatus

log = logging.getLogger("dubbing.daily_metrics")

BKK = timezone(timedelta(hours=7))  # Asia/Bangkok (ไม่พึ่ง tzdata)
SCORES, DAILY = "job_metric_scores", "job_metric_daily"
CRON_HOUR, CRON_MINUTE = 23, 59

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """เริ่ม–จบของวันตามปฏิทินกรุงเทพ (คืนเป็น UTC-aware)"""
    start = datetime(day.year, day.month, day.day, tzinfo=BKK)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _metric_float(block: Any, *keys: str) -> Optional[float]:
    if not isinstance(block, dict):
        return None
    for k in keys:
        v = block.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _flatten_row(run_date: date, metrics: dict) -> dict:
    cov = metrics.get("speech_coverage") or {}
    speakers: list[str] = []
    # speakers จาก speaker_confusion ไม่มี — ดึงจาก metrics ถ้ามี หรือว่าง
    if isinstance(metrics.get("speakers"), list):
        speakers = [str(s) for s in metrics["speakers"]]
    return {
        "run_date": run_date.isoformat(),
        "job_id": metrics.get("job_id") or "",
        "n_lines": int(metrics.get("n_lines") or 0),
        "speakers": speakers,
        "overall": _metric_float(metrics, "overall"),
        "speech_coverage": _metric_float(cov, "coverage"),
        "dub_match": _metric_float(metrics.get("dub_match"), "mean"),
        "timing_fit": _metric_float(metrics.get("timing_fit"), "mean_ratio"),
        "length_vs_source": _metric_float(metrics.get("length_vs_source"), "score"),
        "translate_fidelity": _metric_float(metrics.get("translate_fidelity"), "score"),
        "prosody_match": _metric_float(metrics.get("prosody_match"), "score"),
        "lip_overflow": _metric_float(metrics.get("lip_overflow"), "score"),
        "term_consistency": _metric_float(metrics.get("term_consistency"), "score"),
        "speaker_confusion": _metric_float(metrics.get("speaker_confusion"), "score"),
        "needs_asr_heal": bool(metrics.get("needs_asr_heal")),
        "metrics": metrics,
    }


def _mean(vals: list[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 4) if vals else None


def jobs_done_on(day: date, store) -> list:
    """งาน status=done ที่ updated_at ตกในวันนั้น (Asia/Bangkok)"""
    start, end = _day_bounds(day)
    out = []
    for job in store.all():
        if job.status != JobStatus.done:
            continue
        ts = _aware(job.updated_at)
        if start <= ts < end:
            out.append(job)
    return sorted(out, key=lambda j: _aware(j.updated_at))


def score_and_speakers(job_dir, metrics: dict) -> dict:
    """เติมรายชื่อผู้พูดจากบทที่โหลดได้"""
    utts = job_metrics._load_transcript(job_dir)  # noqa: SLF001 — ใช้ชุดเดียวกับ score
    speakers = sorted({u.speaker for u in utts if u.speaker})
    metrics = {**metrics, "speakers": speakers}
    return metrics


def run_for_date(day: Optional[date] = None, *, store=None) -> dict[str, Any]:
    """ประเมินงานที่เสร็จในวันนั้น เขียน metrics.json และ upsert ลง DB คืนสรุป"""
    day = day or datetime.now(BKK).date()
    if store is None:
        from .jobs import JobStore
        store = JobStore(settings.data_dir)

    jobs = jobs_done_on(day, store)
    dub_min = float(knobs.get("dub_check_min", settings.dub_check_min))
    rows: list[dict] = []
    errors: list[dict] = []

    for job in jobs:
        d = store.dir(job.id)
        try:
            metrics = job_metrics.score_job(d, dub_check_min=dub_min)
            metrics = score_and_speakers(d, metrics)
            # ใช้ speakers จาก job meta ถ้าบทว่าง
            if not metrics.get("speakers") and job.speakers:
                metrics["speakers"] = list(job.speakers)
            job_metrics.write_metrics(d, metrics, dub_check_min=dub_min)
            rows.append(_flatten_row(day, metrics))
        except Exception as exc:  # noqa: BLE001
            log.exception("daily metrics failed for %s", job.id)
            errors.append({"job_id": job.id, "error": str(exc)})

    overalls = [r["overall"] for r in rows if r.get("overall") is not None]
    worst_id = ""
    if overalls:
        worst = min(rows, key=lambda r: (r["overall"] is None, r["overall"] if r["overall"] is not None else 1.0))
        worst_id = worst.get("job_id") or ""

    issues: list[str] = []
    for r in rows:
        if r.get("needs_asr_heal"):
            issues.append(f"{r['job_id']}:needs_asr_heal")
        if r.get("speech_coverage") is not None and r["speech_coverage"] < 0.85:
            issues.append(f"{r['job_id']}:low_coverage={r['speech_coverage']}")
        if r.get("speaker_confusion") is not None and r["speaker_confusion"] < 0.9:
            issues.append(f"{r['job_id']}:speaker={r['speaker_confusion']}")
        if r.get("translate_fidelity") is not None and r["translate_fidelity"] < 0.8:
            issues.append(f"{r['job_id']}:translate={r['translate_fidelity']}")
        if r.get("prosody_match") is not None and r["prosody_match"] < 0.7:
            issues.append(f"{r['job_id']}:prosody={r['prosody_match']}")

    summary = {
        "run_date": day.isoformat(),
        "job_ids": [r["job_id"] for r in rows],
        "errors": errors,
        "top_issues": issues[:20],
        "n_with_transcript": sum(1 for r in rows if r.get("n_lines", 0) > 0),
    }

    daily = {
        "run_date": day.isoformat(),
        "n_jobs": len(rows),
        "needs_heal": sum(1 for r in rows if r.get("needs_asr_heal")),
        "mean_overall": _mean([float(x) for x in overalls]),
        "mean_coverage": _mean([float(r["speech_coverage"]) for r in rows if r.get("speech_coverage") is not None]),
        "mean_dub_match": _mean([float(r["dub_match"]) for r in rows if r.get("dub_match") is not None]),
        "mean_timing": _mean([float(r["timing_fit"]) for r in rows if r.get("timing_fit") is not None]),
        "mean_length": _mean([float(r["length_vs_source"]) for r in rows if r.get("length_vs_source") is not None]),
        "mean_translate": _mean([float(r["translate_fidelity"]) for r in rows if r.get("translate_fidelity") is not None]),
        "mean_prosody": _mean([float(r["prosody_match"]) for r in rows if r.get("prosody_match") is not None]),
        "mean_lip": _mean([float(r["lip_overflow"]) for r in rows if r.get("lip_overflow") is not None]),
        "mean_terms": _mean([float(r["term_consistency"]) for r in rows if r.get("term_consistency") is not None]),
        "mean_speaker": _mean([float(r["speaker_confusion"]) for r in rows if r.get("speaker_confusion") is not None]),
        "worst_job_id": worst_id,
        "summary": summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if sdb.enabled():
        try:
            for i in range(0, len(rows), 100):
                sdb.upsert(SCORES, rows[i:i + 100], "run_date,job_id")
            sdb.upsert(DAILY, daily, "run_date")
            log.info("daily metrics saved run_date=%s n_jobs=%s overall=%s",
                     day.isoformat(), daily["n_jobs"], daily["mean_overall"])
        except sdb.DBError as exc:
            log.warning("daily metrics DB save failed: %s", exc)
            daily["db_error"] = str(exc)
    else:
        log.warning("DB_BACKEND ไม่ใช่ supabase — เก็บแค่ metrics.json บนดิสก์")
        daily["db_skipped"] = True

    # เขียนสรุปไฟล์ใน data/metrics ด้วย (สำรองให้อ่าน offline)
    out_dir = settings.data_dir / "metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"daily-{day.isoformat()}.json"
    import json
    path.write_text(
        json.dumps({"daily": daily, "scores": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return daily


def list_daily(days: int = 30) -> dict:
    """อ่านสรุปรายวันจาก DB สำหรับหน้า admin"""
    days = max(1, min(int(days), 365))
    if not sdb.enabled():
        return {"ok": False, "error": "supabase_disabled", "days": [], "n": 0}
    since = (datetime.now(BKK).date() - timedelta(days=days - 1)).isoformat()
    try:
        rows = sdb.select(
            DAILY,
            select="*",
            run_date=f"gte.{since}",
            order="run_date.desc",
        )
    except sdb.DBError as exc:
        msg = str(exc)
        if "does not exist" in msg or "42P01" in msg or "404" in msg:
            return {
                "ok": False,
                "error": "missing_table",
                "hint": "รัน supabase/migrations/20261109020000_job_metrics_daily.sql ใน SQL Editor",
                "days": [],
                "n": 0,
            }
        raise
    return {"ok": True, "n": len(rows), "days": rows}


def _seconds_until_cron() -> float:
    now = datetime.now(BKK)
    target = now.replace(hour=CRON_HOUR, minute=CRON_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def _loop() -> None:
    last_run: Optional[date] = None
    while not _stop.is_set():
        wait = _seconds_until_cron()
        log.info("daily metrics cron: next run in %.0f s (23:59 Asia/Bangkok)", wait)
        if _stop.wait(wait):
            break
        day = datetime.now(BKK).date()
        if last_run == day:
            continue
        try:
            run_for_date(day)
            last_run = day
        except Exception:
            log.exception("daily metrics cron failed")
        # กันรันซ้ำในนาทีเดียวกัน
        _stop.wait(60)


def start() -> None:
    """เริ่มเธรด cron 23:59 Asia/Bangkok (daemon)"""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="daily-metrics", daemon=True)
    _thread.start()
    log.info("daily metrics cron started (23:59 Asia/Bangkok)")
