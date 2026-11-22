"""คุณภาพคำแปลไทย ระยะที่ 1 (translate_quality): ทุกเทสต์จำลองโมเดล ไม่เรียก API จริง

บทตัวอย่างจากคลิป Shorts "Pov you're a girl" ที่เคยแปลผิด:
- "you've got the whole world telling you what to do with your body" → เคยได้ "ต้องทำอะไรกับร่างกาย"
  ความหมายจริง: ทุกคนคอยบอกว่าเธอ *ควร* ทำอะไรกับร่างกายตัวเอง (ถูกควบคุม)
  ห้ามถือ "จะทำอะไรกับร่างกายตัวเองก็ได้" เป็นคำตอบที่ถูก เพราะความหมายกลับด้าน (ทำได้ตามใจ)
- "change your dress, it's too fast, too short, too shiny" → "too fast" เคยได้ "เร็วเกินไป" (ผิด ควรเป็น โป๊/แรงเกินไป)
"""
import json
from dataclasses import replace

import pytest

from app.config import settings
from app.pipeline import translate as T
from app.pipeline import translate_quality as Q
from app.schemas import Utterance

GOOD_BODY = "ทั้งโลกคอยบอกว่าเธอควรทำอะไรกับร่างกายตัวเอง"
OLD_BAD_BODY = "ต้องทำอะไรกับร่างกาย"
REVERSED_BODY = "ทั้งโลกบอกว่าเธอจะทำอะไรกับร่างกายตัวเองก็ได้"
OLD_BAD_DRESS = "มันเร็วเกินไป สั้นเกินไป แวววาวเกินไป"
GOOD_DRESS = "มันโป๊ไป สั้นไป แวววาวไป"


def _clip(targets=("", "", "", "")) -> list[Utterance]:
    rows = [(1, "Pov: you're a girl", 0.0, 1.2),
            (2, "You've got the whole world telling you what to do with your body.", 1.4, 5.0),
            (3, "Change your dress,", 5.4, 6.4),
            (4, "it's too fast, too short, too shiny.", 6.4, 8.6)]
    return [Utterance(id=i, speaker="speaker_01", start=s, end=e, source=src, target=t)
            for (i, src, s, e), t in zip(rows, targets)]


def _set(monkeypatch, **kw):
    new = replace(settings, mock_pipeline=False, **kw)
    monkeypatch.setattr(T, "settings", new)
    monkeypatch.setattr(Q, "settings", new)
    return new


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    _set(monkeypatch)


def _payload(user: str) -> dict:
    return json.loads(user[user.index("\n\n") + 2:])


# ---------------------------------------------------------------- งบความยาว
def test_syllable_estimator_matches_reference_sentence():
    assert Q.thai_base_chars(GOOD_BODY) == 38
    assert Q.thai_syllables(GOOD_BODY) == 15  # ทั้ง·โลก·คอย·บอก·ว่า·เธอ·ควร·ทำ·อะ·ไร·กับ·ร่าง·กาย·ตัว·เอง
    assert Q.thai_syllables("") == 0


def test_syllable_budget_is_tied_to_tts_rate_and_speedup(monkeypatch):
    _set(monkeypatch, thai_chars_per_sec=12.0, thai_chars_per_syllable=2.5, max_speedup=1.10, fit_tolerance=1.1)
    assert Q.syllables_per_sec() == pytest.approx(4.8)
    b = Q.syllable_budget(3.6)
    assert b == {"target_syllables": 17, "max_syllables": 19}
    # max ไม่เกินที่เร่งเสียงได้: 15 พยางค์พอดีช่อง 3.6 วิ แต่ 30 พยางค์ไม่พอ
    u = _clip((GOOD_BODY,) * 4)[1]
    assert not Q.over_budget(u, 3.6)
    u.target = GOOD_BODY * 2
    assert Q.over_budget(u, 3.6)


