import numpy as np

from app.pipeline import turns, voices
from app.pipeline.common import Word
from app.pipeline.voices import Voice
from app.schemas import Utterance


def _unit(seed):
    v = np.random.default_rng(seed).normal(size=16).astype(np.float32)
    return v / np.linalg.norm(v)


def _line():
    words = []
    t = 0.0
    for w in "I know if I was back in Denmark Issues But they do not exist here".split():
        words.append(Word(start=t, end=t + 0.5, text=w, segment=0))
        t += 0.5
    u = Utterance(id=1, speaker="speaker_01", start=0.0, end=t, source=" ".join(w.text for w in words), target="")
    return u, words


def test_interjections_found_between_same_speaker():
    a, b = _unit(1), _unit(1)
    pv = {0: Voice(a, 12.0), 1: Voice(None, float("nan")), 2: Voice(b, 12.0)}
    assert turns.interjections(pv, 3) == {1}


def test_no_interjection_when_neighbours_differ_or_piece_measurable():
    pv = {0: Voice(_unit(1), 12.0), 1: Voice(None, float("nan")), 2: Voice(_unit(99), 18.0)}
    assert turns.interjections(pv, 3) == set()
    pv = {0: Voice(_unit(1), 12.0), 1: Voice(_unit(1), 12.0), 2: Voice(_unit(1), 12.0)}
    assert turns.interjections(pv, 3) == set()


def test_short_interjection_is_cut_and_given_the_other_speaker(monkeypatch):
    u, words = _line()
    other = Utterance(id=2, speaker="speaker_02", start=20.0, end=23.0, source="Yes", target="")
    proposals = {1: ["I know if I was back in Denmark", "Issues", "But they do not exist here"]}
    same = _unit(1)
    monkeypatch.setattr(voices, "profile", lambda utts, wav, sr, min_sec=None: {
        k: (Voice(None, float("nan")) if (utts[k].end - utts[k].start) < 1.2 else Voice(same, 12.0)) for k in range(len(utts))})
    # ตอนจัดกลุ่มใหม่ทุกท่อนวัดได้เฉพาะที่ยาวพอ ท่อนอื่นของ speaker_02 ใช้ลายเสียงต่างกัน
    out, cuts = turns.resplit_core([u, other], words, proposals, np.zeros(16000 * 30, dtype=np.float32), 16000, 2)
    assert cuts == 2
    assert [x.source for x in out[:3]] == proposals[1]
    assert out[1].speaker != out[0].speaker == out[2].speaker
