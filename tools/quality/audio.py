"""A. Audio score (objective). ffmpeg ebur128 for loudness/true peak, numpy for the rest.

Every number here is measured from the exported files; nothing is predicted."""
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

ANALYSIS_SR = 16000  # levels, ducking and voice activity are measured on 16 kHz mono copies


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    env = os.environ.get(name.upper())
    if env:
        return env
    found = shutil.which(name)
    if found:
        return found
    local = Path.home() / ".local" / "bin" / name
    if local.is_file():
        return str(local)
    raise RuntimeError(f"{name} not found: put it on PATH or set {name.upper()}=/path/to/{name}")


def probe(path: Path) -> tuple[int, int]:
    """(sample_rate, channels) of the first audio stream"""
    out = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate,channels", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return int(s["sample_rate"]), int(s["channels"])


def decode(path: Path, sr: Optional[int] = None, mono: bool = False) -> tuple[np.ndarray, int]:
    """float32 samples, shape (n, channels). sr/mono=None keeps the file's own rate/channels."""
    nsr, nch = probe(path)
    sr = sr or nsr
    ch = 1 if mono else nch
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-vn", "-ac", str(ch), "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, ch), sr


# ---------------------------------------------------------------- loudness
_I = re.compile(r"I:\s+(-?[\d.]+|-inf)\s+LUFS")
_TP = re.compile(r"True peak:\s*\n\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS")


