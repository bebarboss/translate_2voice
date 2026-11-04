"""เว้นจังหวะหยุดตามต้นฉบับ

พากย์ทั้งประโยครวดเดียว F5-TTS จะพูดต่อกันไม่หยุด ทั้งที่นักแสดงเว้นจังหวะ (หยุดหายใจ หยุดคิด กลั้นอารมณ์ เน้นคำ)
จึงหาช่วงเงียบกลางประโยคในเสียงต้นฉบับ ตัดบทไทยตรงตำแหน่งเดียวกัน (ที่ขอบท่อน จุดแบ่งวลี หรือขอบคำที่ใกล้ที่สุด)
แล้วพากย์ทีละช่วง วางแต่ละช่วงตรงเวลาที่นักแสดงพูด
"""
import re
import unicodedata
from itertools import combinations
from typing import NamedTuple, Optional

import numpy as np


class Chunk(NamedTuple):
    start: float
    end: float
    text: str


def find_pauses(seg: np.ndarray, sr: int, min_pause: float) -> list[tuple[float, float]]:
    """ช่วงเงียบกลางเสียง (วินาทีนับจากต้น seg) ไม่นับความเงียบหัวท้าย"""
    hop = int(sr * 0.02)
    if len(seg) < hop * 10:
        return []
    frames = len(seg) // hop
    rms = np.sqrt(np.mean(seg[: frames * hop].reshape(frames, hop) ** 2, axis=1))
    # เพลงที่ยังหลงอยู่ในเสียงพูดทำให้ช่วงหยุดไม่เงียบสนิท ใช้เกณฑ์เทียบกับช่วงที่ดังของประโยคนั้น (−20 dB)
    silent = rms < 0.1 * np.percentile(rms, 95)
    voiced = np.flatnonzero(~silent)
    if len(voiced) == 0:
        return []
    out, run_start = [], None
    for i in range(voiced[0], voiced[-1] + 1):
        if silent[i] and run_start is None:
            run_start = i
        elif not silent[i] and run_start is not None:
            if (i - run_start) * 0.02 >= min_pause:
                out.append((run_start * 0.02, i * 0.02))
            run_start = None
    return out


MARK = "/"  # จุดหยุดในบท: ใส่ในต้นฉบับตรงที่นักแสดงหยุดจริง ให้ผู้แปลวางในบทแปลตรงความหมายเดียวกัน
_MARK_RE = re.compile(r"\s*(?<!\d)/(?!\d)\s*")  # ไม่นับ / ระหว่างตัวเลข (24/7)


def strip_marks(text: str) -> str:
    """บทที่ไม่มีเครื่องหมายจุดหยุด (ใช้กับซับไตเติล เสียงพากย์ และการนับความยาว)"""
    return " ".join(_MARK_RE.sub(" ", text).split())


def split_marks(text: str) -> tuple[str, list[int], bool]:
    """(บทที่ไม่มีเครื่องหมาย, ตำแหน่งตัวอักษรของแต่ละจุดหยุดในบทนั้น, ทุกจุดอยู่ที่ขอบคำ)
    จุดที่ตกกลางคำไทย (เห็/น, เพรา/ะ) ต่อคำกลับโดยไม่เว้นวรรค และไม่นับเป็นจุดหยุด"""
    pieces = [x.strip() for x in _MARK_RE.split(text.strip())]
    pieces = [x for x in pieces if x]
    clean, marks, ok = "", [], True
    for x in pieces:
        if clean and not _thai_mid_word(clean, x):
            marks.append(len(clean) + 1)
            clean += " "
        elif clean:
            ok = False
        clean += x
    return clean, marks, ok


_THAI = re.compile(r"[ก-๛]")
# คำเชื่อมที่ต้องมีคำตามหลังเสมอ ผู้แปลวาง / หลังคำพวกนี้ ("ถ้า / เรา") เสียงพากย์จะหยุดค้างกลางวลี
_DANGLING = {"ถ้า", "หาก", "และ", "กับ", "หรือ", "แต่", "ของ", "ซึ่ง", "ว่า", "เพราะ", "เมื่อ", "ที่", "ตอนที่", "เพื่อ", "โดย"}


