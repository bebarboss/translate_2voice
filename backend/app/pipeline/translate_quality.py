"""คุณภาพคำแปลไทย ระยะที่ 1 (ใช้โมเดลและผู้ให้บริการเดิม)

- งบความยาวต่อบรรทัด: จำนวนพยางค์ไทยเป้าหมายจากเวลาของช่อง (สอดคล้องกับความเร็ว TTS ที่ใช้ย่อบท)
- คำใบ้สำนวน (idiom hints): ต้นฉบับที่มีสำนวนซึ่งเคยแปลผิด ส่งคำอธิบายความหมายให้ผู้แปล และใช้ตรวจคำแปลแบบกฎ
- แปลทั้งฉาก (scene mode): ส่งบรรทัดของฉากพร้อมเวลา ผู้พูด และบทข้างเคียงในคำขอเดียว ตอบ JSON ตาม id บรรทัด
  ตรวจรูปแบบเข้ม ๆ บรรทัดที่ตอบไม่ผ่านแปลแบบเดิม (_translate_groups) ทีละประโยค
- ตรวจตัวเอง (self-check): หลังแปล เทียบทุกบรรทัดกับต้นฉบับ (กฎ + โมเดล) ติดป้ายพร้อมเหตุผล
  แล้วเขียนใหม่เฉพาะบรรทัดที่ติดป้าย ไม่เกิน 1 รอบ ป้ายทั้งหมดเก็บใน Utterance.qa_flags (ที่ยังไม่ผ่านขึ้น check_note ด้วย)

ทุกอย่างเปิด/ปิดได้ใน defaults.py (TRANSLATE_SCENE_MODE, TRANSLATE_SELF_CHECK, TRANSLATE_SYLLABLE_BUDGET,
TRANSLATE_IDIOM_HINTS, TRANSLATE_RULE_FLAGS)
"""
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional

from ..config import settings
from ..schemas import Utterance
from . import translate as T

log = logging.getLogger("dubbing.translate.quality")


# ---------------------------------------------------------------- งบความยาว (พยางค์)
def thai_base_chars(text: str) -> int:
    """ตัวอักษรที่นับเวลาพูด แบบเดียวกับ translate.estimate_seconds (ไม่นับสระบนล่าง วรรณยุกต์ ช่องว่าง และ /)"""
    return sum(1 for ch in text if not ch.isspace() and ch != "/" and unicodedata.category(ch) != "Mn")


def thai_syllables(text: str) -> int:
    """ประมาณจำนวนพยางค์ของบทไทย: ภาษาไทยพูดเฉลี่ยราว THAI_CHARS_PER_SYLLABLE ตัวอักษรฐานต่อพยางค์
    (เช่น "ทั้งโลกคอยบอกว่าเธอควรทำอะไรกับร่างกายตัวเอง" = 38 ตัว / 15 พยางค์)"""
    n = thai_base_chars(text)
    return 0 if n == 0 else max(1, round(n / settings.thai_chars_per_syllable))


def syllables_per_sec() -> float:
    """ความเร็วพูดปกติเป็นพยางค์/วินาที อิงค่าเดียวกับที่ใช้ย่อบท (THAI_CHARS_PER_SEC) ไม่แยกค่ากัน"""
    return settings.thai_chars_per_sec / settings.thai_chars_per_syllable


def syllable_budget(seconds: float, max_speedup: Optional[float] = None) -> dict:
    """target = พูดเต็มช่องด้วยความเร็วปกติ, max = มากสุดที่ยังพอดีเมื่อเร่งเสียงได้ไม่เกิน max_speedup
    ให้โมเดลเลือกคำให้สั้นก่อน แทนที่จะไปยืด/เร่งเสียงทีหลัง"""
    speed = settings.max_speedup if max_speedup is None else max_speedup
    rate = syllables_per_sec()
    return {"target_syllables": max(1, int(seconds * rate)),
            "max_syllables": max(1, int(seconds * rate * min(speed, settings.fit_tolerance)))}


