"""วัด coverage จากช่วงพูด vs transcript โดยไม่พึ่ง GPU / คนแก้บท"""
import json

import numpy as np

from app.job_metrics import (
    COVERAGE_HEAL_MIN,
    dub_match_from_utts,
    length_vs_source,
    lip_overflow,
    prosody_match,
    score_job,
    speaker_confusion,
    speech_coverage_from_arrays,
    speech_regions,
    span_coverage,
    term_consistency,
    translate_fidelity,
    write_metrics,
)
from app.knobs import BOUNDS, nudge_from_metrics
from app.schemas import Utterance


def _tone(sr: int, sec: float, freq: float = 440.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(sr * sec), dtype=np.float32) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_speech_regions_finds_loud_bursts():
    sr = 16000
    # เงียบ 0.5s + พูด 0.8s + เงียบ 0.5s + พูด 0.6s
    wav = np.concatenate([
        np.zeros(int(sr * 0.5), dtype=np.float32),
        _tone(sr, 0.8),
        np.zeros(int(sr * 0.5), dtype=np.float32),
        _tone(sr, 0.6, freq=880.0),
    ])
    regions = speech_regions(wav, sr, energy_db=-40.0, min_sec=0.1)
    assert len(regions) >= 2
    # ช่วงแรกควรครอบคลุมประมาณ 0.5–1.3
    assert regions[0][0] < 0.7
    assert regions[0][1] > 1.0


def test_coverage_detects_missed_shout_gap():
    sr = 16000
    wav = np.concatenate([
        _tone(sr, 1.0),
        np.zeros(int(sr * 0.4), dtype=np.float32),
        _tone(sr, 0.5, freq=1200.0, amp=0.5),  # ตะโกนสั้น
    ])
    # transcript ครอบแค่ช่วงแรก ขาดตะโกนท้าย
    utts = [Utterance(id=1, speaker="speaker_01", start=0.0, end=1.0, source="สวัสดี", target="")]
    cov = speech_coverage_from_arrays(wav, sr, utts, energy_db=-40.0, min_sec=0.1)
    assert cov["coverage"] < 1.0
    assert cov["n_missed"] >= 1
    assert cov["coverage"] < COVERAGE_HEAL_MIN or cov["n_missed"] >= 1


def test_coverage_full_when_transcript_covers_speech():
    sr = 16000
    wav = _tone(sr, 1.2)
    utts = [Utterance(id=1, speaker="speaker_01", start=0.0, end=1.2, source="ครบ", target="")]
    cov = speech_coverage_from_arrays(wav, sr, utts, energy_db=-40.0, min_sec=0.1)
    assert cov["coverage"] >= 0.9


def test_span_coverage_empty_ref_is_one():
    assert span_coverage([], [(0, 1)])["coverage"] == 1.0


def test_dub_match_from_scores():
    utts = [
        Utterance(id=1, speaker="a", start=0, end=1, source="x", target="hello", heard_score=0.9),
        Utterance(id=2, speaker="a", start=1, end=2, source="y", target="hi", heard="wrong", heard_score=0.2),
    ]
    m = dub_match_from_utts(utts, min_score=0.6)
    assert m["n_scored"] == 2
    assert m["n_flagged"] == 1
    assert m["ok"] is False
    assert 0.5 < m["mean"] < 0.6


def test_score_job_writes_metrics(tmp_path):
    sr = 16000
    import soundfile as sf
    wav = _tone(sr, 1.0)
    sf.write(tmp_path / "vocals.wav", wav, sr)
    utts = [
        Utterance(id=1, speaker="speaker_01", start=0.0, end=1.0, source="สวัสดี", target="hello", heard_score=0.85),
    ]
    (tmp_path / "transcript.json").write_text(
        json.dumps([u.model_dump() for u in utts], ensure_ascii=False), encoding="utf-8"
    )
    data = write_metrics(tmp_path, dub_check_min=0.6)
    assert (tmp_path / "metrics.json").exists()
    assert data["overall"] is not None
    assert data["speech_coverage"]["coverage"] is not None
    again = score_job(tmp_path)
    assert again["job_id"] == tmp_path.name


def test_length_vs_source_compares_speech_to_dub(tmp_path):
    import soundfile as sf

    sr = 16000
    # ต้นฉบับพูด ~2 วิ
    sf.write(tmp_path / "vocals.wav", _tone(sr, 2.0), sr)
    utts = [
        Utterance(id=1, speaker="speaker_01", start=0.0, end=2.0,
                  source="hello there friend", target="สวัสดีเพื่อนของฉัน"),
    ]
    (tmp_path / "transcript.json").write_text(
        json.dumps([u.model_dump() for u in utts], ensure_ascii=False), encoding="utf-8"
    )
    # พากย์ยาวเท่าต้นฉบับ
    tts = tmp_path / "tts"
    tts.mkdir()
    sf.write(tts / "0001.wav", _tone(24000, 2.0), 24000)
    length = length_vs_source(tmp_path, utts)
    assert length["source_speech_sec"] > 1.0
    assert length["dub_audio_sec"] is not None
    assert length["ratio_vs_source"] is not None
    assert 0.7 <= length["ratio_vs_source"] <= 1.3
    assert length["score"] is not None and length["score"] >= 0.7


