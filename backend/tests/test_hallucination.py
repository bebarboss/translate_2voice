"""กรอง hallucination / SFX / สระยืด และคะแนนเสียงพากย์ทักทายตายตัว"""
from app.pipeline.hallucination import clean, dead_heard_score, is_noise_line, scrub_source
from app.pipeline.transcribe import match_score
from app.schemas import Utterance


def _u(i, src, start, end, speaker="speaker_01", target=""):
    return Utterance(id=i, speaker=speaker, start=start, end=end, source=src, target=target)


def test_scrub_thanks_and_elongation():
    s = scrub_source("ご視聴ありがとうございましたうううううう")
    assert "視聴" not in s and "ありがとう" not in s
    assert "ううう" not in s


def test_drop_ending_and_sfx():
    utts = [
        _u(1, "マジックカード融合", 0.0, 4.0, target="ใช้การ์ด"),
        _u(2, "ンディング", 4.0, 4.3),
        _u(3, "ちちゅゅーー", 4.5, 4.9),
        _u(4, "視聴ありがとうございましたうううう", 5.0, 8.0, target="ขอบคุณที่รับชมนะ"),
        _u(5, "ネオスナイトは攻撃できる", 8.0, 12.0),
    ]
    out = clean(utts)
    sources = [u.source for u in out]
    assert all("ディング" not in s for s in sources)
    assert all("ちゅ" not in s for s in sources)
    assert all("視聴" not in s and "ありがとう" not in s for s in sources)
    assert any("ネオス" in s or "マジック" in s for s in sources)


def test_drop_short_kana_name():
    utts = [
        _u(1, "お前の力を借りるぜ", 0.0, 2.0),
        _u(2, "ンユセ", 2.0, 3.2),
    ]
    out = clean(utts)
    assert len(out) == 1
    assert "お前" in out[0].source


def test_is_noise_short():
    assert is_noise_line("ンディング", 0.28)
    assert is_noise_line("ンユセ", 1.22)
    assert is_noise_line("あ", 0.2)
    assert not is_noise_line("マジックカード融合フィールド", 4.0)


def test_dead_heard_forces_zero():
    assert dead_heard_score("นี่คือฮีโร่ใหม่", "สวัสดีครับ ทุกคน") == 0.0
    assert match_score("นี่คือฮีโร่ใหม่ของฉัน", "สวัสดีครับ ทุกคน") == 0.0
    assert dead_heard_score("สวัสดีครับ ทุกคน", "สวัสดีครับ ทุกคน") is None
