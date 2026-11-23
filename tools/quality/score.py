"""Score dubbing exports. Three separate scores, never combined:
  A. audio (objective)  B. translation rules (objective)  C. naturalness/meaning (LLM judge, default off)

    python -m tools.quality.score <exports_dir> --out <dir> [--glossary FILE] [--clips]
                                  [--judge [--confirm-spend]] [--seed N] [--spot-frac F] [--spot-min N]

Writes to <dir>:
  segments.csv      one row per segment per job: A + B + C fields, code version, date, thresholds, judge model/prompt
  jobs_summary.csv  one row per job (also jobs_summary.json with thresholds, judge config and notes)
  rating_sheet.csv  C input: job id, segment id, source, translation, audio path, empty rubric columns
  spot_check.csv    seeded random sample (default 10%, min 5) with judge scores beside empty human columns;
                    fill it in, then: python -m tools.quality.judge calibrate spot_check.csv
  clips/            (--clips) one WAV per segment cut from the final mix, for raters

C never calls a model unless QUALITY_JUDGE_MODEL is set AND --judge --confirm-spend are given; --judge alone
prints the cost estimate and stops. See tools/quality/judge.py for the env vars and caps.
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
from . import judge as J
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
    # C. naturalness / meaning (LLM judge)
    *J.JUDGE_FIELDS,
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
               "judge_ok", "judge_failed", "judge_skipped", "judge_provisional",
               "notes", "code_version", "scored_at"])
RATING_FIELDS = ["job_id", "segment_id", "speaker", "start", "end", "source", "translation", "audio_path",
                 "audio_start", "audio_end", "meaning_0to2", "naturalness_1to5", "register_1to5", "rater",
                 "rater_notes"]


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
    spoken = [u for u in sorted(ex.utts, key=lambda u: (u.start, u.id)) if (u.target or "").strip()]
    near = {u.id: (a, b) for u, a, b in zip(spoken, [None] + spoken[:-1], spoken[1:] + [None])}
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
            r = _rating_row(ex, u, h, seg_a.get(h, {}), mix, mix_sr, clips_dir)
            a, b = near[u.id]
            r.update(target_lang=ex.target_lang,
                     prev={"source": a.source, "translation": a.target} if a and ex.has_source else None,
                     next={"source": b.source, "translation": b.target} if b and ex.has_source else None)
            rating.append(r)

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
            "meaning_0to2": "", "naturalness_1to5": "", "register_1to5": "", "rater": "", "rater_notes": ""}


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
            ("unclear", "rule_unclear_source"), ("fast", "segments_over_rate"),
            ("C ok", "judge_ok"), ("C fail", "judge_failed"), ("C cap", "judge_skipped"), ("segs", "segments")]
    table = [[h for h, _ in cols]] + [[_fmt(s.get(k), 3 if k == "lr_corr" else 1)[:24] for _, k in cols] for s in summaries]
    widths = [max(len(r[i]) for r in table) for i in range(len(cols))]
    print("A = audio, B = translation rules, C = LLM judge (separate; no combined score; C details in segments.csv)",
          file=out)
    for i, r in enumerate(table):
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)), file=out)
        if i == 0:
            print("  ".join("-" * w for w in widths), file=out)


def judge_step(rating: list[dict], judge: bool, confirm_spend: bool, cfg: J.JudgeConfig,
               call: Optional[J.Caller], quiet: bool) -> tuple[dict, dict]:
    """(job_id, segment_id) -> C fields, and a run report. No model call unless judge AND confirm_spend."""
    keys = [(str(r["job_id"]), str(r["segment_id"])) for r in rating]
    info: dict = {"requested": judge, "confirmed": confirm_spend, **cfg.public()}
    if not judge:
        return {k: J.off_fields("off") for k in keys}, info
    if not cfg.enabled:
        raise SystemExit("--judge needs QUALITY_JUDGE_MODEL (and its key) set; see tools/quality/judge.py")
    J.check_family(cfg)
    est = J.estimate(rating, cfg)
    info["estimate"] = {"calls": est.calls, "in_tokens": est.in_tokens, "out_tokens": est.out_tokens,
                        "usd": round(est.usd, 6), "calls_within_caps": est.capped_calls}
    print(est.text(cfg))
    if not confirm_spend:
        print("estimate only: no judge calls made. Re-run with --confirm-spend to run the judge.")
        return {k: J.off_fields("estimate_only") for k in keys}, info
    res = J.run_judge(rating, cfg, call or J.http_call)
    info.update(calls=res.calls, est_tokens_used=res.tokens, stopped=res.stopped)
    msg = f"judge: {res.calls} call(s), ~{res.tokens} tokens"
    print(msg + (f"; STOPPED: {res.stopped}" if res.stopped else ""), file=sys.stderr if quiet else sys.stdout)
    return res.results, info


def run(exports_dir: Path, out_dir: Path, glossary: str = "", clips: bool = False, quiet: bool = False,
        judge: bool = False, confirm_spend: bool = False, judge_cfg: Optional[J.JudgeConfig] = None,
        call: Optional[J.Caller] = None, seed: int = 0, spot_frac: float = 0.10, spot_min: int = 5) -> dict:
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
    cfg = judge_cfg or J.config_from_env()
    c, judge_info = judge_step(rating, judge, confirm_spend, cfg, call, quiet)
    for r in all_rows:
        r.update(c.get((str(r["job_id"]), str(r["segment_id"])), J.off_fields("no_translation")))
    for s in summaries:
        mine = [r for r in all_rows if r["job_id"] == s["job_id"]]
        st = [r.get("judge_status") for r in mine]
        s.update(judge_ok=st.count("ok"), judge_failed=st.count("failed"), judge_skipped=st.count("skipped_cap"),
                 judge_provisional=any(r.get("judge_provisional") for r in mine if r.get("judge_status") == "ok"))
    spot = spot_check(all_rows, rating, seed, spot_frac, spot_min)
    _csv(out_dir / "segments.csv", SEGMENT_FIELDS, all_rows)
    _csv(out_dir / "jobs_summary.csv", JOB_FIELDS, summaries)
    _csv(out_dir / "rating_sheet.csv", RATING_FIELDS, rating)
    _csv(out_dir / "spot_check.csv", J.SPOT_FIELDS, spot)
    report = {"code_version": meta["code_version"], "scored_at": meta["scored_at"], "thresholds": th,
              "exports_dir": str(exports_dir), "judge": judge_info,
              "spot_check": {"seed": seed, "frac": spot_frac, "min": spot_min, "rows": len(spot)},
              "jobs": summaries}
    (out_dir / "jobs_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                               encoding="utf-8")
    if not quiet:
        print_table(summaries)
        print(f"\n{len(found)} job(s), {len(all_rows)} segment row(s) -> {out_dir}")
    return report


def spot_check(rows: list[dict], rating: list[dict], seed: int, frac: float, minimum: int) -> list[dict]:
    """seeded sample of rated segments: judge scores beside empty human columns for the owner to fill in"""
    by_seg = {(str(r["job_id"]), str(r["segment_id"])): r for r in rows}
    by_rate = {(str(r["job_id"]), str(r["segment_id"])): r for r in rating}
    out = []
    for k in J.spot_sample(list(by_rate), seed, frac, minimum):
        seg, rt = by_seg.get(k, {}), by_rate[k]
        out.append({**{f: seg.get(f, "") for f in J.SPOT_FIELDS if f.startswith("judge_")},
                    **{f: rt.get(f, "") for f in ("job_id", "segment_id", "speaker", "source", "translation",
                                                  "audio_path", "audio_start", "audio_end")},
                    "human_meaning": "", "human_naturalness": "", "human_register": "", "human_notes": "",
                    "sample_seed": seed})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.quality.score", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("exports_dir", type=Path, help="folder of job exports (job folders, timeline zips/folders, export zips)")
    p.add_argument("--out", type=Path, required=True, help="output folder")
    p.add_argument("--glossary", type=Path, help='project glossary file, one "source = target # note" per line')
    p.add_argument("--clips", action="store_true", help="cut one WAV per segment from the final mix for raters")
    p.add_argument("--judge", action="store_true", help="C: LLM judge. Alone it only prints the cost estimate")
    p.add_argument("--confirm-spend", action="store_true", help="with --judge: actually call the judge (within caps)")
    p.add_argument("--seed", type=int, default=0, help="spot-check sample seed (default 0)")
    p.add_argument("--spot-frac", type=float, default=0.10, help="spot-check fraction (default 0.10)")
    p.add_argument("--spot-min", type=int, default=5, help="spot-check minimum rows per run (default 5)")
    a = p.parse_args(argv)
    if a.confirm_spend and not a.judge:
        p.error("--confirm-spend only makes sense with --judge")
    if not a.exports_dir.is_dir():
        p.error(f"not a folder: {a.exports_dir}")
    glossary = a.glossary.read_text(encoding="utf-8") if a.glossary else ""
    report = run(a.exports_dir, a.out, glossary, a.clips, judge=a.judge, confirm_spend=a.confirm_spend,
                 seed=a.seed, spot_frac=a.spot_frac, spot_min=a.spot_min)
    return 0 if report["jobs"] else 1


if __name__ == "__main__":
    sys.exit(main())