def test_old_prompt_gets_syllable_budget_only_when_enabled(monkeypatch):
    us = _clip()
    hints = T._with_order(us, {})
    _, user = T._groups_prompt(hints["sentences"], "en", "th", [], "Pov you're a girl", hints)
    assert "target_syllables" not in user  # ค่าเริ่มต้นปิด: เส้นทางเดิมไม่เปลี่ยนทุกบรรทัด
    _set(monkeypatch, translate_syllable_budget=True)
    system, user = T._groups_prompt(hints["sentences"], "en", "th", [], "Pov you're a girl", hints)
    parts = [p for s in _payload(user)["sentences"] for p in s["parts"]]
    assert all("target_syllables" in p and "max_syllables" in p for p in parts)
    assert Q.LENGTH_RULE_TH in system


# ---------------------------------------------------------------- คำใบ้สำนวนในคำขอ
def test_old_prompt_includes_idiom_hints_for_both_known_bad_lines():
    us = _clip()
    hints = T._with_order(us, {})
    system, user = T._groups_prompt(hints["sentences"], "en", "th", [], "Pov you're a girl", hints)
    idioms = _payload(user)["idioms"]
    assert Q.IDIOM_RULE_TH in system
    body = next(h for h in idioms if "body" in h)
    assert GOOD_BODY in body and "ควร" in body  # ชี้ไปที่ความหมาย "คนอื่นคอยบอกว่าควรทำอะไร"
    assert 'ไม่ใช่ "ทำอะไรก็ได้"' in body  # และเตือนไม่ให้กลับความหมาย
    dress = next(h for h in idioms if "too fast" in h)
    assert "โป๊" in dress and 'ไม่ใช่ "เร็วเกินไป"' in dress


def test_idiom_hints_off_and_unrelated_lines(monkeypatch):
    us = [Utterance(id=1, speaker="a", start=0, end=2, source="He drove too fast.")]
    hints = T._with_order(us, {})
    _, user = T._groups_prompt(hints["sentences"], "en", "th", [], "", hints)
    assert "idioms" not in _payload(user)  # รถขับเร็ว = เร็วจริง ไม่ใส่คำใบ้เรื่องชุด
    _set(monkeypatch, translate_idiom_hints=False)
    hints = T._with_order(_clip(), {})
    system, user = T._groups_prompt(hints["sentences"], "en", "th", [], "", hints)
    assert "idioms" not in _payload(user) and Q.IDIOM_RULE_TH not in system


# ---------------------------------------------------------------- ตรวจแบบกฎ
@pytest.mark.parametrize("target,kinds", [
    (OLD_BAD_BODY, {"meaning", "naturalness"}),
    (REVERSED_BODY, {"meaning"}),
    ("จะทำอะไรกับร่างกายตัวเองก็ได้", {"meaning"}),
    (GOOD_BODY, set()),
])
def test_body_line_rule_flags(target, kinds):
    us = _clip(("", target, "", ""))
    flags = Q.rule_flags(us)
    assert {k for k, _ in flags.get(2, [])} == kinds


def test_dress_line_rule_flags():
    assert {k for k, _ in Q.rule_flags(_clip(("", "", "", OLD_BAD_DRESS)))[4]} == {"meaning"}
    assert Q.rule_flags(_clip(("", "", "", GOOD_DRESS))) == {}
    # "too fast" ที่ไม่ได้พูดถึงชุดไม่ติดป้าย
    car = [Utterance(id=1, speaker="a", start=0, end=2, source="He drove too fast.", target="เขาขับเร็วเกินไป")]
    assert Q.rule_flags(car) == {}


# ---------------------------------------------------------------- self-check → เขียนใหม่เฉพาะบรรทัดที่ติดป้าย
def _fake_llm(check_flags, rewrites, calls):
    def fake(system, user, temperature=None, max_tokens=4096):
        if system == Q.SELF_CHECK_PROMPT_TH:
            calls.append(("check", json.loads(user)))
            return json.dumps({"flags": check_flags})
        if system == Q.REWRITE_PROMPT_TH:
            payload = json.loads(user)
            calls.append(("rewrite", payload))
            return json.dumps({"lines": [{"id": x["id"], "text": rewrites[x["id"]]} for x in payload["lines"]
                                         if x["id"] in rewrites]})
        raise AssertionError(f"unexpected prompt: {system[:40]}")
    return fake


