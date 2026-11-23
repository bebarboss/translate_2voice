"""Scorer tests. Synthetic WAVs (good / too loud / clipped / overrun) built in a job folder laid out the way
JobStore writes it, plus rule cases from the real Duolingo clip (backend/tests/test_translate_quality_phase2.py).
No network, no model calls.

    python -m pytest tools/quality/tests -q        (from the repo root)
"""
import csv
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tools.quality import audio as A
from tools.quality import exports as E
from tools.quality import rules as R
from tools.quality import score as S
from tools.quality.thresholds import resolved

from app.schemas import Utterance

SR = 48000
DUR = 14.0
# (id, start, end, source, translation)
LINES = [
    (0, 1.0, 3.0, "Hi everyone, welcome back.", "สวัสดีทุกคน ยินดีต้อนรับกลับมา"),
    (1, 5.0, 7.0, "Today we test the mixer.", "วันนี้เราจะทดสอบมิกเซอร์"),
    (2, 9.0, 11.0, "See you next time.", "แล้วพบกันใหม่"),
]

# ---------------------------------------------------------------- Duolingo clip (real case)
TITLE = "Ace the Duolingo English Test Easily"
DUO_SOURCE = "I scored 135! 435. DE Practice AI feedback helped me fix my speaking and writing mistakes."
DUO_BAD = "ฉันได้ 135 คะแนน! 435. ดีอี พรากติส เอไอ ช่วยให้ฉันแก้ข้อผิดพลาดในการพูดและการเขียนได้นะ"
DUO_GOOD = "ฉันได้ 135 คะแนน! 435. ฟีดแบ็กจากเอไอของ DE Practice ช่วยให้ฉันแก้จุดผิดทั้งการพูดและการเขียน"


def _duo(target: str) -> list[Utterance]:
    return [Utterance(id=1, speaker="speaker_01", start=0.0, end=2.0, source="Hi everyone, welcome back.",
                      target="สวัสดีทุกคน ยินดีต้อนรับกลับมา"),
            Utterance(id=2, speaker="speaker_01", start=2.2, end=9.5, source=DUO_SOURCE, target=target),
            Utterance(id=3, speaker="speaker_01", start=9.7, end=11.5, source="Now my score is way higher.",
                      target="ตอนนี้คะแนนฉันสูงขึ้นเยอะเลย")]


def test_duolingo_435_flagged_unclear_and_added_na_flagged():
    rows = R.score_lines(_duo(DUO_BAD), {}, "th")
    r = rows[2]
    assert r["rules_checked"]
    assert r["unclear_source"] >= 1 and "435" in r["rule_reasons"]
    assert r["added_word"] >= 1 and '"นะ"' in r["rule_reasons"]
    assert r["name"] >= 1  # "DE Practice" transliterated as ดีอี พรากติส
    # 135 is kept, so the number rule must not fire on it
    assert "135" not in " ".join(x for x in r["rule_reasons"].split(" | ") if x.startswith("number"))
    # the neighbouring clean lines stay clean
    assert rows[1]["rule_flags"] == 0 and rows[3]["rule_flags"] == 0


def test_duolingo_good_translation_only_keeps_the_unclear_flag():
    r = R.score_lines(_duo(DUO_GOOD), {}, "th")[2]
    assert r["unclear_source"] >= 1  # 435 is a source problem: no translation can fix it
    assert r["added_word"] == 0 and r["name"] == 0 and r["number"] == 0


def test_number_dropped_and_glossary_name_flagged():
    us = [Utterance(id=0, speaker="a", start=0, end=3, source="We sold 250 units to Pakdee.",
                    target="เราขายได้สองร้อยชิ้นให้ปักดี")]
    r = R.score_lines(us, {"glossary": "Pakdee = ภักดี"}, "th")[0]
    assert r["number"] >= 1 and r["name"] >= 1


def test_speaking_rate_over_slot_flagged():
    long = "ฉัน" * 60
    us = [Utterance(id=0, speaker="a", start=0, end=1.0, source="Hi.", target=long),
          Utterance(id=1, speaker="a", start=2, end=5.0, source="Hello there.", target="สวัสดีครับ")]
    rows = R.score_lines(us, {}, "th")
    assert rows[0]["over_rate"] and rows[0]["rate_unit"] == "syllable"
    assert not rows[1]["over_rate"]


def test_no_source_runs_rate_only():
    us = [Utterance(id=0, speaker="", start=0, end=2, source="", target="ได้ 135 คะแนนนะ")]
    r = R.score_lines(us, {}, "th", has_source=False)[0]
    assert not r["rules_checked"] and r["rule_flags"] == 0 and r["rate_units"] > 0


