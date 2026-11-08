"""ซ่อมบท/เวลาที่พังจาก Whisper โดยไม่ต้องให้คนแก้มือ

เคสที่พบบ่อย (ภาษาไทย): วรรณยุกต์หรือตัวอักษรเดี่ยวถูกยืดเวลาหลายวินาที
ทำให้ท่อนถัดไปติดกันเป็นช่วงว่างยาว บทขาดกลางคำ และ TTS พากย์มั่ว
"""
from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from typing import Optional

from ..config import settings
from ..schemas import Utterance
from .common import Turn, Word
from .transcribe import THAI_FOLLOWING, THAI_LEADING, assign_speakers

log = logging.getLogger("dubbing.repair")

# ตัวอักษร/เครื่องหมายหนึ่งก้อนยาวเกินนี้ (วินาที) ถือว่าเวลาเพี้ยน → ตัดทิ้งส่วนเกิน
_MAX_GLYPH_SEC = 0.55
# ช่องว่างระหว่างคำหลัง clamp ยาวเกินนี้ → ตัดเป็นคนละท่อน (เท่ากับ assign_speakers)
_GAP_SEC = 1.0


def clamp_words(words: list[Word], max_glyph_sec: float = _MAX_GLYPH_SEC) -> list[Word]:
    """ตัดเวลาปลายของคำที่ Whisper ยืดผิดปกติ (วรรณยุกต์ยาวเป็นสิบวิ) ให้เหลือความยาวสมเหตุสมผล"""
    if not words:
        return words
    out: list[Word] = []
    for w in words:
        text = w.text or ""
        n = max(1, len(text.strip()) or 1)
        # เครื่องหมายวรรณยุกต์/สระบนล่างยาวเกินจริงบ่อยสุด
        mark = any(unicodedata.category(c) == "Mn" or c in THAI_FOLLOWING or c in THAI_LEADING for c in text)
        cap = (0.25 if mark else max_glyph_sec) * n
        end = min(float(w.end), float(w.start) + max(0.08, cap))
        out.append(Word(round(w.start, 3), round(end, 3), w.text, w.segment))
    for i in range(len(out) - 1):
        if out[i].end > out[i + 1].start:
            out[i] = Word(out[i].start, round(out[i + 1].start, 3), out[i].text, out[i].segment)
    return out


def _cut_marker(text: str) -> bool:
    """บทถูกตัดกลางชัดเจน: ลงท้ายด้วยสระหน้าเปล่าหรือขีด (ไม่นับวรรณยุกต์ท้ายคำปกติ เช่น อยู่)"""
    t = (text or "").rstrip()
    if not t:
        return True
    return t[-1] in "-–—" or t[-1] in THAI_LEADING


def _orphan_fragment(u: Utterance) -> bool:
    """ท่อนสั้นที่เกิดจากวรรณยุกต์ถูกยืดแล้วตัดขาด (เช่น 'เดี๋' ก่อนช่องว่างยาว)"""
    t = (u.source or "").strip()
    return bool(t) and u.duration <= 1.2 and len(t) <= 6


def peel_last_syllable(text: str) -> tuple[str, str]:
    """แยกพยางค์ไทยท้ายสุด: วรรณยุกต์/สระตาม → พยัญชนะ → สระหน้า"""
    t = (text or "").rstrip()
    if not t:
        return "", ""
    i = len(t)
    while i > 0 and (unicodedata.category(t[i - 1]) == "Mn" or t[i - 1] in THAI_FOLLOWING):
        i -= 1
    if i > 0:
        i -= 1
    if i > 0 and t[i - 1] in THAI_LEADING:
        i -= 1
    return t[:i].rstrip(), t[i:]