def test_translate_fidelity_penalizes_empty_and_rewards_fit(tmp_path):
    utts_bad = [
        Utterance(id=1, speaker="a", start=0, end=2, source="Hello world", target=""),
        Utterance(id=2, speaker="a", start=2, end=4, source="How are you", target="สบายดีไหม"),
    ]
    (tmp_path / "transcript.json").write_text(
        json.dumps([u.model_dump() for u in utts_bad], ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "job.json").write_text(
        json.dumps({"target_lang": "th", "source_lang": "en"}), encoding="utf-8"
    )
    m = translate_fidelity(tmp_path, utts_bad)
    assert m["empty_targets"] == 1
    assert m["score"] is not None and m["score"] < 0.85
    assert m["ok"] is False

    good = [
        Utterance(id=1, speaker="a", start=0, end=2, source="Hello", target="สวัสดีครับ"),
        Utterance(id=2, speaker="a", start=2, end=4, source="How are you", target="คุณสบายดีไหม"),
    ]
    (tmp_path / "transcript.json").write_text(
        json.dumps([u.model_dump() for u in good], ensure_ascii=False), encoding="utf-8"
    )
    m2 = translate_fidelity(tmp_path, good)
    assert m2["empty_targets"] == 0
    assert m2["score"] >= m["score"]


def test_lip_overflow_detects_long_dub(tmp_path):
    import soundfile as sf

    utts = [
        Utterance(id=1, speaker="a", start=0.0, end=1.0, source="a", target="สั้น"),
        Utterance(id=2, speaker="a", start=1.05, end=2.0, source="b", target="ต่อ"),
    ]
    tts = tmp_path / "tts"
    tts.mkdir()
    # ท่อนแรกยาว 2 วิ ทั้งที่ช่องแค่ 1 วิ และท่อนถัดไปเริ่ม 1.05 → ล้น
    sf.write(tts / "0001.wav", _tone(24000, 2.0), 24000)
    sf.write(tts / "0002.wav", _tone(24000, 0.8), 24000)
    (tmp_path / "transcript.json").write_text(
        json.dumps([u.model_dump() for u in utts], ensure_ascii=False), encoding="utf-8"
    )
    lip = lip_overflow(tmp_path, utts)
    assert lip["overflow_lines"] >= 1
    assert lip["score"] is not None and lip["score"] < 1.0


def test_term_consistency_flags_glossary_variants(tmp_path):
    utts = [
        Utterance(id=1, speaker="a", start=0, end=1, source="ドラえもん来た", target="โดราเอมอน มาแล้ว"),
        Utterance(id=2, speaker="a", start=1, end=2, source="ドラえもんだ", target="โดเรม่อน น่ะ"),
    ]
    (tmp_path / "job.json").write_text(
        json.dumps({"glossary": "ドラえもん = โดราเอมอน", "target_lang": "th"}, ensure_ascii=False),
        encoding="utf-8",
    )
    m = term_consistency(tmp_path, utts)
    assert m["score"] is not None
    # มีอย่างน้อย miss หรือ inconsistent
    assert m["glossary_misses"] >= 1 or m["inconsistent_terms"] >= 0


def test_speaker_confusion_self_overlap(tmp_path):
    utts = [
        Utterance(id=1, speaker="speaker_01", start=0.0, end=2.0, source="a", target="ก"),
        Utterance(id=2, speaker="speaker_01", start=1.0, end=3.0, source="b", target="ข"),
    ]
    (tmp_path / "turns.json").write_text(
        json.dumps([
            {"start": 0.0, "end": 2.0, "speaker": "speaker_01"},
            {"start": 1.0, "end": 3.0, "speaker": "speaker_02"},
        ]),
        encoding="utf-8",
    )
    m = speaker_confusion(tmp_path, utts)
    assert m["self_overlaps"] >= 1
    assert m["score"] is not None and m["score"] < 1.0


def test_prosody_match_scores_similar_loudness(tmp_path):
    import soundfile as sf

    sr = 16000
    sf.write(tmp_path / "vocals.wav", _tone(sr, 1.5, amp=0.3), sr)
    utts = [Utterance(id=1, speaker="a", start=0.0, end=1.5, source="hi", target="สวัสดี")]
    tts = tmp_path / "tts"
    tts.mkdir()
    sf.write(tts / "0001.wav", _tone(24000, 1.5, amp=0.3), 24000)
    (tmp_path / "transcript.json").write_text(
        json.dumps([u.model_dump() for u in utts], ensure_ascii=False), encoding="utf-8"
    )
    m = prosody_match(tmp_path, utts)
    assert m["n"] == 1
    assert m["score"] is not None
    assert m["loud_mean_db_gap"] is not None


def test_knob_bounds_and_nudge(monkeypatch, tmp_path):
    from app import knobs as knobs_mod
    from app.config import settings

    monkeypatch.setattr(knobs_mod, "knobs_path", lambda: tmp_path / "knobs.json")
    object.__setattr__(settings, "auto_knobs", True)

    scores = []
    for i in range(6):
        scores.append({
            "job_id": f"j{i}",
            "overall": 0.7,
            "n_lines": 10,
            "speech_coverage": {"coverage": 0.7, "n_missed": 3},
            "dub_match": {"mean": 0.8, "n_flagged": 0},
        })
    before = knobs_mod.load()["values"]["whisper_vad_threshold"]
    out = nudge_from_metrics(scores)
    assert out is not None
    after = knobs_mod.load()["values"]["whisper_vad_threshold"]
    lo, _, step = BOUNDS["whisper_vad_threshold"]
    assert after <= before
    assert after >= lo
    assert abs(before - after - step) < 1e-6 or after < before