def test_self_check_rewrites_only_flagged_lines(monkeypatch):
    us = _clip(("มุมมอง: เธอเป็นผู้หญิง", OLD_BAD_BODY, "เปลี่ยนชุดซะ", OLD_BAD_DRESS))
    calls: list = []
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: GOOD_BODY, 4: GOOD_DRESS, 1: "ห้ามแก้", 3: "ห้ามแก้"}, calls))
    still = Q.self_check(us, T._with_order(us, {}))
    assert still == {}
    assert [u.target for u in us] == ["มุมมอง: เธอเป็นผู้หญิง", GOOD_BODY, "เปลี่ยนชุดซะ", GOOD_DRESS]
    assert [c[0] for c in calls] == ["check", "rewrite"]  # ตรวจ 1 ครั้ง เขียนใหม่ 1 รอบ
    sent = calls[1][1]
    assert [x["id"] for x in sent["lines"]] == [2, 4]  # ส่งไปเขียนใหม่เฉพาะบรรทัดที่ติดป้าย
    assert any("โป๊" in h for h in sent["idioms"])
    assert all("target_syllables" in x for x in sent["lines"])
    # ป้ายเก็บไว้ให้เจ้าของงานดู: แก้แล้ว + บทเดิม
    assert us[1].qa_flags and all(f["fixed"] and f["origin"] == "rule" and f["before"] == OLD_BAD_BODY for f in us[1].qa_flags)
    assert us[3].qa_flags[0]["kind"] == "meaning" and us[3].qa_flags[0]["fixed"]
    assert us[0].qa_flags == [] and us[2].qa_flags == []
    assert all(u.check_note == "" for u in us)


def test_self_check_llm_flag_is_stored_with_reason(monkeypatch):
    us = _clip(("มุมมอง: เธอเป็นผู้หญิง", GOOD_BODY, "เปลี่ยนเดรสของคุณ", GOOD_DRESS))
    calls: list = []
    monkeypatch.setattr(T, "_chat", _fake_llm([{"id": 3, "kind": "naturalness", "reason": "แปลตรงตัว ควรเป็น เปลี่ยนชุดซะ"},
                                               {"id": 99, "kind": "meaning", "reason": "id ไม่มีจริง"}],
                                              {3: "เปลี่ยนชุดซะ"}, calls))
    Q.self_check(us, T._with_order(us, {}))
    assert us[2].target == "เปลี่ยนชุดซะ"
    assert us[2].qa_flags == [{"origin": "self_check", "kind": "naturalness", "reason": "แปลตรงตัว ควรเป็น เปลี่ยนชุดซะ",
                               "fixed": True, "before": "เปลี่ยนเดรสของคุณ"}]
    assert us[1].target == GOOD_BODY and us[1].qa_flags == []


def test_rewrite_that_is_still_wrong_is_rejected_and_flag_stays_visible(monkeypatch):
    us = _clip(("", REVERSED_BODY, "", OLD_BAD_DRESS))
    calls: list = []
    # โมเดลเขียนใหม่แล้วยังผิดเหมือนเดิม → คงบทเดิม ไม่วนรอบสอง
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: "จะทำอะไรกับร่างกายตัวเองก็ได้", 4: "เร็วไป สั้นไป"}, calls))
    still = Q.self_check(us, T._with_order(us, {}))
    assert set(still) == {2, 4}
    assert us[1].target == REVERSED_BODY and us[3].target == OLD_BAD_DRESS
    assert [c[0] for c in calls] == ["check", "rewrite"]
    assert us[1].check_note.startswith("ตรวจคำแปล:") and "กลับด้าน" in us[1].check_note
    assert us[3].unclear_reason and not us[3].qa_flags[0]["fixed"]