def over_budget(u: Utterance, seconds: float) -> bool:
    return thai_syllables(u.target) > syllable_budget(seconds)["max_syllables"]


# ---------------------------------------------------------------- สำนวนที่รู้ว่าแปลผิดบ่อย
@dataclass(frozen=True)
class IdiomHint:
    key: str
    source: re.Pattern  # จับในต้นฉบับ (ตัวเล็ก)
    hint: str  # คำอธิบายความหมายให้ผู้แปล/ผู้ตรวจ
    check: Callable[[str], list[tuple[str, str]]]  # คำแปล → [(kind, reason)] ว่าง = ผ่าน


def _check_dress_fast(target: str) -> list[tuple[str, str]]:
    if re.search(r"เร็ว", target):
        return [("meaning", '"too fast" ของชุดแปลว่าโป๊/แรง/ยั่วเกินไป ไม่ใช่ "เร็ว"')]
    return []


def _check_body_control(target: str) -> list[tuple[str, str]]:
    if "ร่างกาย" not in target and "ตัวเอง" not in target:
        return []
    out: list[tuple[str, str]] = []
    if re.search(r"ร่างกาย(?:ตัวเอง|ของ(?:ตัวเอง|เธอ|ฉัน))?\s*(?:ก็)?ได้", target) or "ก็ได้" in target:
        out.append(("meaning", "ความหมายกลับด้าน: ต้นฉบับคือคนอื่นคอยบอกว่าควรทำอะไรกับร่างกายตัวเอง ไม่ใช่ทำอะไรก็ได้"))
    elif not re.search(r"บอก|สั่ง|กำหนด|ชี้นิ้ว|ตัดสิน", target):
        out.append(("meaning", 'ใจความ "ทั้งโลกคอยบอก" หายไป เหลือแค่ "ต้องทำอะไร" ซึ่งไม่ใช่คนอื่นมาควบคุม'))
    if "ร่างกาย" in target and not re.search(r"ร่างกาย(?:ตัวเอง|ของ)", target):
        out.append(("naturalness", 'แปลตรงตัวห้วน ๆ "ร่างกาย" ควรเป็น "ร่างกายตัวเอง" แบบที่คนพูด'))
    return out


IDIOMS: tuple[IdiomHint, ...] = (
    IdiomHint(
        key="dress_too_fast",
        source=re.compile(r"\btoo fast\b.*\b(?:short|shiny|tight|revealing|low)\b|"
                          r"\b(?:dress|skirt|outfit|clothes|top)\b.*\btoo fast\b"),
        hint='"too fast" เมื่อพูดถึงชุด/การแต่งตัวผู้หญิง เป็นสแลง แปลว่า โป๊/แรง/ยั่วเกินไป (ดูไม่เรียบร้อย) ไม่ใช่ "เร็วเกินไป" '
             'เช่น "too fast, too short, too shiny" → "โป๊ไป สั้นไป แวววาวไป"',
        check=_check_dress_fast),
    IdiomHint(
        key="body_control",
        source=re.compile(r"\btell(?:ing|s)? (?:you|her|me|us) what to do with (?:your|her|my|our) (?:own )?bod(?:y|ies)\b"),
        hint='"telling you what to do with your body" = คนอื่นคอยบอก/สั่งว่าเธอ "ควร" ทำอะไรกับร่างกายตัวเอง (ถูกควบคุม) '
             'ไม่ใช่ "ทำอะไรก็ได้" และต้องมีคนที่คอยบอก เช่น "ทั้งโลกคอยบอกว่าเธอควรทำอะไรกับร่างกายตัวเอง"',
        check=_check_body_control),
)


def idioms_for(source: str) -> list[IdiomHint]:
    s = (source or "").lower()
    return [h for h in IDIOMS if h.source.search(s)]


def idiom_hints(sources: list[str]) -> list[str]:
    """คำใบ้ที่ตรงกับต้นฉบับในชุดนี้ (ไม่ซ้ำ) ว่างถ้าปิด TRANSLATE_IDIOM_HINTS"""
    if not settings.translate_idiom_hints:
        return []
    out: list[str] = []
    for s in sources:
        for h in idioms_for(s):
            if h.hint not in out:
                out.append(h.hint)
    return out


