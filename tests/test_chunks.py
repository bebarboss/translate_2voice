"""plan_windows / merge_chunk_results / stitch_wavs"""
import numpy as np

from app.pipeline.chunks import (
    Window,
    merge_chunk_results,
    plan_windows,
    responsibility,
    stitch_wavs,
)
from app.schemas import Utterance


def test_plan_skips_short_clip():
    assert plan_windows(600, chunk_sec=480, overlap_sec=10, min_total_sec=720) == []


def test_plan_skips_single_window():
    # พอเปิดเกณฑ์แต่ยาวไม่เกินชิ้นเดียว → ไม่คุ้มขนาน
    assert plan_windows(450, chunk_sec=480, overlap_sec=10, min_total_sec=400) == []


def test_plan_two_windows_for_12min():
    wins = plan_windows(720, chunk_sec=480, overlap_sec=10, min_total_sec=720)
    assert len(wins) == 2
    assert wins[0].start == 0.0
    assert wins[0].end == 480.0
    # step = 470 → ชิ้น 2 เริ่มที่ 470
    assert wins[1].start == 470.0
    assert wins[1].end == 720.0


def test_plan_long_clip_many_windows():
    wins = plan_windows(3600, chunk_sec=480, overlap_sec=10, min_total_sec=720)
    assert len(wins) >= 7
    assert wins[0].start == 0.0
    assert abs(wins[-1].end - 3600) < 0.1
    # overlap ระหว่างชิ้นติดกัน
    assert wins[1].start < wins[0].end


def test_responsibility_splits_overlap():
    wins = [
        Window(0, 0.0, 480.0),
        Window(1, 470.0, 720.0),
    ]
    left0, right0 = responsibility(wins, 0)
    left1, right1 = responsibility(wins, 1)
    mid = (470.0 + 480.0) / 2
    assert right0 == mid
    assert left1 == mid
    assert left0 == float("-inf")
    assert right1 == float("inf")


def _part(utts, speakers):
    return {
        "turns": [{"start": u["start"], "end": u["end"], "speaker": u["speaker"]} for u in utts],
        "words": [{"start": u["start"], "end": u["end"], "text": "x", "segment": 0} for u in utts],
        "utterances": [
            Utterance(
                id=i, speaker=u["speaker"], start=u["start"], end=u["end"],
                source=u.get("source", f"s{i}"), target="",
            ).model_dump()
            for i, u in enumerate(utts, 1)
        ],
        "speakers": speakers,
        "detected_lang": "th",
        "features": {
            "lines": {
                str(i): {"start": u["start"], "end": u["end"], "quality": 3.0}
                for i, u in enumerate(utts, 1)
            },
            "speech": [],
        },
    }


def test_merge_drops_overlap_duplicates_and_remaps_speakers():
    wins = [
        Window(0, 0.0, 480.0),
        Window(1, 470.0, 720.0),
    ]
    # ชิ้น0 (absolute = relative): early + overlap mid=475 → ไปชิ้น1 (left inclusive)
    part0 = _part([
        {"speaker": "speaker_01", "start": 10.0, "end": 12.0, "source": "early"},
        {"speaker": "speaker_01", "start": 472.0, "end": 478.0, "source": "ovl-a"},
    ], ["speaker_01"])
    # ชิ้น1 relative: abs 472→2.0; คนเดียวกันป้าย speaker_01 + คนใหม่ speaker_02
    part1 = _part([
        {"speaker": "speaker_01", "start": 2.0, "end": 8.0, "source": "ovl-b"},
        {"speaker": "speaker_01", "start": 30.0, "end": 32.0, "source": "later-a"},
        {"speaker": "speaker_02", "start": 40.0, "end": 42.0, "source": "later-b"},
    ], ["speaker_01", "speaker_02"])

    merged = merge_chunk_results(wins, [part0, part1])
    sources = [u.source for u in merged["utterances"]]
    assert "early" in sources
    assert "later-a" in sources
    assert "later-b" in sources
    ovl = [s for s in sources if s.startswith("ovl")]
    assert ovl == ["ovl-b"], sources
    assert len(merged["speakers"]) >= 2
    assert len(merged["features"]["lines"]) == len(merged["utterances"])


def test_stitch_trims_overlap():
    sr = 100
    # ชิ้นละ 1 วินาที, overlap 0.2 → ใช้ 0.9 + 0.9 = 1.8 วินาที
    wins = [Window(0, 0.0, 1.0), Window(1, 0.8, 1.8)]
    a = np.ones((sr, 1), dtype=np.float32)
    b = np.full((sr, 1), 2.0, dtype=np.float32)
    out, out_sr = stitch_wavs([(wins[0], a, sr), (wins[1], b, sr)], overlap_sec=0.2)
    assert out_sr == sr
    # rel: ชิ้น0 ตัดท้าย 0.1s → 90 samples; ชิ้น1 ตัดหัว 0.1s → 90 samples
    assert len(out) == 180
    assert float(out[0]) == 1.0
    assert float(out[-1]) == 2.0
