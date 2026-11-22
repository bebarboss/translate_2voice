"""คุณภาพคำแปลไทย ระยะที่ 2: กฎรายบรรทัด (ตัวเลข ชื่อ คำลงท้ายเกิน ต้นฉบับไม่ชัด) → แก้เอง 1 รอบ → ที่ไม่แน่ใจส่งให้เจ้าของงานตรวจ
ทุกเทสต์จำลองโมเดล ไม่เรียก API จริง

ตัวอย่างจริง: งาน "Ace the Duolingo English Test Easily"
ต้นฉบับ: "I scored 135! 435. DE Practice AI feedback helped me fix my speaking and writing mistakes."
- 135 ต้องคงไว้
- "DE Practice" เคยถูกถอดเป็น "ดีอี พรากติส" (ผิด) → ติดป้ายแล้วแก้
- เคยเติม "นะ" ท้ายประโยคทั้งที่ต้นฉบับเป็นประโยคบอกเล่า → ติดป้ายแล้วแก้
- "435." ลอยอยู่เดี่ยว ๆ หลัง "I scored 135!" (ถอดเสียงซ้ำ/ผิด) → แก้เองไม่ได้ ส่งให้เจ้าของงานตรวจ
"""
import json
from dataclasses import replace

import pytest

from app.config import settings
from app.pipeline import translate as T
from app.pipeline import translate_quality as Q
from app.schemas import Job, JobStatus, Utterance

TITLE = "Ace the Duolingo English Test Easily"
SOURCE = "I scored 135! 435. DE Practice AI feedback helped me fix my speaking and writing mistakes."
BAD = "ฉันได้ 135 คะแนน! 435. ดีอี พรากติส เอไอ ช่วยให้ฉันแก้ข้อผิดพลาดในการพูดและการเขียนได้นะ"
GOOD = "ฉันได้ 135 คะแนน! 435. ฟีดแบ็กจากเอไอของ DE Practice ช่วยให้ฉันแก้จุดผิดทั้งการพูดและการเขียน"


def _set(monkeypatch, **kw):
    new = replace(settings, mock_pipeline=False, **kw)
    monkeypatch.setattr(T, "settings", new)
    monkeypatch.setattr(Q, "settings", new)
    return new


@pytest.fixture(autouse=True)
def _line_checks_on(monkeypatch):
    _set(monkeypatch, translate_line_checks=True)


def _u(i, src, tgt, start=0.0, end=6.0, speaker="speaker_01") -> Utterance:
    return Utterance(id=i, speaker=speaker, start=start, end=end, source=src, target=tgt)


def _clip(target=BAD) -> list[Utterance]:
    return [_u(1, "Hi everyone, welcome back.", "สวัสดีทุกคน ยินดีต้อนรับกลับมา", 0.0, 2.0),
            _u(2, SOURCE, target, 2.2, 9.5),
            _u(3, "Now my score is way higher.", "ตอนนี้คะแนนฉันสูงขึ้นเยอะเลย", 9.7, 11.5)]


def _kinds(flags) -> set[str]:
    return {k for k, _ in flags}


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


# ---------------------------------------------------------------- ตัวอย่างจริงทั้งสาย
def test_duolingo_line_is_flagged_fixed_and_435_goes_to_review(monkeypatch):
    us = _clip()
    calls: list = []
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: GOOD}, calls))
    still = Q.self_check(us, T._with_order(us, {}))

    line = us[1]
    assert line.target == GOOD
    assert "135" in line.target  # ตัวเลขคงไว้
    assert "DE Practice" in line.target and "พรากติส" not in line.target
    assert not line.target.endswith("นะ")
    # ส่งไปเขียนใหม่ครั้งเดียว บอกปัญหาตรง ๆ ไม่ส่ง 435 (ไม่แน่ใจ) ให้โมเดลเดา
    assert [c[0] for c in calls] == ["check", "rewrite"]
    sent = calls[1][1]["lines"]
    assert [x["id"] for x in sent] == [2]
    assert sent[0]["keep_numbers"] == ["135"]
    assert any("DE Practice" in r for r in sent[0]["flags"]) and any('"นะ"' in r for r in sent[0]["flags"])
    assert not any("435" in r for r in sent[0]["flags"])

    by_kind = {f["kind"]: f for f in line.qa_flags}
    assert set(by_kind) == {"name", "added_word", "unclear_source"}
    assert by_kind["name"]["fixed"] and by_kind["name"]["before"] == BAD
    assert by_kind["added_word"]["fixed"]
    assert not by_kind["unclear_source"]["fixed"] and "435" in by_kind["unclear_source"]["reason"]
    # 435 เท่านั้นที่ค้าง → ขึ้นหน้าตรวจบทพร้อมเหตุผล
    assert _kinds(still[2]) == {"unclear_source"}
    assert line.check_note.startswith("ตรวจคำแปล:") and "435" in line.check_note
    assert Q.uncertain_ids(us) == [2]
    assert us[0].qa_flags == [] and us[2].qa_flags == []


