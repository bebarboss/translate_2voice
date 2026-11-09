import json
from dataclasses import replace

import pytest

from app.pipeline import translate
from app.schemas import Utterance


def lines(n, target="แปล"):
    return [Utterance(id=i, speaker="a", start=i * 3.0, end=i * 3.0 + 2.0, source=f"src{i}。", target=target) for i in range(n)]


@pytest.fixture
def flags(monkeypatch):
    def set_flags(**kw):
        monkeypatch.setattr(translate, "settings", replace(translate.settings, typhoon_api_key="x", **kw))
    set_flags()
    return set_flags


def fake_chat(monkeypatch, reply):
    """แทน _chat: จำข้อความที่ส่ง แล้วตอบตาม reply(system, user)"""
    calls = []

    def chat(system, user, temperature=None, max_tokens=4096):
        calls.append((system, user))
        return json.dumps(reply(system, user), ensure_ascii=False)
    monkeypatch.setattr(translate, "_chat", chat)
    return calls


def payload_of(user):
    return json.loads(user[user.index("{\"title\""):])


def echo_translation(system, user):
    return {"sentences": [{"id": s["id"], "parts": ["ใหม่"] * len(s["parts"])} for s in payload_of(user)["sentences"]]}


# ---- content_type
def test_clean_story_content_type():
    assert translate.clean_story({"content_type": "Teaser"}, set(), set())["content_type"] == "teaser"
    assert translate.clean_story({"content_type": "หนัง"}, set(), set())["content_type"] == ""


def test_content_type_flag(flags, monkeypatch):
    calls = fake_chat(monkeypatch, lambda s, u: {"content_type": "teaser"})
    assert translate.analyze_story(lines(1), "zh")["content_type"] == "teaser"
    assert "content_type" in calls[0][0] and "content_type" in calls[0][1]
    assert translate.story_hints({"content_type": "teaser"}, {})["content_type"] == "teaser"

    flags(story_content_type=False)
    calls.clear()
    translate.analyze_story(lines(1), "zh")
    assert "content_type" not in calls[0][0] and "content_type" not in calls[0][1]
    assert translate.story_hints({"content_type": "teaser"}, {})["content_type"] == ""


# ---- บริบทตอนแปล
def test_batch_gets_three_before_two_after(flags, monkeypatch):
    flags(translate_batch_size=2)
    calls = fake_chat(monkeypatch, echo_translation)
    utts = lines(8, target="")
    translate.translate_utterances(utts, "zh")
    p = payload_of(calls[2][1])  # ชุดที่สาม คือ id 4, 5
    assert [s["id"] for s in p["sentences"]] == [4, 5]
    assert [x["source"] for x in p["previous_lines"]] == ["src1。", "src2。", "src3。"]
    assert all(x["text"] == "ใหม่" for x in p["previous_lines"])  # ก่อนหน้าแปลแล้ว
    assert [x["source"] for x in p["next_lines"]] == ["src6。", "src7。"]
    assert all("text" not in x for x in p["next_lines"])  # ถัดไปส่งแต่ต้นฉบับ
    assert p["previous_lines_note"] == p["next_lines_note"] == "บริบท ห้ามแปล"
    assert set(p["sentences"][0]) >= {"id", "speaker", "parts"}  # รูปแบบข้อมูลที่ให้แปลเดิม
    assert all(u.target == "ใหม่" for u in utts)


def test_next_lines_source_only_even_when_translated(flags):
    utts = lines(4)  # ทุกบรรทัดมีคำแปลอยู่แล้ว (เช่นตอนแปลใหม่)
    hints = translate._with_order(utts, {})
    _, user = translate._groups_prompt([hints["sentences"][1]], "zh", "th", [], "", hints)
    p = payload_of(user)
    assert [x["text"] for x in p["previous_lines"]] == ["แปล"]
    assert all("text" not in x for x in p["next_lines"]) and len(p["next_lines"]) == 2
    _, user = translate._groups_prompt([hints["sentences"][1]], "zh", "en", [], "", hints)
    assert payload_of(user)["next_lines_note"] == "context only, do not translate"


def test_extra_ids_in_reply_are_ignored(flags, monkeypatch):
    """โมเดลแปลบทบริบทมาด้วย ต้องไม่ทับบทอื่น"""
    def reply(system, user):
        if system == translate.CONTINUITY_PROMPT:
            return {"breaks": [{"id": 1, "note": "ไม่ต่อ"}] if "src2" in user and "src0" in user and "\"id\": 3" in user else []}
        return {"sentences": [{"id": 0, "parts": ["ผิด"]}, {"id": 1, "parts": ["ถูก"]}, {"id": 2, "parts": ["ผิด"]}]}
    fake_chat(monkeypatch, reply)
    utts = lines(4)
    translate.review_translation(utts, "zh", hints={"content_type": "continuous"})
    assert [u.target for u in utts] == ["แปล", "ถูก", "แปล", "แปล"]


