"""เว้นจังหวะหยุดตามต้นฉบับ

พากย์ทั้งประโยครวดเดียว F5-TTS จะพูดต่อกันไม่หยุด ทั้งที่นักแสดงเว้นจังหวะ (หยุดหายใจ หยุดคิด กลั้นอารมณ์ เน้นคำ)
จึงหาช่วงเงียบกลางประโยคในเสียงต้นฉบับ ตัดบทไทยตรงตำแหน่งเดียวกัน (ที่ขอบท่อน จุดแบ่งวลี หรือขอบคำที่ใกล้ที่สุด)
แล้วพากย์ทีละช่วง วางแต่ละช่วงตรงเวลาที่นักแสดงพูด
"""
import re
import unicodedata
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


def plan(group: list, orig: np.ndarray, sr: int, min_pause: float = 0.3, min_chunk: float = 0.8,
         words: Optional[list] = None) -> list[Chunk]:
    """แบ่งประโยค (ท่อนที่ติดกันของคนเดียว) เป็นช่วงพูดตามจังหวะหยุดของต้นฉบับ
    words: เวลาของแต่ละคำในเสียงต้นฉบับ (words.json) ใช้หาว่าหยุดหลังพูดไปแค่ไหนแล้ว"""
    first, last = group[0], group[-1]
    seg = orig[int(first.start * sr): int(last.end * sr)]
    pauses = [(first.start + a, first.start + b) for a, b in find_pauses(seg, sr, min_pause)]
    # ช่องว่างระหว่างท่อนที่ Whisper บอกว่าไม่มีคำพูด ก็เป็นจังหวะหยุดเช่นกัน
    pauses += [(a.end, b.start) for a, b in zip(group, group[1:]) if b.start - a.end >= min_pause]

    cuts: dict[tuple[int, int], tuple[float, float]] = {}  # (ท่อน, ตำแหน่งตัวอักษร) → ช่วงหยุด
    miss: dict[tuple[int, int], float] = {}  # ระยะจากตำแหน่งที่ควรตัด หลายจุดหยุดได้ตำแหน่งเดียวกัน → เก็บจุดที่ใกล้สุด
    for ps, pe in sorted(pauses):
        mid = (ps + pe) / 2
        for k, u in enumerate(group):
            text = u.target.strip()
            if u.end <= mid and (k + 1 == len(group) or mid <= group[k + 1].start):
                if k + 1 < len(group):  # หยุดระหว่างท่อน → ตัดที่ขอบท่อน
                    cuts.setdefault((k, len(text)), (ps, pe))
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

    # ช่วงที่สั้นหรือมีคำน้อยเกินไป F5-TTS มักพูดมั่ว → ยุบรวมกับช่วงถัดไป
    keys = sorted(cuts)
    while keys:
        chunks = chunks_for(keys)
        bad = next((i for i, c in enumerate(chunks)
                    if c.end - c.start < min_chunk or len(c.text.replace(" ", "")) < 4), None)
        if bad is None:
            return chunks
        keys.pop(min(bad, len(keys) - 1))
    return [Chunk(first.start, last.end, " ".join(u.target.strip() for u in group))]
