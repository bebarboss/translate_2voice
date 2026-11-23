"""C. Naturalness / meaning: LLM judge (default OFF), spot-check sample and calibration.

The judge is a model from a different family than the translator (Typhoon / Qwen), reached over an
OpenAI-compatible /chat/completions endpoint. It never runs by accident:

  1. QUALITY_JUDGE_MODEL unset          -> judge off, C columns say "off"
  2. --judge                           -> prints the cost estimate and stops (no calls)
  3. --judge --confirm-spend           -> runs, inside a hard cap on calls and estimated tokens per run

Scores are "provisional" until calibration (human vs judge agreement >= 80% per rubric field) has passed for the
same model id + prompt version; see `python -m tools.quality.judge calibrate --help`.

Environment (all optional; defaults in brackets):
  QUALITY_JUDGE_MODEL            judge model id                     [""  = off]
  QUALITY_JUDGE_BASE_URL         OpenAI-compatible base URL         [https://api.openai.com/v1]
  QUALITY_JUDGE_KEY_VAR          NAME of the env var with the key   [QUALITY_JUDGE_API_KEY]
  QUALITY_JUDGE_MAX_CALLS        max calls per run                  [200]
  QUALITY_JUDGE_MAX_TOKENS       max estimated tokens per run       [300000]
  QUALITY_JUDGE_OUT_TOKENS       estimated output tokens per call   [120]
  QUALITY_JUDGE_PRICE_IN         USD per 1M input tokens            [0]
  QUALITY_JUDGE_PRICE_OUT        USD per 1M output tokens           [0]
  QUALITY_JUDGE_BLOCKED          model families the judge may not be [typhoon,qwen]
  QUALITY_JUDGE_CALIBRATION      calibration status file            [data/quality/judge_calibration.json]
"""
import argparse
import csv
import json
import math
import os
import random
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import BACKEND  # noqa: F401  (backend/ on sys.path for app.config)

PROMPT_VERSION = "c-v1"
FIELDS = ("meaning", "naturalness", "register")
RANGES = {"meaning": (0, 2), "naturalness": (1, 5), "register": (1, 5)}
PASS_RATE = 0.80
# meaning is a 3-point scale, so "within 1" is almost free there: it must agree exactly.
PASS_METRIC = {"meaning": "exact", "naturalness": "within1", "register": "within1"}
FAMILIES = ("typhoon", "qwen", "llama", "gemma", "mistral", "mixtral", "gpt", "o1", "o3", "o4", "claude",
            "gemini", "deepseek", "phi", "glm", "command", "grok", "kimi", "yi")

SYSTEM_PROMPT = """You review one line of a dubbed video translation. Score it with this rubric:
- meaning: 0 = wrong (meaning changed, lost, or invented), 1 = partly correct, 2 = correct
- naturalness: 1-5, how natural the translation sounds when spoken by a native speaker (5 = fully natural)
- register: 1-5, how well the tone/politeness fits the speaker and the scene (5 = perfect fit)
- reason: one short sentence in English, at most 25 words
Neighbouring lines are context only; score the "line" object.
Reply with ONE JSON object and nothing else:
{"meaning": <0|1|2>, "naturalness": <1-5>, "register": <1-5>, "reason": "<short>"}"""

JUDGE_FIELDS = ["judge_status", "judge_meaning", "judge_naturalness", "judge_register", "judge_reason",
                "judge_error", "judge_model", "judge_prompt_version", "judged_at", "judge_provisional",
                "judge_calibration"]


# ---------------------------------------------------------------- config
@dataclass
class JudgeConfig:
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    key_var: str = "QUALITY_JUDGE_API_KEY"
    max_calls: int = 200
    max_tokens: int = 300_000
    out_tokens: int = 120
    price_in: float = 0.0    # USD per 1M input tokens
    price_out: float = 0.0   # USD per 1M output tokens
    blocked: tuple[str, ...] = ("typhoon", "qwen")
    calibration: Path = Path("data/quality/judge_calibration.json")

    @property
    def enabled(self) -> bool:
        return bool(self.model.strip())

    def public(self) -> dict:
        """config as written into outputs (no key)"""
        return {"model": self.model, "base_url": self.base_url, "prompt_version": PROMPT_VERSION,
                "max_calls": self.max_calls, "max_tokens": self.max_tokens, "out_tokens": self.out_tokens,
                "price_in_per_mtok": self.price_in, "price_out_per_mtok": self.price_out}