# ---------------------------------------------------------------- synthetic audio
def _tone(seconds: float, f0: float = 180.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
    env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)  # 20 ms fades
    return (0.3 * x * env).astype(np.float32)


def _scale_to(x: np.ndarray, lufs: float, tmp: Path) -> np.ndarray:
    p = tmp / "_probe.wav"
    sf.write(p, x, SR, subtype="FLOAT")
    i = A.ebur128(p)["integrated_lufs"]
    p.unlink()
    return (x * 10 ** ((lufs - i) / 20)).astype(np.float32)


def make_job(root: Path, job_id: str, *, gain_db: float = 0.0, clip: bool = False,
             dub_len: dict[int, float] | None = None, duck: bool = True, mono: bool = False,
             lines=LINES, glossary: str = "") -> Path:
    """job folder as JobStore writes it: job.json, transcript.json, final_audio.wav, dub_voice.wav, bgm.wav, tts/"""
    d = root / job_id
    (d / "tts").mkdir(parents=True)
    n = int(DUR * SR)
    rng = np.random.default_rng(7)
    bgm = (rng.standard_normal((n, 2)) * 0.03).astype(np.float32)  # independent L/R = wide stereo
    voice = np.zeros(n, dtype=np.float32)
    duck_gain = np.ones(n, dtype=np.float32)
    for i, s, e, _, _ in lines:
        dl = (dub_len or {}).get(i, (e - s) * 0.9)
        x = _tone(dl, 150 + 40 * i)
        sf.write(d / "tts" / f"{i:04d}.wav", x, SR, subtype="PCM_16")
        a = int(s * SR)
        voice[a:a + len(x)] += x[: n - a]
        if duck:
            duck_gain[int((s - 0.1) * SR):int((s + dl + 0.1) * SR)] = 0.2  # -14 dB under speech
    mix = voice[:, None] + bgm * duck_gain[:, None]
    if mono:
        mix = np.repeat(mix.mean(axis=1, keepdims=True), 2, axis=1)
    mix = _scale_to(mix, -16.0, d)
    g = 10 ** (gain_db / 20)
    mix = mix * g
    if clip:
        mix = np.clip(mix * 10, -1.0, 1.0)
    sf.write(d / "final_audio.wav", mix, SR, subtype="PCM_16")
    sf.write(d / "dub_voice.wav", voice, SR, subtype="PCM_16")
    sf.write(d / "bgm.wav", bgm, SR, subtype="PCM_16")
    (d / "job.json").write_text(json.dumps({"id": job_id, "target_lang": "th", "glossary": glossary,
                                            "speaker_names": {}, "title": TITLE}), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(
        [{"id": i, "speaker": "speaker_01", "start": s, "end": e, "source": src, "target": tgt}
         for i, s, e, src, tgt in lines], ensure_ascii=False), encoding="utf-8")
    return d


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def scored(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("exports")
    make_job(root, "good")
    make_job(root, "too_loud", gain_db=6.0)
    make_job(root, "clipped", clip=True)
    make_job(root, "overrun", dub_len={1: 3.2})
    make_job(root, "mono_noduck", duck=False, mono=True)
    out = tmp_path_factory.mktemp("out")
    report = S.run(root, out, quiet=True)
    return {"out": out, "jobs": {j["job_id"]: j for j in report["jobs"]}, "report": report}


def test_ffmpeg_runs():
    assert Path(A.ffmpeg_bin()).exists()


def test_good_job_passes_every_audio_check(scored):
    j = scored["jobs"]["good"]
    assert abs(j["integrated_lufs"] - (-16.0)) < 0.5
    assert j["ok_lufs"] and j["ok_true_peak"] and j["ok_clipping"] and j["ok_stereo"] and j["ok_ducking"]
    assert j["clipped_samples"] == 0 and j["segments_overrun"] == 0
    assert j["duck_db"] >= 10  # ~14 dB duck built in


def test_too_loud_fails_lufs_only(scored):
    j = scored["jobs"]["too_loud"]
    assert j["lufs_delta"] > 5 and not j["ok_lufs"]
    assert j["ok_clipping"]


def test_clipped_counts_samples_and_fails_true_peak(scored):
    j = scored["jobs"]["clipped"]
    assert j["clipped_samples"] > 1000 and not j["ok_clipping"]
    assert not j["ok_true_peak"]
    assert j["segments_clipped"] >= 1


def test_overrun_flags_the_long_line_only(scored):
    j = scored["jobs"]["overrun"]
    assert j["segments_overrun"] == 1 and j["ok_lufs"]
    rows = [r for r in _read(scored["out"] / "segments.csv") if r["job_id"] == "overrun"]
    by_id = {r["segment_id"]: r for r in rows}
    assert by_id["1"]["overrun"] == "True" and abs(float(by_id["1"]["overrun_sec"]) - 1.2) < 0.01
    assert by_id["0"]["overrun"] == "False" and by_id["2"]["overrun"] == "False"


def test_mono_and_no_ducking_detected(scored):
    j = scored["jobs"]["mono_noduck"]
    assert not j["ok_stereo"] and j["lr_corr"] > 0.99
    assert not j["ok_ducking"] and abs(j["duck_db"]) < 2


def test_segment_csv_has_provenance_and_both_scores(scored):
    rows = _read(scored["out"] / "segments.csv")
    assert len(rows) == 5 * len(LINES)
    r = rows[0]
    for k in ("code_version", "scored_at", "thresholds", "overrun", "rule_flags", "rate_per_sec"):
        assert r[k] != "", k
    th = json.loads(r["thresholds"])
    assert th["target_lufs"] == -16.0 and th["max_true_peak_dbtp"] == -1.5
    assert "score" not in r  # no combined number


def test_rating_sheet_is_unscored(scored):
    rows = _read(scored["out"] / "rating_sheet.csv")
    assert len(rows) == 5 * len(LINES)
    r = rows[0]
    assert r["source"] and r["translation"] and Path(r["audio_path"]).is_file()
    assert r["meaning_1to5"] == "" and r["naturalness_1to5"] == ""


def test_summary_files_written(scored):
    out = scored["out"]
    assert len(_read(out / "jobs_summary.csv")) == 5
    data = json.loads((out / "jobs_summary.json").read_text(encoding="utf-8"))
    assert data["thresholds"]["target_lufs"] == -16.0 and len(data["jobs"]) == 5


def test_duolingo_job_end_to_end(tmp_path):
    lines = [(1, 0.0, 2.0, "Hi everyone, welcome back.", "สวัสดีทุกคน ยินดีต้อนรับกลับมา"),
             (2, 2.2, 9.5, DUO_SOURCE, DUO_BAD)]
    make_job(tmp_path / "in", "duo", lines=lines)
    S.run(tmp_path / "in", tmp_path / "out", quiet=True)
    row = {r["segment_id"]: r for r in _read(tmp_path / "out" / "segments.csv")}["2"]
    assert int(row["unclear_source"]) >= 1 and "435" in row["rule_reasons"]
    assert int(row["added_word"]) >= 1 and "นะ" in row["rule_reasons"]


# ---------------------------------------------------------------- other export layouts
def test_timeline_export_folder_and_zip(tmp_path):
    job = make_job(tmp_path / "src", "j1")
    tl = tmp_path / "in" / "tl"
    tl.mkdir(parents=True)
    x, _ = sf.read(job / "final_audio.wav", dtype="float32")
    sf.write(tl / "TH_mixdown.wav", x, SR, subtype="PCM_24")
    v, _ = sf.read(job / "dub_voice.wav", dtype="float32")
    sf.write(tl / "TH_1_Host.wav", v, SR, subtype="PCM_24")
    (tl / "TH_dub.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nสวัสดีทุกคน\n\n"
                                   "2\n00:00:05,000 --> 00:00:07,000\nวันนี้เราจะทดสอบ\n", encoding="utf-8")
    import shutil
    shutil.make_archive(str(tmp_path / "in" / "zipped"), "zip", tl)
    rep = S.run(tmp_path / "in", tmp_path / "out", quiet=True)
    kinds = sorted(j["export_kind"] for j in rep["jobs"])
    assert kinds == ["timeline", "timeline"]
    j = rep["jobs"][0]
    assert j["ok_lufs"] and j["segments"] == 2 and not j["rules_checked"]


def test_srt_parse():
    us = E.parse_srt("1\n00:00:01,500 --> 00:00:02,250\nบรรทัด\nสอง\n\n2\n00:01:00.000 --> 00:01:01.000\nสาม\n")
    assert [(u.start, u.end, u.target) for u in us] == [(1.5, 2.25, "บรรทัด สอง"), (60.0, 61.0, "สาม")]


def test_thresholds_come_from_audio_constants():
    from app import audio_constants as ac
    th = resolved()
    assert th["target_lufs"] == ac.LOUDNORM_I and th["max_true_peak_dbtp"] == ac.LOUDNORM_TP