def merge_broken_thai(utts: list[Utterance]) -> list[Utterance]:
    """เศษท่อนสั้นจากเวลา Whisper พัง → ต่อเข้าท่อนถัดไปของคนเดิม
    ถ้าช่องว่างระหว่างท่อนยาวผิดปกติ (>1s) แต่พยางค์ท้ายติดท่อนก่อน → ย้ายพยางค์ท้ายไปท่อนหลัง"""
    if not utts:
        return utts
    out: list[Utterance] = []
    i = 0
    while i < len(utts):
        u = utts[i]
        nxt = utts[i + 1] if i + 1 < len(utts) else None
        if nxt and nxt.speaker == u.speaker:
            whole = (u.source or "").strip()
            gap = nxt.start - u.end
            if _orphan_fragment(u) or (whole and whole[-1] in "-–—"):
                piece = whole.rstrip("-–—")
                merged = nxt.model_copy(update={
                    "source": (piece + nxt.source).strip(),
                    "target": ((u.target or "") + (nxt.target or "")).strip() if (u.target or nxt.target) else "",
                })
                log.info("merge orphan Thai fragment %d+%d → %r", u.id, nxt.id, merged.source)
                out.append(merged)
                i += 2
                continue
            # วรรณยุกต์ยืดทำให้พยางค์ต้นคำไปติดท่อนก่อน แล้วเว้นว่างยาวผิดปกติถึงท่อนจริง
            # เกณฑ์สูงกว่าช่องว่างประโยคปกติ (~1s) เพื่อไม่ฉีกคำท้ายอย่าง "อยู่"
            if gap > 3.0 and len(whole) > 6:
                head, tail = peel_last_syllable(whole)
                if head and tail and len(tail) <= 6:
                    log.info("move trailing syllable across gap: %r → next (%r)", tail, head)
                    out.append(u.model_copy(update={
                        "source": head,
                        "target": head if u.target == u.source else (u.target or ""),
                    }))
                    utts[i + 1] = nxt.model_copy(update={"source": (tail + nxt.source).strip()})
                    i += 1
                    continue
            if _cut_marker(u.source):
                head, tail = peel_last_syllable(u.source) if u.source.rstrip()[-1:] in THAI_LEADING else (u.source[:-1], u.source[-1])
                if head and tail:
                    out.append(u.model_copy(update={"source": head}))
                    utts[i + 1] = nxt.model_copy(update={"source": (tail + nxt.source).strip()})
                    i += 1
                    continue
        out.append(u)
        i += 1
    for i, u in enumerate(out, 1):
        if u.id != i:
            out[i - 1] = u.model_copy(update={"id": i})
    return out


def _fingerprint(utts: list[Utterance]) -> list[tuple]:
    return [(u.speaker, round(u.start, 2), round(u.end, 2), u.source) for u in utts]


def repair_transcript(utterances: list[Utterance], words: Optional[list[Word]],
                      turns: Optional[list[Turn]], lang: str = "") -> tuple[list[Utterance], list[Word], int]:
    """ซ่อมเวลาคำ → สร้างท่อนใหม่ → รวมเศษพยางค์ไทย
    คืน (ท่อน, คำที่ clamp แล้ว, จำนวนท่อนที่เปลี่ยนเทียบของเดิม)"""
    if not words:
        return utterances, words or [], 0
    clamped = clamp_words(words)
    changed_words = sum(
        1 for a, b in zip(words, clamped)
        if abs(a.end - b.end) > 0.05 or abs(a.start - b.start) > 0.05
    )
    if turns:
        rebuilt = assign_speakers(clamped, turns, max_len=settings.max_line_sec, lang=lang or "")
    else:
        # ไม่มี turns: ใช้ speaker จากท่อนเดิมตามเวลาทับ
        rebuilt = _reassign_from_old(utterances, clamped, lang or "")
    if lang == "th" or (lang or "").startswith("th"):
        rebuilt = merge_broken_thai(rebuilt)
    # คง target/mood ที่ผู้ใช้หรือขั้นแปลใส่ไว้ ถ้าต้นฉบับยังตรง
    by_src = {}
    for u in utterances:
        by_src.setdefault(u.source.strip(), u)
    kept = []
    for u in rebuilt:
        prev = by_src.get(u.source.strip())
        if prev and prev.target:
            u = u.model_copy(update={
                "target": prev.target, "mood": prev.mood, "mood_auto": prev.mood_auto,
                "mood_auto_text": prev.mood_auto_text, "take": prev.take,
                "check_note": prev.check_note, "unclear": prev.unclear,
            })
        kept.append(u)
    n = 0 if _fingerprint(utterances) == _fingerprint(kept) else max(1, abs(len(kept) - len(utterances)) + changed_words)
    if n:
        log.info("repair transcript: %d lines → %d lines (%d word timings clamped)",
                 len(utterances), len(kept), changed_words)
    return kept, clamped, n