def test_neighbours_flag_off_keeps_old_context(flags, monkeypatch):
    flags(translate_batch_size=1, translate_neighbors=False)
    calls = fake_chat(monkeypatch, echo_translation)
    translate.translate_utterances(lines(8, target=""), "zh")
    p = payload_of(calls[7][1])
    assert len(p["previous_lines"]) == 6 and "source" not in p["previous_lines"][0]
    assert "next_lines" not in p


# ---- ย่อและขยายบท
def test_shorten_sends_neighbours(flags, monkeypatch):
    calls = fake_chat(monkeypatch, lambda s, u: {"lines": [{"id": 1, "text": "สั้น"}]})
    utts = lines(3, target="ก")
    utts[1].target = "ยาว" * 100
    translate.fit_lengths(utts, "th")
    line = json.loads(calls[0][1])["lines"][0]
    assert line["before"]["text"] == "ก" and line["after"]["text"] == "ก"
    assert "src" not in json.dumps(line)
    assert utts[1].target == "สั้น" and utts[0].target == "ก"


def test_fit_neighbours_flag_off(flags, monkeypatch):
    flags(fit_neighbors=False)
    calls = fake_chat(monkeypatch, lambda s, u: {"lines": [{"id": 1, "text": "สั้น"}]})
    utts = lines(3, target="ก")
    utts[1].target = "ยาว" * 100
    translate.fit_lengths(utts, "th")
    assert "before" not in json.loads(calls[0][1])["lines"][0]


def test_fit_only_touches_listed_lines(flags, monkeypatch):
    calls = fake_chat(monkeypatch, lambda s, u: {"lines": []})
    utts = lines(3, target="ยาว" * 100)
    translate.fit_lengths(utts, "th", only={2})
    assert {x["id"] for c in calls for x in json.loads(c[1])["lines"]} == {2}


# ---- ตรวจหลังแปล
def review_reply(found):
    """found: รายการผลตรวจแต่ละรอบ ตอบแปลใหม่ตามปกติ"""
    rounds = iter(found)

    def reply(system, user):
        if system == translate.CONTINUITY_PROMPT:
            return {"breaks": next(rounds)}
        return echo_translation(system, user)
    return reply


def test_continuous_fixed_on_first_round(flags, monkeypatch):
    calls = fake_chat(monkeypatch, review_reply([[{"id": 2, "note": "คำตอบไม่ตรงคำถาม"}], []]))
    utts = lines(6)
    translate.review_translation(utts, "zh", hints={"content_type": "continuous"})
    assert utts[2].target == "ใหม่" and utts[0].target == "แปล"
    assert not any(u.check_note for u in utts)
    sent = next(c[1] for c in calls if c[0] == translate.SYSTEM_PROMPT_TH)
    assert payload_of(sent)["sentences"][0]["continuity_issue"] == "คำตอบไม่ตรงคำถาม"
    # ตรวจซ้ำเฉพาะบรรทัดที่แปลใหม่กับบรรทัดที่ติดกัน
    assert [x["id"] for x in json.loads(calls[-1][1])["lines"]] == [1, 2, 3]


def test_continuous_stops_after_two_rounds_and_labels(flags, monkeypatch):
    bad = [{"id": 2, "note": "ไม่ต่อ"}]
    calls = fake_chat(monkeypatch, review_reply([bad, bad, bad, bad, bad]))
    utts = lines(6)
    translate.review_translation(utts, "zh", hints={"content_type": "continuous"})
    assert sum(c[0] == translate.SYSTEM_PROMPT_TH for c in calls) == 2
    assert sum(c[0] == translate.CONTINUITY_PROMPT for c in calls) == 3
    assert "ไม่ต่อ" in utts[2].check_note


def test_context_only_id_from_check_is_ignored(flags, monkeypatch):
    fake_chat(monkeypatch, review_reply([[{"id": 99, "note": "มั่ว"}], []]))
    utts = lines(3)
    translate.review_translation(utts, "zh", hints={"content_type": "continuous"})
    assert all(u.target == "แปล" and not u.check_note for u in utts)


@pytest.mark.parametrize("kind", ["teaser", ""])
def test_teaser_only_labels_never_edits(flags, monkeypatch, kind):
    calls = fake_chat(monkeypatch, lambda s, u: {"issues": [{"id": 1, "note": "สะกดชื่อไม่ตรงกัน"}]})
    utts = lines(3)
    translate.review_translation(utts, "zh", hints={"content_type": kind})
    assert [u.target for u in utts] == ["แปล"] * 3
    assert utts[1].check_note == "สะกดชื่อไม่ตรงกัน" and not utts[0].check_note
    assert [c[0] for c in calls] == [translate.TERMS_PROMPT]


