"""same-lang เติมบท + เกตบทว่าง / coverage ก่อนพากย์"""
from app.pipeline.translate import ensure_same_lang_targets, fill_empty_targets, same_lang
from app.schemas import Utterance


def test_same_lang_matches_prefix():
    assert same_lang("th", "th")
    assert same_lang("th-TH", "th")
    assert same_lang("en", "en")
    assert not same_lang("ja", "th")
    assert not same_lang("", "th")


def test_ensure_same_lang_copies_empty_targets():
    utts = [
        Utterance(id=1, speaker="a", start=0, end=1, source="สวัสดี", target=""),
        Utterance(id=2, speaker="a", start=1, end=2, source="ไปกัน", target="  "),
        Utterance(id=3, speaker="a", start=2, end=3, source="ทักทาย", target="ทักทายแล้ว"),
    ]
    n = ensure_same_lang_targets(utts, "th", "th")
    assert n == 2
    assert utts[0].target == "สวัสดี"
    assert utts[1].target == "ไปกัน"
    assert utts[2].target == "ทักทายแล้ว"


def test_ensure_same_lang_skips_other_language():
    utts = [Utterance(id=1, speaker="a", start=0, end=1, source="Hello", target="")]
    assert ensure_same_lang_targets(utts, "en", "th") == 0
    assert utts[0].target == ""


def test_fill_empty_same_lang_without_api(monkeypatch):
    from app.pipeline import translate as tr
    from dataclasses import replace

    monkeypatch.setattr(tr, "settings", replace(
        tr.settings, typhoon_api_key="", ai_fill_empty=True, mock_pipeline=False))
    utts = [Utterance(id=1, speaker="a", start=0, end=1, source="ว้าว", target="")]
    n = fill_empty_targets(utts, "th", "th")
    assert n == 1
    assert utts[0].target == "ว้าว"
