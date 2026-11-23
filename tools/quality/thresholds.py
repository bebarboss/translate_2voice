"""Pass/fail thresholds. Loudness targets come from backend/app/audio_constants.py (the mixer's own targets)
so the scorer and the pipeline never disagree; everything else is scorer-only."""
from app import audio_constants as ac

THRESHOLDS = {
    # A. audio
    "target_lufs": ac.LOUDNORM_I,          # -16 LUFS integrated
    "lufs_tolerance": 1.0,                 # |measured - target| <= 1 LU passes
    "max_true_peak_dbtp": ac.LOUDNORM_TP,  # -1.5 dBTP ceiling
    "clip_level": 0.999,                   # |sample| >= this counts as clipped
    "max_clipped_samples": 0,
    "overrun_ratio": 1.02,                 # dub longer than slot * this (same 2% the pipeline allows) ...
    "overrun_min_sec": 0.10,               # ... and by at least this many seconds -> overrun
    "overlap_next_min_sec": 0.05,          # dub running into the next line's start
    "min_duck_db": 3.0,                    # bgm must drop at least this much in speech windows vs gaps
    "min_voice_over_bg_db": 6.0,           # dub voice level above background inside speech windows
    "gap_min_sec": 0.5,                    # only gaps at least this long count as "no speech"
    "gap_margin_sec": 0.3,                 # keep this far from speech edges (duck release)
    "stereo_max_corr": 0.995,              # L/R correlation above this = effectively mono
    "stereo_min_side_db": -30.0,           # side energy below mid by more than this = effectively mono
    "voice_active_db": -45.0,              # dBFS envelope that counts as "voice present" (stems only)
    # B. translation rules
    "fit_tolerance": None,                 # filled from app settings at runtime (syllable budget)
    "max_speedup": None,
}


def resolved() -> dict:
    from app.config import settings
    out = dict(THRESHOLDS)
    out["fit_tolerance"] = settings.fit_tolerance
    out["max_speedup"] = settings.max_speedup
    out["thai_chars_per_syllable"] = settings.thai_chars_per_syllable
    out["thai_chars_per_sec"] = settings.thai_chars_per_sec
    out["en_words_per_sec"] = settings.en_words_per_sec
    return out