def test_rewrite_over_length_budget_is_rejected(monkeypatch):
    us = _clip(("", OLD_BAD_BODY, "", ""))
    long = GOOD_BODY + " และไม่มีใครถามเธอเลยสักคำว่าเธอรู้สึกยังไงกับเรื่องทั้งหมดนี้"
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: long}, []))
    Q.self_check(us, T._with_order(us, {}))
    assert us[1].target == OLD_BAD_BODY and us[1].check_note


def test_rule_only_mode_flags_without_calling_the_model(monkeypatch):
    us = _clip(("", OLD_BAD_BODY, "", OLD_BAD_DRESS))

    def boom(*a, **k):
        raise AssertionError("must not call the LLM")
    monkeypatch.setattr(T, "_chat", boom)
    still = Q.self_check(us, T._with_order(us, {}), use_llm=False)
    assert set(still) == {2, 4}
    assert us[1].target == OLD_BAD_BODY  # ไม่แก้บทเอง ติดป้ายอย่างเดียว
    assert us[1].check_note and us[3].check_note


def test_verify_flags_are_recorded_alongside():
    us = _clip(("a", "b", "c", "d"))
    Q.record_verify_flags(us, {3: "แปลผิด"})
    assert us[2].qa_flags == [{"origin": "verify", "kind": "meaning", "reason": "แปลผิด", "fixed": False}]
    Q.record_verify_flags(us, {3: "แปลผิด"})
    assert len(us[2].qa_flags) == 1


# ---------------------------------------------------------------- แปลทั้งฉาก
def test_split_scenes_on_gap_and_size():
    us = _clip() + [Utterance(id=5, speaker="speaker_02", start=20.0, end=21.0, source="Hey.")]
    groups = T._group_lines(us)
    scenes = Q.split_scenes(groups, max_lines=24, gap=4.0)
    assert [[u.id for g in s for u in g] for s in scenes] == [[1, 2, 3, 4], [5]]
    small = Q.split_scenes(groups, max_lines=2, gap=99)
    assert all(sum(map(len, s)) <= 2 for s in small)
    assert [u.id for s in small for g in s for u in g] == [1, 2, 3, 4, 5]


def test_scene_prompt_has_timestamps_speakers_budget_and_overlap():
    us = _clip()
    prev = Utterance(id=0, speaker="speaker_02", start=-3.0, end=-1.0, source="Earlier line", target="บทก่อน")
    hints = T._with_order(us, {"names": {"speaker_01": "หญิงสาว"}})
    system, user = Q.scene_prompt(hints["sentences"], "en", "Pov you're a girl", hints, [prev], [])
    p = _payload(user)
    line = next(x for x in p["lines"] if x["id"] == 2)
    assert line["start"] == 1.4 and line["end"] == 5.0 and line["speaker"] == "หญิงสาว"
    assert {"target_syllables", "max_syllables", "max_chars", "seconds", "sentence"} <= set(line)
    assert p["previous_lines"][0]["text"] == "บทก่อน"
    assert any(GOOD_BODY in h for h in p["idioms"])
    assert '{"lines":[{"id":1,"text":"คำแปล"}]}' in user
    assert Q.SCENE_RULE_TH in system and Q.LENGTH_RULE_TH in system


@pytest.mark.parametrize("reply,expected", [
    ('{"lines":[{"id":1,"text":"ก"},{"id":2,"text":"ข"}]}', {1: "ก", 2: "ข"}),
    ('```json\n{"lines":{"1":"ก","2":"ข"}}\n```', {1: "ก", 2: "ข"}),
    ('{"lines":[{"id":1,"text":"ก"},{"id":7,"text":"เกิน"},{"id":2,"text":""}]}', {1: "ก"}),
    ('{"lines":[{"id":1,"text":"ก"},{"id":1,"text":"ซ้ำ"},{"id":2,"text":"你好"}]}', {}),
    ('{"lines":[{"id":"2","text":{"x":1}},{"id":1,"text":"[\\"ก\\"]"}]}', {}),
])
def test_parse_scene_reply_is_strict(reply, expected):
    assert Q.parse_scene_reply(reply, [1, 2]) == expected


