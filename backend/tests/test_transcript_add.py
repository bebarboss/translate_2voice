"""เพิ่มท่อนว่างบนไทม์ไลน์ (เสียงถอดหลุด)"""
import pytest

from app.schemas import Utterance
from app.transcript_edit import add_blank


def line(i, speaker="a", start=0.0, end=1.0, source="", target=""):
    return Utterance(id=i, speaker=speaker, start=start, end=end, source=source, target=target)


def test_add_blank_in_gap():
    utts = [line(1, start=0, end=1), line(2, start=4, end=5)]
    new = add_blank(utts, speaker="a", start=1.5, end=3.0, target="สวัสดี")
    assert new.id == 3 and new.start == 1.5 and new.end == 3.0 and new.target == "สวัสดี"


def test_add_blank_rejects_overlap_same_speaker():
    utts = [line(1, start=0, end=2)]
    with pytest.raises(ValueError, match="ทับ"):
        add_blank(utts, speaker="a", start=1.0, end=2.5)


def test_add_blank_allows_other_speaker_overlap():
    utts = [line(1, speaker="a", start=0, end=2)]
    new = add_blank(utts, speaker="b", start=0.5, end=1.5, source="hi")
    assert new.speaker == "b" and new.source == "hi"


def test_add_blank_too_short():
    with pytest.raises(ValueError, match="0.2"):
        add_blank([], speaker="a", start=1.0, end=1.1)


def test_add_blank_clamps_to_clip_duration():
    new = add_blank([], speaker="a", start=9.0, end=12.0, clip_duration=10.0)
    assert new.end == 10.0