# ---------------------------------------------------------------- ป้ายตรวจ
def add_flag(u: Utterance, origin: str, kind: str, reason: str, *, fixed: bool = False, before: str = "") -> None:
    """origin: rule | self_check | verify; kind: meaning | naturalness | length"""
    flag = {"origin": origin, "kind": kind, "reason": reason[:200], "fixed": fixed, **({"before": before} if before else {})}
    if not any(f.get("origin") == origin and f.get("reason") == flag["reason"] for f in u.qa_flags):
        u.qa_flags.append(flag)


def note_unresolved(u: Utterance, reason: str) -> None:
    """ป้ายที่ยังไม่ได้แก้ → check_note / unclear_reason (ช่องที่หน้าตรวจบทแสดงอยู่แล้ว)"""
    if reason in (u.check_note or ""):
        return
    u.check_note = f"{u.check_note}; {reason}".strip("; ") if u.check_note else reason
    u.unclear_reason = u.unclear_reason or reason


def rule_flags(utts: list[Utterance]) -> dict[int, list[tuple[str, str]]]:
    """id → [(kind, reason)] จากสำนวนที่รู้ว่าแปลผิดบ่อย ไม่เรียกโมเดล"""
    out: dict[int, list[tuple[str, str]]] = {}
    for u in utts:
        if not (u.target or "").strip():
            continue
        for h in idioms_for(u.source):
            found = h.check(u.target)
            if found:
                out.setdefault(u.id, []).extend(found)
    return out


# ---------------------------------------------------------------- แปลทั้งฉาก
SCENE_RULE_TH = """
15. (โหมดแปลทั้งฉาก) lines คือบรรทัดของฉากเดียวกันเรียงตามเวลา start/end เป็นวินาที speaker คือผู้พูด sentence บอกว่าบรรทัดไหนเป็นประโยคเดียวกันที่ถูกตัดตามเวลา
    อ่านทั้งฉากก่อนแปลเพื่อให้ความหมาย สรรพนาม และน้ำเสียงต่อกัน แต่แปลแต่ละบรรทัดจาก source ของบรรทัดนั้นเท่านั้น
    ตอบทุก id ใน lines ครบ ห้ามตอบ id ของ previous_lines/next_lines ห้ามรวมหรือแยกบรรทัด"""

LENGTH_RULE_TH = """
16. แต่ละบรรทัดมี target_syllables (จำนวนพยางค์ที่พูดเต็มช่องเวลาด้วยความเร็วปกติ) และ max_syllables (มากสุดที่ยังพูดทัน)
    เลือกคำให้ได้ราว target_syllables ห้ามเกิน max_syllables ถ้ายาวเกินให้เรียบเรียงใหม่ให้สั้น (ตัดคำเสริม คำซ้ำ) ตั้งแต่ตอนแปล
    อย่าปล่อยให้ยาวแล้วไปเร่งเสียงทีหลัง แต่ห้ามตัดชื่อ ตัวเลข คำปฏิเสธ หรือใจความ"""

IDIOM_RULE_TH = """
17. idioms คือคำอธิบายสำนวน/สแลงในต้นฉบับที่มักแปลผิด ให้แปลตามความหมายที่อธิบายไว้ ไม่แปลตามตัวอักษร"""


def _scene_lines(groups: list[list[Utterance]], hints: dict, budget: dict[int, float]) -> list[dict]:
    out = []
    for g in groups:
        for u in g:
            sec = budget.get(u.id, u.duration)
            out.append({"id": u.id, "sentence": g[0].id, "start": round(u.start, 2), "end": round(u.end, 2),
                        "speaker": T._speaker_label(u.speaker, hints), "seconds": round(sec, 1),
                        **syllable_budget(sec), "max_chars": T.max_length(sec, "th"),
                        "source": (hints.get("marked") or {}).get(u.id, u.source),
                        **({"likely_said": hints["asr_fixes"][u.id]} if u.id in (hints.get("asr_fixes") or {}) else {})})
    return out


