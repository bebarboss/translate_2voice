"""Score dubbing exports. Three separate scores, never combined:
  A. audio (objective)  B. translation rules (objective)  C. naturalness/meaning: not scored, exported for rating

    python -m tools.quality.score <exports_dir> --out <dir> [--glossary FILE] [--clips]

Writes to <dir>:
  segments.csv      one row per segment per job: A + B fields, code version, date, thresholds
  jobs_summary.csv  one row per job (also jobs_summary.json with thresholds and notes)
  rating_sheet.csv  C: job id, segment id, source, translation, audio path, empty rating columns
  clips/            (--clips) one WAV per segment cut from the final mix, for raters
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import BACKEND  # noqa: F401  (puts backend/ on sys.path)
from . import audio as A
from . import exports as E
from . import rules as R
from .thresholds import resolved

REPO = Path(__file__).resolve().parents[2]

SEGMENT_FIELDS = [
    "job_id", "export_kind", "segment_id", "speaker", "start", "end", "source", "translation",
    # A. audio
    "dub_file", "dub_group_head", "dub_sec", "dub_slot_sec", "overrun_sec", "overrun", "overlap_next_sec",
    "overlaps_next", "seg_clipped_samples", "seg_voice_db", "seg_bg_db", "seg_voice_over_bg_db",
    # B. translation rules
    "rules_checked", "number", "name", "added_word", "unclear_source", "idiom", "rule_flags", "rule_reasons",
    "asr_unclear", "pipeline_open_flags", "rate_unit", "rate_units", "slot_sec", "rate_per_sec",
    "rate_nominal_per_sec", "rate_max_units", "over_rate",
    # provenance
    "code_version", "scored_at", "thresholds",
]
JOB_AUDIO_FIELDS = [
    "final_file", "duration_sec", "sample_rate", "integrated_lufs", "lufs_delta", "true_peak_dbtp",
    "clipped_samples", "channels", "lr_corr", "side_mid_db", "bg_speech_db", "bg_gap_db", "bgm_raw_speech_db",
    "bgm_raw_gap_db", "duck_db", "voice_over_bg_db", "duck_basis",
    "ok_lufs", "ok_true_peak", "ok_clipping", "ok_stereo", "ok_ducking",
]
JOB_FIELDS = (["job_id", "export_kind", "segments", "dubbed"] + JOB_AUDIO_FIELDS +
              ["segments_overrun", "segments_overlap_next", "segments_clipped",
               "rule_number", "rule_name", "rule_added_word", "rule_unclear_source", "rule_idiom",
               "segments_with_rule_flags", "segments_over_rate", "segments_asr_unclear", "rules_checked",
               "notes", "code_version", "scored_at"])
RATING_FIELDS = ["job_id", "segment_id", "speaker", "start", "end", "source", "translation", "audio_path",
                 "audio_start", "audio_end", "meaning_1to5", "naturalness_1to5", "rater", "rater_notes"]


def code_version() -> str:
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "tools", "backend/app"],
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _groups(ex: E.JobExport) -> dict[int, list]:
    """dub line head id -> utterances it covers. With per-line files (tts/NNNN.wav) a file covers its own line
    and the following lines of the same speaker that have no file (the pipeline merges them). Otherwise 1:1."""
    order = sorted(ex.utts, key=lambda u: (u.start, u.id))
    out: dict[int, list] = {}
    head = None
    for u in order:
        if not (u.target or "").strip():
            head = None
            continue
        if not ex.tts or u.id in ex.tts:
            head = u
            out[u.id] = [u]
        elif head is not None and u.speaker == head.speaker:
            out[head.id].append(u)
    return out


def score_job(ex: E.JobExport, th: dict, meta: dict, clips_dir: Optional[Path]) -> tuple[list[dict], dict, list[dict]]:
    speech = [(u.start, u.end) for u in ex.utts if (u.target or "").strip()]
    tr = A.load_tracks(ex.final, ex.voice, ex.bgm) if ex.final or ex.voice else A.Tracks(None, None, None, None)
    job_a, mix, mix_sr = A.job_audio(ex.final, tr, speech, th)
    rules = R.score_lines(ex.utts, ex.hints, ex.target_lang, ex.has_source)
    groups = _groups(ex)
    head_of = {u.id: h for h, us in groups.items() for u in us}
    heads = sorted(groups, key=lambda h: groups[h][0].start)
    next_start = {h: groups[b][0].start for h, b in zip(heads, heads[1:])}
    total = (len(tr.final) if tr.final is not None else len(tr.voice) if tr.voice is not None else 0) / A.ANALYSIS_SR

    # A per dub line (group head)
    seg_a: dict[int, dict] = {}
    for h, us in groups.items():
        start, slot = us[0].start, max(us[-1].end - us[0].start, 0.3)
        row: dict = {"dub_group_head": h, "dub_slot_sec": round(slot, 3), "dub_file": ""}
        dub = None
        if h in ex.tts:
            row["dub_file"] = str(ex.tts[h])
            dub = A.duration(ex.tts[h])
        elif tr.voice is not None:
            dub = A.voice_end(tr.voice, start, next_start.get(h, total), th)
            row["dub_file"] = "voice track (measured)"
        if dub is not None:
            over = dub - slot
            nxt = next_start.get(h)
            ov_next = (start + dub - nxt) if nxt is not None else 0.0
            row.update(dub_sec=round(dub, 3), overrun_sec=round(over, 3),
                       overrun=dub > slot * th["overrun_ratio"] and over >= th["overrun_min_sec"],
                       overlap_next_sec=round(max(0.0, ov_next), 3),
                       overlaps_next=ov_next >= th["overlap_next_min_sec"])
        end = start + max(slot, dub or 0)
        if mix is not None:
            row["seg_clipped_samples"] = A.clipped(mix[int(start * mix_sr):int(end * mix_sr)], th["clip_level"])
        sl = slice(int(start * A.ANALYSIS_SR), int(end * A.ANALYSIS_SR))
        if tr.voice is not None and tr.bed is not None:
            v, b = A.rms_db(tr.voice_gain * tr.voice[sl]), A.rms_db(tr.bed[sl])
            row.update(seg_voice_db=round(v, 2), seg_bg_db=round(b, 2), seg_voice_over_bg_db=round(v - b, 2))
        seg_a[h] = row

    rows, rating = [], []
    for u in sorted(ex.utts, key=lambda u: (u.start, u.id)):
        h = head_of.get(u.id)
        row = {"job_id": ex.job_id, "export_kind": ex.kind, "segment_id": u.id, "speaker": u.speaker,
               "start": round(u.start, 3), "end": round(u.end, 3), "source": u.source, "translation": u.target}
        if h is not None:
            row.update(seg_a[h])
            if h != u.id:  # line merged into an earlier dub file: audio checks belong to the head row
                for k in ("overrun", "overlaps_next", "seg_clipped_samples"):
                    row.pop(k, None)
        row.update(rules[u.id])
        row.update(meta)
        rows.append(row)
        if (u.target or "").strip():
            rating.append(_rating_row(ex, u, h, seg_a.get(h, {}), mix, mix_sr, clips_dir))

    flagged = lambda k: sum(1 for r in rows if r.get(k))  # noqa: E731
    summary = {"job_id": ex.job_id, "export_kind": ex.kind, "segments": len(ex.utts), "dubbed": len(groups),
               **{k: job_a.get(k) for k in JOB_AUDIO_FIELDS},
               "segments_overrun": flagged("overrun"), "segments_overlap_next": flagged("overlaps_next"),
               "segments_clipped": flagged("seg_clipped_samples"),
               **{f"rule_{k}": sum(r[k] for r in rows) for k in R.RULE_KINDS},
               "segments_with_rule_flags": flagged("rule_flags"), "segments_over_rate": flagged("over_rate"),
               "segments_asr_unclear": flagged("asr_unclear"), "rules_checked": ex.has_source,
               "notes": "; ".join(ex.notes), "code_version": meta["code_version"], "scored_at": meta["scored_at"]}
    return rows, summary, rating


def _rating_row(ex, u, h, a: dict, mix, mix_sr: int, clips_dir: Optional[Path]) -> dict:
    a_start = u.start
    a_end = max(u.end, u.start + (a.get("dub_sec") or 0)) if h == u.id else u.end
    path = ""
    if clips_dir is not None and mix is not None:
        import soundfile as sf
        d = clips_dir / re.sub(r"[^\w.-]+", "_", ex.job_id)
        d.mkdir(parents=True, exist_ok=True)
        lo, hi = max(0.0, a_start - 0.2), a_end + 0.3
        p = d / f"{u.id:04d}.wav"
        sf.write(str(p), mix[int(lo * mix_sr):int(hi * mix_sr)], mix_sr)
        path, a_start, a_end = str(p), lo, hi
    elif h == u.id and h in ex.tts:
        path, a_start, a_end = str(ex.tts[h]), 0.0, a.get("dub_sec") or 0.0
    elif ex.final is not None:
        path = str(ex.final)
    return {"job_id": ex.job_id, "segment_id": u.id, "speaker": u.speaker, "start": round(u.start, 3),
            "end": round(u.end, 3), "source": u.source, "translation": u.target, "audio_path": path,
            "audio_start": round(a_start, 3), "audio_end": round(a_end, 3),
            "meaning_1to5": "", "naturalness_1to5": "", "rater": "", "rater_notes": ""}


def _csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel opens Thai text correctly
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def _fmt(v, digits: int = 1) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, bool):
        return "ok" if v else "FAIL"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def print_table(summaries: list[dict], out=sys.stdout) -> None:
    cols = [("job", "job_id"), ("LUFS", "integrated_lufs"), ("dBTP", "true_peak_dbtp"), ("clip", "clipped_samples"),
            ("duck dB", "duck_db"), ("v/bg dB", "voice_over_bg_db"), ("L/R corr", "lr_corr"), ("side dB", "side_mid_db"),
            ("overrun", "segments_overrun"), ("overlap", "segments_overlap_next"),
            ("num", "rule_number"), ("name", "rule_name"), ("particle", "rule_added_word"),
            ("unclear", "rule_unclear_source"), ("fast", "segments_over_rate"), ("segs", "segments")]
    table = [[h for h, _ in cols]] + [[_fmt(s.get(k), 3 if k == "lr_corr" else 1)[:24] for _, k in cols] for s in summaries]
    widths = [max(len(r[i]) for r in table) for i in range(len(cols))]
    print("A = audio, B = translation rules (separate; no combined score). C (naturalness/meaning) -> rating_sheet.csv",
          file=out)
    for i, r in enumerate(table):
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)), file=out)
        if i == 0:
            print("  ".join("-" * w for w in widths), file=out)


def run(exports_dir: Path, out_dir: Path, glossary: str = "", clips: bool = False, quiet: bool = False) -> dict:
    A.ffmpeg_bin()  # fail early with a clear message
    out_dir.mkdir(parents=True, exist_ok=True)
    th = resolved()
    meta = {"code_version": code_version(), "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "thresholds": json.dumps(th, separators=(",", ":"))}
    found = E.discover(exports_dir, out_dir / "_unzipped")
    all_rows, summaries, rating = [], [], []
    for d in found:
        ex = E.load(d, glossary)
        rows, summary, rate = score_job(ex, th, meta, out_dir / "clips" if clips else None)
        all_rows += rows
        summaries.append(summary)
        rating += rate
    _csv(out_dir / "segments.csv", SEGMENT_FIELDS, all_rows)
    _csv(out_dir / "jobs_summary.csv", JOB_FIELDS, summaries)
    _csv(out_dir / "rating_sheet.csv", RATING_FIELDS, rating)
    report = {"code_version": meta["code_version"], "scored_at": meta["scored_at"], "thresholds": th,
              "exports_dir": str(exports_dir), "jobs": summaries}
    (out_dir / "jobs_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                               encoding="utf-8")
    if not quiet:
        print_table(summaries)
        print(f"\n{len(found)} job(s), {len(all_rows)} segment row(s) -> {out_dir}")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.quality.score", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("exports_dir", type=Path, help="folder of job exports (job folders, timeline zips/folders, export zips)")
    p.add_argument("--out", type=Path, required=True, help="output folder")
    p.add_argument("--glossary", type=Path, help='project glossary file, one "source = target # note" per line')
    p.add_argument("--clips", action="store_true", help="cut one WAV per segment from the final mix for raters")
    a = p.parse_args(argv)
    if not a.exports_dir.is_dir():
        p.error(f"not a folder: {a.exports_dir}")
    glossary = a.glossary.read_text(encoding="utf-8") if a.glossary else ""
    report = run(a.exports_dir, a.out, glossary, a.clips)
    return 0 if report["jobs"] else 1


if __name__ == "__main__":
    sys.exit(main())
