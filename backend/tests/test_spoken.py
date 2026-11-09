"""spoken / speak_latin / pronounce: ตัวย่อต้องกลายเป็นคำอ่านก่อนพากย์"""
from app.pipeline import translate as tr
from app.pipeline.translate import (
    apply_latin_readings,
    find_latin_tokens,
    pronounce_thai,
    pronounce_targets,
    speak_latin,
    spoken,
)
from app.schemas import Utterance


def test_gpt_not_left_as_latin():
    assert "GPT" not in speak_latin("ใช้ GPT-6 อัสตรา")
    assert "จีพีที6" in speak_latin("ใช้ GPT-6 อัสตรา")
    assert speak_latin("คุยกับ ChatGPT สักสัปดาห์") == "คุยกับ แชทจีพีที สักสัปดาห์"
    assert speak_latin("โมเดล GPT ใหม่") == "โมเดล จีพีที ใหม่"


def test_spoken_runs_latin():
    out = spoken("ตั้งค่าดอท แล้วลองคุยกับ ChatGPT")
    assert "ChatGPT" not in out and "GPT" not in out
    assert "แชทจีพีที" in out


def test_ai_api_order():
    assert speak_latin("OpenAI API") == "โอเพนเอไอ เอพีไอ"
    assert speak_latin("ใช้ AI ช่วย") == "ใช้ เอไอ ช่วย"


def test_find_latin_after_dict():
    # พจนานุกรมกิน GPT แล้ว — ไม่เหลือโทเคน
    assert find_latin_tokens(spoken("ใช้ GPT ช่วย")) == []
    # ชื่อแปลกยังเหลือ
    left = find_latin_tokens(spoken("ใช้ OpenClaw กับ Hermes"))
    assert "OpenClaw" in left and "Hermes" in left


def test_apply_readings_longest_first():
    text = "GPT-6 และ GPT"
    out = apply_latin_readings(text, {"GPT-6": "จีพีทีหก", "GPT": "จีพีที"})
    assert out == "จีพีทีหก และ จีพีที"


def test_pronounce_uses_cache_without_ai(monkeypatch):
    object.__setattr__(tr.settings, "ai_speak_latin", True)
    object.__setattr__(tr.settings, "mock_pipeline", False)
    tr._latin_cache = {"openclaw": "โอเพนคลอว์", "hermes": "เฮอร์เมส"}
    monkeypatch.setattr(tr, "_save_latin_cache", lambda: None)
    out = pronounce_thai("เชื่อม OpenClaw กับ Hermes", use_ai=False)
    assert "OpenClaw" not in out and "Hermes" not in out
    assert "โอเพนคลอว์" in out and "เฮอร์เมส" in out


def test_pronounce_targets_batch(monkeypatch):
    object.__setattr__(tr.settings, "ai_speak_latin", True)
    object.__setattr__(tr.settings, "typhoon_api_key", "x")
    object.__setattr__(tr.settings, "mock_pipeline", False)
    tr._latin_cache = {}
    monkeypatch.setattr(tr, "_save_latin_cache", lambda: None)

    def fake_ai(terms):
        return {t: {"OpenClaw": "โอเพนคลอว์", "Hermes": "เฮอร์เมส"}.get(t, f"อ่าน{t}") for t in terms}

    monkeypatch.setattr(tr, "_ai_latin_readings", fake_ai)
    utts = [
        Utterance(id=1, speaker="speaker_01", start=0, end=1, source="x", target="ใช้ OpenClaw เลย"),
        Utterance(id=2, speaker="speaker_01", start=1, end=2, source="y", target="และ Hermes ด้วย"),
    ]
    n = pronounce_targets(utts, use_ai=True)
    assert n == 2
    assert "OpenClaw" not in utts[0].target
    assert "Hermes" not in utts[1].target
    assert "โอเพนคลอว์" in utts[0].target and "เฮอร์เมส" in utts[1].target
