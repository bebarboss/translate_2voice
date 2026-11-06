import numpy as np

from app.pipeline.common import Turn, Word
from app.pipeline.transcribe import _holes, _loud_bgm, _speech_spans, _windows, better_take, mark_unclear
from app.schemas import Utterance


def test_loud_bgm_only_inside_speech():
    sr = 1000
    vocals = np.full(10 * sr, 0.1, dtype=np.float32)
    bgm = np.full(10 * sr, 0.01, dtype=np.float32)
    bgm[2 * sr: 5 * sr] = 0.2  # เพลงดังกว่าเสียงพูด 2–5 วินาที
    bgm[7 * sr: 9 * sr] = 0.2  # เพลงดังแต่ไม่มีคนพูด
    spans = _speech_spans([Turn(1.0, 6.0, "a")])
    assert _loud_bgm(vocals, bgm, sr, spans) == [(2.0, 5.0)]


def test_holes_and_windows():
    spans = _speech_spans([Turn(0.0, 4.0, "a"), Turn(4.2, 10.0, "b")])
    assert spans == [[0.0, 10.0]]
    holes = _holes([Word(0.0, 1.0, "hi", 0), Word(6.0, 7.0, "yo", 1)], spans, 1.0)
    assert holes == [(1.0, 6.0), (7.0, 10.0)]
    assert _windows([(1.0, 2.0), (2.3, 3.0), (9.0, 30.0)], 0.5, 25.0) == [[1.0, 3.0], [9.0, 30.0]]


def test_better_take():
    assert better_take(10, -1.2, 10, -0.5)  # มั่นใจกว่าชัดเจน
    assert not better_take(10, -0.6, 3, -0.2)  # มั่นใจกว่าแต่คำหายเยอะ
    assert better_take(10, -0.7, 20, -0.75)  # คำครบกว่ามาก ความมั่นใจพอ ๆ กัน
    assert not better_take(10, -0.5, 20, -0.9)  # คำมากขึ้นแต่มั่นใจน้อยลงมาก (น่าจะเนื้อเพลง)
    assert better_take(0, float("-inf"), 8, -0.6)  # รอบแรกไม่มีคำ รอบสองมั่นใจพอ
    assert not better_take(0, float("-inf"), 8, -1.5)  # รอบแรกไม่มีคำ รอบสองเดามั่ว
    assert not better_take(5, -1.0, 0, float("-inf"))


def test_mark_unclear():
    utts = [Utterance(id=1, speaker="a", start=0.0, end=4.0, source="x"),
            Utterance(id=2, speaker="a", start=5.0, end=6.0, source="y"),
            Utterance(id=3, speaker="a", start=8.0, end=12.0, source="z")]
    assert mark_unclear(utts, [(3.8, 5.4)]) == 1
    assert [u.unclear for u in utts] == [False, True, False]  # ประโยคแรกทับแค่ 0.2 วินาที