def config_from_env(env: Optional[dict] = None) -> JudgeConfig:
    e = os.environ if env is None else env
    g = lambda k, d: (e.get(k) or "").strip() or d  # noqa: E731
    return JudgeConfig(
        model=g("QUALITY_JUDGE_MODEL", ""), base_url=g("QUALITY_JUDGE_BASE_URL", JudgeConfig.base_url),
        key_var=g("QUALITY_JUDGE_KEY_VAR", JudgeConfig.key_var),
        max_calls=int(g("QUALITY_JUDGE_MAX_CALLS", "200")), max_tokens=int(g("QUALITY_JUDGE_MAX_TOKENS", "300000")),
        out_tokens=int(g("QUALITY_JUDGE_OUT_TOKENS", "120")),
        price_in=float(g("QUALITY_JUDGE_PRICE_IN", "0")), price_out=float(g("QUALITY_JUDGE_PRICE_OUT", "0")),
        blocked=tuple(x.strip().lower() for x in g("QUALITY_JUDGE_BLOCKED", "typhoon,qwen").split(",") if x.strip()),
        calibration=Path(g("QUALITY_JUDGE_CALIBRATION", str(JudgeConfig.calibration))))


def family(model_id: str) -> str:
    """'openai/gpt-4.1-mini' -> 'gpt', 'scb10x/typhoon2.1-gemma3-12b' -> 'typhoon' (first known family named)"""
    s = model_id.lower()
    hits = [(m.start(), f) for f in FAMILIES for m in [re.search(rf"(?<![a-z]){re.escape(f)}", s)] if m]
    return min(hits)[1] if hits else ""


def translator_models() -> list[str]:
    """model ids the pipeline translates with (from app settings)"""
    try:
        from app.config import settings
    except Exception:  # noqa: BLE001  (scorer still works without backend settings)
        return []
    return [m for m in (settings.llm_model, settings.typhoon_translate_model, settings.typhoon_model) if m]


def check_family(cfg: JudgeConfig, translators: Optional[list[str]] = None) -> None:
    """raise if the judge could share a family with the translator (it would grade its own habits)"""
    s = cfg.model.lower()
    banned = set(cfg.blocked)
    for t in translators if translators is not None else translator_models():
        banned |= {f for f in FAMILIES if re.search(rf"(?<![a-z]){re.escape(f)}", t.lower())}
    clash = sorted(f for f in banned if re.search(rf"(?<![a-z]){re.escape(f)}", s))
    if clash:
        raise ValueError(f"judge model {cfg.model!r} is in the translator's family ({', '.join(clash)}); "
                         "pick a model from another family")


# ---------------------------------------------------------------- prompt + tokens
def est_tokens(text: str) -> int:
    """conservative token estimate without a tokenizer: ~4 ASCII chars per token, 1 token per other char (Thai)"""
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return math.ceil(ascii_n / 4) + (len(text) - ascii_n)


def user_message(item: dict) -> str:
    return json.dumps({"target_language": item.get("target_lang") or "th",
                       "previous": item.get("prev") or None, "next": item.get("next") or None,
                       "line": {"speaker": item.get("speaker") or "", "source": item.get("source") or "",
                                "translation": item.get("translation") or ""}}, ensure_ascii=False)


def est_call_tokens(item: dict, cfg: JudgeConfig) -> tuple[int, int]:
    return est_tokens(SYSTEM_PROMPT) + est_tokens(user_message(item)) + 8, cfg.out_tokens


