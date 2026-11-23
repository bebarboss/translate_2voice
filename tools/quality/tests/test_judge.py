"""Score C (LLM judge): strict JSON, spend caps, cost estimate gate, seeded spot-check, calibration math.
The LLM is always mocked; no network."""
import csv
import json
from pathlib import Path

import pytest

from tools.quality import judge as J
from tools.quality import score as S
from tools.quality.tests.test_score import DUO_BAD, DUO_SOURCE, make_job

GOOD = '{"meaning": 2, "naturalness": 4, "register": 5, "reason": "Accurate and natural."}'


def _cfg(tmp_path: Path, **kw) -> J.JudgeConfig:
    base = dict(model="gpt-4.1-mini", max_calls=100, max_tokens=10_000_000, price_in=0.4, price_out=1.6,
                calibration=tmp_path / "cal.json")
    base.update(kw)
    return J.JudgeConfig(**base)


def _items(n: int) -> list[dict]:
    return [{"job_id": "j", "segment_id": i, "speaker": "a", "source": f"Line {i}.", "translation": f"บรรทัด {i}"}
            for i in range(n)]


# ---------------------------------------------------------------- JSON parsing
def test_parse_valid():
    assert J.parse_reply(GOOD) == {"meaning": 2, "naturalness": 4, "register": 5, "reason": "Accurate and natural."}


def test_parse_valid_inside_json_fence():
    assert J.parse_reply("```json\n" + GOOD + "\n```")["meaning"] == 2


@pytest.mark.parametrize("reply", [
    "",
    "not json",
    '{"meaning": 2, "naturalness": 4, "register": 5, "reason": "ok"',            # truncated
    "Here is my rating: " + GOOD,                                                 # text before
    GOOD + "\nHope this helps!",                                                  # text after
    "[" + GOOD + "]",                                                             # not an object
    '{"meaning": 3, "naturalness": 4, "register": 5, "reason": "x"}',             # out of range
    '{"meaning": 2, "naturalness": 0, "register": 5, "reason": "x"}',
    '{"meaning": 2, "naturalness": 4.5, "register": 5, "reason": "x"}',           # not an int
    '{"meaning": "2", "naturalness": 4, "register": 5, "reason": "x"}',
    '{"meaning": true, "naturalness": 4, "register": 5, "reason": "x"}',
    '{"meaning": 2, "naturalness": 4, "register": 5}',                            # missing reason
    '{"meaning": 2, "naturalness": 4, "register": 5, "reason": "x", "score": 9}', # extra key
    '{"meaning": 2, "naturalness": 4, "register": 5, "reason": "  "}',
])
def test_parse_invalid(reply):
    with pytest.raises(ValueError):
        J.parse_reply(reply)


def test_invalid_reply_is_a_failed_row_not_a_score(tmp_path):
    replies = iter([GOOD, "Sure! " + GOOD, "garbage"])
    res = J.run_judge(_items(3), _cfg(tmp_path), lambda s, u, c: (next(replies), None))
    st = [res.results[("j", str(i))] for i in range(3)]
    assert st[0]["judge_status"] == "ok" and st[0]["judge_meaning"] == 2
    for r in st[1:]:
        assert r["judge_status"] == "failed" and "invalid JSON" in r["judge_error"]
        assert "judge_meaning" not in r
    assert res.calls == 3


def test_call_error_is_a_failed_row(tmp_path):
    def boom(s, u, c):
        raise TimeoutError("slow")
    r = J.run_judge(_items(1), _cfg(tmp_path), boom).results[("j", "0")]
    assert r["judge_status"] == "failed" and "slow" in r["judge_error"]


# ---------------------------------------------------------------- caps
def test_call_cap_stops_the_run(tmp_path):
    calls = []
    res = J.run_judge(_items(10), _cfg(tmp_path, max_calls=3), lambda s, u, c: (calls.append(1) or GOOD, None))
    assert len(calls) == 3 and res.calls == 3
    assert "call cap" in res.stopped
    st = [res.results[("j", str(i))]["judge_status"] for i in range(10)]
    assert st == ["ok"] * 3 + ["skipped_cap"] * 7


def test_token_cap_stops_before_going_over(tmp_path):
    cfg = _cfg(tmp_path)
    per = sum(J.est_call_tokens(_items(1)[0], cfg))
    cfg.max_tokens = per * 2 + per // 2  # room for 2 calls, not 3
    calls = []
    res = J.run_judge(_items(5), cfg, lambda s, u, c: (calls.append(1) or GOOD, None))
    assert len(calls) == 2 and "token cap" in res.stopped and res.tokens <= cfg.max_tokens


