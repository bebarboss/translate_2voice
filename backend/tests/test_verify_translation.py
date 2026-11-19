"""ผู้ตรวจคำแปล (translate.verify_translation): แปลใหม่เฉพาะบรรทัดที่ผิด ไม่เกินรอบ ไม่ทำลายบรรทัดอื่น"""
import json
from dataclasses import replace

import pytest

from app.config import settings
from app.pipeline import translate as T
from app.schemas import Utterance


def _utts():
    srcs = ["How are you processing that?", "I let it consume me.", "Thank you."]
    return [Utterance(id=i + 1, speaker="speaker_01", start=i * 3.0, end=i * 3.0 + 2.5, source=s,
                      target=t) for i, (s, t) in enumerate(zip(srcs, ["ฉันปล่อยให้มันครอบงำฉัน", "ฉันปล่อยให้มันครอบงำฉัน", "ขอบคุณ"]))]


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(T, "settings", replace(settings, translate_verify=True, translate_verify_fix=True, mock_pipeline=False))


def test_flagged_line_is_retranslated_and_others_untouched(monkeypatch):
    us = _utts()
    calls = {"n": 0}

    def fake_chat(system, user, temperature=None, max_tokens=4096):
        if system == T.ACCURACY_PROMPT_TH:
            calls["n"] += 1
            bad = [{"id": 1, "note": "แปลเป็นคำตอบของบรรทัดถัดไป"}] if calls["n"] == 1 else []
            return json.dumps({"bad": bad})
        data = json.loads(user[user.index("{", user.index("\n\n")):])
        return json.dumps({"sentences": [{"id": s["id"], "parts": ["คุณรู้สึกยังไงกับเรื่องนี้" for _ in s["parts"]]}
                                         for s in data["sentences"]]})

    monkeypatch.setattr(T, "_chat", fake_chat)
    left = T.verify_translation(us, "en", "th")
    assert left == {}
    assert us[0].target == "คุณรู้สึกยังไงกับเรื่องนี้"
    assert us[1].target == "ฉันปล่อยให้มันครอบงำฉัน" and us[2].target == "ขอบคุณ"


def test_persistent_issue_is_returned_after_max_rounds(monkeypatch):
    us = _utts()
    monkeypatch.setattr(T, "_chat", lambda system, user, temperature=None, max_tokens=4096: (
        json.dumps({"bad": [{"id": 1, "note": "ยังผิด"}]}) if system == T.ACCURACY_PROMPT_TH else
        json.dumps({"sentences": [{"id": 1, "parts": ["คุณรู้สึกยังไง"]}]})))
    left = T.verify_translation(us, "en", "th")
    assert left == {1: "ยังผิด"}
    assert us[0].target == "ฉันปล่อยให้มันครอบงำฉัน"  # ไม่ผ่านตรวจซ้ำ → ย้อนกลับบทเดิม


def test_runaway_longer_rewrite_is_reverted(monkeypatch):
    us = _utts()
    state = {"n": 0}

    def fake(system, user, temperature=None, max_tokens=4096):
        if system == T.ACCURACY_PROMPT_TH:
            state["n"] += 1
            return json.dumps({"bad": [{"id": 1, "note": "ผิด"}] if state["n"] == 1 else []})
        return json.dumps({"sentences": [{"id": 1, "parts": ["ต้องการความยุติธรรม ต้องการให้ทุกอย่างถูกต้อง ต้องการให้โลกนี้ปลอดภัยสำหรับคนที่ฉันรัก"]}]})

    monkeypatch.setattr(T, "_chat", fake)
    T.verify_translation(us, "en", "th")
    assert us[0].target == "ฉันปล่อยให้มันครอบงำฉัน"


def test_checker_failure_keeps_everything(monkeypatch):
    us = _utts()
    before = [u.target for u in us]

    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(T, "_chat", boom)
    assert T.verify_translation(us, "en", "th") == {}
    assert [u.target for u in us] == before


def test_disabled_and_non_thai_do_nothing(monkeypatch):
    us = _utts()
    monkeypatch.setattr(T, "_chat", lambda *a, **k: pytest.fail("must not call"))
    assert T.verify_translation(us, "en", "en") == {}
    monkeypatch.setattr(T, "settings", replace(settings, translate_verify=False))
    assert T.verify_translation(us, "en", "th") == {}


def test_flag_only_mode_does_not_rewrite(monkeypatch):
    us = _utts()
    before = [u.target for u in us]
    monkeypatch.setattr(T, "settings", replace(settings, translate_verify=True, translate_verify_fix=False, mock_pipeline=False))
    monkeypatch.setattr(T, "_chat", lambda system, user, temperature=None, max_tokens=4096: (
        json.dumps({"bad": [{"id": 1, "note": "ผิด"}]}) if system == T.ACCURACY_PROMPT_TH else pytest.fail("must not retranslate")))
    assert T.verify_translation(us, "en", "th") == {1: "ผิด"}
    assert [u.target for u in us] == before