def test_duolingo_line_rule_only_mode_flags_everything_without_model(monkeypatch):
    us = _clip()

    def boom(*a, **k):
        raise AssertionError("must not call the LLM")
    monkeypatch.setattr(T, "_chat", boom)
    still = Q.self_check(us, T._with_order(us, {}), use_llm=False)
    assert us[1].target == BAD  # ไม่แก้บทเอง
    assert _kinds(still[2]) == {"name", "added_word", "unclear_source"}
    assert all(not f["fixed"] for f in us[1].qa_flags)


def test_rewrite_that_loses_the_number_is_rejected(monkeypatch):
    us = _clip()
    worse = "ฉันได้คะแนนเยอะ! ฟีดแบ็กจากเอไอของ DE Practice ช่วยให้ฉันแก้จุดผิดทั้งการพูดและการเขียน"
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: worse}, []))
    still = Q.self_check(us, T._with_order(us, {}))
    assert us[1].target == BAD  # บทเดิมดีกว่า (ตัวเลขหายแย่กว่าคำลงท้าย) คงไว้ แล้วให้คนตรวจ
    assert _kinds(still[2]) == {"name", "added_word", "unclear_source"}
    assert all(not f["fixed"] for f in us[1].qa_flags)


def test_rewrite_that_is_better_but_not_clean_is_kept_and_stays_uncertain(monkeypatch):
    us = _clip()
    better = "ฉันได้ 135 คะแนน! 435. ดีอี พรากติส เอไอ ช่วยให้ฉันแก้จุดผิดทั้งการพูดและการเขียน"  # ตัด นะ แล้ว ชื่อยังผิด
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: better}, []))
    still = Q.self_check(us, T._with_order(us, {}))
    assert us[1].target == better
    assert _kinds(still[2]) == {"name", "unclear_source"}
    flags = {f["kind"]: f["fixed"] for f in us[1].qa_flags}
    assert flags == {"name": False, "added_word": True, "unclear_source": False}


# ---------------------------------------------------------------- กฎรายข้อ
def test_line_checks_are_off_by_default(monkeypatch):
    _set(monkeypatch, translate_line_checks=False)
    assert Q.rule_flags(_clip()) == {}
    assert Q.final_gate(_clip()) == {}


@pytest.mark.parametrize("target, ok", [
    ("ฉันได้ 135 คะแนน", True),
    ("ฉันได้ ๑๓๕ คะแนน", True),
    ("ฉันได้หนึ่งร้อยสามสิบห้าคะแนน", True),
    ("ฉันได้ร้อยสามสิบห้าคะแนน", True),
    ("ฉันได้ 153 คะแนน", False),
    ("ฉันได้คะแนนเยอะมาก", False),
])
def test_numbers_must_survive(target, ok):
    flags = Q.rule_flags([_u(1, "I scored 135.", target)]).get(1, [])
    assert ("number" not in _kinds(flags)) is ok
    if not ok:
        assert "135" in flags[0][1]


def test_number_formats():
    assert Q.thai_number_words(135) == "หนึ่งร้อยสามสิบห้า"
    assert Q.thai_number_words(21) == "ยี่สิบเอ็ด"
    assert Q.thai_number_words(1_250_000) == "หนึ่งล้านสองแสนห้าหมื่น"
    assert Q.rule_flags([_u(1, "It cost 1,000 dollars in 2024.", "ราคา 1000 ดอลลาร์ในปี 2567")]) == {}
    assert Q.rule_flags([_u(1, "About 3.5 hours.", "ประมาณ 3.5 ชั่วโมง")]) == {}