def tidy_marks(text: str) -> str:
    """ย้าย / ที่ตกหลังคำเชื่อมไปไว้หน้าคำเชื่อมนั้น ("ฉันจัดให้ได้ ถ้า / เรา…" → "ฉันจัดให้ได้ / ถ้าเรา…")"""
    if MARK not in text or not _THAI.search(text):
        return text
    pieces = [x.strip() for x in _MARK_RE.split(text.strip())]
    if len(pieces) < 2 or not all(pieces):
        return text
    try:
        from pythainlp.tokenize import word_tokenize
    except ImportError:
        return text
    for i in range(len(pieces) - 1):
        toks = word_tokenize(pieces[i], engine="newmm", keep_whitespace=False)
        if len(toks) > 1 and toks[-1] in _DANGLING:
            word = toks[-1]
            pieces[i] = pieces[i][: len(pieces[i]) - len(word)].rstrip()
            pieces[i + 1] = word + pieces[i + 1]
    return f" {MARK} ".join(x for x in pieces if x)


def _thai_mid_word(left: str, right: str) -> bool:
    """รอยต่อ left|right อยู่กลางคำไทยไหม (สระหรือวรรณยุกต์ขึ้นต้น สระหน้าค้างท้าย หรือตัวตัดคำบอกว่าไม่ใช่ขอบคำ)"""
    if not (_THAI.match(right[:1]) and _THAI.match(left[-1:])):
        return False
    if unicodedata.category(right[0]) == "Mn" or right[0] in "ะาำๅๆฯ" or left[-1] in "เแโใไ":
        return True
    try:
        from pythainlp.tokenize import word_tokenize
    except ImportError:
        return False
    a, b = left[-15:], right[:15]
    pos, edges = 0, set()
    for tok in word_tokenize(a + b, engine="newmm"):
        edges.add(pos)
        pos += len(tok)
    return len(a) not in edges


def source_pauses(u, orig: np.ndarray, sr: int, words: Optional[list], min_pause: float) -> list[tuple[float, float, int]]:
    """จุดหยุดกลางท่อน u ในเสียงต้นฉบับ: (เริ่ม, จบ, ลำดับคำแรกหลังจุดหยุด ในคำของท่อนนี้)
    เวลาจบคำของ Whisper มักลากคร่อมช่วงหยุด จึงใช้เวลาเริ่มคำ: คำแรกที่เริ่มหลังช่วงหยุดเริ่ม"""
    own = [w for w in words or [] if u.start - 0.01 <= (w.start + w.end) / 2 <= u.end + 0.01]
    if len(own) < 2:
        return []
    seg = orig[int(u.start * sr): int(u.end * sr)]
    edges = _word_edges(own)
    out = []
    for a, b in find_pauses(seg, sr, min_pause):
        ps, pe = u.start + a, u.start + b
        # คำที่ Whisper ให้เวลาคร่อมช่วงหยุดเกินครึ่งคำ (What 28.24–28.58 กับหยุด 28.26–28.58) ที่จริงพูดหลังหยุด
        k = next((i for i, w in enumerate(own)
                  if w.start > ps + 0.02 or min(w.end, pe) - max(w.start, ps) > 0.5 * (w.end - w.start)), None)
        # ญี่ปุ่น/จีน: คำของ Whisper เป็นแค่ตัวอักษรหรือพยางค์ จุดที่ตกกลางคำ (ジャ|イアン) ไม่ใช่จุดหยุดจริง
        # ถ้าส่งไปแปล ผู้แปลจะตัดชื่อในบทไทยตามด้วย (ไจ / แอนท์)
        if k and (not out or k > out[-1][2]) and (edges is None or k in edges):
            out.append((ps, pe, k))
    return out


def _word_edges(own: list) -> Optional[set[int]]:
    """ลำดับคำ (ของ Whisper) ที่เป็นจุดเริ่มคำจริงในภาษาที่ไม่เว้นวรรค (ญี่ปุ่น จีน) ภาษาอื่นคืน None = ทุกคำ"""
    text = "".join(w.text for w in own)
    lang = "ja" if re.search(r"[぀-ヿ]", text) else "zh" if re.search(r"[一-鿿]", text) else ""
    if not lang:
        return None
    from .transcribe import _tokenize

    tokens = _tokenize(text, lang)
    if not tokens:
        return None
    bounds, pos = set(), 0
    for t in tokens:
        bounds.add(pos)
        pos += len(t)
    edges, pos = set(), 0
    for i, w in enumerate(own):
        if pos in bounds or text[pos - 1:pos] in "、。！？!?…, ":
            edges.add(i)
        pos += len(w.text)
    return edges


