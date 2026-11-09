"""ตัดคลิปยาวเป็นชิ้น + รวมผลวิเคราะห์ (ขนานบน Modal)

คลิปยาวเกินเกณฑ์ → ตัดช่วงละ ANALYZE_CHUNK_SEC ซ้อนทับ overlap
วิเคราะห์ขนานแล้วเลื่อนเวลา / แม็ปผู้พูด / ตัดท่อนซ้ำในโซนซ้อน
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from ..schemas import Utterance
from .common import Turn, Word

log = logging.getLogger("dubbing.chunks")


@dataclass(frozen=True)
class Window:
    index: int
    start: float  # วินาทีจากต้นคลิป
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def plan_windows(
    duration: float,
    *,
    chunk_sec: float = 480.0,
    overlap_sec: float = 10.0,
    min_total_sec: float = 720.0,
) -> list[Window]:
    """คืนช่วงตัด หรือ [] ถ้าคลิปสั้นเกินเกณฑ์ / ชิ้นเดียวไม่คุ้ม"""
    if duration < min_total_sec or chunk_sec <= 0:
        return []
    overlap = max(0.0, min(overlap_sec, chunk_sec * 0.25))
    step = max(1.0, chunk_sec - overlap)
    out: list[Window] = []
    i, t = 0, 0.0
    while t < duration - 0.5:
        end = min(duration, t + chunk_sec)
        out.append(Window(i, round(t, 3), round(end, 3)))
        i += 1
        if end >= duration - 0.05:
            break
        t += step
    return out if len(out) >= 2 else []


def _overlap_mid(a: Window, b: Window) -> Optional[float]:
    lo, hi = max(a.start, b.start), min(a.end, b.end)
    if hi <= lo:
        return None
    return (lo + hi) / 2


def responsibility(windows: list[Window], i: int) -> tuple[float, float]:
    """ช่วงเวลา (absolute) ที่ชิ้น i รับผิดชอบหลังตัดซ้ำใน overlap: [left, right)"""
    left = float("-inf")
    right = float("inf")
    if i > 0:
        mid = _overlap_mid(windows[i - 1], windows[i])
        if mid is not None:
            left = mid
    if i + 1 < len(windows):
        mid = _overlap_mid(windows[i], windows[i + 1])
        if mid is not None:
            right = mid
    return left, right


def _owns(mid: float, left: float, right: float) -> bool:
    return mid >= left and mid < right


def _shift_turn(t: Turn, offset: float) -> Turn:
    return Turn(round(t.start + offset, 3), round(t.end + offset, 3), t.speaker)


def _shift_word(w: Word, offset: float) -> Word:
    return Word(round(w.start + offset, 3), round(w.end + offset, 3), w.text, w.segment)


def _shift_utt(u: Utterance, offset: float) -> Utterance:
    return u.model_copy(update={
        "start": round(u.start + offset, 3),
        "end": round(u.end + offset, 3),
    })


def _as_turn(t: Any) -> Turn:
    return t if isinstance(t, Turn) else Turn(**t)


def _as_word(w: Any) -> Word:
    return w if isinstance(w, Word) else Word(**w)


def _as_utt(u: Any) -> Utterance:
    return u if isinstance(u, Utterance) else Utterance.model_validate(u)


def _map_speakers(prev: list[Turn], nxt: list[Turn], mid: float, pad: float = 8.0) -> dict[str, str]:
    """แม็ปชื่อผู้พูดของชิ้นถัดไป → ชื่อในชิ้นก่อน จากช่วงซ้อน"""
    lo, hi = mid - pad, mid + pad
    prev_sp = {t.speaker for t in prev}
    mapping: dict[str, str] = {}
    for sp in sorted({t.speaker for t in nxt}):
        best, best_ov = None, 0.0
        for ps in prev_sp:
            ov = 0.0
            for a in (t for t in nxt if t.speaker == sp):
                for b in (t for t in prev if t.speaker == ps):
                    s, e = max(a.start, b.start, lo), min(a.end, b.end, hi)
                    if e > s:
                        ov += e - s
            if ov > best_ov:
                best, best_ov = ps, ov
        if best and best_ov >= 0.15:
            mapping[sp] = best
    return mapping


def _apply_speaker_map(
    turns: list[Turn],
    utts: list[Utterance],
    mapping: dict[str, str],
    taken: set[str],
) -> tuple[list[Turn], list[Utterance], set[str]]:
    local = dict(mapping)
    for sp in sorted({t.speaker for t in turns} | {u.speaker for u in utts}):
        if sp in local:
            continue
        n = 1
        while f"speaker_{n:02d}" in taken:
            n += 1
        name = f"speaker_{n:02d}"
        local[sp] = name
        taken.add(name)

    def ren(s: str) -> str:
        return local.get(s, s)

    turns2 = [Turn(t.start, t.end, ren(t.speaker)) for t in turns]
    utts2 = [u.model_copy(update={"speaker": ren(u.speaker)}) for u in utts]
    return turns2, utts2, taken


def merge_chunk_results(
    windows: list[Window],
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    """รวม turns/words/utterances/speakers/features/recheck จากหลายชิ้น

    แต่ละ part ใช้เวลาสัมพัทธ์ในชิ้น (เริ่มที่ 0) — ฟังก์ชันนี้เลื่อนเป็น absolute
    """
    if len(windows) != len(parts):
        raise ValueError("windows/parts length mismatch")

    all_turns: list[Turn] = []
    all_words: list[Word] = []
    kept_pairs: list[tuple[Utterance, Optional[dict]]] = []
    speech_spans: list[list[float]] = []
    rechecks: list = []
    lang = None
    taken: set[str] = set()
    prev_turns: list[Turn] = []  # ทั้งชิ้นก่อนตัด overlap — ใช้แม็ปผู้พูด

    for i, (win, part) in enumerate(zip(windows, parts)):
        offset = win.start
        left, right = responsibility(windows, i)
        turns = [_shift_turn(_as_turn(t), offset) for t in part.get("turns") or []]
        words = [_shift_word(_as_word(w), offset) for w in part.get("words") or []]
        utts = [_shift_utt(_as_utt(u), offset) for u in part.get("utterances") or []]

        if i == 0:
            taken = {t.speaker for t in turns} | {u.speaker for u in utts}
        else:
            mid = _overlap_mid(windows[i - 1], win) or win.start
            mapping = _map_speakers(prev_turns, turns, mid)
            turns, utts, taken = _apply_speaker_map(turns, utts, mapping, taken)

        prev_turns = turns
        feat_src = (part.get("features") or {}).get("lines") or {}
        for u in utts:
            mid = (u.start + u.end) / 2
            if not _owns(mid, left, right):
                continue
            raw = feat_src.get(str(u.id), feat_src.get(u.id))
            feat = dict(raw) if isinstance(raw, dict) else None
            kept_pairs.append((u, feat))

        turns = [t for t in turns if _owns((t.start + t.end) / 2, left, right)]
        words = [w for w in words if _owns((w.start + w.end) / 2, left, right)]

        all_turns.extend(turns)
        all_words.extend(words)
        lang = lang or part.get("lang") or part.get("detected_lang")
        for span in (part.get("features") or {}).get("speech") or []:
            if isinstance(span, (list, tuple)) and len(span) >= 2:
                a = round(float(span[0]) + offset, 3)
                b = round(float(span[1]) + offset, 3)
                if _owns((a + b) / 2, left, right):
                    speech_spans.append([a, b])
        if part.get("recheck"):
            rechecks.append(part["recheck"])

    kept_pairs.sort(key=lambda p: (p[0].start, p[0].end))
    all_utts: list[Utterance] = []
    features_lines: dict[int, Any] = {}
    for nid, (u, feat) in enumerate(kept_pairs, 1):
        nu = u.model_copy(update={"id": nid})
        all_utts.append(nu)
        if feat is not None:
            features_lines[nid] = {**feat, "start": nu.start, "end": nu.end}

    all_turns.sort(key=lambda t: (t.start, t.end))
    all_words.sort(key=lambda w: (w.start, w.end))
    speakers = sorted({u.speaker for u in all_utts} | {t.speaker for t in all_turns})
    recheck = None
    if rechecks:
        recheck = {
            "chunks": len(rechecks),
            "words_before": sum(int(r.get("words_before") or 0) for r in rechecks),
            "words_after": sum(int(r.get("words_after") or 0) for r in rechecks),
            "seconds": round(sum(float(r.get("seconds") or 0) for r in rechecks), 1),
        }
    log.info(
        "merged %d chunks → %d utts, %d speakers, %d turns",
        len(windows), len(all_utts), len(speakers), len(all_turns),
    )
    return {
        "turns": all_turns,
        "words": all_words,
        "utterances": all_utts,
        "speakers": speakers,
        "lang": lang,
        "features": {"lines": features_lines, "speech": speech_spans},
        "recheck": recheck,
    }


def stitch_wavs(
    pieces: list[tuple[Window, np.ndarray, int]],
    overlap_sec: float,
) -> tuple[np.ndarray, int]:
    """ต่อ vocals/bgm จากหลายชิ้น โดยตัดครึ่ง overlap ตรงกลาง — คืน (wav, sr)"""
    if not pieces:
        raise RuntimeError("ไม่มีเสียงต่อจากชิ้นวิเคราะห์")
    sr0 = pieces[0][2]
    out: list[np.ndarray] = []
    n = len(pieces)
    for i, (win, wav, sr) in enumerate(pieces):
        if wav.ndim == 1:
            wav = wav[:, None]
        if sr != sr0:
            raise RuntimeError(f"sample rate ไม่ตรง: {sr} vs {sr0}")
        rel_start = (overlap_sec / 2) if i > 0 and overlap_sec > 0 else 0.0
        rel_end = win.duration - ((overlap_sec / 2) if i + 1 < n and overlap_sec > 0 else 0.0)
        a = max(0, int(rel_start * sr))
        b = min(len(wav), int(rel_end * sr))
        if b > a:
            out.append(wav[a:b])
    if not out:
        raise RuntimeError("ช่วงตัด overlap ทับกันจนไม่เหลือเสียง")
    merged = np.concatenate(out, axis=0)
    if merged.shape[1] == 1:
        merged = merged[:, 0]
    return merged, sr0