def split_scenes(groups: list[list[Utterance]], max_lines: Optional[int] = None,
                 gap: Optional[float] = None) -> list[list[list[Utterance]]]:
    """แบ่งประโยค (กลุ่มท่อน) เป็นฉาก: ตัดเมื่อเงียบนานกว่า gap วินาที หรือบรรทัดเกิน max_lines (ไม่ตัดกลางประโยค)"""
    max_lines = max_lines or settings.translate_scene_max_lines
    gap = settings.translate_scene_gap_sec if gap is None else gap
    scenes: list[list[list[Utterance]]] = []
    cur: list[list[Utterance]] = []
    for g in groups:
        if cur and (g[0].start - cur[-1][-1].end > gap or sum(map(len, cur)) + len(g) > max_lines):
            scenes.append(cur)
            cur = []
        cur.append(g)
    if cur:
        scenes.append(cur)
    return scenes


def scene_prompt(scene: list[list[Utterance]], lang: str, title: str, hints: dict,
                 before: list[Utterance], after: list[Utterance]) -> tuple[str, str]:
    """ระบบ + ข้อความผู้ใช้ของการแปลทั้งฉาก before/after คือบรรทัดซ้อนทับ (overlap) จากฉากข้างเคียง ไว้ดูบริบท"""
    budget = hints.get("budgets") or T.budgets([u for g in scene for u in g])
    lines = _scene_lines(scene, hints, budget)
    glossary = T._glossary(hints)
    idioms = idiom_hints([x["source"] for x in lines])
    speakers = {u.speaker for g in scene for u in g}
    payload = {
        "title": title,
        "source_language": T.LANG_NAMES.get(lang, lang),
        **({"content_type": hints["content_type"]} if hints.get("content_type") else {}),
        **({"genre": hints["genre"]} if hints.get("genre") else {}),
        **({"register": hints["register"]} if hints.get("register") else {}),
        **({"glossary": glossary} if glossary else {}),
        **({"idioms": idioms} if idioms else {}),
        **({"characters": {T._speaker_label(sp, hints): info for sp, info in hints["characters"].items() if sp in speakers}}
           if hints.get("characters") else {}),
        "previous_lines_note": T.CONTEXT_NOTE_TH,
        "previous_lines": [{"speaker": T._speaker_label(u.speaker, hints), "start": round(u.start, 2), "source": u.source,
                            **({"text": u.target} if u.target else {})} for u in before],
        "next_lines_note": T.CONTEXT_NOTE_TH,
        "next_lines": [{"speaker": T._speaker_label(u.speaker, hints), "start": round(u.start, 2), "source": u.source}
                       for u in after],
        "lines": lines,
    }
    system = T.SYSTEM_PROMPT_TH + SCENE_RULE_TH + LENGTH_RULE_TH + (IDIOM_RULE_TH if idioms else "")
    user = ("แปล lines ของฉากนี้เป็นภาษาไทยพูด ทีละบรรทัดตาม id (previous_lines และ next_lines ไว้ดูบริบท ห้ามแปลหรือใส่ในคำตอบ)\n"
            'ตอบ JSON รูปแบบ {"lines":[{"id":1,"text":"คำแปล"}]} ครบทุก id\n\n'
            + json.dumps(payload, ensure_ascii=False))
    return system, user