def test_glossary_miss_labels_even_if_model_fails(flags, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(translate, "_chat", broken)
    utts = lines(2)
    utts[0].source = "悟空来了。"
    utts[1].source = "悟空走了。"
    utts[1].target = "โกคูไปแล้ว"
    translate.review_translation(utts, "zh", hints={"content_type": "teaser", "glossary": "悟空 = โกคู"})
    assert "悟空" in utts[0].check_note and not utts[1].check_note


def test_retranslate_failure_keeps_text_and_labels(flags, monkeypatch):
    def chat(system, user, temperature=None, max_tokens=4096):
        if system == translate.CONTINUITY_PROMPT:
            return json.dumps({"breaks": [{"id": 1, "note": "ไม่ต่อ"}]}, ensure_ascii=False)
        raise RuntimeError("quota")
    monkeypatch.setattr(translate, "_chat", chat)
    utts = lines(3)
    translate.review_translation(utts, "zh", hints={"content_type": "continuous"})
    assert utts[1].target == "แปล" and "ไม่ต่อ" in utts[1].check_note


def test_same_language_skips_review(flags, monkeypatch):
    calls = fake_chat(monkeypatch, lambda s, u: {})
    translate.review_translation(lines(2), "th", "th", hints={"content_type": "continuous"})
    assert not calls


# ---- เกตเนื้อหาเลื่อนข้ามท่อน (part bleed)
def test_source_anchors_numbers_and_latin():
    assert translate._source_anchors("AI has 1,200 users.") == {"ai", "has", "users", "1200"}
    assert "0" not in translate._source_anchors("score 0 points")


def test_part_bleed_detects_moved_number_and_ai():
    sources = ["The AI model scored 95.", "Then they left."]
    # ท่อน 2 ดึง AI + 95 จากท่อน 1
    bad = ["โมเดลได้คะแนนสูง", "เอไอได้ 95 คะแนน แล้วพวกเขาก็ไป"]
    assert translate.part_bleed_indices(sources, bad) == [1]
    good = ["โมเดลเอไอได้ 95 คะแนน", "แล้วพวกเขาก็ไป"]
    assert translate.part_bleed_indices(sources, good) == []


def test_part_bleed_ignores_ai_inside_thai_word():
    # "ai" ใน "thai" ต้องไม่นับเป็นสมอเอไอ
    sources = ["AI wins.", "Go."]
    targets = ["เอไอชนะ", "ไปเลย"]
    assert translate.part_bleed_indices(sources, targets) == []


def test_part_bleed_incomplete_finish_and_healthcare():
    """ตัดกลางประโยคแล้วแปลจบ / ดึง healthcare จากท่อนถัดไป — เคสจริงจากงานพากย์"""
    sources = [
        "And he said, we should stop training radiologists now because it's obvious that within five",
        "years we won't need any. And I can tell you at UCSF today, we can't hire radiologists",
    ]
    bad = [
        "เขาบอกว่าควรหยุดฝึกแพทย์ภาพถ่ายรังสี เพราะอีกห้าปีข้างหน้าเราคงไม่ต้องมีใครแล้ว",
        "และฉันบอกได้เลยว่าที่ ยูซีเอสเอฟ จ้างแพทย์ภาพถ่ายรังสีไม่ทันพอ",
    ]
    assert 0 in translate.part_bleed_indices(sources, bad)
    good = [
        "เขาบอกว่าควรหยุดฝึกแพทย์ภาพถ่ายรังสี เพราะชัดเจนว่าภายในห้า",
        "ปีข้างหน้าเราคงไม่ต้องมีใครแล้ว และที่ ยูซีเอสเอฟ จ้างแพทย์ภาพถ่ายรังสีไม่ทันพอ",
    ]
    assert translate.part_bleed_indices(sources, good) == []

    sources2 = [
        "Within 20 years, I could see a world where you're getting a decent amount",
        "of your healthcare from AI, but I still think you're going to want a doctor",
    ]
    assert 0 in translate.part_bleed_indices(
        sources2,
        ["ภายในยี่สิบปี ฉันมองเห็นโลกที่คุณได้รับบริการด้านสุขภาพจากเอไอในระดับหนึ่ง",
         "ฉันว่าคุณจะยังอยากได้หมออยู่ดี"],
    )


def test_translate_retries_on_part_bleed(flags, monkeypatch):
    """โมเดลย้ายตัวเลขข้ามท่อน → เกตรีเจกต์ แล้วรับรอบที่ถูก"""
    replies = iter([
        {"sentences": [{"id": 0, "parts": ["บทนำ", "เอไอได้ 95 แล้วจบ"]}]},
        {"sentences": [{"id": 0, "parts": ["เอไอได้ 95", "แล้วจบ"]}]},
    ])
    calls = fake_chat(monkeypatch, lambda s, u: next(replies))
    utts = [
        Utterance(id=0, speaker="a", start=0.0, end=2.0, source="AI scored 95.", target=""),
        Utterance(id=1, speaker="a", start=2.1, end=4.0, source="Then done.", target=""),
    ]
    translate._translate_groups([utts], "en", "th", [], "")
    assert [u.target for u in utts] == ["เอไอได้ 95", "แล้วจบ"]
    assert len(calls) == 2


def test_groups_prompt_includes_part_index(flags):
    utts = lines(2, target="")
    hints = translate._with_order(utts, {})
    _, user = translate._groups_prompt([utts], "zh", "th", [], "", hints)
    parts = payload_of(user)["sentences"][0]["parts"]
    assert [p["index"] for p in parts] == [1, 2]
    assert "ห้ามย้าย" in user