def test_unclear_number_detection():
    assert Q.unclear_numbers(_u(1, SOURCE, "x")) == ["435"]
    assert Q.unclear_numbers(_u(1, "3. 2. 1. Go!", "x")) == []  # นับถอยหลัง
    assert Q.unclear_numbers(_u(1, "What's my score? 135.", "x")) == []  # คำตอบ ไม่ใช่เลขซ้ำ
    prev = _u(1, "I scored 135!", "x")
    assert Q.unclear_numbers(_u(2, "435.", "x", 2, 3), prev) == ["435"]  # ข้ามบรรทัด


def test_brand_names_keep_latin_or_glossary():
    assert Q.brand_names(SOURCE) == ["DE Practice"]
    assert Q.brand_names("I love AI and the USA.") == []  # ตัวย่อที่คนไทยอ่านเป็นไทยกันทั่วไป
    assert Q.rule_flags([_u(1, "Try DE Practice today, okay?", "ลอง DE Practice วันนี้สิ")]) == {}
    bad = Q.rule_flags([_u(1, "Try DE Practice today, okay?", "ลองดีอี พรากติส วันนี้สิ")])[1]
    assert _kinds(bad) == {"name"} and "DE Practice" in bad[0][1]
    # glossary ของโปรเจกต์กำหนดคำสะกดไทยเองได้ (มีหมายเหตุท้ายบรรทัด)
    hints = {"glossary": "DE Practice = ดีอี แพรคทิส # ชื่อแอปฝึกสอบ\nDuolingo = ดูโอลิงโก"}
    assert Q.rule_flags([_u(1, "Try DE Practice today, okay?", "ลองดีอี แพรคทิส วันนี้สิ")], hints) == {}
    miss = Q.rule_flags([_u(1, "Duolingo is great, right?", "ดูโอลิงโกเยี่ยมไปเลยใช่ไหม"),
                         _u(2, "Duolingo is great, right?", "ดูโอลิงโกเยี่ยมไปเลยใช่ไหม", 7, 9),
                         _u(3, "I like Duolingo.", "ฉันชอบดูลิงโก", 10, 12)], hints)
    assert set(miss) == {3} and "ดูโอลิงโก" in miss[3][0][1]


def test_glossary_parsing_and_old_glossary_check_ignore_notes():
    terms = Q.parse_glossary("DE Practice = DE Practice # ชื่อแอป คงอักษรละติน\nドラえもん = โดราเอมอน\nbroken line\n = x")
    assert terms == [Q.Term("DE Practice", "DE Practice", "ชื่อแอป คงอักษรละติน"), Q.Term("ドラえもん", "โดราเอมอน", "")]
    us = [_u(1, "DE Practice helped.", "DE Practice ช่วยได้")]
    hints = T._with_order(us, {"glossary": "DE Practice = DE Practice # ชื่อแอป"})
    assert T._glossary_misses(hints) == {}


@pytest.mark.parametrize("source, target, flagged", [
    ("I scored 135!", "ฉันได้ 135 คะแนนนะ", True),
    ("I scored 135!", "ฉันได้ 135 คะแนนนะคะ", True),
    ("I scored 135!", "ฉันได้ 135 คะแนนครับ", True),
    ("Please subscribe.", "กดติดตามด้วยนะ", False),  # ขอร้อง
    ("Don't forget to like.", "อย่าลืมกดไลก์นะ", False),  # คำสั่ง
    ("Is this your score?", "นี่คะแนนเธอเหรอคะ", False),  # คำถาม
    ("Thank you so much.", "ขอบคุณมากนะ", False),
    ("He won the game.", "เขาชนะเกม", False),  # ชนะ ไม่ใช่ นะ
    ("Hello everyone.", "สวัสดีครับทุกคน", False),  # คำทักทาย
])
def test_added_particles(source, target, flagged):
    assert ("added_word" in _kinds(Q.rule_flags([_u(1, source, target)]).get(1, []))) is flagged