def mark_source(u, orig: np.ndarray, sr: int, words: Optional[list], min_pause: float) -> Optional[str]:
    """ต้นฉบับของท่อน u ที่ใส่ / ตรงจุดที่นักแสดงหยุด (ไม่มีจุดหยุด หรือคำไม่ตรงกับบท = None)"""
    ps = source_pauses(u, orig, sr, words, min_pause)
    if not ps:
        return None
    own = [w for w in words if u.start - 0.01 <= (w.start + w.end) / 2 <= u.end + 0.01]
    if "".join(w.text for w in own).split() != u.source.split():
        return None  # ผู้ใช้แก้บทต้นฉบับแล้ว ตำแหน่งคำไม่ตรง
    at = {k for _, _, k in ps}
    return "".join((f" {MARK}" if i in at else "") + w.text for i, w in enumerate(own)).strip()


def _weight(text: str) -> int:
    """ความยาวที่ใช้เทียบสัดส่วน: ไม่นับสระบนล่าง วรรณยุกต์ และช่องว่าง (ใกล้จำนวนเสียงที่พูดจริงกว่านับตัวอักษร)"""
    return sum(1 for ch in text if not ch.isspace() and unicodedata.category(ch) != "Mn")


def _bounds(text: str) -> dict[int, float]:
    """ตำแหน่งที่ตัดบทได้ → ค่าปรับ (ยิ่งมากยิ่งไม่อยากตัด)

    หลังเว้นวรรคหรือเครื่องหมายวรรคตอนดีที่สุด (ผู้แปลเว้นวรรคตรงจุดแบ่งวลีของภาษาไทยอยู่แล้ว)
    บทที่ไม่เว้นวรรค (เช่น บทที่ถอดจากเสียงไทยตรง ๆ) ตัดที่ขอบคำได้ แต่เสียเปรียบกว่า กันชื่อหรือวลีขาดกลาง
    ไม่ตัดระหว่างตัวเลขกับคำที่ตามมา ("5,000 | ดอลลาร์")
    """
    punct = " ,.!?…"
    out: dict[int, float] = {}
    for i in range(1, len(text)):
        if text[i - 1] in punct and text[i] not in punct:
            out[i] = 0.0
    if re.search(r"[ก-๛]", text):
        try:
            from pythainlp.tokenize import word_tokenize
            pos = 0
            for tok in word_tokenize(text, engine="newmm", keep_whitespace=True)[:-1]:
                pos += len(tok)
                if 0 < pos < len(text) and pos not in out and not text[pos].isspace():
                    out[pos] = 0.15
        except ImportError:
            pass
    return {b: c for b, c in out.items() if not re.search(r"\d[\d,.]*\s*$", text[:b])}


def _spoken_fraction(u, t: float, words: Optional[list]) -> float:
    """สัดส่วนของท่อน u ที่พูดไปแล้วก่อนเวลา t

    มีเวลาของแต่ละคำจาก Whisper → นับจากคำที่พูดจบก่อน t (แม่นกว่าสัดส่วนเวลา เพราะไม่นับช่วงหยุดและพูดเร็วช้าไม่เท่ากัน)
    ไม่มี → ใช้สัดส่วนเวลา
    """
    own = [w for w in words or [] if u.start - 0.05 <= w.start <= u.end + 0.05]
    total = sum(_weight(w.text) for w in own)
    if total:  # ใช้เวลาเริ่มคำ เวลาจบของคำก่อนหยุดมักลากยาวคร่อมช่วงหยุด
        return sum(_weight(w.text) for w in own if w.start < t) / total
    return (t - u.start) / max(u.duration, 1e-3)


def _position(text: str, fraction: float) -> float:
    """ตำแหน่งตัวอักษรใน text ที่ตรงกับสัดส่วน fraction ของเสียงที่พูด"""
    want, seen = fraction * _weight(text), 0
    for i, ch in enumerate(text):
        if seen >= want:
            return i
        if not ch.isspace() and unicodedata.category(ch) != "Mn":
            seen += 1
    return len(text)


