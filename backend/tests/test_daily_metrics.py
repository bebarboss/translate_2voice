"""daily_metrics: ขอบเขตวันกรุงเทพ + flatten คะแนน"""
from datetime import date, datetime, timezone

from app.daily_metrics import BKK, _day_bounds, _flatten_row, jobs_done_on
from app.schemas import Job, JobStatus


def test_day_bounds_bangkok():
    start, end = _day_bounds(date(2026, 11, 9))
    # 00:00 BKK = 17:00 UTC วันก่อน
    assert start == datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc)


def test_flatten_row_reads_nested_scores():
    row = _flatten_row(date(2026, 11, 9), {
        "job_id": "abc",
        "n_lines": 3,
        "speakers": ["speaker_01", "speaker_02"],
        "overall": 0.9,
        "speech_coverage": {"coverage": 0.95},
        "dub_match": {"mean": 0.8},
        "timing_fit": {"mean_ratio": 1.0},
        "length_vs_source": {"score": 0.88},
        "translate_fidelity": {"score": 0.85},
        "prosody_match": {"score": 0.7},
        "lip_overflow": {"score": 1.0},
        "term_consistency": {"score": 1.0},
        "speaker_confusion": {"score": 1.0},
        "needs_asr_heal": False,
    })
    assert row["run_date"] == "2026-11-09"
    assert row["speakers"] == ["speaker_01", "speaker_02"]
    assert row["speech_coverage"] == 0.95
    assert row["dub_match"] == 0.8
    assert row["overall"] == 0.9


class _Store:
    def __init__(self, jobs):
        self._jobs = jobs

    def all(self):
        return list(self._jobs)


def test_jobs_done_on_filters_by_bangkok_day():
    day = date(2026, 11, 9)
    # กลางวัน 9 พ.ย. BKK = 04:00 UTC
    in_day = Job(id="in", filename="a.mp4", status=JobStatus.done,
                 updated_at=datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc))
    # ก่อนเที่ยงคืน BKK เล็กน้อยยังอยู่ในวัน 8
    out_day = Job(id="out", filename="b.mp4", status=JobStatus.done,
                  updated_at=datetime(2026, 11, 8, 16, 59, tzinfo=timezone.utc))
    running = Job(id="run", filename="c.mp4", status=JobStatus.running,
                  updated_at=datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc))
    got = jobs_done_on(day, _Store([in_day, out_day, running]))
    assert [j.id for j in got] == ["in"]
    assert BKK.utcoffset(None).total_seconds() == 7 * 3600
