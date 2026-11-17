"""กล่องที่ผู้ใช้เพิ่ม/ซ้ำแล้วพิมพ์บทเอง ต้องรอดตอนพากย์ใหม่ (เดิมถูกตัดโดย hallucination.clean และถูก repair สร้างใหม่ทับ)"""
import json

from app import quality
from app.pipeline import hallucination
from app.schemas import Utterance


def _u(i, start, end, source="Hello there my friend", target="สวัสดี", speaker="speaker_01"):
    return Utterance(id=i, speaker=speaker, start=start, end=end, source=source, target=target)


def test_clean_keeps_blank_box_with_typed_text():
    box = _u(2, 5.0, 7.0, source="", target="ข้อความที่พิมพ์เอง")
    out = hallucination.clean([_u(1, 0.0, 3.0), box])
    assert [u.id for u in out] == [1, 2] and out[1].target == "ข้อความที่พิมพ์เอง"


def test_clean_keeps_short_box_instead_of_merging_it():
    out = hallucination.clean([_u(1, 0.0, 3.0), _u(2, 3.2, 3.5, source="", target="ใช่")])
    assert [u.id for u in out] == [1, 2] and out[0].target == "สวัสดี"


def test_clean_still_drops_empty_box_without_text_and_real_noise():
    out = hallucination.clean([_u(1, 0.0, 3.0), _u(2, 5.0, 7.0, source="", target="")])
    assert [u.id for u in out] == [1]


def _baseline(tmp_path, utts):
    quality.snapshot(tmp_path, utts)


def test_structure_unchanged_detects_add_duplicate_and_retime(tmp_path):
    base = [_u(1, 0.0, 3.0), _u(2, 4.0, 6.0, speaker="speaker_02")]
    _baseline(tmp_path, base)
    assert quality.structure_unchanged(tmp_path, [u.model_copy() for u in base])
    # แก้เฉพาะข้อความพากย์ ไม่ใช่การแก้โครง
    edited = [u.model_copy(update={"target": "แก้แล้ว"}) for u in base]
    assert quality.structure_unchanged(tmp_path, edited)
    # เพิ่ม/ซ้ำบรรทัด
    assert not quality.structure_unchanged(tmp_path, base + [_u(3, 8.0, 10.0)])
    # เลื่อนเวลา / เปลี่ยนผู้พูด / ตัดบรรทัดออก
    assert not quality.structure_unchanged(tmp_path, [base[0].model_copy(update={"end": 3.5}), base[1]])
    assert not quality.structure_unchanged(tmp_path, [base[0].model_copy(update={"speaker": "speaker_02"}), base[1]])
    assert not quality.structure_unchanged(tmp_path, base[:1])


def test_structure_unknown_without_baseline_is_not_trusted(tmp_path):
    assert not quality.structure_unchanged(tmp_path, [_u(1, 0.0, 3.0)])
    (tmp_path / quality.AI_FILE).write_text("not json", encoding="utf-8")
    assert not quality.structure_unchanged(tmp_path, [_u(1, 0.0, 3.0)])


def test_user_text_ids_marks_added_and_edited_lines_only(tmp_path):
    base = [_u(1, 0.0, 3.0, target="คำแปลของ AI"), _u(2, 4.0, 6.0, target="อีกบรรทัด")]
    quality.snapshot(tmp_path, base)
    now = [base[0].model_copy(), base[1].model_copy(update={"target": "ฉันพิมพ์แก้เอง"}),
           _u(3, 8.0, 12.0, target="สวัสดี ฉันชื่อบอส"),               # สำเนา/กล่องใหม่
           _u(4, 13.0, 14.0, target="")]                                # ไม่มีข้อความ ไม่ต้องล็อก
    assert quality.user_text_ids(tmp_path, now) == {2, 3}


def test_user_text_ids_ignores_pause_marks_and_whitespace(tmp_path):
    base = [_u(1, 0.0, 3.0, target="สวัสดี / ครับ")]
    quality.snapshot(tmp_path, base)
    assert quality.user_text_ids(tmp_path, [base[0].model_copy(update={"target": " สวัสดี  ครับ "})]) == set()


def test_user_text_ids_without_baseline_only_trusts_blank_source_boxes(tmp_path):
    now = [_u(1, 0.0, 3.0, target="x"), _u(2, 5.0, 7.0, source="", target="พิมพ์เอง")]
    assert quality.user_text_ids(tmp_path, now) == {2}
