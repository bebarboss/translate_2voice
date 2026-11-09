"""วัดคุณภาพจากไฟล์ใน job (ต้นฉบับ vs ผลถอด/พากย์) โดยไม่พึ่งคนแก้บท

สัญญาณหลัก:
- speech_coverage: ช่วงมีเสียงพูดบน vocals เทียบช่วง transcript
- dub_match: ค่าเฉลี่ย heard_score / สัดส่วนท่อนที่ผ่าน
- timing_fit: ความยาวไฟล์ tts เทียบช่องปาก
- recheck_gain: คำที่กู้ได้จาก recheck.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .schemas import Utterance

log = logging.getLogger("dubbing.job_metrics")

# เกณฑ์ auto-heal (coverage ต่ำกว่านี้ → ซ่อม ASR รอบหนึ่ง)
COVERAGE_HEAL_MIN = 0.85


def _load_wav(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if getattr(wav, "ndim", 1) > 1:
        wav = wav.mean(axis=1)
    return np.asarray(wav, dtype=np.float32), int(sr)


def speech_regions(
    wav: np.ndarray,
    sr: int,
    *,
    frame_ms: float = 30.0,
    hop_ms: float = 10.0,
    energy_db: float = -35.0,
    min_sec: float = 0.12,
    pad_sec: float = 0.05,
) -> list[tuple[float, float]]:
    """ช่วงที่มีเสียงพูดโดยประมาณจากพลังงาน (ไม่ต้องมี Silero/GPU) — ใช้เป็นต้นฉบับสำหรับ coverage"""
    if wav is None or len(wav) == 0 or sr <= 0:
        return []
    frame = max(1, int(sr * frame_ms / 1000))
    hop = max(1, int(sr * hop_ms / 1000))
    if len(wav) < frame:
        return []
    # RMS ต่อเฟรม → dB เทียบ peak
    peak = float(np.max(np.abs(wav))) + 1e-9
    norm = wav / peak
    n = 1 + (len(norm) - frame) // hop
    energies = np.empty(n, dtype=np.float32)
    for i in range(n):
        seg = norm[i * hop: i * hop + frame]
        energies[i] = 20.0 * np.log10(float(np.sqrt(np.mean(seg * seg)) + 1e-12))
    spoken = energies >= energy_db
    regions: list[tuple[float, float]] = []
    i = 0
    while i < n:
        if not spoken[i]:
            i += 1
            continue
        j = i + 1
        while j < n and spoken[j]:
            j += 1
        start = max(0.0, (i * hop) / sr - pad_sec)
        end = min(len(wav) / sr, (j * hop + frame) / sr + pad_sec)
        if end - start >= min_sec:
            regions.append((round(start, 3), round(end, 3)))
        i = j
    return _merge_spans(regions, gap=0.15)


def _merge_spans(spans: list[tuple[float, float]], gap: float = 0.15) -> list[tuple[float, float]]:
    if not spans:
        return []
    out = [spans[0]]
    for a, b in spans[1:]:
        pa, pb = out[-1]
        if a <= pb + gap:
            out[-1] = (pa, max(pb, b))
        else:
            out.append((a, b))
    return out


def transcript_spans(utts: list[Utterance]) -> list[tuple[float, float]]:
    return _merge_spans([(float(u.start), float(u.end)) for u in utts if u.end > u.start], gap=0.05)


def span_coverage(reference: list[tuple[float, float]], got: list[tuple[float, float]]) -> dict[str, Any]:
    """สัดส่วนเวลาใน reference ที่ถูกคลุมด้วย got"""
    ref_dur = sum(max(0.0, b - a) for a, b in reference)
    if ref_dur <= 1e-6:
        return {"coverage": 1.0, "ref_sec": 0.0, "covered_sec": 0.0, "missed": []}
    covered = 0.0
    missed: list[dict] = []
    for a, b in reference:
        hit = 0.0
        for c, d in got:
            hit += max(0.0, min(b, d) - max(a, c))
        hit = min(hit, b - a)
        covered += hit
        if hit / max(1e-6, b - a) < 0.35:
            missed.append({"start": a, "end": b, "covered": round(hit, 3)})
    return {
        "coverage": round(covered / ref_dur, 4),
        "ref_sec": round(ref_dur, 3),
        "covered_sec": round(covered, 3),
        "missed": missed[:20],
        "n_missed": len(missed),
    }


def speech_coverage_from_arrays(
    wav: np.ndarray, sr: int, utts: list[Utterance], **kwargs: Any
) -> dict[str, Any]:
    speech = speech_regions(wav, sr, **kwargs)
    got = transcript_spans(utts)
    cov = span_coverage(speech, got)
    cov["speech_spans"] = len(speech)
    cov["transcript_spans"] = len(got)
    return cov


def speech_coverage_file(job_dir: Path, utts: Optional[list[Utterance]] = None) -> dict[str, Any]:
    wav_path = job_dir / "vocals.wav"
    if not wav_path.exists():
        wav_path = job_dir / "audio.wav"
    if not wav_path.exists():
        return {"coverage": None, "error": "no_audio"}
    if utts is None:
        utts = _load_transcript(job_dir)
    try:
        wav, sr = _load_wav(wav_path)
    except Exception as exc:  # noqa: BLE001
        return {"coverage": None, "error": str(exc)}
    return speech_coverage_from_arrays(wav, sr, utts)


def dub_match_from_utts(utts: list[Utterance], *, min_score: float = 0.6) -> dict[str, Any]:
    scores = [float(u.heard_score) for u in utts if u.heard_score is not None]
    flagged = sum(1 for u in utts if u.heard)
    if not scores:
        return {
            "mean": None, "n_scored": 0, "n_flagged": flagged, "pass_rate": None,
            "ok": flagged == 0,
        }
    mean = sum(scores) / len(scores)
    passed = sum(1 for s in scores if s >= min_score)
    return {
        "mean": round(mean, 4),
        "n_scored": len(scores),
        "n_flagged": flagged,
        "pass_rate": round(passed / len(scores), 4),
        "ok": flagged == 0 and mean >= min_score,
    }


def timing_fit(job_dir: Path, utts: list[Utterance], *, sr_hint: int = 24000) -> dict[str, Any]:
    """เทียบความยาวไฟล์ tts/NNNN.wav กับช่องปาก"""
    import soundfile as sf

    tts_dir = job_dir / "tts"
    ratios: list[float] = []
    missing = 0
    for u in utts:
        slot = max(0.05, float(u.end) - float(u.start))
        path = tts_dir / f"{u.id:04d}.wav"
        if not path.exists():
            missing += 1
            continue
        try:
            info = sf.info(str(path))
            dur = float(info.frames) / float(info.samplerate or sr_hint)
        except Exception:  # noqa: BLE001
            missing += 1
            continue
        ratios.append(dur / slot)
    if not ratios:
        return {"mean_ratio": None, "n": 0, "missing": missing, "ok": None}
    mean = sum(ratios) / len(ratios)
    # พอดีถ้าเฉลี่ยอยู่ใน 0.65–1.15
    ok = 0.65 <= mean <= 1.15
    return {
        "mean_ratio": round(mean, 4),
        "n": len(ratios),
        "missing": missing,
        "under": sum(1 for r in ratios if r < 0.65),
        "over": sum(1 for r in ratios if r > 1.15),
        "ok": ok,
    }


def recheck_gain(job_dir: Path) -> dict[str, Any]:
    path = job_dir / "recheck.json"
    if not path.exists():
        return {"gain_letters": None, "replaced": None, "unclear": None, "ok": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"gain_letters": None, "replaced": None, "unclear": None, "ok": None}
    before = int(data.get("letters_before") or 0)
    after = int(data.get("letters_after") or 0)
    return {
        "gain_letters": after - before,
        "replaced": data.get("replaced"),
        "unclear": data.get("unclear") or data.get("unclear_lines"),
        "words_before": data.get("words_before"),
        "words_after": data.get("words_after"),
        "ok": True,
    }


def _load_transcript(job_dir: Path) -> list[Utterance]:
    """อ่านบทจาก transcript.json หรือจาก Postgres (DB_BACKEND=supabase ไม่เขียนไฟล์)"""
    path = job_dir / "transcript.json"
    if path.exists():
        try:
            return [Utterance.model_validate(u) for u in json.loads(path.read_text(encoding="utf-8"))]
        except (OSError, ValueError) as exc:
            log.warning("transcript.json เสียใน %s: %s", job_dir.name, exc)
    try:
        from .config import settings
        if settings.db_backend == "supabase":
            from . import jobstore_pg
            rows = jobstore_pg.load_transcript(job_dir.name)
            if rows:
                try:
                    job_dir.mkdir(parents=True, exist_ok=True)
                    path.write_text(
                        json.dumps([u.model_dump() for u in rows], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    log.warning("cache transcript.json ไม่ได้สำหรับ %s: %s", job_dir.name, exc)
                return list(rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("โหลดบทจาก Postgres ไม่ได้สำหรับ %s: %s", job_dir.name, exc)
    return []


def _load_job_meta(job_dir: Path) -> dict:
    path = job_dir / "job.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _tts_total_sec(job_dir: Path, utts: list[Utterance], *, sr_hint: int = 24000) -> tuple[float, int]:
    import soundfile as sf

    tts_dir = job_dir / "tts"
    total, n = 0.0, 0
    for u in utts:
        path = tts_dir / f"{u.id:04d}.wav"
        if not path.exists():
            continue
        try:
            info = sf.info(str(path))
            total += float(info.frames) / float(info.samplerate or sr_hint)
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return total, n


def length_vs_source(job_dir: Path, utts: list[Utterance]) -> dict[str, Any]:
    """เทียบความยาวเสียงต้นฉบับ (ช่วงพูดจริง) กับช่องปากและเสียงพากย์ทั้งงาน"""
    slot_sec = sum(max(0.0, float(u.end) - float(u.start)) for u in utts)
    # ต้นฉบับ: รวมช่วงมีเสียงบน vocals (ถ้าวัดได้) ไม่เช่นนั้นใช้ผลรวมช่องปาก
    source_speech_sec = None
    wav_path = job_dir / "vocals.wav"
    if not wav_path.exists():
        wav_path = job_dir / "audio.wav"
    if wav_path.exists():
        try:
            wav, sr = _load_wav(wav_path)
            regions = speech_regions(wav, sr)
            source_speech_sec = round(sum(b - a for a, b in regions), 3)
        except Exception:  # noqa: BLE001
            source_speech_sec = None
    if source_speech_sec is None:
        source_speech_sec = round(slot_sec, 3)

    dub_sec, n_tts = _tts_total_sec(job_dir, utts)
    # ถ้ายังไม่มีไฟล์พากย์ ประมาณจากความยาวบทปลายทาง
    target_lang = (_load_job_meta(job_dir).get("target_lang") or "th")
    try:
        from .pipeline.translate import estimate_seconds
        est_target = sum(estimate_seconds(u.target or "", target_lang) for u in utts)
    except Exception:  # noqa: BLE001
        est_target = sum(len((u.target or "").replace(" ", "")) / 11.0 for u in utts)

    dub_or_est = dub_sec if n_tts else est_target
    ratio_slot = (dub_or_est / slot_sec) if slot_sec > 1e-6 else None
    ratio_source = (dub_or_est / source_speech_sec) if source_speech_sec > 1e-6 else None

    # คะแนน: ใกล้ 1.0 ดี — ยอมช่วง 0.7–1.2 เป็นผ่าน
    def _fit(r: Optional[float]) -> Optional[float]:
        if r is None:
            return None
        if 0.7 <= r <= 1.2:
            return round(1.0 - abs(r - 1.0) * 0.5, 4)
        return round(max(0.0, 1.0 - abs(r - 1.0)), 4)

    score = _fit(ratio_source if ratio_source is not None else ratio_slot)
    ok = score is not None and score >= 0.7
    return {
        "source_speech_sec": round(float(source_speech_sec), 3),
        "slot_sec": round(slot_sec, 3),
        "dub_audio_sec": round(dub_sec, 3) if n_tts else None,
        "est_target_sec": round(est_target, 3),
        "n_tts": n_tts,
        "ratio_vs_source": round(ratio_source, 4) if ratio_source is not None else None,
        "ratio_vs_slot": round(ratio_slot, 4) if ratio_slot is not None else None,
        "score": score,
        "ok": ok,
    }


def translate_fidelity(job_dir: Path, utts: list[Utterance]) -> dict[str, Any]:
    """คุณภาพการแปลแบบออฟไลน์: บทว่าง, สัดส่วนความยาว source↔target, glossary, ป้าย check_note

    ไม่เรียก LLM เป็นค่าเริ่มต้น (เร็ว/ฟรี) — ใช้ heuristics ที่เทียบต้นฉบับกับบทพากย์โดยตรง
    """
    if not utts:
        return {"score": None, "n": 0, "ok": None}

    meta = _load_job_meta(job_dir)
    target_lang = meta.get("target_lang") or "th"
    source_lang = meta.get("detected_lang") or meta.get("source_lang") or ""
    glossary = (meta.get("glossary") or "").strip()
    names = meta.get("speaker_names") or {}

    empty = sum(1 for u in utts if not (u.target or "").strip())
    flagged = sum(1 for u in utts if (u.check_note or "").strip())
    same_lang = bool(source_lang) and source_lang[:2] == str(target_lang)[:2]

    try:
        from .pipeline.translate import estimate_seconds
    except Exception:  # noqa: BLE001
        estimate_seconds = None  # type: ignore

    line_scores: list[float] = []
    short_long = 0
    for u in utts:
        src = (u.source or "").strip()
        tgt = (u.target or "").strip()
        if not src:
            continue
        if not tgt:
            line_scores.append(0.0)
            continue
        if same_lang:
            # ต้นทาง = ปลายทาง: บทควรใกล้เคียงต้นฉบับ (อนุญาตเว้นวรรค /)
            from difflib import SequenceMatcher
            a = "".join(src.split()).replace("/", "")
            b = "".join(tgt.split()).replace("/", "")
            line_scores.append(SequenceMatcher(None, a, b, autojunk=False).ratio())
            continue
        slot = max(0.2, float(u.end) - float(u.start))
        if estimate_seconds:
            need = estimate_seconds(tgt, target_lang)
        else:
            need = len(tgt.replace(" ", "").replace("/", "")) / 11.0
        # บทสั้น/ยาวผิดปกติเทียบช่องปาก
        ratio = need / slot
        if ratio < 0.35 or ratio > 1.6:
            short_long += 1
            line_scores.append(0.45)
        elif 0.55 <= ratio <= 1.25:
            line_scores.append(0.95)
        else:
            line_scores.append(0.75)

    # glossary: ต้นฉบับมีคำต้น แต่บทไม่มีคำแปลที่กำหนด
    gloss_miss = 0
    if glossary:
        for line in glossary.splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            src_g, _, dst_g = line.partition("=")
            src_g, dst_g = src_g.strip().lower(), dst_g.strip().lower()
            if len(src_g) < 2 or not dst_g:
                continue
            for u in utts:
                if src_g in (u.source or "").lower() and dst_g not in (u.target or "").lower():
                    gloss_miss += 1

    # ชื่อตัวละครใน names ควรโผล่ในบทถ้าต้นฉบับมีชื่อนั้น (หลวม ๆ)
    name_miss = 0
    for _, name in (names or {}).items():
        n = (name or "").strip()
        if len(n) < 2:
            continue
        for u in utts:
            if n.lower() in (u.source or "").lower() and n.lower() not in (u.target or "").lower():
                # ต้นฉบับเป็นภาษาอื่น มักไม่มีชื่อไทยใน source — ข้าม
                if any("\u0e00" <= ch <= "\u0e7f" for ch in u.source or ""):
                    name_miss += 1

    n = len(utts)
    empty_pen = empty / n
    flag_pen = flagged / n
    gloss_pen = min(0.3, gloss_miss / max(1, n))
    base = sum(line_scores) / len(line_scores) if line_scores else (0.0 if empty else 0.8)
    score = round(max(0.0, base * (1.0 - 0.5 * empty_pen) - 0.15 * flag_pen - gloss_pen), 4)
    return {
        "score": score,
        "n": n,
        "empty_targets": empty,
        "check_flagged": flagged,
        "short_or_long": short_long,
        "glossary_misses": gloss_miss,
        "name_misses": name_miss,
        "same_lang": same_lang,
        "ok": score >= 0.7 and empty == 0,
    }


def _rms_db(seg: np.ndarray) -> Optional[float]:
    if seg is None or len(seg) < 32:
        return None
    # เฉพาะช่วงดัง (ตัดเงียบหาง)
    hop = max(1, len(seg) // 50)
    if hop < 8:
        rms = float(np.sqrt(np.mean(seg ** 2) + 1e-12))
    else:
        frames = len(seg) // hop
        vals = np.sqrt(np.mean(seg[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
        thr = 0.1 * np.percentile(vals, 95)
        on = vals[vals > thr]
        rms = float(np.mean(on)) if len(on) else float(np.mean(vals))
    if rms <= 1e-8:
        return None
    return float(10.0 * np.log10(rms ** 2 + 1e-12))


def _pitch_hz(seg: np.ndarray, sr: int) -> Optional[float]:
    """median F0 (Hz) — ใช้ parselmouth ถ้ามี ไม่เช่นนั้นคืน None"""
    if seg is None or sr <= 0 or len(seg) < int(sr * 0.25):
        return None
    try:
        import parselmouth
        f0 = parselmouth.Sound(seg.astype(np.float64), sr).to_pitch(
            time_step=0.01, pitch_floor=75.0, pitch_ceiling=600.0
        ).selected_array["frequency"]
        f0 = f0[f0 > 0]
        if len(f0) < 8:
            return None
        return float(np.median(f0))
    except Exception:  # noqa: BLE001
        return None


def _hz_to_st(hz: float) -> float:
    return 12.0 * np.log2(max(hz, 1e-6) / 440.0)


def prosody_match(job_dir: Path, utts: list[Utterance]) -> dict[str, Any]:
    """ความดัง + pitch ของพากย์เทียบต้นฉบับรายท่อน (0–1)"""
    import soundfile as sf

    vocals = job_dir / "vocals.wav"
    if not vocals.exists():
        vocals = job_dir / "audio.wav"
    tts_dir = job_dir / "tts"
    if not vocals.exists() or not tts_dir.exists():
        return {"score": None, "n": 0, "ok": None}

    try:
        orig, osr = _load_wav(vocals)
    except Exception as exc:  # noqa: BLE001
        return {"score": None, "n": 0, "error": str(exc), "ok": None}

    loud_gaps: list[float] = []
    pitch_gaps: list[float] = []
    n = 0
    for u in utts:
        path = tts_dir / f"{u.id:04d}.wav"
        if not path.exists():
            continue
        a, b = int(u.start * osr), int(u.end * osr)
        src = orig[max(0, a): max(0, b)]
        try:
            dub, dsr = sf.read(str(path), dtype="float32", always_2d=False)
            if getattr(dub, "ndim", 1) > 1:
                dub = dub.mean(axis=1)
        except Exception:  # noqa: BLE001
            continue
        n += 1
        sdb, ddb = _rms_db(np.asarray(src, dtype=np.float32)), _rms_db(np.asarray(dub, dtype=np.float32))
        if sdb is not None and ddb is not None:
            loud_gaps.append(abs(sdb - ddb))
        sp = _pitch_hz(np.asarray(src, dtype=np.float32), osr)
        dp = _pitch_hz(np.asarray(dub, dtype=np.float32), int(dsr))
        if sp and dp:
            pitch_gaps.append(abs(_hz_to_st(sp) - _hz_to_st(dp)))

    if n == 0:
        return {"score": None, "n": 0, "ok": None}

    # ดังห่าง ≤6 dB → ดี; pitch ห่าง ≤4 st → ดี
    loud_score = None
    if loud_gaps:
        loud_score = float(np.mean([max(0.0, 1.0 - g / 12.0) for g in loud_gaps]))
    pitch_score = None
    if pitch_gaps:
        pitch_score = float(np.mean([max(0.0, 1.0 - g / 8.0) for g in pitch_gaps]))
    parts = [x for x in (loud_score, pitch_score) if x is not None]
    score = round(sum(parts) / len(parts), 4) if parts else None
    return {
        "score": score,
        "n": n,
        "loud_mean_db_gap": round(float(np.mean(loud_gaps)), 3) if loud_gaps else None,
        "pitch_mean_st_gap": round(float(np.mean(pitch_gaps)), 3) if pitch_gaps else None,
        "n_loud": len(loud_gaps),
        "n_pitch": len(pitch_gaps),
        "ok": score is not None and score >= 0.65,
    }


def lip_overflow(job_dir: Path, utts: list[Utterance]) -> dict[str, Any]:
    """เสียงพากย์ล้นทับท่อนถัดไป หรือสั้นกว่าปากมาก (เงียบตอนปากยังขยับ)"""
    import soundfile as sf

    if not utts:
        return {"score": None, "n": 0, "ok": None}
    order = sorted(utts, key=lambda u: u.start)
    tts_dir = job_dir / "tts"
    overflow = 0
    underfill = 0
    scored = 0
    worst = 0.0
    for i, u in enumerate(order):
        path = tts_dir / f"{u.id:04d}.wav"
        slot = max(0.05, float(u.end) - float(u.start))
        next_start = order[i + 1].start if i + 1 < len(order) else u.end + 99.0
        gap_to_next = max(0.0, next_start - u.start)
        if path.exists():
            try:
                info = sf.info(str(path))
                dub_dur = float(info.frames) / float(info.samplerate or 24000)
            except Exception:  # noqa: BLE001
                continue
        else:
            # ไม่มีไฟล์ → ประมาณจากบท
            try:
                from .pipeline.translate import estimate_seconds
                meta = _load_job_meta(job_dir)
                dub_dur = estimate_seconds(u.target or "", meta.get("target_lang") or "th")
            except Exception:  # noqa: BLE001
                continue
        scored += 1
        # ล้น: เสียงยาวเกินช่องถึงท่อนถัดไป (เผื่อ 50ms)
        limit = min(slot * 1.08, gap_to_next + 0.05)
        over = max(0.0, dub_dur - limit)
        if over > 0.12:
            overflow += 1
            worst = max(worst, over)
        # ปากยังขยับแต่เสียงสั้นมาก
        if slot >= 1.0 and dub_dur < slot * 0.55:
            underfill += 1

    if scored == 0:
        return {"score": None, "n": 0, "ok": None}
    pen = (overflow + underfill) / scored
    score = round(max(0.0, 1.0 - pen), 4)
    return {
        "score": score,
        "n": scored,
        "overflow_lines": overflow,
        "underfill_lines": underfill,
        "worst_overflow_sec": round(worst, 3),
        "ok": overflow == 0 and underfill / max(1, scored) < 0.25,
    }


def _norm_token(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if not ch.isspace() and ch not in "/·・")


def term_consistency(job_dir: Path, utts: list[Utterance]) -> dict[str, Any]:
    """ชื่อเฉพาะ/glossary สะกดเดียวกันทั้งเรื่อง + ต้นฉบับซ้ำได้คำแปลเดียวกัน"""
    from collections import defaultdict
    from difflib import SequenceMatcher

    meta = _load_job_meta(job_dir)
    glossary = (meta.get("glossary") or "").strip()
    names = meta.get("speaker_names") or {}
    variants: dict[str, set[str]] = defaultdict(set)
    misses = 0

    for line in glossary.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        src, _, dst = line.partition("=")
        src, dst = src.strip(), dst.strip()
        if len(src) < 2 or len(dst) < 1:
            continue
        key = _norm_token(src)
        dst_n = _norm_token(dst)
        found_forms: set[str] = set()
        for u in utts:
            if src.lower() not in (u.source or "").lower():
                continue
            tgt = _norm_token(u.target or "")
            if not tgt:
                misses += 1
                continue
            if dst_n and dst_n in tgt:
                found_forms.add(dst_n)
            else:
                # หาชิ้นที่คล้าย dst ใน target (กันสะกดเพี้ยน)
                for i in range(len(u.target or "")):
                    chunk = _norm_token((u.target or "")[i: i + max(len(dst) + 2, 4)])
                    if chunk and SequenceMatcher(None, dst_n, chunk).ratio() >= 0.75:
                        found_forms.add(chunk)
                        break
                else:
                    misses += 1
        if found_forms:
            variants[key] |= found_forms

    # ชื่อตัวละครที่ผู้ใช้ตั้ง — ควรสะกดแบบเดียวในบท
    for _, name in (names or {}).items():
        n = (name or "").strip()
        if len(n) < 2:
            continue
        forms = set()
        nn = _norm_token(n)
        for u in utts:
            t = _norm_token(u.target or "")
            if nn in t:
                forms.add(nn)
            elif t and SequenceMatcher(None, nn, t[: len(nn) + 3]).ratio() >= 0.8:
                forms.add(t[: len(nn) + 3])
        if len(forms) > 1:
            variants[f"name:{nn}"] = forms

    # ต้นฉบับซ้ำทั้งประโยคสั้น (≥2 ครั้ง) → บทควรคล้ายกัน
    by_src: dict[str, list[str]] = defaultdict(list)
    for u in utts:
        s = _norm_token(u.source or "")
        if 2 <= len(s) <= 40:
            by_src[s].append(_norm_token(u.target or ""))
    drift = 0
    for s, tgts in by_src.items():
        uniq = {t for t in tgts if t}
        if len(tgts) >= 2 and len(uniq) >= 2:
            # ถ้าทุกคู่คล้าย ≥0.7 ถือว่าโอเค
            bad = False
            uniq_l = list(uniq)
            for i in range(len(uniq_l)):
                for j in range(i + 1, len(uniq_l)):
                    if SequenceMatcher(None, uniq_l[i], uniq_l[j]).ratio() < 0.7:
                        bad = True
            if bad:
                drift += 1
                variants[f"src:{s[:20]}"] = uniq

    inconsistent = sum(1 for forms in variants.values() if len(forms) > 1)
    n_terms = max(1, len(variants) + (1 if glossary else 0))
    pen = (inconsistent + misses * 0.25 + drift) / max(1.0, n_terms + drift)
    score = round(max(0.0, 1.0 - min(1.0, pen)), 4)
    return {
        "score": score,
        "inconsistent_terms": inconsistent,
        "glossary_misses": misses,
        "source_drift": drift,
        "ok": inconsistent == 0 and drift == 0,
    }


def speaker_confusion(job_dir: Path, utts: list[Utterance]) -> dict[str, Any]:
    """ผู้พูดสับสน: ชนกับ turns, ทับเวลาคนเดียวกัน, pitch ในคนเดียวกันกระโดดผิดปกติ"""
    if not utts:
        return {"score": None, "n": 0, "ok": None}

    turns: list[dict] = []
    tp = job_dir / "turns.json"
    if tp.exists():
        try:
            turns = json.loads(tp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            turns = []

    conflict = 0
    for u in utts:
        if not turns:
            break
        votes: dict[str, float] = {}
        for t in turns:
            ov = max(0.0, min(u.end, float(t["end"])) - max(u.start, float(t["start"])))
            if ov > 0.05:
                sp = t.get("speaker") or ""
                votes[sp] = votes.get(sp, 0.0) + ov
        if votes:
            maj = max(votes, key=votes.get)
            if maj and maj != u.speaker and votes[maj] >= 0.5 * (u.end - u.start):
                conflict += 1

    # คนเดียวกันทับเวลาตัวเอง
    self_overlap = 0
    by_sp: dict[str, list[Utterance]] = {}
    for u in utts:
        by_sp.setdefault(u.speaker, []).append(u)
    for group in by_sp.values():
        g = sorted(group, key=lambda x: x.start)
        for a, b in zip(g, g[1:]):
            if min(a.end, b.end) - max(a.start, b.start) > 0.1:
                self_overlap += 1

    # pitch กระโดดใน speaker เดียวกัน (ต้องมี vocals)
    pitch_jumps = 0
    pitch_n = 0
    vocals = job_dir / "vocals.wav"
    if not vocals.exists():
        vocals = job_dir / "audio.wav"
    if vocals.exists():
        try:
            wav, sr = _load_wav(vocals)
            for group in by_sp.values():
                pitches = []
                for u in sorted(group, key=lambda x: x.start):
                    seg = wav[int(u.start * sr): int(u.end * sr)]
                    p = _pitch_hz(np.asarray(seg, dtype=np.float32), sr)
                    if p:
                        pitches.append((_hz_to_st(p), u))
                for (pa, _), (pb, _) in zip(pitches, pitches[1:]):
                    pitch_n += 1
                    if abs(pa - pb) > 7.0:  # >~7 semitone ในคนเดียวกัน → น่าสงสัยว่าคนละคน
                        pitch_jumps += 1
        except Exception:  # noqa: BLE001
            pass

    n = max(1, len(utts))
    pen = conflict / n + self_overlap / n + (pitch_jumps / max(1, pitch_n)) * 0.5
    score = round(max(0.0, 1.0 - min(1.0, pen)), 4)
    return {
        "score": score,
        "n": len(utts),
        "turn_conflicts": conflict,
        "self_overlaps": self_overlap,
        "pitch_jumps": pitch_jumps,
        "ok": conflict == 0 and self_overlap == 0 and pitch_jumps <= max(1, pitch_n // 5),
    }


def score_job(job_dir: Path, *, dub_check_min: float = 0.6) -> dict[str, Any]:
    """คะแนนรวมหนึ่ง job จากไฟล์อย่างเดียว"""
    job_dir = Path(job_dir)
    utts = _load_transcript(job_dir)
    cov = speech_coverage_file(job_dir, utts)
    dub = dub_match_from_utts(utts, min_score=dub_check_min)
    timing = timing_fit(job_dir, utts)
    recheck = recheck_gain(job_dir)
    length = length_vs_source(job_dir, utts)
    translate = translate_fidelity(job_dir, utts)
    prosody = prosody_match(job_dir, utts)
    lip = lip_overflow(job_dir, utts)
    terms = term_consistency(job_dir, utts)
    speaker = speaker_confusion(job_dir, utts)

    parts: list[tuple[str, float, float]] = []  # name, weight, value 0-1
    weights = {
        "speech_coverage": 0.16,
        "dub_match": 0.12,
        "timing_fit": 0.06,
        "length_vs_source": 0.10,
        "translate_fidelity": 0.12,
        "prosody_match": 0.14,
        "lip_overflow": 0.12,
        "term_consistency": 0.10,
        "speaker_confusion": 0.08,
    }
    if cov.get("coverage") is not None:
        parts.append(("speech_coverage", weights["speech_coverage"], float(cov["coverage"])))
    if dub.get("mean") is not None:
        parts.append(("dub_match", weights["dub_match"], float(dub["mean"])))
    elif dub.get("ok") is True:
        parts.append(("dub_match", weights["dub_match"], 1.0))
    if timing.get("mean_ratio") is not None:
        r = float(timing["mean_ratio"])
        parts.append(("timing_fit", weights["timing_fit"], max(0.0, 1.0 - abs(r - 1.0))))
    if length.get("score") is not None:
        parts.append(("length_vs_source", weights["length_vs_source"], float(length["score"])))
    if translate.get("score") is not None:
        parts.append(("translate_fidelity", weights["translate_fidelity"], float(translate["score"])))
    if prosody.get("score") is not None:
        parts.append(("prosody_match", weights["prosody_match"], float(prosody["score"])))
    if lip.get("score") is not None:
        parts.append(("lip_overflow", weights["lip_overflow"], float(lip["score"])))
    if terms.get("score") is not None:
        parts.append(("term_consistency", weights["term_consistency"], float(terms["score"])))
    if speaker.get("score") is not None:
        parts.append(("speaker_confusion", weights["speaker_confusion"], float(speaker["score"])))

    if parts:
        wsum = sum(w for _, w, _ in parts)
        overall = round(sum(w * v for _, w, v in parts) / wsum, 4)
    else:
        overall = None

    return {
        "job_id": job_dir.name,
        "n_lines": len(utts),
        "speech_coverage": cov,
        "dub_match": dub,
        "timing_fit": timing,
        "length_vs_source": length,
        "translate_fidelity": translate,
        "prosody_match": prosody,
        "lip_overflow": lip,
        "term_consistency": terms,
        "speaker_confusion": speaker,
        "recheck_gain": recheck,
        "overall": overall,
        "needs_asr_heal": (
            cov.get("coverage") is not None and float(cov["coverage"]) < COVERAGE_HEAL_MIN
        ),
    }


def write_metrics(job_dir: Path, metrics: Optional[dict] = None, *, dub_check_min: float = 0.6) -> dict:
    """คำนวณแล้วเขียน metrics.json"""
    job_dir = Path(job_dir)
    data = metrics or score_job(job_dir, dub_check_min=dub_check_min)
    path = job_dir / "metrics.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("job %s metrics overall=%s coverage=%s", job_dir.name,
             data.get("overall"), (data.get("speech_coverage") or {}).get("coverage"))
    return data


def scan_jobs(root: Path, *, limit: int = 100) -> list[dict]:
    """สแกน data/jobs แล้วให้คะแนน (ดึงบทจาก PG ได้ถ้าไม่มี transcript.json)"""
    root = Path(root)
    if not root.exists():
        return []
    out: list[dict] = []
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for d in dirs:
        # มีไฟล์บท / เสียง / หรือ metrics เดิม — โหมด PG อาจไม่มี transcript.json
        if not any((d / name).exists() for name in ("transcript.json", "vocals.wav", "metrics.json", "ai_lines.json")):
            continue
        try:
            row = score_job(d)
            if row.get("n_lines", 0) == 0 and not (d / "vocals.wav").exists():
                continue
            out.append(row)
        except Exception as exc:  # noqa: BLE001
            out.append({"job_id": d.name, "error": str(exc), "overall": None})
        if len(out) >= limit:
            break
    return out
