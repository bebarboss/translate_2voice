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
    """origin: rule | self_check | verify
    kind: meaning | naturalness | number | name | added_word | unclear_source (แก้เองไม่ได้ ต้องให้คนฟัง)"""
    flag = {"origin": origin, "kind": kind, "reason": reason[:200], "fixed": fixed, **({"before": before} if before else {})}
    if not any(f.get("origin") == origin and f.get("reason") == flag["reason"] for f in u.qa_flags):
        u.qa_flags.append(flag)


def note_unresolved(u: Utterance, reason: str) -> None:
    """ป้ายที่ยังไม่ได้แก้ → check_note / unclear_reason (ช่องที่หน้าตรวจบทแสดงอยู่แล้ว)"""
    if reason in (u.check_note or ""):
        return
    u.check_note = f"{u.check_note}; {reason}".strip("; ") if u.check_note else reason
    u.unclear_reason = u.unclear_reason or reason


# ---------------------------------------------------------------- ตรวจรายบรรทัดแบบกฎ (ระยะที่ 2)
# ตัวเลข ชื่อ/แบรนด์ คำลงท้ายที่เติมเอง และต้นฉบับที่ถอดเสียงไม่ชัด ไม่เรียกโมเดล ผลเหมือนเดิมทุกครั้ง
# unclear_source แก้เองไม่ได้ (ต้องฟังเสียงจริง) ส่งให้เจ้าของงานตรวจเสมอ ที่เหลือส่งไปเขียนใหม่ 1 รอบได้
UNFIXABLE = frozenset({"unclear_source"})


@dataclass(frozen=True)
class Term:
    source: str
    target: str
    note: str = ""


def parse_glossary(text: str) -> list[Term]:
    """บรรทัดละคำ "ต้นฉบับ = คำที่ต้องใช้ # หมายเหตุ" (หมายเหตุไม่บังคับ) บรรทัดที่ไม่มี = ข้าม"""
    out: list[Term] = []
    for line in (text or "").splitlines():
        src, eq, rest = line.partition("=")
        src, dst = src.strip(), T.gloss_target(rest)
        if not eq or not src or not dst:
            continue
        note = rest.strip()[len(dst):].strip().lstrip("#").strip()
        out.append(Term(src, dst, note))
    return out