def test_polite_particles_allowed_by_register_or_speaker_habit():
    line = _u(1, "I scored 135.", "ผมได้ 135 คะแนนครับ")
    assert Q.rule_flags([line]) != {}
    assert Q.rule_flags([line], {"register": "สุภาพ ลงท้ายครับ"}) == {}
    assert Q.rule_flags([line], {"characters": {"speaker_01": {"self": "ผม", "role": "ครูสอนภาษา พูดสุภาพ"}}}) == {}
    habit = [line, _u(2, "It took two weeks.", "ใช้เวลาสองอาทิตย์ครับ", 7, 9), _u(3, "Easy.", "ง่ายมาก", 10, 11)]
    assert Q.rule_flags(habit) == {}  # ผู้พูดลงท้ายครับเป็นปกติ = สไตล์ ไม่ใช่เติมเอง
    # แต่ "นะ" ยังต้องมีที่มาจากต้นฉบับแม้ผู้พูดสุภาพ
    assert "added_word" in _kinds(Q.rule_flags([_u(1, "I scored 135.", "ผมได้ 135 คะแนนนะครับ")],
                                               {"register": "สุภาพ"})[1])


# ---------------------------------------------------------------- ด่านสุดท้ายและการบังคับตรวจบท
def test_final_gate_reflags_a_line_broken_after_self_check(monkeypatch):
    us = _clip()
    monkeypatch.setattr(T, "_chat", _fake_llm([], {2: GOOD}, []))
    Q.self_check(us, T._with_order(us, {}))
    assert {f["kind"]: f["fixed"] for f in us[1].qa_flags}["added_word"]
    us[1].target = GOOD + "นะ"  # ขั้นเรียบเรียงทีหลังเติมกลับมา
    us[2].target += "นะ"
    still = Q.final_gate(us, {})
    assert set(still) == {2, 3}
    assert {f["kind"]: f["fixed"] for f in us[1].qa_flags}["added_word"] is False
    assert us[2].qa_flags[0]["kind"] == "added_word" and "นะ" in us[2].check_note
    assert Q.uncertain_ids(us) == [2, 3]


def _job_with(tmp_path, monkeypatch, review: bool, flags: list[dict], uncertain_review: bool):
    from app import jobs
    from app.pipeline import runner
    monkeypatch.setattr(jobs, "using_postgres", lambda: False, raising=False)
    monkeypatch.setattr(runner, "settings", replace(runner.settings, translate_uncertain_review=uncertain_review))
    store = jobs.JobStore(tmp_path)
    job = store.add(Job(id="j1", filename=f"{TITLE}.mp4", status=JobStatus.queued, review=review))
    synth: list = []

    def analyze(st, job_id):
        u = _u(2, SOURCE, GOOD)
        u.qa_flags = flags
        st.save_transcript(job_id, [u])
    monkeypatch.setattr(runner, "run_analyze", analyze)
    monkeypatch.setattr(runner, "run_synthesize", lambda *a, **k: synth.append(a[1]))
    monkeypatch.setattr(jobs.Worker, "_archive_r2", lambda self, job_id: None)
    monkeypatch.setattr(jobs, "notify", None, raising=False)
    worker = jobs.Worker(store)
    worker._execute(job.id, "analyze")
    return store.get(job.id), synth


UNSURE = [{"origin": "rule", "kind": "unclear_source", "reason": "435", "fixed": False}]
FIXED = [{"origin": "rule", "kind": "added_word", "reason": "นะ", "fixed": True, "before": BAD}]


def test_uncertain_lines_force_review_even_when_owner_skipped_it(tmp_path, monkeypatch):
    job, synth = _job_with(tmp_path, monkeypatch, review=False, flags=UNSURE, uncertain_review=True)
    assert job.status == JobStatus.awaiting_review and job.review and synth == []


def test_no_forced_review_when_all_flags_fixed_or_switch_off(tmp_path, monkeypatch):
    job, synth = _job_with(tmp_path, monkeypatch, review=False, flags=FIXED, uncertain_review=True)
    assert job.status == JobStatus.done and synth == ["j1"]
    job, synth = _job_with(tmp_path / "b", monkeypatch, review=False, flags=UNSURE, uncertain_review=False)
    assert job.status == JobStatus.done and synth == ["j1"]
