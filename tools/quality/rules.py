"""B. Translation rule score (objective, rule-visible only). All checks come from
backend/app/pipeline/translate_quality.py; this file only runs them and counts the results."""
import re
from typing import Optional

from app.config import settings
from app.pipeline import translate_quality as Q
from app.schemas import Utterance

RULE_KINDS = ("number", "name", "added_word", "unclear_source", "idiom")


def _rate(u: Utterance, target_lang: str) -> dict:
    slot = max(u.end - u.start, 0.3)
    text = u.target or ""
    if target_lang == "th":
        units = Q.thai_syllables(text)
        budget = Q.syllable_budget(slot)
        nominal = Q.syllables_per_sec()
        limit = budget["max_syllables"]
        unit = "syllable"
    else:
        units = len(re.findall(r"[\w'-]+", text))
        nominal = settings.en_words_per_sec
        limit = max(1, int(slot * nominal * min(settings.max_speedup, settings.fit_tolerance)))
        unit = "word"
    return {"rate_unit": unit, "rate_units": units, "slot_sec": round(slot, 3),
            "rate_per_sec": round(units / slot, 2), "rate_nominal_per_sec": round(nominal, 2),
            "rate_max_units": limit, "over_rate": units > limit}


def score_lines(utts: list[Utterance], hints: Optional[dict], target_lang: str = "th",
                has_source: bool = True) -> dict[int, dict]:
    """id -> rule fields. Without source text only the speaking-rate check can run."""
    ctx = Q.line_context(utts, hints) if has_source else None
    out: dict[int, dict] = {}
    for u in utts:
        row: dict = {k: 0 for k in RULE_KINDS}
        reasons: list[str] = []
        if (u.target or "").strip() and has_source:
            found = list(Q.line_flags(u, ctx))
            for h in Q.idioms_for(u.source):
                found += [("idiom", r) for _, r in h.check(u.target)]
            for kind, reason in found:
                row[kind if kind in row else "idiom"] += 1
                reasons.append(f"{kind}: {reason}")
        row["rules_checked"] = bool(has_source and (u.target or "").strip())
        row["rule_flags"] = sum(row[k] for k in RULE_KINDS)
        row["rule_reasons"] = " | ".join(reasons)
        row["asr_unclear"] = bool(u.unclear)  # transcription itself unsure (pipeline flag)
        row["pipeline_open_flags"] = sum(1 for f in u.qa_flags or [] if not f.get("fixed"))
        row.update(_rate(u, target_lang) if (u.target or "").strip() else
                   {"rate_unit": "", "rate_units": 0, "slot_sec": round(max(u.end - u.start, 0.3), 3),
                    "rate_per_sec": 0.0, "rate_nominal_per_sec": None, "rate_max_units": None, "over_rate": False})
        out[u.id] = row
    return out
