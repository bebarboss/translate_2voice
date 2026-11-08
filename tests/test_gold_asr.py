"""Regression จากชุดคลิปทอง — ห้ามถอย recall ของแท็ก shout/child"""
from app.gold import ROOT, list_cases, load_case, record_corrections, score_all, score_case
from app.schemas import Utterance


def test_gold_fixtures_exist():
    cases = list_cases(ROOT)
    assert len(cases) >= 4
    names = {p.name for p in cases}
    assert "shout_orphan_th" in names
    assert "child_gap_th" in names


def test_gold_shout_and_child_pass():
    """เคสแท็ก shout/child ต้องผ่าน min_recall — กัน VAD/repair ถอย"""
    for tag in ("shout", "child"):
        summary = score_all(ROOT, tag=tag)
        assert summary["n"] >= 1, tag
        failed = [c["id"] for c in summary["cases"] if not c["pass"]]
        assert not failed, f"แท็ก {tag} ถอย: {failed} mean={summary['mean_recall']}"


def test_gold_repair_rebuilds_orphan():
    case = load_case(ROOT / "shout_orphan_th")
    result = score_case(case)
    assert result["pass"] is True
    assert result["recall"] >= 0.8
    assert result["hit"] == result["n_expected"]


def test_record_corrections_writes_diff(tmp_path, monkeypatch):
    corr = tmp_path / "corrections"
    corr.mkdir()
    monkeypatch.setattr("app.gold.corrections_dir", lambda: corr)
    before = [
        Utterance(id=1, speaker="speaker_01", start=1.0, end=2.0, source="hello", target="สวัสดี"),
        Utterance(id=2, speaker="speaker_01", start=3.0, end=4.0, source="wow", target="ว้าว"),
    ]
    after = [
        Utterance(id=1, speaker="speaker_01", start=1.0, end=2.0, source="hello", target="สวัสดีครับ"),
        Utterance(id=2, speaker="speaker_02", start=3.2, end=4.1, source="wow", target="ว้าว"),
    ]
    path = record_corrections("jobabc", before, after, stage="review")
    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "jobabc" in text
    assert "target" in text
    assert "speaker" in text or "time" in text
    # ไม่มี diff → ไม่เขียน
    assert record_corrections("jobabc", after, after) is None
