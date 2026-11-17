"""เสียงพากย์เงียบบนบทสั้น: ลองใหม่ และรอบสุดท้ายไม่บังคับความยาว (slot)"""
from pathlib import Path

import numpy as np

from app.pipeline import gpu

LINE = {"id": 7, "text": "ใช่", "target_lang": "en", "ref_text": "hello", "slot": 0.4,
        "max_speedup": 1.1, "max_slowdown": 1.2}
LOUD = (np.ones(2400) * 0.3).astype(np.float32)
QUIET = np.zeros(2400, dtype=np.float32)


def _run(outputs, checks=None):
    calls = []

    def fake(ref, ref_text, text, speed, steps, lang, slot=None, max_speedup=1.1, max_slowdown=1.2,
             attempt=0, limit=None):
        calls.append(slot)
        return outputs[min(len(calls) - 1, len(outputs) - 1)]

    voice = gpu.speak_line(fake, Path("ref.wav"), dict(LINE), 16, 1.0, checks)
    return voice, calls


def test_is_audible():
    assert gpu.is_audible(LOUD)
    assert not gpu.is_audible(QUIET)
    assert not gpu.is_audible(np.array([], dtype=np.float32))
    assert not gpu.is_audible(np.array([np.nan, 0.5], dtype=np.float32))


def test_last_attempt_drops_the_slot():
    voice, calls = _run([QUIET, QUIET, LOUD])
    assert calls == [0.4, 0.4, None]
    assert gpu.is_audible(voice)


def test_first_success_makes_one_call():
    _, calls = _run([LOUD])
    assert calls == [0.4]


def test_still_silent_is_flagged_for_the_user():
    checks: dict = {}
    voice, calls = _run([QUIET], checks)
    assert len(calls) == gpu.SILENT_RETRIES
    assert not gpu.is_audible(voice)
    assert checks == {7: [0.0, ""]}
