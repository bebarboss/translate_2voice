# Quality scorer (offline)

Scores finished dubbing exports. Not part of the app request path. No network or model calls unless the C judge is explicitly enabled (below).

Three **separate** scores, never combined into one number:

| | What | How |
|---|---|---|
| A | Audio (objective) | ffmpeg `ebur128` (integrated LUFS, true peak) + numpy: clipped samples, dub overrunning its slot / running into the next line, background level under speech vs gaps (ducking), voice over background, stereo (L/R correlation, side vs mid) |
| B | Translation rules (objective) | `backend/app/pipeline/translate_quality.py` rule functions (numbers, names vs glossary, sentence-final particles with no source basis, unclear source, idioms) + speaking rate vs slot (syllable budget) |
| C | Naturalness / meaning | LLM judge, **default off**. Rubric per segment: meaning 0/1/2 (wrong/partly/correct), naturalness 1-5, register fit 1-5, short reason. Strict JSON; an invalid reply is a failed row, never a score. `rating_sheet.csv` is the judge's input and stays exported for humans |

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

- `segments.csv`: one row per segment per job, A + B + C fields, `code_version` (git sha, `-dirty` if tools/ or
  backend/app has local changes), `scored_at`, `thresholds` (JSON)
- `jobs_summary.csv` / `jobs_summary.json`: one row per job (pass/fail per check, flag counts); also printed as a table
- `rating_sheet.csv`: C input (rubric columns empty, for humans)
- `spot_check.csv`: seeded sample for the owner to score by hand (see below)
- `clips/` with `--clips`: one WAV per segment cut from the final mix for raters

## C: LLM judge

The judge must be a different model family from the translator: Typhoon and Qwen are always refused
(`QUALITY_JUDGE_BLOCKED`), plus any family named in the app's translator settings (`LLM_MODEL`, Typhoon models).
It talks to any OpenAI-compatible `/chat/completions` endpoint.

```sh
export QUALITY_JUDGE_MODEL=<model id>            # unset = judge off
export QUALITY_JUDGE_BASE_URL=<https://.../v1>   # default https://api.openai.com/v1
export QUALITY_JUDGE_KEY_VAR=MY_KEY_VAR          # name of the env var that holds the key (default QUALITY_JUDGE_API_KEY)
export QUALITY_JUDGE_PRICE_IN=0.40 QUALITY_JUDGE_PRICE_OUT=1.60   # USD per 1M tokens, for the estimate
export QUALITY_JUDGE_MAX_CALLS=200 QUALITY_JUDGE_MAX_TOKENS=300000 # hard caps per run

python -m tools.quality.score <exports> --out <dir> --judge                   # prints the estimate, makes no calls
python -m tools.quality.score <exports> --out <dir> --judge --confirm-spend   # runs, within the caps
```

Estimated cost = calls x (est. input + output tokens) x price per token, i.e.
`sum(input tokens) x PRICE_IN/1M + calls x QUALITY_JUDGE_OUT_TOKENS (120) x PRICE_OUT/1M`. Input tokens are estimated
without a tokenizer (4 ASCII characters = 1 token, every other character, e.g. Thai, = 1 token). When the next call
would pass either cap the run stops, the rest of the rows get `judge_status=skipped_cap` and the reason is printed.

C columns in `segments.csv`: `judge_status` (ok / failed / skipped_cap / estimate_only / off), `judge_meaning`,
`judge_naturalness`, `judge_register`, `judge_reason`, `judge_error`, `judge_model`, `judge_prompt_version`,
`judged_at`, `judge_provisional`, `judge_calibration`.

### Spot check and calibration

Every run writes `spot_check.csv`: a seeded random sample (`--seed`, default 0; `--spot-frac` 10%, `--spot-min` 5)
with the judge's scores beside empty `human_*` columns. The owner fills in the human columns, then:

```sh
python -m tools.quality.judge calibrate <dir>/spot_check.csv --out <dir>/calibration [--judged <dir>/segments.csv]
```

This reports exact and within-1 agreement per rubric field and passes when every field reaches 80% (meaning: exact
agreement, since within 1 is almost free on a 0-2 scale; naturalness and register: within 1). The result is saved per
judge model + prompt version in `QUALITY_JUDGE_CALIBRATION` (default `data/quality/judge_calibration.json`). Judge
scores stay `judge_provisional=True` until a passing calibration exists for the same model and prompt version.
`side_by_side.csv` keeps human and judge scores next to each other.

## Thresholds

`tools/quality/thresholds.py`. Loudness targets are read from `backend/app/audio_constants.py`
(`LOUDNORM_I` = -16 LUFS, `LOUDNORM_TP` = -1.5 dBTP) and the speaking-rate budget from app settings, so the scorer
and the pipeline agree. The values used are written into every output row.

## Tests

```sh
python -m pytest tools/quality/tests -q
```