_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_NUM = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
_TH_UNITS = ("", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า")
_TH_PLACES = ("", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน")


def _num_key(s: str) -> str:
    """"1,000" → "1000" "3.50" → "3.5" (เทียบตัวเลขโดยไม่สนตัวคั่นหลักพัน)"""
    s = s.translate(_THAI_DIGITS)
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
        s = s.replace(",", "")
    s = s.replace(",", ".")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.lstrip("0") or "0"


def thai_number_words(n: int) -> str:
    """135 → หนึ่งร้อยสามสิบห้า (ใช้เทียบเมื่อผู้แปลเขียนตัวเลขเป็นคำ)"""
    if n == 0:
        return "ศูนย์"
    if n >= 1_000_000:
        hi, lo = divmod(n, 1_000_000)
        return thai_number_words(hi) + "ล้าน" + (thai_number_words(lo) if lo else "")
    digits = str(n)
    out = []
    for i, ch in enumerate(digits):
        d, place = int(ch), len(digits) - i - 1
        if d == 0:
            continue
        if place == 1:
            out.append(("ยี่" if d == 2 else "" if d == 1 else _TH_UNITS[d]) + "สิบ")
        elif place == 0 and d == 1 and len(digits) > 1:
            out.append("เอ็ด")
        else:
            out.append(_TH_UNITS[d] + _TH_PLACES[place])
    return "".join(out)


def _number_forms(raw: str) -> set[str]:
    key = _num_key(raw)
    forms = {key}
    if key.isdigit():
        n = int(key)
        if n < 10 ** 12:
            w = thai_number_words(n)
            forms.add(w)
            if w.startswith("หนึ่ง") and n >= 100:
                forms.add(w[len("หนึ่ง"):])  # "ร้อยสามสิบห้า" แบบที่คนพูด
        if 1900 <= n <= 2100:
            forms.add(str(n + 543))  # ปี ค.ศ. → พ.ศ.
    elif re.fullmatch(r"\d+\.\d+", key):
        a, b = key.split(".")
        forms.add(thai_number_words(int(a)) + "จุด" + "".join(_TH_UNITS[int(c)] or "ศูนย์" for c in b))
    return forms


_SENT = re.compile(r"(?<=[.!?…])\s+")
_ONLY_NUM = re.compile(r"^\W*(\d+(?:[.,]\d+)*)\W*$")


def unclear_numbers(u: Utterance, prev: Optional[Utterance] = None) -> list[str]:
    """ตัวเลขที่ลอยอยู่เดี่ยว ๆ ทั้งประโยคต่อจากประโยคที่มีตัวเลข เช่น "I scored 135! 435." (เสียงสะท้อน/ถอดผิด)
    นับถอยหลัง/รายการ (ตัวเลขเดี่ยวหลายประโยค) ไม่นับ"""
    parts = [p for p in _SENT.split((u.source or "").strip()) if p.strip()]
    alone = [i for i, p in enumerate(parts) if _ONLY_NUM.match(p)]
    if len(alone) != 1:
        return []
    i = alone[0]
    if i > 0:
        before = parts[i - 1]
    elif prev is not None and len(parts) == 1:
        before = ([p for p in _SENT.split((prev.source or "").strip()) if p.strip()] or [""])[-1]
    else:
        return []
    if not _NUM.search(before) or _ONLY_NUM.match(before):
        return []
    return [_ONLY_NUM.match(parts[i]).group(1)]


def _check_numbers(source: str, target: str, skip: set[str]) -> list[tuple[str, str]]:
    tgt = target.translate(_THAI_DIGITS)
    have = {_num_key(m) for m in _NUM.findall(tgt)}
    flat = re.sub(r"\s+", "", tgt)
    missing = []
    for raw in _NUM.findall(source or ""):
        if raw in skip or raw in missing:
            continue
        forms = _number_forms(raw)
        if forms & have or any(f in flat for f in forms if not f.isdigit()):
            continue
        missing.append(raw)
    return [("number", f'ตัวเลข "{x}" ในต้นฉบับหายหรือเปลี่ยนไป ต้องคง {x} ไว้ตามต้นฉบับ') for x in missing]


# ตัวย่อที่คนไทยอ่านหรือเขียนเป็นไทยกันทั่วไป ไม่ถือเป็นชื่อแบรนด์ที่ต้องคงอักษรละติน
COMMON_ACRONYMS = frozenset("""AI OK TV US USA UK EU UN CEO DJ IT AM PM VIP DIY FAQ ID PC DNA NASA FBI CIA GPS PDF LOL OMG
BTW ASAP IQ PR HR VS MR MRS MS DR II III IV TBH FYI IG FB""".split())
_STOP = frozenset("I A An The My Our Your His Her Their This That These Those And Or But So If When Then Oh Hey Hi Yes No".split())
_CAP_RUN = re.compile(r"[A-Z][A-Za-z0-9'&.-]*(?:\s+[A-Z][A-Za-z0-9'&.-]*)*")


def brand_names(source: str) -> list[str]:
    """ชื่อแบรนด์/ผลิตภัณฑ์ในต้นฉบับ: กลุ่มคำขึ้นต้นตัวใหญ่ที่มีตัวย่อตัวใหญ่ล้วน (ไม่ใช่ตัวย่อทั่วไป) เช่น "DE Practice"
    ตัดคำทั่วไปหัวท้าย ("I", "The", "AI") และคำแรกของประโยคออก"""
    out: list[str] = []
    for m in _CAP_RUN.finditer(source or ""):
        toks = [t.strip(".'") for t in m.group(0).split()]
        head = (source or "")[:m.start()].rstrip()
        if len(toks) > 1 and (not head or head[-1] in ".!?…") and not toks[0].isupper():
            toks.pop(0)  # คำแรกของประโยคขึ้นต้นตัวใหญ่อยู่แล้ว ("Try DE Practice" → "DE Practice")
        while toks and (toks[0] in _STOP or toks[0].upper() in COMMON_ACRONYMS):
            toks.pop(0)
        while toks and (toks[-1] in _STOP or toks[-1].upper() in COMMON_ACRONYMS):
            toks.pop()
        if any(re.fullmatch(r"[A-Z]{2,}\d*", t) and t not in COMMON_ACRONYMS for t in toks):
            name = " ".join(toks)
            if name not in out:
                out.append(name)
    return out


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, re.I) is not None


def _check_names(source: str, target: str, terms: list[Term]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    covered: list[str] = []
    for t in terms:
        if len(t.source) < 2 or not _has_word(source, t.source):
            continue
        covered.append(t.source.lower())
        if t.target.lower() not in target.lower():
            out.append(("name", f'"{t.source}" ต้องเขียนว่า "{t.target}" ตาม glossary ของโปรเจกต์'))
    for name in brand_names(source):
        if any(name.lower() in c or c in name.lower() for c in covered):
            continue
        lost = [w for w in name.split() if not _has_word(target, w)]
        if lost:
            out.append(("name", f'ชื่อ "{name}" ถูกถอดเป็นอักษรไทยเอง ให้คงอักษรละติน "{name}" '
                                f'(หรือเพิ่มคำสะกดที่ถูกใน glossary)'))
    return out


# คำลงท้ายอ่อนลง (นะ ฯลฯ) ต้องมีที่มาในต้นฉบับ คำสุภาพ (ครับ/ค่ะ) ใช้ได้เมื่อระดับภาษาหรือนิสัยผู้พูดเป็นแบบนั้น
SOFT_PARTICLES = ("นะคะ", "นะครับ", "นะจ๊ะ", "เนอะ", "จ้ะ", "จ้า", "น่ะ", "นะ")
POLITE_PARTICLES = ("ครับ", "ค่ะ", "คะ")
_NOT_PARTICLE = ("เจ้า", "ชนะ", "ขณะ", "ฐานะ", "คณะ", "ทัศนะ", "ภาชนะ", "พาหนะ", "มานะ", "ปณะ")
_SOFT_BASIS = re.compile(
    r"\?|\b(?:please|pls|let'?s|let us|okay|ok|alright|all right|you know|ya know|y'know|huh|eh|hey|come on|trust me|"
    r"remember|don'?t forget|promise|honey|sweetie|dear|babe|buddy|bye|goodbye|see you|take care|thanks|thank you|"
    r"sorry|good ?night|good ?luck|right)\b", re.I)
_IMPERATIVE = re.compile(
    r"(?:^|[.!?]\s+)(?:don'?t|do|go|come|wait|look|listen|try|make|take|be|tell|give|check|keep|stop|see|watch|get|let|"
    r"hold|follow|subscribe|like|click|stay|calm|relax|enjoy|imagine|call|send|write|read|use|start|eat|drink|sit|"
    r"stand|leave|put|bring|help|show|ask|smile|believe|forget|hurry|run|move|join)\b", re.I)
_POLITE_BASIS = re.compile(r"\b(?:sir|ma'?am|madam|hello|hi|welcome|good (?:morning|afternoon|evening)|excuse me)\b", re.I)
_POLITE_HINT = re.compile(r"สุภาพ|ทางการ|ครับ|ค่ะ|polite|formal", re.I)


def _end_particles(target: str) -> list[str]:
    """คำลงท้ายของแต่ละช่วง (คั่นด้วยช่องว่าง/เครื่องหมาย) ที่เป็น particle"""
    out = []
    for chunk in re.split(r"[\s!?.,…/\"'“”]+", target or ""):
        if not chunk or any(chunk.endswith(w) for w in _NOT_PARTICLE):
            continue
        for p in SOFT_PARTICLES + POLITE_PARTICLES:
            if chunk.endswith(p):
                out.append(p)
                break
    return out


@dataclass
class LineContext:
    """ข้อมูลที่กฎต้องใช้ทั้งชุด: glossary ระดับภาษา นิสัยคำลงท้ายของผู้พูด บรรทัดก่อนหน้า"""
    terms: list[Term]
    polite_speakers: set[str]
    prev: dict[int, Utterance]
    register: str = ""


def line_context(utts: list[Utterance], hints: Optional[dict] = None) -> LineContext:
    hints = hints or {}
    order = sorted(utts, key=lambda u: u.start)
    register = str(hints.get("register") or "")
    chars = hints.get("characters") or {}
    names = hints.get("names") or {}
    polite: set[str] = set()
    by_spk: dict[str, list[Utterance]] = {}
    for u in order:
        if (u.target or "").strip():
            by_spk.setdefault(u.speaker, []).append(u)
    for spk, lines in by_spk.items():
        info = chars.get(spk) or chars.get(names.get(spk, "")) or {}
        if _POLITE_HINT.search(register) or _POLITE_HINT.search(json.dumps(info, ensure_ascii=False)):
            polite.add(spk)
            continue
        # ผู้พูดลงท้ายสุภาพเกินครึ่งของบท (อย่างน้อย 2 บรรทัด) = สไตล์ของคนนี้ ไม่ใช่เติมเอง
        n = sum(1 for u in lines if any(p in POLITE_PARTICLES for p in _end_particles(u.target)))
        if n >= 2 and n * 2 >= len(lines):
            polite.add(spk)
    return LineContext(parse_glossary(str(hints.get("glossary") or "")), polite,
                       {b.id: a for a, b in zip(order, order[1:])}, register)


def _check_particles(u: Utterance, ctx: LineContext) -> list[tuple[str, str]]:
    src = u.source or ""
    soft_ok = bool(_SOFT_BASIS.search(src) or _IMPERATIVE.search(src.strip()))
    polite_ok = soft_ok or bool(_POLITE_BASIS.search(src)) or u.speaker in ctx.polite_speakers
    out: list[tuple[str, str]] = []
    for p in dict.fromkeys(_end_particles(u.target)):
        if p in ctx.register:  # ระดับภาษาของเรื่องกำหนดคำลงท้ายนี้ไว้เอง
            continue
        soft = p in SOFT_PARTICLES
        if (soft and not soft_ok) or (not soft and not polite_ok):
            out.append(("added_word", f'เติม "{p}" ท้ายประโยคเองทั้งที่ต้นฉบับไม่มีน้ำเสียงนี้ ควรตัดออก'))
    return out


def line_flags(u: Utterance, ctx: LineContext) -> list[tuple[str, str]]:
    """ตรวจบรรทัดเดียว: ตัวเลข ชื่อ คำลงท้ายเกิน ต้นฉบับไม่ชัด → [(kind, reason)]"""
    if not (u.target or "").strip():
        return []
    unclear = unclear_numbers(u, ctx.prev.get(u.id))
    out = [("unclear_source", f'ต้นฉบับมี "{x}" ลอยอยู่เดี่ยว ๆ อาจถอดเสียงผิดหรือซ้ำ ฟังต้นฉบับแล้วแก้หรือลบ')
           for x in unclear]
    out += _check_numbers(u.source, u.target, set(unclear))
    out += _check_names(u.source, u.target, ctx.terms)
    out += _check_particles(u, ctx)
    return out


def rule_flags(utts: list[Utterance], hints: Optional[dict] = None, *,
               ctx: Optional[LineContext] = None) -> dict[int, list[tuple[str, str]]]:
    """id → [(kind, reason)] จากสำนวนที่รู้ว่าแปลผิดบ่อย + (TRANSLATE_LINE_CHECKS) ตัวเลข ชื่อ คำลงท้ายเกิน ต้นฉบับไม่ชัด
    ไม่เรียกโมเดล ctx = ข้อมูลทั้งชุด (ส่งมาเมื่อตรวจบางบรรทัดซ้ำ ให้รู้ผู้พูดและบรรทัดก่อนหน้า)"""
    out: dict[int, list[tuple[str, str]]] = {}
    if settings.translate_line_checks and ctx is None:
        ctx = line_context(utts, hints)
    for u in utts:
        if not (u.target or "").strip():
            continue
        for h in idioms_for(u.source):
            found = h.check(u.target)
            if found:
                out.setdefault(u.id, []).extend(found)
        if settings.translate_line_checks:
            for f in line_flags(u, ctx):
                if f not in out.get(u.id, []):
                    out.setdefault(u.id, []).append(f)
    return out


def uncertain_ids(utts: list[Utterance]) -> list[int]:
    """บรรทัดที่ยังมีป้ายไม่ได้แก้ (ทุกแหล่ง) = ระบบไม่แน่ใจ ต้องให้เจ้าของงานดูในหน้าตรวจบทก่อนพากย์"""
    return [u.id for u in utts if any(not f.get("fixed") for f in u.qa_flags or [])]


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
ตัวเลขต้องตรงต้นฉบับทุกตัว (keep_numbers) ชื่อแบรนด์/ชื่อเฉพาะคงอักษรละตินหรือสะกดตาม glossary ทุกตัวอักษร
ห้ามเติมคำลงท้าย (นะ นะคะ ครับ ค่ะ) ที่ต้นฉบับไม่มีน้ำเสียงนั้น
ตอบ JSON อย่างเดียว {"lines":[{"id":1,"text":"บทใหม่"}]} เฉพาะ id ที่ส่งมา"""

KINDS = ("meaning", "naturalness", "number", "name", "added_word")  # โมเดลติดป้าย unclear_source ไม่ได้ (เป็นของกฎ)


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


def _fixable(found: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [f for f in found if f[0] not in UNFIXABLE]


# น้ำหนักความร้ายแรงเมื่อเทียบบทเดิมกับบทใหม่ (ตัวเลข/ความหมายผิด แย่กว่าคำลงท้ายเกิน)
SEVERITY = {"meaning": 3, "number": 3, "name": 2, "added_word": 1, "naturalness": 1}


def _badness(found: list[tuple[str, str]]) -> int:
    return sum(SEVERITY.get(k, 1) for k, _ in _fixable(found))


def rewrite_flagged(order: list[Utterance], flags: dict[int, list[tuple[str, str]]], hints: dict,
                    ctx: Optional[LineContext] = None) -> set[int]:
    """เขียนใหม่ครั้งเดียวเฉพาะบรรทัดที่ติดป้าย โดยบอกปัญหาของบรรทัดนั้นตรง ๆ ใน flags คืน id ที่เปลี่ยนจริง
    ไม่ใช้คำตอบที่ว่าง / เหมือนเดิม / ยังผิดกฎสำนวน / ยาวเกินงบพยางค์และยาวกว่าเดิม
    กฎรายบรรทัด (ตัวเลข ชื่อ คำลงท้าย): ผ่านหมด = ใช้บทใหม่ ไม่ผ่านแต่ดีขึ้น (SEVERITY รวมน้อยลง) = ใช้บทใหม่แต่ยังไม่แน่ใจ
    แย่เท่าเดิมหรือแย่ลง = คงบทเดิม"""
    at = {u.id: i for i, u in enumerate(order)}
    budget = hints.get("budgets") or T.budgets(order)
    flagged = [u for u in order if u.id in flags]
    if not flagged:
        return set()
    if settings.translate_line_checks and ctx is None:
        ctx = line_context(order, hints)
    lines = []
    for u in flagged:
        i, sec = at[u.id], budget.get(u.id, u.duration)
        skip = set(unclear_numbers(u, ctx.prev.get(u.id))) if ctx else set()
        nums = [x for x in dict.fromkeys(_NUM.findall(u.source or "")) if x not in skip]
        lines.append({**_brief(u), **syllable_budget(sec),
                      "flags": [r for _, r in flags[u.id]],
                      **({"keep_numbers": nums} if nums else {}),
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
        if ctx is not None:
            bad_old = _badness(line_flags(u, ctx))
            bad_new = _badness(line_flags(u.model_copy(update={"target": new}), ctx))
            if bad_new and bad_new >= bad_old:
                log.info("self-check: rewrite of line %d is no better on line rules (%s), kept old", u.id, bad_new)
                continue
        u.target = new
        changed.add(u.id)
    return changed


def self_check(utts: list[Utterance], hints: Optional[dict] = None, *, use_llm: bool = True,
               check_cancel: Optional[Callable[[], None]] = None) -> dict[int, list[tuple[str, str]]]:
    """ตรวจคำแปลเทียบต้นฉบับ (กฎ + โมเดลถ้า use_llm) → เขียนใหม่เฉพาะบรรทัดที่ติดป้ายที่แก้ได้ 1 รอบ (เฉพาะ use_llm)
    → ตรวจซ้ำด้วยกฎ บันทึกป้ายทุกอันใน qa_flags (fixed = แก้แล้ว) ที่ยังไม่ผ่านขึ้น check_note ให้คนดู
    unclear_source (ต้นฉบับถอดเสียงไม่ชัด) ไม่ส่งไปแก้ ค้างเป็นไม่แน่ใจเสมอ
    คืน id → ป้ายที่ยังไม่ผ่าน"""
    hints = hints or {}
    order = sorted([u for u in utts if (u.target or "").strip()], key=lambda u: u.start)
    ctx = line_context(order, hints) if settings.translate_line_checks else None
    rules = rule_flags(order, hints, ctx=ctx)
    flags = {k: list(v) for k, v in rules.items()}
    if use_llm:
        for uid, found in llm_flags(order, check_cancel).items():
            for f in found:
                if f not in flags.setdefault(uid, []):
                    flags[uid].append(f)
    if not flags:
        return {}
    fixable = {uid: _fixable(found) for uid, found in flags.items() if _fixable(found)}
    cap = max(2, int(len(order) * 0.4))  # ติดป้ายเกิน 40% แปลว่าผู้ตรวจเกินเหตุ แก้แค่ส่วนแรก
    fix = dict(list(fixable.items())[:cap])
    before = {u.id: u.target for u in order}
    changed = rewrite_flagged(order, fix, hints, ctx) if use_llm and fix else set()
    still: dict[int, list[tuple[str, str]]] = {}
    by_id = {u.id: u for u in order}
    for uid, found in flags.items():
        u = by_id[uid]
        # รอบเดียว: บรรทัดที่เขียนใหม่ตรวจซ้ำด้วยกฎเท่านั้น (ไม่เรียกโมเดลอีกรอบ)
        remaining = rule_flags([u], hints, ctx=ctx).get(uid, []) if uid in changed else found
        for kind, reason in found:
            origin = "rule" if (kind, reason) in rules.get(uid, []) else "self_check"
            add_flag(u, origin, kind, reason, fixed=uid in changed and (kind, reason) not in remaining,
                     before=before[uid] if uid in changed else "")
        for kind, reason in remaining:  # บทใหม่มีปัญหาใหม่ที่บทเดิมไม่มี
            if (kind, reason) not in found:
                add_flag(u, "rule", kind, reason)
        if remaining:
            still[uid] = remaining
            note_unresolved(u, "ตรวจคำแปล: " + "; ".join(r for _, r in remaining))
    log.info("self-check: %d flagged, %d rewritten, %d still flagged", len(flags), len(changed), len(still))
    return still


def final_gate(utts: list[Utterance], hints: Optional[dict] = None) -> dict[int, list[tuple[str, str]]]:
    """ก่อนเข้าหน้าตรวจบท (ก่อนแปลงละตินเป็นคำอ่าน): ตรวจกฎรายบรรทัดซ้ำทุกบรรทัด เพราะขั้นเรียบเรียง/ตรวจ/เติมบท
    หลัง self_check อาจแก้บทอีก ไม่เรียกโมเดล ไม่แก้บท ป้ายที่เคยแก้แล้วแต่กลับมา = ไม่แน่ใจอีกครั้ง"""
    if not settings.translate_line_checks:
        return {}
    order = sorted([u for u in utts if (u.target or "").strip()], key=lambda u: u.start)
    ctx = line_context(order, hints)
    still = rule_flags(order, hints, ctx=ctx)
    for u in order:
        found = still.get(u.id, [])
        for kind, reason in found:
            again = [f for f in u.qa_flags if f.get("reason") == reason[:200]]
            for f in again:
                f["fixed"] = False
            if not again:
                add_flag(u, "rule", kind, reason)
        new = [r for _, r in found if r not in (u.check_note or "")]
        if new:
            note_unresolved(u, "ตรวจคำแปล: " + "; ".join(new))
    return still


def record_verify_flags(utts: list[Utterance], still: dict[int, str]) -> None:
    """เก็บป้ายของผู้ตรวจเดิม (verify_translation) ลง qa_flags ด้วย ให้ป้ายทุกแหล่งอยู่ที่เดียว"""
    for u in utts:
        if u.id in still:
            add_flag(u, "verify", "meaning", still[u.id])