def _reassign_from_old(old: list[Utterance], words: list[Word], lang: str) -> list[Utterance]:
    """เมื่อไม่มี turns สร้างท่อนจากคำ โดยยืมชื่อผู้พูดจากท่อนเดิมที่ทับเวลามากที่สุด"""
    dummy = [Turn(0.0, 1e9, "speaker_01")]
    if old:
        dummy = [Turn(u.start, u.end, u.speaker) for u in old]
    rebuilt = assign_speakers(words, dummy, max_len=settings.max_line_sec, lang=lang)

    def speaker_at(t: float) -> str:
        hit = [u for u in old if u.start - 0.05 <= t <= u.end + 0.05]
        return max(hit, key=lambda u: min(u.end, t + 0.1) - max(u.start, t - 0.1)).speaker if hit else (
            old[0].speaker if old else "speaker_01")

    out = []
    for u in rebuilt:
        mid = (u.start + u.end) / 2
        out.append(u.model_copy(update={"speaker": speaker_at(mid)}))
    return out


def _estimate_sec(text: str, lang: str) -> float:
    from .translate import estimate_seconds
    return estimate_seconds(text or "", "en" if lang == "en" else "th")


def is_bloated(u: Utterance, lang: str) -> bool:
    """ช่วงยาวผิดปกติเทียบกับความยาวบท (มักเกิดจากวรรณยุกต์ยืด / รวมท่อนผิด)"""
    need = _estimate_sec(u.source, lang)
    return u.duration >= 2.0 and need > 0 and need < u.duration * 0.35


def suspects(utts: list[Utterance], lang: str) -> list[Utterance]:
    """ท่อนที่ยังไม่ควรส่งไปแปล/พากย์โดยไม่ซ่อม"""
    out = []
    for u in utts:
        src = (u.source or "").strip()
        if not src:
            out.append(u)
        elif _cut_marker(src):
            out.append(u)
        elif is_bloated(u, lang):
            out.append(u)
        elif u.duration >= settings.max_line_sec and _estimate_sec(src, lang) < u.duration * 0.5:
            out.append(u)
    return out


def _dense_run(words: list[Word], max_gap: float = 0.45) -> list[Word]:
    if not words:
        return []
    runs: list[list[Word]] = [[words[0]]]
    for w in words[1:]:
        if w.start - runs[-1][-1].end <= max_gap:
            runs[-1].append(w)
        else:
            runs.append([w])
    return max(runs, key=lambda r: (sum(len(x.text or "") for x in r), r[-1].end - r[0].start))


def tighten_bloated(utts: list[Utterance], words: list[Word], lang: str) -> list[Utterance]:
    """รัด start/end/source ของท่อนบวมให้เหลือช่วงคำที่หนาแน่นที่สุด"""
    if not words:
        return utts
    out: list[Utterance] = []
    for u in utts:
        if not is_bloated(u, lang):
            out.append(u)
            continue
        mid = lambda w: (w.start + w.end) / 2  # noqa: E731
        ws = [w for w in words if u.start - 0.05 <= mid(w) <= u.end + 0.05]
        run = _dense_run(ws)
        if not run:
            out.append(u)
            continue
        text = "".join(w.text or "" for w in run).strip()
        if not text:
            out.append(u)
            continue
        nu = u.model_copy(update={
            "start": round(run[0].start, 3),
            "end": round(run[-1].end, 3),
            "source": text,
        })
        log.info("tighten bloated line %d: %.1fs → %.1fs %r", u.id, u.duration, nu.duration, text[:40])
        out.append(nu)
    for i, u in enumerate(out, 1):
        if u.id != i:
            out[i - 1] = u.model_copy(update={"id": i})
    return out