def test_token_cap_counts_reported_usage(tmp_path):
    cfg = _cfg(tmp_path, max_tokens=1000)
    calls = []
    res = J.run_judge(_items(5), cfg, lambda s, u, c: (calls.append(1) or GOOD, {"total_tokens": 800}))
    assert len(calls) == 1 and res.tokens == 800 and "token cap" in res.stopped


def test_estimate_formula(tmp_path):
    cfg = _cfg(tmp_path, max_calls=2)
    items = _items(4)
    est = J.estimate(items, cfg)
    ins = sum(J.est_call_tokens(i, cfg)[0] for i in items)
    assert est.calls == 4 and est.in_tokens == ins and est.out_tokens == 4 * cfg.out_tokens
    assert est.usd == pytest.approx(ins * 0.4 / 1e6 + 4 * cfg.out_tokens * 1.6 / 1e6)
    assert est.capped_calls == 2
    assert "calls x (est. input + output tokens) x price per token" in est.text(cfg)


def test_est_tokens_counts_thai_per_char():
    assert J.est_tokens("abcd") == 1 and J.est_tokens("สวัสดี") == 6


# ---------------------------------------------------------------- family
@pytest.mark.parametrize("model", ["typhoon-v2.1-12b-instruct", "Qwen/Qwen3-32B", "scb10x/llama3.1-typhoon2-8b"])
def test_same_family_rejected(tmp_path, model):
    with pytest.raises(ValueError):
        J.check_family(_cfg(tmp_path, model=model), translators=[])


def test_translator_family_from_settings_rejected(tmp_path):
    with pytest.raises(ValueError):
        J.check_family(_cfg(tmp_path, model="gemma-3-27b-it"), translators=["typhoon2.1-gemma3-12b"])
    J.check_family(_cfg(tmp_path, model="gpt-4.1-mini"), translators=["typhoon-v2.1-12b-instruct"])


def test_config_default_off():
    cfg = J.config_from_env({})
    assert not cfg.enabled and cfg.blocked == ("typhoon", "qwen")
    on = J.config_from_env({"QUALITY_JUDGE_MODEL": "gpt-4.1-mini", "QUALITY_JUDGE_MAX_CALLS": "7",
                            "QUALITY_JUDGE_PRICE_IN": "0.4"})
    assert on.enabled and on.max_calls == 7 and on.price_in == 0.4


# ---------------------------------------------------------------- sampling
def test_spot_sample_reproducible_with_seed():
    keys = [("j", str(i)) for i in range(100)]
    a = J.spot_sample(keys, seed=42)
    assert a == J.spot_sample(list(reversed(keys)), seed=42)  # input order does not matter
    assert len(a) == 10
    assert a != J.spot_sample(keys, seed=43)


def test_spot_sample_minimum_and_small_runs():
    keys = [("j", str(i)) for i in range(20)]
    assert len(J.spot_sample(keys, seed=1)) == 5     # 10% = 2 -> min 5
    assert len(J.spot_sample(keys[:3], seed=1)) == 3  # fewer than min -> all
    assert len(J.spot_sample(keys, seed=1, frac=0.5, minimum=5)) == 10


# ---------------------------------------------------------------- calibration
FAKE = [  # human, judge for meaning / naturalness / register
    ((2, 5, 4), (2, 4, 4)),
    ((2, 4, 4), (2, 4, 5)),
    ((1, 3, 3), (1, 5, 3)),   # naturalness off by 2
    ((0, 2, 3), (1, 2, 3)),   # meaning off by 1
    ((2, 4, 5), (2, 3, 4)),
    ((2, 5, 5), (2, 5, 5)),
    ((1, 3, 4), (1, 3, 4)),
    ((2, 4, 4), (2, 4, 1)),   # register off by 3
    ((2, 5, 4), (2, 5, 4)),
    ((2, 4, 3), (2, 4, 3)),
]


def _rows(pairs):
    out = []
    for i, (h, j) in enumerate(pairs):
        r = {"job_id": "j", "segment_id": str(i)}
        for f, hv, jv in zip(J.FIELDS, h, j):
            r[f"human_{f}"], r[f"judge_{f}"] = str(hv), str(jv)
        out.append(r)
    return out


def test_calibration_math():
    res = J.calibrate(_rows(FAKE))
    m, n, r = (res["fields"][f] for f in J.FIELDS)
    assert m == {"n": 10, "exact": 0.9, "within1": 1.0, "metric": "exact", "passed": True}
    assert n["exact"] == 0.7 and n["within1"] == 0.9 and n["passed"]
    assert r["exact"] == 0.7 and r["within1"] == 0.9 and r["passed"]
    assert res["passed"] and res["pairs"] == 10


def test_calibration_fails_below_80_and_skips_blank_rows():
    bad = FAKE[:5] + [((2, 5, 5), (0, 1, 1))] * 3
    rows = _rows(bad) + [{"job_id": "j", "segment_id": "99", "human_meaning": "", "judge_meaning": "2"}]
    res = J.calibrate(rows)
    assert res["fields"]["meaning"]["n"] == 8 and res["fields"]["meaning"]["exact"] == 0.5
    assert not res["passed"]