MAX_MARK_GAP = 0.3  # จุด / กับจุดหยุดต้นฉบับที่ตำแหน่ง (สัดส่วนของประโยค) ห่างกันเกินนี้ ไม่จับคู่กัน


def match_marks(marks: list[int], n_chars: int, src: list[tuple[float, float, int]], u) -> list[tuple[int, tuple[float, float]]]:
    """จับคู่จุด / ในบทแปล (ตำแหน่งตัวอักษร) กับจุดหยุดในเสียงต้นฉบับของท่อน u ตามลำดับ
    จำนวนเท่ากัน = คู่กันตามลำดับ ไม่เท่า (ผู้แปลวางขาดหรือเกิน หรือบางจุดตกกลางคำ) = เลือกชุดที่ตำแหน่งตามสัดส่วน
    (ตัวอักษรในบท ↔ เวลาที่พูด) ใกล้กันที่สุด แล้วตัดคู่ที่ห่างเกิน MAX_MARK_GAP ทิ้ง"""
    if not marks or not src:
        return []
    spans = [(ps, pe) for ps, pe, _ in src]
    if len(marks) == len(src):
        return list(zip(marks, spans))
    dur = max(u.end - u.start, 1e-6)
    mf = [m / max(n_chars, 1) for m in marks]
    sf = [((ps + pe) / 2 - u.start) / dur for ps, pe in spans]
    n = min(len(mf), len(sf))
    best: Optional[tuple[float, list[tuple[int, int]]]] = None
    if len(mf) > len(sf):  # เลือก n จุด / ให้เข้ากับจุดหยุดทุกจุด
        options = ([(i, j) for j, i in enumerate(idx)] for idx in combinations(range(len(mf)), n))
    else:  # เลือก n จุดหยุดให้เข้ากับจุด / ทุกจุด
        options = ([(i, j) for i, j in enumerate(idx)] for idx in combinations(range(len(sf)), n))
    for pairs in options:
        cost = sum(abs(mf[i] - sf[j]) for i, j in pairs)
        if best is None or cost < best[0]:
            best = (cost, pairs)
    return [(marks[i], spans[j]) for i, j in best[1] if abs(mf[i] - sf[j]) <= MAX_MARK_GAP]