def parse_scene_reply(reply: str, ids: list[int]) -> dict[int, str]:
    """อ่านคำตอบแบบเข้ม: รับ {"lines":[{"id","text"}]} หรือ {"lines":{"id":"text"}} เท่านั้น
    ตัดทิ้ง id ที่ไม่ได้ขอ ข้อความว่าง ข้อความที่ไม่ใช่ string และข้อความที่มีอักษรต้นฉบับ (จีน ฯลฯ)
    id ซ้ำ = ไม่เชื่อ id นั้น คืน id → ข้อความที่ผ่าน (บรรทัดที่ขาดให้ผู้เรียกแปลแบบเดิม)
    อ่าน JSON ไม่ได้ → ValueError"""
    data = T._parse_json(reply)
    raw = data.get("lines") if isinstance(data, dict) else None
    pairs: list[tuple[object, object]]
    if isinstance(raw, dict):
        pairs = list(raw.items())
    elif isinstance(raw, list):
        pairs = [(x.get("id"), x.get("text")) for x in raw if isinstance(x, dict)]
    else:
        raise ValueError("คำตอบไม่มี lines")
    wanted, seen, dup = set(ids), {}, set()
    for k, v in pairs:
        try:
            uid = int(k)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if uid not in wanted or not isinstance(v, str):
            continue
        text = v.strip()
        if not text or T.FOREIGN_SCRIPT.search(text) or text.lstrip().startswith(("{", "[")):
            continue
        if uid in seen:
            dup.add(uid)
        seen[uid] = text
    return {k: v for k, v in seen.items() if k not in dup}


def translate_scenes(groups: list[list[Utterance]], lang: str, title: str, hints: dict,
                     on_progress: Optional[Callable[[float], None]] = None,
                     check_cancel: Optional[Callable[[], None]] = None) -> None:
    """แปลทั้งฉาก (ภาษาไทยเท่านั้น) บรรทัดที่ตอบไม่ผ่านแปลแบบเดิมทีละประโยค (_translate_groups) ซึ่งมี fallback ของมันเอง"""
    order = [u for g in groups for u in g]
    total, done = max(1, len(order)), 0
    overlap = settings.translate_scene_overlap
    for scene in split_scenes(groups):
        if check_cancel:
            check_cancel()
        lines = [u for g in scene for u in g]
        i0 = order.index(lines[0])
        before = order[max(0, i0 - overlap):i0]
        after = order[i0 + len(lines):i0 + len(lines) + overlap]
        system, user = scene_prompt(scene, lang, title, hints, before, after)
        got: dict[int, str] = {}
        try:
            got = parse_scene_reply(T._chat(system, user, None, min(4096, 400 + 120 * len(lines))), [u.id for u in lines])
        except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
            log.warning("scene %s..%s: reply unusable (%s), per-sentence fallback", lines[0].id, lines[-1].id, exc)
        retry = []
        for g in scene:
            if all(u.id in got for u in g):
                for u in g:
                    u.target = T.tidy_marks(got[u.id])
            else:
                retry.append(g)
        if retry:
            log.info("scene fallback for sentences %s", [g[0].id for g in retry])
            context = [u for u in before if u.target][-6:]
            for g in retry:
                T._translate_groups([g], lang, "th", context, title, hints)
        for u in lines:
            u.target = T.spoken(u.target)
        done += len(lines)
        if on_progress:
            on_progress(done / total)


# ---------------------------------------------------------------- ตรวจตัวเองหลังแปล
SELF_CHECK_PROMPT_TH = """คุณคือบรรณาธิการตรวจบทพากย์ไทย เทียบ text (คำแปล) กับ source (ต้นฉบับ) ทีละบรรทัด
ติดป้ายเฉพาะบรรทัดที่ผิดจริง 2 แบบ:
- meaning: ความหมายผิด กลับด้าน หาย หรือเกินจากต้นฉบับ (เช่น ถูกสั่ง ↔ ทำได้ตามใจ, สแลงแปลตามตัวอักษร)
- naturalness: คนไทยไม่พูดแบบนี้ แปลตรงตัวคำต่อคำ ห้วนจนไม่เข้าใจ หรือเป็นภาษาเขียน
idioms คือคำอธิบายสำนวนที่มักแปลผิด ใช้เทียบความหมาย previous_lines/next_lines ไว้ดูบริบท ไม่ต้องตรวจ
ไม่นับความยาวหรือสำนวนที่ถูกอยู่แล้ว ไม่แน่ใจไม่ต้องใส่ reason บอกสิ่งที่ผิดและควรเป็นอย่างไร สั้น ๆ ภาษาไทย
ตอบ JSON อย่างเดียว {"flags":[{"id":1,"kind":"meaning","reason":"..."}]} ไม่มีให้ตอบ {"flags":[]}"""