def retranscribe_windows(words: list[Word], audio_path: Path, lang: str,
                         windows: list[tuple[float, float]]) -> list[Word]:
    """ถอดช่วงน่าสงสัยใหม่จาก vocals/เสียงพูด (ต้องมี faster-whisper บนเครื่องที่รัน)
    API image (ML=0 / WORKER=modal) ไม่มีแพ็กเกจนี้ — ข้ามแล้วใช้ผลจาก Modal ที่ gate ไปแล้ว"""
    if not windows:
        return words
    try:
        import soundfile as sf
        from .transcribe import _load
        model = _load()  # import faster_whisper อยู่ข้างใน — จับที่นี่ ไม่ให้งานพังบน API
    except Exception as exc:  # noqa: BLE001
        log.info("retranscribe skipped (no whisper here): %s", exc)
        return words
    try:
        audio, sr = sf.read(str(audio_path), dtype="float32")
    except Exception as exc:  # noqa: BLE001
        log.warning("retranscribe read failed: %s", exc)
        return words
    audio = audio.mean(axis=1) if getattr(audio, "ndim", 1) > 1 else audio
    seg_id = max((w.segment for w in words), default=-1) + 1
    out = list(words)
    for a, b in windows:
        lo, hi = max(0.0, a - 0.15), min(len(audio) / sr, b + 0.15)
        if hi - lo < 0.4:
            continue
        try:
            segments, _ = model.transcribe(
                audio[int(lo * sr): int(hi * sr)], language=lang or None, vad_filter=False,
                word_timestamps=True, beam_size=5, condition_on_previous_text=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("retranscribe window %.1f-%.1f failed: %s", a, b, exc)
            continue
        new: list[Word] = []
        for seg in segments:
            if getattr(seg, "no_speech_prob", 0) > 0.7:
                continue
            for w in seg.words or []:
                new.append(Word(round(lo + w.start, 3), round(lo + w.end, 3), w.word, seg_id))
            if new:
                seg_id += 1
        if not new:
            continue
        mid = lambda w: (w.start + w.end) / 2  # noqa: E731
        drop = {id(w) for w in out if a <= mid(w) <= b}
        out = [w for w in out if id(w) not in drop] + new
        log.info("retranscribe %.1f-%.1f: %d words → %r", a, b, len(new),
                 "".join(w.text for w in new)[:60])
    return sorted(out, key=lambda w: w.start)


def gate_before_translate(utterances: list[Utterance], words: Optional[list[Word]],
                          turns: Optional[list[Turn]], lang: str,
                          vocals_path: Optional[Path] = None) -> tuple[list[Utterance], list[Word], dict]:
    """เกณฑ์ก่อนแปล: รัดท่อนบวม → ถอดช่วงน่าสงสัยใหม่ (ถ้ามี whisper) → repair อีกครั้ง
    คืน (ท่อน, คำ, สถิติ)"""
    stats = {"bloated": 0, "retranscribed": 0, "still_bad": 0}
    if not settings.transcript_gate or not words:
        return utterances, words or [], stats
    words = clamp_words(words)
    before_bad = suspects(utterances, lang)
    stats["bloated"] = sum(1 for u in before_bad if is_bloated(u, lang))
    utterances = tighten_bloated(utterances, words, lang)
    bad = suspects(utterances, lang)
    if bad and vocals_path is not None and Path(vocals_path).exists():
        windows = [(u.start, u.end) for u in bad]
        # ขยายหน้าต่างให้คลุมช่องว่างที่อาจมีคำหาย
        merged: list[list[float]] = []
        for a, b in sorted(windows):
            if merged and a - merged[-1][1] < 0.8:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        new_words = retranscribe_windows(words, Path(vocals_path), lang, [(a, b) for a, b in merged])
        if new_words != words:
            stats["retranscribed"] = len(merged)
            words = clamp_words(new_words)
            utterances, words, _ = repair_transcript(utterances, words, turns, lang)
            utterances = tighten_bloated(utterances, words, lang)
    still = suspects(utterances, lang)
    stats["still_bad"] = len(still)
    for u in still:
        note = "ท่อนเวลาหรือบทยังน่าสงสัยหลังซ่อมอัตโนมัติ"
        if not u.check_note:
            u.check_note = note
        u.unclear = True
    if any(stats.values()):
        log.info("transcript gate: %s", stats)
    return utterances, words, stats