def ebur128(path: Path) -> dict:
    """integrated LUFS and true peak (dBTP) from ffmpeg's ebur128 summary"""
    err = subprocess.run([ffmpeg_bin(), "-nostats", "-hide_banner", "-i", str(path), "-vn",
                          "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    i = _I.findall(err)
    tp = _TP.findall(err)
    num = lambda s: -math.inf if s == "-inf" else float(s)  # noqa: E731
    return {"integrated_lufs": num(i[-1]) if i else None, "true_peak_dbtp": num(tp[-1]) if tp else None}


# ---------------------------------------------------------------- helpers
def db(power: float) -> float:
    return 10 * math.log10(power) if power > 1e-12 else -120.0


def rms_db(x: np.ndarray) -> float:
    return db(float(np.mean(np.square(x, dtype=np.float64)))) if x.size else -120.0


def clipped(x: np.ndarray, level: float) -> int:
    return int(np.count_nonzero(np.abs(x) >= level))


def stereo(x: np.ndarray) -> dict:
    """L/R correlation and side-vs-mid energy. Mono file -> channels=1, no stereo."""
    if x.ndim < 2 or x.shape[1] < 2:
        return {"channels": 1, "lr_corr": None, "side_mid_db": None}
    left, right = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
    loud = np.abs(left) + np.abs(right) > 1e-4
    if np.count_nonzero(loud) < 10:
        return {"channels": int(x.shape[1]), "lr_corr": None, "side_mid_db": None}
    left, right = left[loud], right[loud]
    sl, sr_ = left.std(), right.std()
    corr = float(np.mean((left - left.mean()) * (right - right.mean())) / (sl * sr_)) if sl > 0 and sr_ > 0 else 1.0
    mid, side = (left + right) / 2, (left - right) / 2
    return {"channels": int(x.shape[1]), "lr_corr": round(corr, 4),
            "side_mid_db": round(db(float(np.mean(side ** 2))) - db(float(np.mean(mid ** 2))), 2)}


def _mask(windows: list[tuple[float, float]], n: int, sr: int) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    for a, b in windows:
        m[max(0, int(a * sr)):max(0, min(n, int(b * sr)))] = True
    return m


def gaps(speech: list[tuple[float, float]], total: float, min_len: float, margin: float) -> list[tuple[float, float]]:
    """stretches with no speech, at least min_len long after pulling margin in from both sides"""
    out, cur = [], 0.0
    for a, b in sorted(speech) + [(total, total)]:
        lo, hi = cur + margin, a - margin
        if hi - lo >= min_len:
            out.append((lo, hi))
        cur = max(cur, b)
    return out


# ---------------------------------------------------------------- job level
@dataclass
class Tracks:
    """16 kHz mono copies, all the same length (timeline-aligned)"""
    final: Optional[np.ndarray]
    voice: Optional[np.ndarray]
    bgm: Optional[np.ndarray]
    bed: Optional[np.ndarray]     # final - gain * voice = background as heard in the mix (after ducking)
    voice_gain: float = 1.0


def load_tracks(final: Optional[Path], voice: list[Path], bgm: Optional[Path]) -> Tracks:
    f = decode(final, ANALYSIS_SR, mono=True)[0][:, 0] if final else None
    v = None
    for p in voice:
        x = decode(p, ANALYSIS_SR, mono=True)[0][:, 0]
        v = x if v is None else _pad_add(v, x)
    b = decode(bgm, ANALYSIS_SR, mono=True)[0][:, 0] if bgm else None
    n = max((len(a) for a in (f, v, b) if a is not None), default=0)
    f, v, b = (None if a is None else np.pad(a, (0, n - len(a))) for a in (f, v, b))
    bed, gain = None, 1.0
    if f is not None and v is not None:
        # loudnorm scales the whole mix linearly, so fit that gain before subtracting the voice
        vv = float(np.dot(v, v))
        gain = float(np.dot(f, v) / vv) if vv > 0 else 1.0
        gain = gain if 0.05 < gain < 20 else 1.0
        bed = f - gain * v
    return Tracks(f, v, b, bed, gain)


def _pad_add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = max(len(a), len(b))
    return np.pad(a, (0, n - len(a))) + np.pad(b, (0, n - len(b)))


def ducking(tr: Tracks, speech: list[tuple[float, float]], th: dict) -> dict:
    """background level in speech windows vs gaps.
    duck_db: how much more the background drops under speech than the raw bgm stem does by itself
    (bgm content alone can be quieter under dialogue; the raw stem cancels that out). Without a bgm stem
    the raw term is 0 and duck_basis says so."""
    out = {"bg_speech_db": None, "bg_gap_db": None, "bgm_raw_speech_db": None, "bgm_raw_gap_db": None,
           "duck_db": None, "voice_over_bg_db": None, "duck_basis": ""}
    if tr.bed is None:
        return out
    n, sr = len(tr.bed), ANALYSIS_SR
    total = n / sr
    sp = _mask(speech, n, sr)
    gp = _mask(gaps(speech, total, th["gap_min_sec"], th["gap_margin_sec"]), n, sr)
    if not sp.any():
        return out
    out["bg_speech_db"] = round(rms_db(tr.bed[sp]), 2)
    out["voice_over_bg_db"] = round(rms_db(tr.voice_gain * tr.voice[sp]) - out["bg_speech_db"], 2)
    if not gp.any():
        out["duck_basis"] = "no gaps"
        return out
    out["bg_gap_db"] = round(rms_db(tr.bed[gp]), 2)
    drop = out["bg_gap_db"] - out["bg_speech_db"]
    if tr.bgm is not None and rms_db(tr.bgm) > -90:
        out["bgm_raw_speech_db"] = round(rms_db(tr.bgm[sp]), 2)
        out["bgm_raw_gap_db"] = round(rms_db(tr.bgm[gp]), 2)
        drop -= out["bgm_raw_gap_db"] - out["bgm_raw_speech_db"]
        out["duck_basis"] = "mix vs bgm stem"
    else:
        out["duck_basis"] = "mix only (no bgm stem)"
    out["duck_db"] = round(drop, 2)
    return out


def job_audio(final: Optional[Path], tr: Tracks, speech: list[tuple[float, float]],
              th: dict) -> tuple[dict, Optional[np.ndarray], int]:
    """job-level audio fields + the decoded final mix (native rate/channels) for per-segment checks"""
    out: dict = {"final_file": str(final) if final else ""}
    if final is None:
        return out, None, 0
    out.update(ebur128(final))
    x, sr = decode(final)
    out["sample_rate"] = sr
    out["duration_sec"] = round(len(x) / sr, 2)
    out["clipped_samples"] = clipped(x, th["clip_level"])
    out.update(stereo(x))
    out.update(ducking(tr, speech, th))
    i, tp = out.get("integrated_lufs"), out.get("true_peak_dbtp")
    out["lufs_delta"] = None if i is None or math.isinf(i) else round(i - th["target_lufs"], 2)
    # pass/fail per check (never summed)
    out["ok_lufs"] = out["lufs_delta"] is not None and abs(out["lufs_delta"]) <= th["lufs_tolerance"]
    out["ok_true_peak"] = tp is not None and tp <= th["max_true_peak_dbtp"]
    out["ok_clipping"] = out["clipped_samples"] <= th["max_clipped_samples"]
    out["ok_stereo"] = out["channels"] >= 2 and out["lr_corr"] is not None and (
        out["lr_corr"] < th["stereo_max_corr"] or out["side_mid_db"] > th["stereo_min_side_db"])
    out["ok_ducking"] = None if out["duck_db"] is None else (
        out["duck_db"] >= th["min_duck_db"] and (out["voice_over_bg_db"] or 0) >= th["min_voice_over_bg_db"])
    return out, x, sr


# ---------------------------------------------------------------- segment level
def voice_end(voice: np.ndarray, start: float, limit: float, th: dict) -> Optional[float]:
    """seconds from start to the last moment the voice track is active before limit (stems without per-line files)"""
    sr = ANALYSIS_SR
    a, b = int(start * sr), min(len(voice), int(limit * sr))
    if b <= a:
        return None
    seg = voice[a:b]
    hop = int(0.02 * sr)
    if len(seg) < hop:
        return None
    frames = seg[: len(seg) // hop * hop].reshape(-1, hop)
    level = 10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    on = np.flatnonzero(level > th["voice_active_db"])
    return None if not len(on) else (on[-1] + 1) * hop / sr


def duration(path: Path) -> float:
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / info.samplerate
