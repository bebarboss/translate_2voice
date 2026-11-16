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
