"""ปุ่มประเมินคลิปในหน้าผู้ดูแล + ตัวสรุปรายสัปดาห์ของหน้าคุณภาพที่เคยล้มบน Postgres (updated_at เป็น datetime)"""
from datetime import datetime, timezone

from app import job_metrics, quality


def test_component_values_maps_every_dimension():
    m = {"speech_coverage": {"coverage": 0.9}, "dub_match": {"mean": 0.8}, "timing_fit": {"mean_ratio": 1.2},
         "length_vs_source": {"score": 0.7}, "translate_fidelity": {"score": None},
         "prosody_match": {"score": 0.6}, "lip_overflow": {}, "term_consistency": {"score": 1}, "speaker_confusion": {"score": 0.5}}
    got = job_metrics.component_values(m)
    assert set(got) == set(job_metrics.EVAL_COMPONENTS)
    assert got["speech_coverage"] == 0.9 and got["dub_match"] == 0.8
    assert got["timing_fit"] == 0.8  # 1 - |1.2 - 1|
    assert got["translate_fidelity"] is None and got["lip_overflow"] is None


def test_component_values_dub_ok_without_mean_counts_as_full():
    assert job_metrics.component_values({"dub_match": {"ok": True}})["dub_match"] == 1.0
    assert job_metrics.component_values({})["dub_match"] is None


def _row(ts):
    return {"updated_at": ts, "source_lang": "en", "target_lang": "th", "lines_ai": 10, "text_edited": 2, "speaker_changed": 0,
            "retimed": 0, "added": 0, "removed": 0, "edit_distance": 0.1, "synth_runs": 1, "translations": 1}


def test_summary_accepts_datetime_and_iso_strings(monkeypatch):
    for ts in (datetime(2026, 11, 16, 10, tzinfo=timezone.utc), "2026-11-16T10:00:00Z"):
        monkeypatch.setattr(quality.sdb, "select", lambda *a, _ts=ts, **k: [_row(_ts)])
        out = quality.summary(30)
        assert out["available"] and out["weeks"][0]["key"] == "2026-11-16"


# ---- ตัวประเมินต้องไม่ลงโทษประโยคที่พากย์รวม / ส่วนต่างคงที่ของเสียง ----
import numpy as np
import soundfile as sf

from app.schemas import Utterance


def _utt(i, start, end, speaker="speaker_01"):
    return Utterance(id=i, speaker=speaker, start=start, end=end, source="x", target="ก")


def _tone(sec, amp=0.3, sr=24000):
    t = np.arange(int(sec * sr)) / sr
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr


def _job(tmp_path, files):
    (tmp_path / "tts").mkdir()
    for uid, sec in files.items():
        wav, sr = _tone(sec)
        sf.write(tmp_path / "tts" / f"{uid:04d}.wav", wav, sr)
    return tmp_path


def test_grouped_lines_are_one_unit(tmp_path):
    # บรรทัด 13 กับ 14 พากย์รวมเป็นไฟล์เดียว (9.2 วินาทีเท่ากับสองช่องรวมกัน) บรรทัด 14 ไม่มีไฟล์
    d = _job(tmp_path, {13: 9.2, 15: 2.0})
    utts = [_utt(13, 0.0, 4.9), _utt(14, 5.0, 9.2), _utt(15, 12.0, 14.0)]
    units = job_metrics.tts_units(d, utts)
    assert [[m.id for m in x["members"]] for x in units] == [[13, 14], [15]]
    t = job_metrics.timing_fit(d, utts)
    assert t["missing"] == 0 and t["over"] == 0 and 0.95 < t["mean_ratio"] < 1.1
    lip = job_metrics.lip_overflow(d, utts)
    assert lip["overflow_lines"] == 0 and lip["score"] == 1.0


def test_unrelated_line_without_file_stays_missing(tmp_path):
    d = _job(tmp_path, {1: 2.0})
    utts = [_utt(1, 0.0, 2.0), _utt(2, 10.0, 12.0), _utt(3, 2.2, 3.0, speaker="speaker_02")]
    units = job_metrics.tts_units(d, utts)
    assert sum(1 for x in units if x["path"] is None) == 2  # คนละคน / ห่างเกิน 0.6 วินาที ไม่ต่อเข้ากัน
    assert job_metrics.timing_fit(d, utts)["missing"] == 2


def test_real_overflow_is_still_caught(tmp_path):
    d = _job(tmp_path, {1: 6.0, 2: 1.0})
    utts = [_utt(1, 0.0, 2.0), _utt(2, 3.0, 4.0)]
    lip = job_metrics.lip_overflow(d, utts)
    assert lip["overflow_lines"] == 1 and lip["worst_overflow_sec"] > 3


def test_relative_gaps_ignore_constant_offset_and_need_samples():
    # ส่วนต่างคงที่ +16 dB ทั้งงาน = ไม่มีส่วนต่าง
    assert job_metrics._relative_gaps([("all", 16.0), ("all", 16.2), ("all", 15.8)]) == [0.0, 0.2, 0.2] or \
        all(g < 0.3 for g in job_metrics._relative_gaps([("all", 16.0), ("all", 16.2), ("all", 15.8)]))
    assert job_metrics._relative_gaps([("a", 5.0), ("a", 5.1)]) == []  # น้อยกว่า 3 ตัวอย่างไม่นับ
    spread = job_metrics._relative_gaps([("a", 0.0), ("a", 12.0), ("a", 24.0)])
    assert max(spread) == 12.0  # ผันแปรจริงยังถูกจับ