def plan(group: list, orig: np.ndarray, sr: int, min_pause: float = 0.3, min_chunk: float = 0.8,
         words: Optional[list] = None, min_marked_chunk: float = 0.3) -> list[Chunk]:
    """แบ่งประโยค (ท่อนที่ติดกันของคนเดียว) เป็นช่วงพูดตามจังหวะหยุดของต้นฉบับ
    words: เวลาของแต่ละคำในเสียงต้นฉบับ (words.json) ใช้หาว่าหยุดหลังพูดไปแค่ไหนแล้ว
    min_chunk: ช่วงที่ตัดเองจากความเงียบสั้นกว่านี้ยุบรวม ช่วงที่ตัดตาม / ใช้ min_marked_chunk แทน
    (นักแสดงหยุดจริงหลังคำสั้น ๆ เช่น เรียกชื่อแล้วเว้น ต้องคงจังหวะนั้นไว้)"""
    # บทที่มี / (ผู้แปลวางจุดหยุดตามความหมาย) ตัดตรงนั้นพอดี จับคู่กับจุดหยุดของต้นฉบับในท่อนนั้น (match_marks)
    marked: dict[int, list[tuple[int, tuple[float, float]]]] = {}
    clean = []
    for k, u in enumerate(group):
        text, marks, _ = split_marks(u.target)
        if marks:
            pairs = match_marks(marks, len(text), source_pauses(u, orig, sr, words, min_pause), u)
            if pairs:
                marked[k] = pairs
        clean.append(u.model_copy(update={"target": text}) if text != u.target else u)
    group = clean
    first, last = group[0], group[-1]
    seg = orig[int(first.start * sr): int(last.end * sr)]
    pauses = [(first.start + a, first.start + b) for a, b in find_pauses(seg, sr, min_pause)]
    # ช่องว่างระหว่างท่อนที่ Whisper บอกว่าไม่มีคำพูด ก็เป็นจังหวะหยุดเช่นกัน
    pauses += [(a.end, b.start) for a, b in zip(group, group[1:]) if b.start - a.end >= min_pause]

    cuts: dict[tuple[int, int], tuple[float, float]] = {}  # (ท่อน, ตำแหน่งตัวอักษร) → ช่วงหยุด
    miss: dict[tuple[int, int], float] = {}  # ระยะจากตำแหน่งที่ควรตัด หลายจุดหยุดได้ตำแหน่งเดียวกัน → เก็บจุดที่ใกล้สุด
    for k, ms in marked.items():
        for pos, span in ms:
            cuts[(k, pos)] = span
    marked_keys = set(cuts)
    for ps, pe in sorted(pauses):
        mid = (ps + pe) / 2
        # หยุดคร่อมขอบท่อน (ขอบที่ผู้ใช้ตั้งเวลาเลยเข้าไปในช่วงหยุด) → ตัดที่ขอบท่อน ไม่ตัดกลางบทของท่อนก่อน
        edge = next((k for k, (a, b) in enumerate(zip(group, group[1:]))
                     if min(a.end, b.start) <= pe + 0.05 and ps - 0.05 <= max(a.end, b.start)), None)
        if edge is not None:
            cuts.setdefault((edge, len(group[edge].target.strip())), (ps, pe))
            continue
        for k, u in enumerate(group):
            text = u.target.strip()
            if u.end <= mid and (k + 1 == len(group) or mid <= group[k + 1].start):
                if k + 1 < len(group):  # หยุดระหว่างท่อน → ตัดที่ขอบท่อน
                    cuts.setdefault((k, len(text)), (ps, pe))
                break
            if u.start <= mid < u.end and k in marked:  # ท่อนนี้ตัดตาม / แล้ว
                break
            if u.start <= mid < u.end:  # หยุดกลางท่อน → ตัดที่จุดแบ่งวลีหรือขอบคำที่ใกล้ตำแหน่งที่พูดถึงที่สุด
                target = _position(text, _spoken_fraction(u, ps, words))
                bounds = _bounds(text)
                if bounds:
                    pos = min(bounds, key=lambda b: abs(b - target) / max(len(text), 1) + bounds[b])
                    gap = abs(pos - target)
                    if gap <= 0.25 * len(text) and gap < miss.get((k, pos), float("inf")):
                        cuts[(k, pos)], miss[(k, pos)] = (ps, pe), gap
                break

    def chunks_for(keys: list[tuple[int, int]]) -> list[Chunk]:
        out, t0, k0, p0 = [], first.start, 0, 0
        for k, p in keys + [(len(group) - 1, len(group[-1].target.strip()))]:
            parts = [group[j].target.strip() for j in range(k0, k + 1)]
            parts[-1] = parts[-1][: p] if k0 != k else parts[-1][p0: p]
            if k0 != k:
                parts[0] = parts[0][p0:]
            ps, pe = cuts.get((k, p), (last.end, last.end))
            out.append(Chunk(t0, ps, " ".join(" ".join(parts).split())))
            t0, k0, p0 = pe, k, p
        return out

    def too_short(i: int, c: Chunk) -> bool:
        # ช่วงที่ขอบด้านใดด้านหนึ่งตัดตาม / ยอมให้สั้นกว่า (นักแสดงหยุดตรงนั้นจริง และผู้แปลวางจุดตามความหมาย)
        soft = (i < len(keys) and keys[i] in marked_keys) or (i > 0 and keys[i - 1] in marked_keys)
        limit, chars = (min_marked_chunk, 2) if soft else (min_chunk, 4)
        return c.end - c.start < limit or len(c.text.replace(" ", "")) < chars

    # ช่วงที่สั้นหรือมีคำน้อยเกินไป F5-TTS มักพูดมั่ว → ยุบรวมกับช่วงถัดไป
    keys = sorted(cuts)
    while keys:
        chunks = chunks_for(keys)
        bad = next((i for i, c in enumerate(chunks) if too_short(i, c)), None)
        if bad is None:
            return chunks
        keys.pop(min(bad, len(keys) - 1))
    return [Chunk(first.start, last.end, " ".join(u.target.strip() for u in group))]
