"""ซ่อมท่อนที่วรรณยุกต์ถูกยืดเวลาผิดปกติ + บทขาดกลางคำ"""
from app.pipeline.common import Turn, Word
from app.pipeline.repair import clamp_words, merge_broken_thai, repair_transcript
from app.schemas import Utterance


def test_clamp_stretched_tone_mark():
    words = [
        Word(5.22, 5.34, "เด", 2),
        Word(5.34, 5.36, "ี", 2),
        Word(5.36, 21.26, "๋", 2),  # ยืดผิด ~16 วิ
        Word(27.82, 27.84, "ย", 2),
        Word(27.84, 27.86, "ว", 2),
        Word(27.86, 27.90, "เรา", 2),
        Word(27.90, 27.94, "จะทำให", 2),
        Word(27.94, 30.90, "้", 2),
    ]
    out = clamp_words(words)
    assert out[2].end - out[2].start < 0.5
    assert out[2].end < 6.0
    assert out[7].end - out[7].start < 0.5


def test_merge_orphan_fragment():
    utts = [
        Utterance(id=1, speaker="speaker_01", start=5.2, end=5.5, source="เดี๋"),
        Utterance(id=2, speaker="speaker_01", start=27.8, end=28.5, source="ยวเราจะทำให้"),
    ]
    out = merge_broken_thai(utts)
    assert len(out) == 1
    assert out[0].source == "เดี๋ยวเราจะทำให้"
    assert out[0].start == 27.8


def test_merge_keeps_complete_line_ending_with_tone():
    """คำไทยจบด้วยวรรณยุกต์ปกติต้องไม่ถูกยุบเข้าท่อนถัดไป"""
    utts = [
        Utterance(id=1, speaker="speaker_01", start=0.0, end=2.0, source="น้องผมหลับอยู่"),
        Utterance(id=2, speaker="speaker_01", start=3.0, end=4.0, source="ขับรถอันตราย"),
    ]
    out = merge_broken_thai(utts)
    assert len(out) == 2
    assert out[0].source == "น้องผมหลับอยู่"


def test_tighten_bloated_snaps_to_dense_words():
    from app.pipeline.repair import tighten_bloated
    words = [
        Word(3.0, 3.2, "ถ้า", 1), Word(3.2, 4.5, "ง่วงอันตราย", 1),
        Word(5.0, 5.2, "เด", 1), Word(5.2, 20.0, "๋", 1),  # ยืดพัง
    ]
    utts = [Utterance(id=1, speaker="speaker_01", start=3.0, end=20.0, source="ถ้าง่วงอันตรายเดี๋")]
    out = tighten_bloated(utts, words, "th")
    assert len(out) == 1
    assert out[0].end - out[0].start < 5
    assert "ง่วง" in out[0].source


def test_suspects_finds_bloated():
    from app.pipeline.repair import suspects
    utts = [
        Utterance(id=1, speaker="a", start=0, end=1.5, source="สวัสดีครับ"),
        Utterance(id=2, speaker="a", start=2, end=20, source="สั้น"),
    ]
    bad = suspects(utts, "th")
    assert [u.id for u in bad] == [2]


def test_repair_transcript_rebuilds_bloated_line():
    words = [
        Word(0.0, 0.2, "เริ่", 0), Word(0.2, 0.5, "มงาน", 0), Word(0.5, 1.0, "แล้ว", 0),
        Word(2.98, 3.2, "ถ้า", 1), Word(3.2, 4.9, "ง่วงอันตราย", 1),
        Word(5.22, 5.34, "เด", 2), Word(5.34, 5.36, "ี", 2), Word(5.36, 21.26, "๋", 2),
        Word(27.82, 27.86, "ยว", 2), Word(27.86, 28.5, "เราจะทำให้", 2),
    ]
    turns = [Turn(0, 30, "speaker_01")]
    broken = [
        Utterance(id=1, speaker="speaker_01", start=0.0, end=1.0, source="เริ่มงานแล้ว"),
        Utterance(id=2, speaker="speaker_01", start=2.98, end=21.26, source="ถ้าง่วงอันตรายเดี๋"),
        Utterance(id=3, speaker="speaker_01", start=27.82, end=30.9, source="ยวเราจะทำให้"),
    ]
    fixed, clamped, n = repair_transcript(broken, words, turns, "th")
    assert n >= 1
    sources = [u.source for u in fixed]
    assert any("เดี๋ยว" in s for s in sources), sources
    assert any("ง่วง" in s or "อันตราย" in s for s in sources), sources
    assert all(u.end - u.start < 10 for u in fixed), sources