@dataclass
class Estimate:
    calls: int
    in_tokens: int
    out_tokens: int
    usd: float
    capped_calls: int  # calls the caps allow (<= calls)

    def text(self, cfg: JudgeConfig) -> str:
        return (f"judge {cfg.model or '(off)'} prompt {PROMPT_VERSION}: {self.calls} call(s), "
                f"~{self.in_tokens} input + ~{self.out_tokens} output tokens\n"
                f"estimated cost = calls x (est. input + output tokens) x price per token\n"
                f"               = {self.in_tokens} x ${cfg.price_in}/1M + {self.out_tokens} x ${cfg.price_out}/1M"
                f" = ${self.usd:.4f}\n"
                f"caps: {cfg.max_calls} calls, {cfg.max_tokens} est. tokens per run -> "
                f"{self.capped_calls} of {self.calls} call(s) would run")


def estimate(items: list[dict], cfg: JudgeConfig) -> Estimate:
    ti = to = 0
    allowed, used = 0, 0
    for it in items:
        i, o = est_call_tokens(it, cfg)
        ti, to = ti + i, to + o
        if allowed < cfg.max_calls and used + i + o <= cfg.max_tokens:
            allowed, used = allowed + 1, used + i + o
    usd = ti * cfg.price_in / 1e6 + to * cfg.price_out / 1e6
    return Estimate(len(items), ti, to, usd, allowed)


# ---------------------------------------------------------------- strict JSON
_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.S)


def parse_reply(text: str) -> dict:
    """strict: the reply must be exactly one JSON object (a ```json fence around it is tolerated).
    Any other text around it, missing/extra keys, wrong types or out-of-range values -> ValueError."""
    s = (text or "").strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a single JSON object: {exc.msg}") from None
    if not isinstance(obj, dict):
        raise ValueError("JSON is not an object")
    keys = set(obj)
    want = set(FIELDS) | {"reason"}
    if keys != want:
        raise ValueError(f"keys must be {sorted(want)}, got {sorted(keys)}")
    out = {}
    for k in FIELDS:
        v = obj[k]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{k} must be an integer, got {v!r}")
        lo, hi = RANGES[k]
        if not lo <= v <= hi:
            raise ValueError(f"{k}={v} outside {lo}-{hi}")
        out[k] = v
    if not isinstance(obj["reason"], str) or not obj["reason"].strip():
        raise ValueError("reason must be a non-empty string")
    out["reason"] = obj["reason"].strip()[:300]
    return out


# ---------------------------------------------------------------- calling
Caller = Callable[[str, str, JudgeConfig], tuple[str, Optional[dict]]]