REWRITE_PROMPT_TH = """คุณแก้บทพากย์ไทยเฉพาะบรรทัดที่ผู้ตรวจติดป้ายไว้ (flags บอกเหตุผล) โดยแปลใหม่จาก source ของบรรทัดนั้น
ให้ความหมายตรงต้นฉบับ เป็นภาษาพูดที่คนไทยพูดจริง ไม่แปลทีละคำ คงสรรพนามและชื่อตามบทเดิม
idioms คือคำอธิบายสำนวนที่ต้องแปลตามความหมาย ความยาวราว target_syllables ห้ามเกิน max_syllables
before/after คือบทข้างเคียง ไว้ดูบริบท ห้ามแก้หรือใส่ในคำตอบ
ตอบ JSON อย่างเดียว {"lines":[{"id":1,"text":"บทใหม่"}]} เฉพาะ id ที่ส่งมา"""

KINDS = ("meaning", "naturalness")


def _brief(u: Utterance) -> dict:
    return {"id": u.id, "speaker": u.speaker, "source": u.source, "text": u.target}


def llm_flags(order: list[Utterance], check_cancel: Optional[Callable[[], None]] = None) -> dict[int, list[tuple[str, str]]]:
    """เรียกโมเดลตรวจเป็นชุดตามฉาก ล้มเหลวถือว่าไม่พบ (ขั้นตรวจไม่ทำให้งานล้ม)"""
    out: dict[int, list[tuple[str, str]]] = {}
    size = settings.translate_scene_max_lines
    for lo in range(0, len(order), size):
        chunk = [u for u in order[lo:lo + size] if (u.target or "").strip()]
        if not chunk:
            continue
        if check_cancel:
            check_cancel()
        idioms = idiom_hints([u.source for u in chunk])
        payload = {**({"idioms": idioms} if idioms else {}),
                   "previous_lines": [_brief(u) for u in order[max(0, lo - 2):lo]],
                   "lines": [_brief(u) for u in chunk],
                   "next_lines": [_brief(u) for u in order[lo + size:lo + size + 1]]}
        try:
            data = T._parse_json(T._chat(SELF_CHECK_PROMPT_TH, json.dumps(payload, ensure_ascii=False), 0.1,
                                         min(2048, 300 + 100 * len(chunk))))
        except Exception as exc:  # noqa: BLE001
            log.warning("self-check call failed: %s", exc)
            continue
        ids = {u.id for u in chunk}
        for x in data.get("flags") or [] if isinstance(data, dict) else []:
            if not isinstance(x, dict) or not str(x.get("id", "")).isdigit() or int(x["id"]) not in ids:
                continue
            kind = str(x.get("kind") or "meaning").strip().lower()
            reason = str(x.get("reason") or "").strip()[:200] or "คำแปลอาจผิดความหมาย"
            out.setdefault(int(x["id"]), []).append((kind if kind in KINDS else "meaning", reason))
    return out


