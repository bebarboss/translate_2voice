"""บันไดแก้เสียงพากย์เงียบบนประโยคสั้น: ความยาวขั้นต่ำ ยืดทีละขั้น ตัวตรวจ RMS รวมประโยคข้างเคียง ป้าย "ควรฟัง" """
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

from app.config import settings
from app.pipeline import gpu, tts
from app.pipeline.runner import SILENT_LABEL, _apply_merge, _merge_candidate, heard_label

SR = 24000
LOUD = (np.ones(SR // 2) * 0.3).astype(np.float32)
QUIET = np.zeros(SR // 2, dtype=np.float32)
HUM = (np.ones(SR // 2) * 0.0005).astype(np.float32)  # แผ่วจน RMS ต่ำกว่าเกณฑ์ทุกเฟรม
BLIP = np.zeros(SR, dtype=np.float32)
BLIP[:200] = 0.3  # เสียงสั้น ๆ ครั้งเดียวในไฟล์ยาว 1 วินาที (< 15% ของเฟรม)
LINE = {"id": 14, "text": "ใช่", "target_lang": "th", "ref_text": "hello", "slot": 0.3, "limit": 2.0,
        "max_speedup": 1.1, "max_slowdown": 1.05}


# ---------------------------------------------------------------- ความยาวที่ขอ
def test_short_line_gets_the_minimum():
    sec = tts.request_seconds(natural=0.2, slot=0.25, max_speedup=1.1, max_slowdown=1.05)
    assert sec >= settings.tts_min_sec


def test_normal_line_is_unchanged():
    # ยาวพอ: เท่า _fit เดิมทุกประการ
    args = (2.0, 2.2, 1.1, 1.05)
    assert tts.request_seconds(*args) == tts._fit(*args)


def test_retry_asks_for_more_and_stops_at_the_cap():
    a = [tts.request_seconds(0.2, 0.25, 1.1, 1.05, attempt=n, limit=1.2) for n in range(5)]
    assert a[1] > a[0] and a[2] > a[1]
    assert abs(a[1] / a[0] - settings.tts_retry_stretch) < 1e-6
    assert max(a) <= 1.2  # ไม่เกินช่องที่วางเสียงได้


def test_retry_never_below_first_ask_even_without_room():
    base = tts.request_seconds(0.2, 0.25, 1.1, 1.05)
    assert tts.request_seconds(0.2, 0.25, 1.1, 1.05, attempt=3, limit=0.1) == base


# ---------------------------------------------------------------- ตัวตรวจเงียบ
def test_audible_uses_rms_not_only_peak():
    assert gpu.is_audible(LOUD)
    assert not gpu.is_audible(QUIET)
    assert not gpu.is_audible(HUM)
    assert not gpu.is_audible(BLIP)  # peak ผ่านแต่แทบไม่มีเฟรมที่เป็นเสียง


def test_silence_stats_empty_and_nan():
    assert gpu.silence_stats(np.array([], dtype=np.float32))[2] == 0.0
    assert gpu.silence_stats(np.array([np.nan], dtype=np.float32))[2] == 0.0


# ---------------------------------------------------------------- บันไดใน speak_line
def _run(outputs, checks=None, line=None):
    calls = []

    def fake(ref, ref_text, text, speed, steps, lang, slot=None, max_speedup=1.1, max_slowdown=1.2,
             attempt=0, limit=None):
        calls.append({"slot": slot, "attempt": attempt, "limit": limit})
        return outputs[min(len(calls) - 1, len(outputs) - 1)]

    voice = gpu.speak_line(fake, Path("ref.wav"), dict(line or LINE), 16, 1.0, checks)
    return voice, calls


def test_each_silent_retry_changes_the_request():
    voice, calls = _run([QUIET, QUIET, LOUD])
    assert [c["attempt"] for c in calls] == [0, 1, 2]  # ขอเพิ่มขึ้นทีละขั้น
    assert [c["slot"] for c in calls] == [0.3, 0.3, None]  # รอบสุดท้ายไม่กำหนดความยาว
    assert all(c["limit"] == 2.0 for c in calls)
    assert gpu.is_audible(voice)


def test_normal_line_calls_once():
    _, calls = _run([LOUD])
    assert calls == [{"slot": 0.3, "attempt": 0, "limit": 2.0}]


def test_ladder_exhausted_is_flagged_for_the_user():
    checks: dict = {}
    voice, calls = _run([QUIET], checks)
    assert len(calls) == gpu.SILENT_RETRIES
    assert checks == {14: [0.0, ""]}


def test_ladder_is_logged(caplog):
    import logging
    with caplog.at_level(logging.INFO):
        _run([QUIET, LOUD])
    assert any("tts-ladder line=14" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- รวมประโยคข้างเคียง
def u(i, start, end, speaker="A"):
    return NS(id=i, start=start, end=end, speaker=speaker, duration=end - start, source="", target="x")


def test_merge_picks_nearest_same_speaker_neighbour():
    groups = [[u(1, 0, 1)], [u(2, 2.0, 2.2)], [u(3, 2.5, 3.5)]]
    assert _merge_candidate(groups, 1) == 2  # ห่างหลังแค่ 0.3 วินาที ใกล้กว่าหน้า 1.0 วินาที


def test_merge_ignores_other_speaker_far_gap_and_typed():
    groups = [[u(1, 0, 1, "B")], [u(2, 2.0, 2.2)], [u(3, 5.0, 6.0)]]
    assert _merge_candidate(groups, 1) is None  # หน้าคนละคน หลังห่าง 2.8 วินาที
    near = [[u(1, 0, 1)], [u(2, 1.2, 1.4)]]
    assert _merge_candidate(near, 1) == 0
    assert _merge_candidate(near, 1, blocked=frozenset({1})) is None  # ข้อความที่ผู้ใช้พิมพ์ไม่ถูกกลืน


def test_merge_respects_max_span():
    groups = [[u(1, 0, 11.8)], [u(2, 12.0, 12.2)]]
    assert _merge_candidate(groups, 1) is None


def test_merge_keeps_every_other_clip_under_its_own_group():
    groups = [[u(1, 0, 1)], [u(2, 2.0, 2.2)], [u(3, 2.5, 3.5)], [u(4, 6, 7)]]
    done = {0: "a", 1: "b", 2: "c", 3: "d"}
    plans = [NS(i=1), NS(i=3)]
    keep = plans[1]
    _apply_merge(groups, done, plans, 1, 2)
    assert [[x.id for x in g] for g in groups] == [[1], [2, 3], [4]]
    assert done == {0: "a", 2: "d"}  # เสียงของกลุ่ม 0 และ 4 อยู่ครบ ส่วนที่รวมรอพากย์ใหม่
    assert plans == [keep] and keep.i == 2
    assert groups[keep.i][0].id == 4


def test_exhausted_ladder_gets_the_should_listen_label():
    assert heard_label([[0.0, ""]]) == (True, SILENT_LABEL)
    assert heard_label([[0.9, "ok"], [0.0, ""]]) == (True, SILENT_LABEL)
    assert SILENT_LABEL  # synth_stats.unclear นับจาก u.heard ที่ไม่ว่าง


def test_normal_results_are_not_labelled_silent():
    assert heard_label([]) == (False, "")
    assert heard_label([[0.4, "พูดผิด"], [0.9, "ok"]]) == (False, "พูดผิด")