def http_call(system: str, user: str, cfg: JudgeConfig) -> tuple[str, Optional[dict]]:
    """OpenAI-compatible chat completion -> (reply text, usage dict or None)"""
    key = os.environ.get(cfg.key_var, "")
    if not key:
        raise RuntimeError(f"judge API key missing: set {cfg.key_var}")
    body = json.dumps({"model": cfg.model, "temperature": 0, "max_tokens": max(cfg.out_tokens * 2, 200),
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(cfg.base_url.rstrip("/") + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"] or "", data.get("usage")


@dataclass
class RunResult:
    results: dict = field(default_factory=dict)  # (job_id, segment_id) -> judge fields
    calls: int = 0
    tokens: int = 0
    stopped: str = ""  # why the run stopped early ("" = all items done)


def calibration_status(cfg: JudgeConfig) -> dict:
    """{'passed': bool, 'id': str} for this model + prompt version (anything else = not calibrated)"""
    try:
        data = json.loads(cfg.calibration.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"passed": False, "id": ""}
    rec = data.get(f"{cfg.model}|{PROMPT_VERSION}") or {}
    return {"passed": bool(rec.get("passed")), "id": rec.get("id", "")}


def run_judge(items: list[dict], cfg: JudgeConfig, call: Caller = http_call) -> RunResult:
    """judge each item until done or a cap is hit. A cap stops the run (remaining items -> skipped_cap)."""
    cal = calibration_status(cfg)
    base = {"judge_model": cfg.model, "judge_prompt_version": PROMPT_VERSION,
            "judge_provisional": not cal["passed"], "judge_calibration": cal["id"] or "not calibrated"}
    res = RunResult()
    for it in items:
        key = (str(it["job_id"]), str(it["segment_id"]))
        i, o = est_call_tokens(it, cfg)
        if not res.stopped:
            if res.calls >= cfg.max_calls:
                res.stopped = f"call cap reached ({cfg.max_calls})"
            elif res.tokens + i + o > cfg.max_tokens:
                res.stopped = f"token cap reached ({res.tokens} used + ~{i + o} next > {cfg.max_tokens})"
        if res.stopped:
            res.results[key] = {**base, "judge_status": "skipped_cap", "judge_error": res.stopped}
            continue
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        res.calls += 1
        try:
            text, usage = call(SYSTEM_PROMPT, user_message(it), cfg)
        except Exception as exc:  # noqa: BLE001  (one failed call = one failed row)
            res.tokens += i + o
            res.results[key] = {**base, "judge_status": "failed", "judge_error": f"call: {exc}"[:300],
                                "judged_at": now}
            continue
        used = (usage or {}).get("total_tokens")
        res.tokens += int(used) if isinstance(used, (int, float)) and used > 0 else i + o
        try:
            p = parse_reply(text)
        except ValueError as exc:
            res.results[key] = {**base, "judge_status": "failed", "judge_error": f"invalid JSON: {exc}"[:300],
                                "judged_at": now}
            continue
        res.results[key] = {**base, "judge_status": "ok", "judge_meaning": p["meaning"],
                            "judge_naturalness": p["naturalness"], "judge_register": p["register"],
                            "judge_reason": p["reason"], "judged_at": now}
    return res


def off_fields(reason: str = "off") -> dict:
    return {"judge_status": reason, "judge_prompt_version": PROMPT_VERSION}


# ---------------------------------------------------------------- spot-check sample
SPOT_FIELDS = ["job_id", "segment_id", "speaker", "source", "translation", "audio_path", "audio_start", "audio_end",
               "judge_status", "judge_meaning", "judge_naturalness", "judge_register", "judge_reason",
               "human_meaning", "human_naturalness", "human_register", "human_notes",
               "judge_model", "judge_prompt_version", "sample_seed"]


def spot_sample(keys: list, seed: int, frac: float = 0.10, minimum: int = 5) -> list:
    """seeded random sample: max(minimum, ceil(frac * n)) keys (all of them if fewer), in input order"""
    keys = sorted(keys, key=lambda k: (str(k[0]), int(k[1]) if str(k[1]).lstrip("-").isdigit() else str(k[1])))
    k = min(len(keys), max(minimum, math.ceil(frac * len(keys))))
    picked = set(random.Random(seed).sample(range(len(keys)), k))
    return [x for i, x in enumerate(keys) if i in picked]


# ---------------------------------------------------------------- calibration
def _int(v) -> Optional[int]:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def agreement(pairs: list[tuple[Optional[int], Optional[int]]]) -> dict:
    """pairs of (human, judge); pairs with either side missing are left out"""
    ok = [(h, j) for h, j in pairs if h is not None and j is not None]
    n = len(ok)
    exact = sum(1 for h, j in ok if h == j)
    within = sum(1 for h, j in ok if abs(h - j) <= 1)
    return {"n": n, "exact": round(exact / n, 4) if n else None, "within1": round(within / n, 4) if n else None}


def calibrate(rows: list[dict], pass_rate: float = PASS_RATE) -> dict:
    """rows need human_<field> and judge_<field> columns (spot-check sheet filled in by the owner)"""
    fields = {}
    for f in FIELDS:
        a = agreement([(_int(r.get(f"human_{f}")), _int(r.get(f"judge_{f}"))) for r in rows])
        metric = PASS_METRIC[f]
        a["metric"] = metric
        a["passed"] = a["n"] > 0 and a[metric] is not None and a[metric] >= pass_rate
        fields[f] = a
    return {"pass_rate": pass_rate, "fields": fields, "passed": all(v["passed"] for v in fields.values()),
            "pairs": min((v["n"] for v in fields.values()), default=0)}


def save_calibration(cfg: JudgeConfig, result: dict, source: str) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec = {"id": f"{PROMPT_VERSION}@{now}", "model": cfg.model, "prompt_version": PROMPT_VERSION,
           "passed": result["passed"], "calibrated_at": now, "source": source,
           "pass_rate": result["pass_rate"], "fields": result["fields"]}
    try:
        data = json.loads(cfg.calibration.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[f"{cfg.model}|{PROMPT_VERSION}"] = rec
    cfg.calibration.parent.mkdir(parents=True, exist_ok=True)
    cfg.calibration.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def _read_csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def merge_judge(human: list[dict], judged: list[dict]) -> list[dict]:
    """fill missing judge_* columns of the human sheet from a segments.csv (joined on job_id + segment_id)"""
    by = {(r.get("job_id"), str(r.get("segment_id"))): r for r in judged}
    out = []
    for r in human:
        j = by.get((r.get("job_id"), str(r.get("segment_id"))), {})
        out.append({**{k: v for k, v in j.items() if k.startswith("judge_")},
                    **{k: v for k, v in r.items() if v not in (None, "")}})
    return out


def main_calibrate(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.quality.judge calibrate",
                                description="human vs judge agreement; marks the judge calibrated when every "
                                            f"rubric field reaches {PASS_RATE:.0%} (meaning: exact, others: within 1)")
    p.add_argument("human_csv", type=Path, help="spot_check.csv with human_* columns filled in")
    p.add_argument("--judged", type=Path, help="segments.csv to take judge_* scores from when the sheet has none")
    p.add_argument("--out", type=Path, help="write side_by_side.csv + calibration_report.json here")
    p.add_argument("--no-save", action="store_true", help="report only, do not update the calibration status file")
    a = p.parse_args(argv)
    cfg = config_from_env()
    rows = _read_csv(a.human_csv)
    if a.judged:
        rows = merge_judge(rows, _read_csv(a.judged))
    models = {r.get("judge_model") for r in rows if r.get("judge_model")}
    if models and cfg.model and models != {cfg.model}:
        p.error(f"sheet was judged by {sorted(models)}, QUALITY_JUDGE_MODEL is {cfg.model!r}")
    if not cfg.model and len(models) == 1:
        cfg.model = models.pop()
    res = calibrate(rows)
    print(f"calibration: judge {cfg.model or '?'} prompt {PROMPT_VERSION}, {res['pairs']} scored pair(s)")
    for f, v in res["fields"].items():
        fmt = lambda x: "-" if x is None else f"{x:.0%}"  # noqa: E731
        print(f"  {f:<12} n={v['n']:<4} exact={fmt(v['exact']):<5} within1={fmt(v['within1']):<5} "
              f"pass on {v['metric']} >= {PASS_RATE:.0%}: {'yes' if v['passed'] else 'NO'}")
    print("result:", "PASSED - judge scores are final" if res["passed"] else "NOT PASSED - judge scores stay provisional")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        cols = ["job_id", "segment_id", "source", "translation"] + [
            c for f in FIELDS for c in (f"human_{f}", f"judge_{f}")] + ["judge_reason", "human_notes"]
        with open(a.out / "side_by_side.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        (a.out / "calibration_report.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    if not a.no_save and cfg.model:
        rec = save_calibration(cfg, res, str(a.human_csv))
        print(f"saved {rec['id']} -> {cfg.calibration}")
    return 0 if res["passed"] else 2


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["calibrate"]:
        return main_calibrate(argv[1:])
    print("usage: python -m tools.quality.judge calibrate <spot_check.csv> [--judged segments.csv] [--out DIR]\n"
          "judge runs from the scorer: python -m tools.quality.score <exports> --out <dir> --judge [--confirm-spend]",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
