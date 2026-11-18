"""Whisper ถอดคำท้ายประโยคซ้ำเป็นท่อนของตัวเอง (งาน 5b98fa303097: "down," → "down." และ "again." สองครั้ง)"""
from app.pipeline import hallucination as h
from app.pipeline.common import Word
from app.schemas import Utterance


def W(text, a, b, seg):
    return Word(a, b, text, seg)


# เหมือนงานจริง: คำท้ายประโยคถูกถอดซ้ำเป็นท่อนใหม่ที่เริ่มชิดจุดจบพอดี
REAL = [W("upside", 4.02, 4.30, 0), W("down,", 4.30, 4.58, 0), W("down.", 4.58, 5.00, 2),
        W("these", 6.96, 7.60, 1), W("again.", 12.08, 12.26, 1), W("again.", 12.26, 12.52, 3)]


def test_echoed_last_words_are_dropped():
    out = h.drop_echo_words(REAL)
    assert [w.text for w in out] == ["upside", "down,", "these", "again."]
    assert out[1].end == 4.58  # คำจริงไม่ถูกแก้


def test_real_repetition_is_kept():
    # คนพูดซ้ำจริง: มีช่องว่าง หรืออยู่ท่อนเดียวกัน หรือท่อนใหม่มีหลายคำ
    gap = [W("no", 1.0, 1.3, 0), W("no", 1.6, 1.9, 1)]
    same_seg = [W("no", 1.0, 1.3, 0), W("no", 1.3, 1.6, 0)]
    multi = [W("no", 1.0, 1.3, 0), W("no", 1.3, 1.6, 1), W("way", 1.6, 1.9, 1)]
    assert len(h.drop_echo_words(gap)) == 2
    assert len(h.drop_echo_words(same_seg)) == 2
    assert len(h.drop_echo_words(multi)) == 3


def test_different_word_is_kept():
    words = [W("down,", 4.3, 4.58, 0), W("up.", 4.58, 5.0, 1)]
    assert len(h.drop_echo_words(words)) == 2


def U(i, a, b, src, spk="speaker_01", tgt="x"):
    return Utterance(id=i, speaker=spk, start=a, end=b, source=src, target=tgt)


def test_echo_line_is_dropped_and_previous_gets_its_time():
    utts = [U(1, 0.0, 4.58, "If the first woman God ever made was strong enough to turn this world upside down,"),
            U(2, 4.58, 5.2, "down.", tgt="กลับหัว"),
            U(3, 6.96, 12.26, "these women together ought to be able to turn it right again."),
            U(4, 12.26, 12.52, "again.", tgt="กลับขึ้นมาใหม่")]
    out = h.clean(utts)
    assert [u.id for u in out] == [1, 3]
    assert out[0].end == 5.2 and "กลับหัว" not in out[0].target  # ท่อนก่อนหน้าได้เวลาของเสียงสะท้อน


def test_repeat_with_a_gap_or_other_speaker_or_typed_is_kept():
    base = U(1, 0.0, 2.0, "I said stop.")
    for second in (U(2, 2.4, 3.2, "stop."),  # ห่างเกินเกณฑ์: พูดซ้ำจริง
                   U(2, 2.0, 2.8, "stop.", spk="speaker_02"),  # คนละคน
                   U(2, 2.0, 2.4, "", tgt="ไม่")):  # กล่องที่ผู้ใช้พิมพ์เอง
        out = h.clean([base.model_copy(), second])
        assert len(out) == 2, second