def rewrite_flagged(order: list[Utterance], flags: dict[int, list[tuple[str, str]]], hints: dict) -> set[int]:
    """เขียนใหม่ครั้งเดียวเฉพาะบรรทัดที่ติดป้าย คืน id ที่เปลี่ยนจริง
    ไม่ใช้คำตอบที่ว่าง / มีอักษรต้นฉบับ / เหมือนเดิม / ยังผิดกฎสำนวน / ยาวเกินงบพยางค์และยาวกว่าเดิม"""
    at = {u.id: i for i, u in enumerate(order)}
    budget = hints.get("budgets") or T.budgets(order)
    flagged = [u for u in order if u.id in flags]
    if not flagged:
        return set()
    lines = []
    for u in flagged:
        i, sec = at[u.id], budget.get(u.id, u.duration)
        lines.append({**_brief(u), **syllable_budget(sec),
                      "flags": [r for _, r in flags[u.id]],
                      **({"before": _brief(order[i - 1])} if i > 0 else {}),
                      **({"after": _brief(order[i + 1])} if i + 1 < len(order) else {})})
    idioms = idiom_hints([u.source for u in flagged])
    glossary = T._glossary(hints)
    payload = {**({"idioms": idioms} if idioms else {}), **({"glossary": glossary} if glossary else {}), "lines": lines}
    try:
        got = parse_scene_reply(T._chat(REWRITE_PROMPT_TH, json.dumps(payload, ensure_ascii=False), 0.3,
                                        min(4096, 300 + 150 * len(flagged))), [u.id for u in flagged])
    except Exception as exc:  # noqa: BLE001
        log.warning("self-check rewrite failed: %s", exc)
        return set()
    changed: set[int] = set()
    for u in flagged:
        new = T.spoken(got.get(u.id, ""))
        old = (u.target or "").strip()
        if not new or new == old:
            continue
        if any(h.check(new) for h in idioms_for(u.source)):
            log.info("self-check: rewrite of line %d still breaks an idiom rule, kept old", u.id)
            continue
        sec = budget.get(u.id, u.duration)
        if thai_syllables(new) > syllable_budget(sec)["max_syllables"] and thai_syllables(new) > thai_syllables(old):
            log.info("self-check: rewrite of line %d is over the length budget, kept old", u.id)
            continue
        u.target = new
        changed.add(u.id)
    return changed


def self_check(utts: list[Utterance], hints: Optional[dict] = None, *, use_llm: bool = True,
               check_cancel: Optional[Callable[[], None]] = None) -> dict[int, list[tuple[str, str]]]:
    """ตรวจคำแปลเทียบต้นฉบับ (กฎสำนวน + โมเดลถ้า use_llm) → เขียนใหม่เฉพาะบรรทัดที่ติดป้าย 1 รอบ (เฉพาะ use_llm)
    → ตรวจซ้ำด้วยกฎ บันทึกป้ายทุกอันใน qa_flags (fixed = แก้แล้ว) ที่ยังไม่ผ่านขึ้น check_note ให้คนดู
    คืน id → ป้ายที่ยังไม่ผ่าน"""
    hints = hints or {}
    order = sorted([u for u in utts if (u.target or "").strip()], key=lambda u: u.start)
    rules = rule_flags(order)
    flags = {k: list(v) for k, v in rules.items()}
    if use_llm:
        for uid, found in llm_flags(order, check_cancel).items():
            for f in found:
                if f not in flags.setdefault(uid, []):
                    flags[uid].append(f)
    if not flags:
        return {}
    cap = max(2, int(len(order) * 0.4))  # ติดป้ายเกิน 40% แปลว่าผู้ตรวจเกินเหตุ แก้แค่ส่วนแรก
    fix = dict(list(flags.items())[:cap])
    before = {u.id: u.target for u in order}
    changed = rewrite_flagged(order, fix, hints) if use_llm else set()
    still: dict[int, list[tuple[str, str]]] = {}
    by_id = {u.id: u for u in order}
    for uid, found in flags.items():
        u = by_id[uid]
        # รอบเดียว: บรรทัดที่เขียนใหม่ตรวจซ้ำด้วยกฎเท่านั้น (ไม่เรียกโมเดลอีกรอบ)
        remaining = rule_flags([u]).get(uid, []) if uid in changed else found
        for kind, reason in found:
            origin = "rule" if (kind, reason) in rules.get(uid, []) else "self_check"
            add_flag(u, origin, kind, reason, fixed=uid in changed and (kind, reason) not in remaining,
                     before=before[uid] if uid in changed else "")
        if remaining:
            still[uid] = remaining
            note_unresolved(u, "ตรวจคำแปล: " + "; ".join(r for _, r in remaining))
    log.info("self-check: %d flagged, %d rewritten, %d still flagged", len(flags), len(changed), len(still))
    return still


def record_verify_flags(utts: list[Utterance], still: dict[int, str]) -> None:
    """เก็บป้ายของผู้ตรวจเดิม (verify_translation) ลง qa_flags ด้วย ให้ป้ายทุกแหล่งอยู่ที่เดียว"""
    for u in utts:
        if u.id in still:
            add_flag(u, "verify", "meaning", still[u.id])
