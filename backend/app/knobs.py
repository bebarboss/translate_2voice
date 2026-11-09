"""เกณฑ์ที่ระบบปรับเองได้ในขอบเขตปลอดภัย (ไม่แตะ .env ด้วยมือ)

อ่าน/เขียน data/metrics/knobs.json แล้วทับค่า runtime ของ settings ที่เกี่ยวข้อง
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from .config import Settings, settings

log = logging.getLogger("dubbing.knobs")

# ช่วงที่อนุญาตให้ขยับอัตโนมัติ
BOUNDS: dict[str, tuple[float, float, float]] = {
    # key: (lo, hi, step)
    "whisper_vad_threshold": (0.25, 0.55, 0.02),
    "whisper_fill_gap_sec": (0.25, 1.0, 0.05),
    "dub_check_min": (0.5, 0.75, 0.02),
}

DEFAULTS: dict[str, float] = {
    "whisper_vad_threshold": float(settings.whisper_vad_threshold),
    "whisper_fill_gap_sec": float(settings.whisper_fill_gap_sec),
    "dub_check_min": float(settings.dub_check_min),
}

MIN_JOBS_FOR_NUDGE = 5


def knobs_path() -> Path:
    return settings.data_dir / "metrics" / "knobs.json"


def load() -> dict[str, Any]:
    path = knobs_path()
    if not path.exists():
        return {"values": dict(DEFAULTS), "updated_at": None, "history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"values": dict(DEFAULTS), "updated_at": None, "history": []}
    values = dict(DEFAULTS)
    raw = data.get("values") or {}
    for k, (lo, hi, _) in BOUNDS.items():
        if k in raw:
            values[k] = float(min(hi, max(lo, float(raw[k]))))
    return {
        "values": values,
        "updated_at": data.get("updated_at"),
        "history": list(data.get("history") or [])[-50:],
    }


def save(data: dict[str, Any]) -> Path:
    path = knobs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def get(name: str, default: Optional[float] = None) -> float:
    values = load()["values"]
    if name in values:
        return float(values[name])
    if default is not None:
        return float(default)
    return float(DEFAULTS.get(name, 0.0))


def apply_to_settings(base: Optional[Settings] = None) -> Settings:
    """คืน Settings ใหม่ที่ทับด้วย knobs (settings โมดูลยังเป็นตัวเดิม — ใช้ object.__setattr__)"""
    cur = base or settings
    vals = load()["values"]
    for key, val in vals.items():
        if hasattr(cur, key):
            object.__setattr__(cur, key, type(getattr(cur, key))(val))
    return cur


def ensure_applied() -> None:
    """เรียกตอนเริ่มงาน / หลัง nudge — ทับ settings ปัจจุบัน"""
    if not getattr(settings, "auto_knobs", True):
        return
    apply_to_settings(settings)


def nudge_from_metrics(job_scores: list[dict]) -> Optional[dict]:
    """ขยับ knobs จากสถิติหลาย job — คืนค่าใหม่ถ้ามีการเปลี่ยน"""
    if not getattr(settings, "auto_knobs", True):
        return None
    ok = [s for s in job_scores if s.get("overall") is not None and not s.get("error")]
    if len(ok) < MIN_JOBS_FOR_NUDGE:
        return None

    coverages = [
        float(s["speech_coverage"]["coverage"])
        for s in ok
        if (s.get("speech_coverage") or {}).get("coverage") is not None
    ]
    if not coverages:
        return None
    mean_cov = sum(coverages) / len(coverages)
    falsey = sum(
        1 for s in ok
        if (s.get("speech_coverage") or {}).get("n_missed", 0) == 0
        and (s.get("dub_match") or {}).get("n_flagged", 0) > max(2, (s.get("n_lines") or 0) // 5)
    )

    data = load()
    values = dict(data["values"])
    changed: dict[str, tuple[float, float]] = {}

    def _step(key: str, direction: int) -> None:
        lo, hi, step = BOUNDS[key]
        old = float(values[key])
        new = min(hi, max(lo, round(old + direction * step, 4)))
        if new != old:
            values[key] = new
            changed[key] = (old, new)

    # coverage ต่ำ → ผ่อน VAD + เติมช่องว่างถี่ขึ้น
    if mean_cov < 0.88:
        _step("whisper_vad_threshold", -1)
        _step("whisper_fill_gap_sec", -1)
    # coverage สูงแต่มีท่อนพากย์เพี้ยนเยอะ → ดึง VAD กลับขึ้นเล็กน้อย กันเก็บ noise
    elif mean_cov > 0.96 and falsey >= max(2, len(ok) // 3):
        _step("whisper_vad_threshold", +1)

    dub_means = [
        float(s["dub_match"]["mean"])
        for s in ok
        if (s.get("dub_match") or {}).get("mean") is not None
    ]
    if dub_means:
        mean_dub = sum(dub_means) / len(dub_means)
        if mean_dub < 0.7:
            _step("dub_check_min", -1)  # ผ่อนนิดเพื่อไม่ retry วน; heal ใช้ judge อยู่แล้ว
        elif mean_dub > 0.9:
            _step("dub_check_min", +1)

    if not changed:
        return None

    data["values"] = values
    data["updated_at"] = time.time()
    data["history"] = (data.get("history") or []) + [{
        "ts": data["updated_at"],
        "mean_coverage": round(mean_cov, 4),
        "n_jobs": len(ok),
        "changed": {k: {"from": a, "to": b} for k, (a, b) in changed.items()},
    }]
    save(data)
    apply_to_settings(settings)
    log.info("auto knobs nudged: %s (mean_coverage=%.3f n=%d)", changed, mean_cov, len(ok))
    return data