def test_calibration_status_makes_scores_final(tmp_path):
    cfg = _cfg(tmp_path)
    r = J.run_judge(_items(1), cfg, lambda s, u, c: (GOOD, None)).results[("j", "0")]
    assert r["judge_provisional"] is True and r["judge_calibration"] == "not calibrated"
    J.save_calibration(cfg, J.calibrate(_rows(FAKE)), "fake.csv")
    r = J.run_judge(_items(1), cfg, lambda s, u, c: (GOOD, None)).results[("j", "0")]
    assert r["judge_provisional"] is False and r["judge_calibration"].startswith(J.PROMPT_VERSION + "@")
    # another prompt version / model is not covered by this calibration
    other = _cfg(tmp_path, model="claude-x")
    assert not J.calibration_status(other)["passed"]


def test_calibrate_cli_side_by_side(tmp_path, monkeypatch):
    rows = _rows(FAKE)
    for r in rows:
        r["judge_model"] = "gpt-4.1-mini"
    p = tmp_path / "spot.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    monkeypatch.delenv("QUALITY_JUDGE_MODEL", raising=False)
    monkeypatch.setenv("QUALITY_JUDGE_CALIBRATION", str(tmp_path / "cal.json"))
    assert J.main(["calibrate", str(p), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "side_by_side.csv").is_file()
    saved = json.loads((tmp_path / "cal.json").read_text())
    assert saved[f"gpt-4.1-mini|{J.PROMPT_VERSION}"]["passed"] is True


# ---------------------------------------------------------------- end to end through the scorer
@pytest.fixture(scope="module")
def exports(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("judge_in")
    make_job(root, "duo", lines=[(1, 0.0, 2.0, "Hi everyone, welcome back.", "สวัสดีทุกคน ยินดีต้อนรับกลับมา"),
                                 (2, 2.2, 9.5, DUO_SOURCE, DUO_BAD),
                                 (3, 9.7, 11.5, "Now my score is way higher.", "ตอนนี้คะแนนฉันสูงขึ้นเยอะเลย")])
    return root


def _read(p: Path) -> list[dict]:
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_judge_flag_alone_only_estimates(exports, tmp_path, capsys):
    calls = []
    rep = S.run(exports, tmp_path, quiet=True, judge=True, judge_cfg=_cfg(tmp_path),
                call=lambda s, u, c: (calls.append(1) or GOOD, None))
    assert calls == []
    assert "estimated cost" in capsys.readouterr().out
    assert rep["judge"]["estimate"]["calls"] == 3
    assert {r["judge_status"] for r in _read(tmp_path / "segments.csv")} == {"estimate_only"}


def test_judge_without_model_refuses(exports, tmp_path):
    with pytest.raises(SystemExit):
        S.run(exports, tmp_path, quiet=True, judge=True, confirm_spend=True, judge_cfg=J.JudgeConfig(model=""))


def test_judge_same_family_refuses(exports, tmp_path):
    with pytest.raises(ValueError):
        S.run(exports, tmp_path, quiet=True, judge=True, confirm_spend=True,
              judge_cfg=_cfg(tmp_path, model="qwen3-32b"), call=lambda s, u, c: (GOOD, None))


def test_judge_results_in_segments_csv_and_spot_check(exports, tmp_path):
    seen = []

    def fake(system, user, cfg):
        seen.append(json.loads(user))
        return GOOD, {"total_tokens": 300}
    rep = S.run(exports, tmp_path, quiet=True, judge=True, confirm_spend=True, judge_cfg=_cfg(tmp_path),
                call=fake, seed=3)
    assert len(seen) == 3
    assert seen[1]["line"]["source"] == DUO_SOURCE and seen[1]["previous"]["source"].startswith("Hi")
    rows = _read(tmp_path / "segments.csv")
    r = rows[1]
    assert r["judge_status"] == "ok" and r["judge_meaning"] == "2" and r["judge_naturalness"] == "4"
    assert r["judge_model"] == "gpt-4.1-mini" and r["judge_prompt_version"] == J.PROMPT_VERSION
    assert r["judged_at"] and r["judge_provisional"] == "True"
    # A and B are still separate columns in the same row
    assert r["unclear_source"] == "1" and r["overrun"] in ("True", "False")
    spot = _read(tmp_path / "spot_check.csv")
    assert len(spot) == 3 and spot[0]["judge_meaning"] == "2" and spot[0]["human_meaning"] == ""
    assert spot[0]["sample_seed"] == "3"
    assert rep["jobs"][0]["judge_ok"] == 3 and rep["judge"]["calls"] == 3