@pytest.mark.parametrize("reply", ["ขอโทษค่ะ แปลไม่ได้", '{"sentences":[]}'])
def test_parse_scene_reply_rejects_bad_shape(reply):
    with pytest.raises(ValueError):
        Q.parse_scene_reply(reply, [1, 2])


def test_scene_mode_translates_whole_clip_in_one_call(monkeypatch):
    _set(monkeypatch, translate_scene_mode=True)
    us = _clip()
    calls: list = []

    def fake(system, user, temperature=None, max_tokens=4096):
        calls.append(system)
        ids = [x["id"] for x in _payload(user)["lines"]]
        return json.dumps({"lines": [{"id": i, "text": f"บรรทัด{i}"} for i in ids]})
    monkeypatch.setattr(T, "_chat", fake)
    T.translate_utterances(us, "en", "th", title="Pov you're a girl")
    assert len(calls) == 1 and Q.SCENE_RULE_TH in calls[0]
    assert [u.target for u in us] == ["บรรทัด1", "บรรทัด2", "บรรทัด3", "บรรทัด4"]


def test_scene_mode_falls_back_per_sentence_for_missing_lines(monkeypatch):
    _set(monkeypatch, translate_scene_mode=True)
    us = _clip()
    old_path: list = []

    def fake(system, user, temperature=None, max_tokens=4096):
        if Q.SCENE_RULE_TH in system:  # ตอบขาดบรรทัด 3 และ 4 (ประโยคเดียวกัน)
            return json.dumps({"lines": [{"id": 1, "text": "หนึ่ง"}, {"id": 2, "text": GOOD_BODY}, {"id": 3, "text": "สาม"}]})
        data = _payload(user)
        old_path.append([s["id"] for s in data["sentences"]])
        parts = [["เปลี่ยนชุดซะ", GOOD_DRESS][i] for i in range(len(data["sentences"][0]["parts"]))]
        return json.dumps({"sentences": [{"id": data["sentences"][0]["id"], "parts": parts}]})
    monkeypatch.setattr(T, "_chat", fake)
    T.translate_utterances(us, "en", "th")
    assert us[0].target == "หนึ่ง" and us[1].target == GOOD_BODY
    assert old_path == [[3]]  # แปลใหม่ทั้งประโยค 3–4 ด้วยเส้นทางเดิม บรรทัด 3 ที่ได้แล้วก็แปลใหม่ให้ท่อนต่อกัน
    assert us[2].target == "เปลี่ยนชุดซะ" and us[3].target == GOOD_DRESS


def test_scene_mode_unparseable_reply_falls_back_for_all(monkeypatch):
    _set(monkeypatch, translate_scene_mode=True)
    us = _clip()

    def fake(system, user, temperature=None, max_tokens=4096):
        if Q.SCENE_RULE_TH in system:
            return "ไม่ใช่ JSON"
        data = _payload(user)
        return json.dumps({"sentences": [{"id": s["id"], "parts": ["แผนสำรอง"] * len(s["parts"])} for s in data["sentences"]]})
    monkeypatch.setattr(T, "_chat", fake)
    T.translate_utterances(us, "en", "th")
    assert all(u.target == "แผนสำรอง" for u in us)


def test_scene_mode_is_off_by_default(monkeypatch):
    us = _clip()
    systems: list = []

    def fake(system, user, temperature=None, max_tokens=4096):
        systems.append(system)
        data = _payload(user)
        return json.dumps({"sentences": [{"id": s["id"], "parts": ["ก"] * len(s["parts"])} for s in data["sentences"]]})
    monkeypatch.setattr(T, "_chat", fake)
    T.translate_utterances(us, "en", "th")
    assert systems and all(Q.SCENE_RULE_TH not in s for s in systems)
