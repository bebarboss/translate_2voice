from app.quality import compare
from app.schemas import Utterance


def U(i, target, speaker="speaker_01", start=0.0, end=1.0, source="hi"):
    return Utterance(id=i, start=start, end=end, speaker=speaker, source=source, target=target)


def test_compare_counts_each_kind():
    ai = {1: {"source": "a", "target": "สวัสดี / ครับ", "speaker": "speaker_01", "start": 0.0, "end": 1.0},
          2: {"source": "b", "target": "ไปกัน", "speaker": "speaker_01", "start": 1.0, "end": 2.0},
          3: {"source": "c", "target": "ลาก่อน", "speaker": "speaker_02", "start": 2.0, "end": 3.0}}
    final = [U(1, "สวัสดี ครับ"),  # เอา / ออกอย่างเดียว ไม่นับว่าแก้
             U(2, "ไปกันเถอะ", speaker="speaker_02", start=1.2, end=2.0),
             U(4, "ใหม่", start=3.0, end=4.0)]
    stats, lines = compare(ai, final)
    assert stats["lines_ai"] == 3 and stats["lines_final"] == 3
    assert (stats["text_edited"], stats["speaker_changed"], stats["retimed"]) == (1, 1, 1)
    assert (stats["added"], stats["removed"]) == (1, 1)
    assert [x["line_id"] for x in lines] == [2] and lines[0]["kinds"] == "text,speaker,time"
    assert 0 < stats["edit_distance"] < 0.5


def test_match_score():
    from app.pipeline.transcribe import match_score
    assert match_score("เดี๋ยวให้คนติดต่อไป / เข้าใจไหม", "เดี๋ยวให้คนติดต่อไป เข้าใจไหม") == 1.0
    assert match_score("ค่ะ", "คะ") == 1.0  # บทสั้นมาก (ไม่ถึง 4 ตัว) ถือว่าผ่าน
    assert match_score("ครับ", "คับ") > 0.6
    assert match_score("ฉันต้องไปถ่ายคลิปยูทูบ", "") == 0.0
    assert match_score("ฉันต้องไปถ่ายคลิปยูทูบ", "ฉันต้องไปถ่ายคลิปยูทูป") > 0.9
