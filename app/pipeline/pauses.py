"""เว้นจังหวะหยุดตามต้นฉบับ

พากย์ทั้งประโยครวดเดียว F5-TTS จะพูดต่อกันไม่หยุด ทั้งที่นักแสดงเว้นจังหวะ (หยุดคิด กลั้นอารมณ์ เน้นคำ)
จึงหาช่วงเงียบกลางประโยคในเสียงต้นฉบับ ตัดบทไทยตรงตำแหน่งเดียวกัน (ที่ขอบท่อนหรือขอบคำที่ใกล้ที่สุด)
แล้วพากย์ทีละช่วง วางแต่ละช่วงตรงเวลาที่นักแสดงพูด
"""
from typing import NamedTuple

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


def _phrase_bounds(text: str) -> list[int]:
    """ตำแหน่งที่ตัดบทได้: หลังเว้นวรรคหรือเครื่องหมายวรรคตอน (ผู้แปลเว้นวรรคตรงจุดแบ่งวลีของภาษาไทยอยู่แล้ว)
    ไม่ตัดที่ขอบคำทั่วไป เพราะจังหวะหยุดในภาษาต้นฉบับไม่ตรงกับคำไทยพอดี ตัดแล้วชื่อหรือวลีขาดกลาง"""
    punct = " ,.!?…"
    return [i for i in range(1, len(text)) if text[i - 1] in punct and text[i] not in punct]


def plan(group: list, orig: np.ndarray, sr: int, min_pause: float = 0.3, min_chunk: float = 1.0) -> list[Chunk]:
    """แบ่งประโยค (ท่อนที่ติดกันของคนเดียว) เป็นช่วงพูดตามจังหวะหยุดของต้นฉบับ"""
    first, last = group[0], group[-1]
    seg = orig[int(first.start * sr): int(last.end * sr)]
    pauses = [(first.start + a, first.start + b) for a, b in find_pauses(seg, sr, min_pause)]
    # ช่องว่างระหว่างท่อนที่ Whisper บอกว่าไม่มีคำพูด ก็เป็นจังหวะหยุดเช่นกัน
    pauses += [(a.end, b.start) for a, b in zip(group, group[1:]) if b.start - a.end >= min_pause]

    cuts: dict[tuple[int, int], tuple[float, float]] = {}  # (ท่อน, ตำแหน่งตัวอักษร) → ช่วงหยุด
    for ps, pe in sorted(pauses):
        mid = (ps + pe) / 2
        for k, u in enumerate(group):
            text = u.target.strip()
            if u.end <= mid and (k + 1 == len(group) or mid <= group[k + 1].start):
                if k + 1 < len(group):  # หยุดระหว่างท่อน → ตัดที่ขอบท่อน
                    cuts.setdefault((k, len(text)), (ps, pe))
                break
            if u.start <= mid < u.end:  # หยุดกลางท่อน → ตัดที่จุดแบ่งวลีที่ใกล้สัดส่วนเวลาที่สุด
                target = (mid - u.start) / max(u.duration, 1e-3) * len(text)
                bounds = _phrase_bounds(text)
                if bounds:
                    pos = min(bounds, key=lambda b: abs(b - target))
                    if abs(pos - target) <= 0.3 * len(text):
                        cuts.setdefault((k, pos), (ps, pe))
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
