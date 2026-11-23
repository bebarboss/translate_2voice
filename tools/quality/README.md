# Quality scorer (offline)

Scores finished dubbing exports. Not part of the app request path; no network, no model calls.

Three **separate** scores, never combined into one number:

| | What | How |
|---|---|---|
| A | Audio (objective) | ffmpeg `ebur128` (integrated LUFS, true peak) + numpy: clipped samples, dub overrunning its slot / running into the next line, background level under speech vs gaps (ducking), voice over background, stereo (L/R correlation, side vs mid) |
| B | Translation rules (objective) | `backend/app/pipeline/translate_quality.py` rule functions (numbers, names vs glossary, sentence-final particles with no source basis, unclear source, idioms) + speaking rate vs slot (syllable budget) |
| C | Naturalness / meaning | **Not scored.** `rating_sheet.csv` lists job, segment, source, translation, audio path with empty rating columns for humans or an LLM later |

## Run

From the repo root, with the backend requirements installed (numpy, soundfile, pydantic) and ffmpeg/ffprobe on
PATH, in `~/.local/bin`, or set via `FFMPEG=` / `FFPROBE=`:

```sh
python -m tools.quality.score <exports_dir> --out <dir> [--glossary FILE] [--clips]
```

`<exports_dir>` may hold any mix of:

1. job folders as JobStore writes them (`data/jobs/<id>/`: `job.json`, `transcript.json`, `final_audio.wav`,
   `dub_voice.wav`, `bgm.wav`, `tts/NNNN.wav`). Full A + B.
2. timeline exports (`timeline/exporter.py` zip or unpacked folder: `TH_mixdown.wav`, `TH_<n>_<name>.wav`, `*.srt`).
   A (no bgm stem, so ducking uses the mix only) + speaking rate; no source text, so the other B rules are skipped.
3. plain exports (`GET /jobs/{id}/export` zip: `<name>.mp4` + `<name>.srt`). Loudness/peak/clip/stereo + speaking rate.

Zips are unpacked to `<out>/_unzipped/`. Each skipped check is noted in the job's `notes`.

Output in `<dir>`:

- `segments.csv`: one row per segment per job, A + B fields, `code_version` (git sha, `-dirty` if tools/ or
  backend/app has local changes), `scored_at`, `thresholds` (JSON)
- `jobs_summary.csv` / `jobs_summary.json`: one row per job (pass/fail per check, flag counts); also printed as a table
- `rating_sheet.csv`: C, for later rating
- `clips/` with `--clips`: one WAV per segment cut from the final mix for raters

## Thresholds

`tools/quality/thresholds.py`. Loudness targets are read from `backend/app/audio_constants.py`
(`LOUDNORM_I` = -16 LUFS, `LOUDNORM_TP` = -1.5 dBTP) and the speaking-rate budget from app settings, so the scorer
and the pipeline agree. The values used are written into every output row.

## Tests

```sh
python -m pytest tools/quality/tests -q
```
