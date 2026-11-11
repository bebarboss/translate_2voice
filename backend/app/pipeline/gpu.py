"""ขั้นที่ใช้การ์ดจอ: แยกเสียงพูดกับเพลง (Demucs) แยกผู้พูด (pyannote) ถอดเสียง (faster-whisper) พากย์ (F5-TTS)

runner.py และ library.py เรียกขั้นเหล่านี้ผ่านโมดูลนี้เท่านั้น
- WORKER=local : เรียกฟังก์ชัน *_core บนเครื่องนี้
- WORKER=modal : ส่งเสียง (FLAC mono) ไป modal_app.py บน Modal GPU L4 ซึ่งเรียก *_core ชุดเดียวกัน
                 แล้วรับผลเป็น bytes/JSON กลับมาเขียนลง data/ (บน Modal ไม่เก็บไฟล์งานถาวร)
MOCK_PIPELINE=1 รันบนเครื่องเสมอ
"""
import io
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from ..config import settings
from ..schemas import Utterance
from . import audio
from .common import Turn, Word

log = logging.getLogger("dubbing.gpu")

Stage = Callable[[str, float], None]

ANALYSIS_FILE = "gpu_analysis.json"  # ค่าที่คำนวณบน Modal ตอนวิเคราะห์ เก็บไว้ใช้ตอนพากย์
CHECKS_KEY = "__checks__"  # คีย์ในผลพากย์จาก Modal ที่เก็บผลตรวจเสียงพากย์ (JSON) แทนเสียง
PROGRESS_DICT = "dubbing-progress"  # modal.Dict ที่ฝั่ง Modal เขียนความคืบหน้าให้ฝั่งนี้อ่าน
POLL_SEC = 2.0
SOURCE_SR = 44100  # เสียงที่ส่งไปแยกเสียงพูด
REF_SR = 24000  # เสียงตัวอย่างของ F5-TTS (tts.SAMPLE_RATE)

# ค่าตั้งค่าที่ส่งไปใช้บน Modal ทุกครั้งที่เรียก ไม่ต้อง deploy ใหม่เมื่อแก้ .env
# ไม่ส่งค่าเฉพาะเครื่อง (DEVICE, LOW_VRAM, F5_FP32, WHISPER_COMPUTE_TYPE, F5_CACHE_DIR) และ HF_TOKEN (อยู่ใน Secret)
REMOTE_FIELDS = (
    "separator", "separator_model", "separator_overlap", "denoise_model", "demucs_model", "diarization_model", "whisper_model", "f5_model", "f5_en_model", "f5_cfg",
    "whisper_vad_threshold", "whisper_vad_min_speech_ms", "whisper_vad_min_silence_ms",
    "whisper_vad_speech_pad_ms", "whisper_fill_gap_sec",
    "ref_min_sec", "ref_max_sec", "ref_min_quality", "max_line_sec",
    "voice_match", "voice_min_sim", "voice_max_pitch_diff", "voice_split_pitch", "voice_profile_min_sec",
    "diar_refine", "diar_exclusive", "diar_merge_sim", "voice_max_input_min", "voice_drift", "voice_retries", "overlap_recover", "turn_split_sim",
    "retranscribe_noisy", "auto_heal_asr", "second_denoise",
    "dub_check", "dub_check_min", "dub_check_retries",
)


def remote() -> bool:
    return settings.worker == "modal" and not settings.mock_pipeline


def voice_tools() -> bool:
    """ใช้โมเดลลายเสียง (pyannote) ได้ไหม โหมด modal ใช้ HF_TOKEN จาก Secret บน Modal"""
    return not settings.mock_pipeline and (remote() or bool(settings.hf_token))


def release(*names: str) -> None:
    """โหมด LOW_VRAM: ปล่อยโมเดลที่ใช้เสร็จแล้วออกจากการ์ดจอ ก่อนโหลดตัวถัดไป"""
    if not settings.low_vram or settings.mock_pipeline or remote():
        return
    import gc
    import importlib

    for name in names:
        importlib.import_module(f"{__package__}.{name}").unload()
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def apply_config(config: Optional[dict]) -> None:
    """ฝั่ง Modal: ใช้ค่าตั้งค่าที่ส่งมากับคำขอ (settings เป็น frozen dataclass ที่ทุกโมดูลถืออ้างอิงเดียวกัน)"""
    for key, value in (config or {}).items():
        if key in REMOTE_FIELDS:
            object.__setattr__(settings, key, value)


def _models():
    if settings.mock_pipeline:
        from . import mock
        return mock.separate_vocals, mock.diarize, mock.transcribe, mock.synthesize
    from . import diarize, transcribe, tts
    return audio.separate_vocals, diarize.diarize, transcribe.transcribe, tts.synthesize


def _mono(path: Path) -> tuple[np.ndarray, int]:
    wav, sr = sf.read(path, dtype="float32")
    return (wav.mean(axis=1) if wav.ndim > 1 else wav), sr


# ================================================================ งานจริง (รันที่ที่มีการ์ดจอ)
def _use_as_vocals(mixed: Path, work: Path) -> tuple[Path, Path]:
    """แทร็กที่แยกคนไว้แล้ว (ไทม์ไลน์) — ใช้เป็น vocals โดยตรง ไม่รัน Demucs; bgm เป็นความเงียบ"""
    wav, sr = sf.read(mixed, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    vocals, bgm = work / "vocals.wav", work / "bgm.wav"
    sf.write(vocals, wav, sr)
    sf.write(bgm, np.zeros(len(wav), dtype=np.float32), sr)
    return vocals, bgm


def analyze_core(mixed: Path, work: Path, source_lang: Optional[str], num_speakers: Optional[int],
                 stage: Stage, preseparated: bool = False) -> dict:
    """แยกเสียงพูด/เพลง → แยกผู้พูด → ถอดเสียง → แบ่งประโยคตามผู้พูด เขียน vocals.wav, bgm.wav ลง work
    preseparated=True: แทร็กคนละคนจากไทม์ไลน์แล้ว — ข้าม Demucs และ pyannote ไปถอดเสียงเลย"""
    from .transcribe import assign_speakers

    separate, diarize, transcribe, _ = _models()
    voice_ok = bool(settings.hf_token) and not settings.mock_pipeline

    release("tts")  # เผื่อโมเดลพากย์จากงานก่อนยังค้างอยู่
    if preseparated:
        stage("transcribe", 0.1)
        vocals, bgm = _use_as_vocals(mixed, work)
        wav16k = audio.to_mono(vocals, work / "vocals16k.wav", 16000)
        wav, sr = _mono(wav16k)
        dur = round(len(wav) / sr, 3) if sr else 0.0
        turns = word_turns = [Turn(0.0, max(dur, 0.01), "speaker_01")]
        speakers = ["speaker_01"]
    else:
        stage("separate_vocals", 0.1)
        vocals, bgm = separate(mixed, work, settings.demucs_model, settings.device)
        release("audio")
        wav16k = audio.to_mono(vocals, work / "vocals16k.wav", 16000)

        stage("diarize", 0.25)
        if settings.mock_pipeline:
            turns = word_turns = diarize(wav16k, num_speakers)
        else:
            from .diarize import diarize_both
            turns, word_turns = diarize_both(wav16k, num_speakers)
        release("diarize")
        speakers = sorted({t.speaker for t in turns})

    stage("transcribe", 0.4)
    confidence: dict[int, float] = {}
    if settings.mock_pipeline:
        words, lang = transcribe(wav16k, source_lang)
    else:
        words, lang = transcribe(wav16k, source_lang, confidence)
        # ช่วงที่มีคนพูดแต่ถอดไม่ออก (เพลงดังทับ) → ถอดซ้ำเฉพาะช่วงนั้น
        from .transcribe import fill_gaps
        words = fill_gaps(wav16k, words, turns, lang, confidence=confidence)
    unclear, recheck = [], None
    if settings.retranscribe_noisy and not settings.mock_pipeline and words:
        # รอบสอง: ช่วงน่าสงสัยถอดใหม่จากเสียงต้นฉบับ (เสียงพูดยังไม่ถูกตัดไปพร้อมเพลง) โมเดลเดิมใน container เดิม
        from .transcribe import recheck_noisy
        stage("transcribe", 0.45)
        t0 = time.monotonic()
        before = len(words)
        mixed16k = audio.to_mono(mixed, work / "mixed16k.wav", 16000)
        bgm16k = audio.to_mono(bgm, work / "bgm16k.wav", 16000) if bgm else None
        words, unclear, recheck = recheck_noisy(mixed16k, wav16k, bgm16k, words, confidence, turns, lang)
        recheck.update(words_before=before, words_after=len(words), seconds=round(time.monotonic() - t0, 1))
        log.info("recheck noisy took %.1f s, words %d → %d", recheck["seconds"], before, len(words))
    release("transcribe")
    if not words:
        raise RuntimeError("ไม่พบคำพูดในคลิป")
    utterances = assign_speakers(words, word_turns, lang=lang)
    raw_turns = list(turns)  # ช่วงพูดตามป้ายของ pyannote (relabel_turns ด้านล่างเปลี่ยนชื่อให้ตรงกับประโยค)
    hidden = []
    # แทร็กไทม์ไลน์คนละคนแล้ว — ไม่กู้ซ้อน/ไม่จัดกลุ่มผู้พูดซ้ำ
    if not preseparated and settings.overlap_recover and not settings.mock_pipeline:  # คนที่ถูกกลบตอนพูดพร้อมกัน
        from . import overlap
        stage("transcribe", 0.48)
        hidden = overlap.recover(sf.read(wav16k, dtype="float32")[0], turns, utterances, words, lang)
        release("overlap", "transcribe")
    if not preseparated and settings.voice_match and voice_ok:
        from . import voices
        wav, wsr = sf.read(wav16k, dtype="float32")
        # ท่อนเดียวที่มีหลายคนพูดต่อกัน (pyannote จับไม่ทัน) → แบ่งตรงจุดจบประโยคย่อยที่เสียงต่างกันชัด
        before = len(utterances)
        utterances = voices.split_lines(utterances, words, wav, wsr)
        if len(utterances) != before:
            log.info("split %d lines with more than one voice", len(utterances) - before)
        profiles = voices.profile(utterances, wav, wsr)
        release("voices")
        # ไม่ได้ระบุจำนวนคน → จัดกลุ่มผู้พูดใหม่ทีละประโยคจากลายเสียง (ระบบแยกผู้พูดมักรวมคนเสียงคล้ายกัน)
        labels = voices.cluster_lines(utterances, profiles) if not num_speakers and settings.diar_refine else None
        if labels:
            names: dict[str, str] = {}
            for u in sorted(utterances, key=lambda u: u.start):
                u.speaker = names.setdefault(labels[u.id], f"speaker_{len(names) + 1:02d}")
            from .diarize import relabel_turns
            turns = relabel_turns(turns, utterances)
            # word_turns ใช้ตอน assign_speakers / auto-heal — ต้อง sync ด้วย ไม่งั้นรวมกลับเป็นคนเดียว
            word_turns = relabel_turns(word_turns, utterances)
            speakers = sorted(names.values())
            log.info("cluster speakers applied: %s", speakers)
        else:
            # ระบบแยกผู้พูดรวมเด็กกับผู้ใหญ่ (หรือชายกับหญิง) เป็นคนเดียว → แยกตามระดับเสียงและลายเสียง
            renamed = voices.split_speakers(utterances, profiles, taken={t.speaker for t in turns})
            if renamed:
                log.info("split speakers by voice: %s", renamed)
                speakers = sorted({u.speaker for u in utterances})
    if hidden:
        from .overlap import map_speakers
        hidden = map_speakers(hidden, raw_turns, utterances)
        log.info("recovered %d overlapping lines", len(hidden))
        utterances = sorted(utterances + hidden, key=lambda u: (u.start, u.end))
        for i, u in enumerate(utterances, 1):
            u.id = i
        speakers = sorted({*speakers, *(u.speaker for u in hidden)})
    if unclear:
        from .transcribe import mark_unclear
        recheck["unclear_lines"] = mark_unclear(utterances, unclear)
    if turns and utterances:
        from .transcribe import flag_lyrics_suspects
        recheck["lyrics_flags"] = flag_lyrics_suspects(utterances, words or [], turns)
    # ซ่อมท่อนพัง + ถอดช่วงน่าสงสัยใหม่ก่อนส่งไปแปล (รันบนเครื่องที่มี Whisper)
    if settings.transcript_gate and not settings.mock_pipeline and words:
        from . import repair as repair_mod
        stage("transcribe", 0.5)
        utterances, words, gate = repair_mod.gate_before_translate(
            utterances, words, turns, lang or "", wav16k)
        speakers = sorted({u.speaker for u in utterances} | set(speakers or []))
        log.info("transcript gate after ASR: %s", gate)
    # coverage ต่ำเทียบช่วงมีเสียงบน vocals → ผ่อน VAD ชั่วคราว แล้ว fill_gaps/recheck รอบเดียว
    if settings.auto_heal_asr and not settings.mock_pipeline and words and utterances:
        utterances, words, heal = _auto_heal_asr(
            wav16k, mixed, bgm, utterances, words, turns, word_turns, lang or "", confidence, stage)
        if heal.get("healed"):
            speakers = sorted({u.speaker for u in utterances} | set(speakers or []))
            if recheck is None:
                recheck = {}
            recheck["auto_heal"] = heal
            log.info("auto-heal ASR: %s", heal)
    return {"vocals": vocals, "bgm": bgm, "turns": turns, "words": words, "lang": lang,
            "utterances": utterances, "speakers": speakers, "recheck": recheck}


def _auto_heal_asr(
    wav16k: Path,
    mixed: Path,
    bgm: Optional[Path],
    utterances: list[Utterance],
    words: list[Word],
    turns: list[Turn],
    word_turns: list[Turn],
    lang: str,
    confidence: dict,
    stage: Stage,
) -> tuple[list[Utterance], list[Word], dict]:
    """ถ้า speech_coverage ต่ำ → ผ่อน VAD ชั่วคราว + fill_gaps + recheck แล้วเก็บผลที่ดีกว่า"""
    from ..job_metrics import COVERAGE_HEAL_MIN, speech_coverage_from_arrays
    from .transcribe import assign_speakers, fill_gaps, recheck_noisy

    try:
        wav, sr = sf.read(str(wav16k), dtype="float32")
        if getattr(wav, "ndim", 1) > 1:
            wav = wav.mean(axis=1)
    except Exception as exc:  # noqa: BLE001
        return utterances, words, {"healed": False, "error": str(exc)}

    before = speech_coverage_from_arrays(np.asarray(wav, dtype=np.float32), int(sr), utterances)
    cov0 = float(before.get("coverage") or 0.0)
    if cov0 >= COVERAGE_HEAL_MIN:
        return utterances, words, {"healed": False, "coverage_before": cov0, "reason": "ok"}

    stage("transcribe", 0.51)
    old_thr = settings.whisper_vad_threshold
    old_gap = settings.whisper_fill_gap_sec
    # ผ่อนชั่วคราวในขอบเขตปลอดภัย
    object.__setattr__(settings, "whisper_vad_threshold", max(0.25, float(old_thr) - 0.08))
    object.__setattr__(settings, "whisper_fill_gap_sec", max(0.25, float(old_gap) - 0.15))
    heal: dict = {"healed": False, "coverage_before": cov0}
    try:
        soft_words = fill_gaps(wav16k, list(words), turns, lang, min_gap=settings.whisper_fill_gap_sec,
                               confidence=confidence)
        # บังคับ recheck ช่วงที่ coverage พลาด แม้ RETRANSCRIBE_NOISY ปิด
        mixed16k = audio.to_mono(mixed, wav16k.parent / "mixed16k_heal.wav", 16000)
        bgm16k = audio.to_mono(bgm, wav16k.parent / "bgm16k_heal.wav", 16000) if bgm else None
        soft_words, unclear, stats = recheck_noisy(
            mixed16k, wav16k, bgm16k, soft_words, confidence, turns, lang)
        # ใช้ turns ที่ sync หลัง cluster — ถ้า word_turns ยังคนเดียวจะรวมผู้พูดกลับ
        spk_turns = turns if len({t.speaker for t in turns}) >= len({t.speaker for t in word_turns}) else word_turns
        new_utts = assign_speakers(soft_words, spk_turns, lang=lang)
        from . import repair as repair_mod
        new_utts, soft_words, n_rep = repair_mod.repair_transcript(new_utts, soft_words, turns, lang)
        # คงป้ายผู้พูดที่แยกไว้แล้วถ้า heal สร้างท่อนใหม่จาก turns ที่ยังรวมคน
        if len({u.speaker for u in utterances}) > len({u.speaker for u in new_utts}):
            new_utts = repair_mod._reassign_from_old(utterances, soft_words, lang)
        after = speech_coverage_from_arrays(np.asarray(wav, dtype=np.float32), int(sr), new_utts)
        cov1 = float(after.get("coverage") or 0.0)
        heal.update({
            "coverage_after": cov1, "words_before": len(words), "words_after": len(soft_words),
            "recheck": stats, "repaired": n_rep, "unclear": len(unclear or []),
        })
        if cov1 > cov0 + 0.01 or (cov1 >= cov0 and len(soft_words) > len(words)):
            heal["healed"] = True
            return new_utts, soft_words, heal
        heal["reason"] = "no_improvement"
        return utterances, words, heal
    except Exception as exc:  # noqa: BLE001
        heal["error"] = str(exc)
        log.warning("auto-heal ASR failed: %s", exc)
        return utterances, words, heal
    finally:
        object.__setattr__(settings, "whisper_vad_threshold", old_thr)
        object.__setattr__(settings, "whisper_fill_gap_sec", old_gap)


def features_core(utterances: list[Utterance], vocals: Path, lang: str) -> dict:
    """ค่าที่ขั้นพากย์ต้องใช้โมเดล คำนวณไว้ตั้งแต่ขั้นวิเคราะห์ (ใช้ในโหมด modal)
    เวลาของแต่ละท่อนไม่เปลี่ยนแม้แก้บท ขั้นพากย์จึงไม่ต้องส่งเสียงทั้งคลิปขึ้นไปวัดใหม่"""
    orig, sr = _mono(vocals)
    lines = {u.id: {"start": u.start, "end": u.end} for u in utterances}
    if settings.ref_min_quality > 0:
        from . import quality
        for u in utterances:
            lines[u.id]["quality"] = round(quality.score(orig[int(u.start * sr): int(u.end * sr)], sr), 2)
        release("quality")
    if settings.voice_match and settings.hf_token:
        from . import voices
        for i, v in voices.profile(utterances, orig, sr).items():
            lines[i]["emb"] = v.emb.tolist() if v.emb is not None else None
            lines[i]["pitch"] = v.pitch if np.isfinite(v.pitch) else None
        release("voices")
    return {"lines": lines, "speech": untranscribed_speech(utterances, orig, sr, lang)}


def untranscribed_speech(utterances: list[Utterance], orig: np.ndarray, sr: int, lang: Optional[str],
                         pad: float = 0.15) -> list[list[float]]:
    """ช่วงเสียงดังนอกบทที่ Whisper ฟังแล้วเป็นคำพูด (ถอดตกไป) mix.nonspeech จะไม่ใส่ช่วงนี้กลับเข้าเสียงพากย์"""
    import librosa

    from .mix import _loud_runs
    from .transcribe import words_in

    keep = np.ones(len(orig), dtype=np.float32)
    for u in utterances:
        keep[max(0, int((u.start - pad) * sr)): max(0, int((u.end + pad) * sr))] = 0
    out = []
    for a, b in _loud_runs(orig * keep, sr):
        words = words_in(librosa.resample(orig[a:b], orig_sr=sr, target_sr=16000), lang or None)
        if words:
            log.info("untranscribed speech in original vocals: %r", words)
            out.append([round(a / sr, 3), round(b / sr, 3)])
    release("transcribe")
    return out


def speak_line(synthesize, ref_path: Path, line: dict, steps: int, speed: float,
               checks: Optional[dict] = None) -> np.ndarray:
    """พากย์หนึ่งช่วง โมเดลปรับจังหวะพูดให้พอดีฉากเองตอนสร้างเสียง ไม่ต้องเร่งความเร็วทีหลัง
    checks: ใส่ผลตรวจเสียงพากย์ id → [คะแนน, ที่ได้ยิน] (เฉพาะช่วงที่ line["check_text"])"""
    from .tts import SAMPLE_RATE

    speak_text = line["text"]
    if (line.get("target_lang") or "th") == "th":
        from .translate import pronounce_thai
        # พจนานุกรม + แคช AI (บน Modal ถ้าไม่มีคีย์จะใช้แค่พจนานุกรม/แคชที่ฝังในบทแล้ว)
        speak_text = pronounce_thai(speak_text, use_ai=bool(settings.typhoon_api_key) and settings.ai_speak_latin)

    # F5-TTS สุ่มได้เสียงเงียบเป็นครั้งคราว → สร้างใหม่ (สูงสุด 3 รอบ)
    def once():
        for _ in range(3):
            v = synthesize(ref_path, line["ref_text"], speak_text, speed, steps, line["target_lang"],
                           slot=line["slot"], max_speedup=line["max_speedup"], max_slowdown=line["max_slowdown"])
            if len(v) and np.isfinite(v).all() and np.abs(v).max() > 0.02:
                break
            log.warning("line %s: silent TTS output, retrying", line["id"])
        return np.nan_to_num(v)

    voice = once()
    # บางรอบ F5-TTS พูดหลุดจากเสียงตัวอย่าง (ผู้หญิงกลายเป็นเสียงต่ำ เด็กกลายเป็นผู้ใหญ่)
    # → วัดระดับเสียงเทียบเสียงตัวอย่าง ห่างเกินเกณฑ์ก็พากย์ใหม่ แล้วเลือกรอบที่ใกล้ที่สุด
    if line.get("check_pitch"):
        from .voices import _pitch
        ref_wav, ref_sr = _mono(ref_path)
        ref_pitch = _pitch(ref_wav, ref_sr)
        if np.isfinite(ref_pitch):
            gap = lambda v: abs(_pitch(v, SAMPLE_RATE) - ref_pitch)  # noqa: E731  (nan → ไม่ลองใหม่)
            tries = [(gap(voice), voice)]
            for _ in range(settings.voice_retries):
                if not tries[-1][0] > settings.voice_drift:
                    break
                log.info("line %s: voice drifted %.1f st from reference, retrying", line["id"], tries[-1][0])
                v = once()
                tries.append((gap(v), v))
            voice = min(tries, key=lambda x: x[0] if np.isfinite(x[0]) else 99)[1]
    # F5-TTS บางรอบพูดไม่ตรงบท (ตกคำ พูดซ้ำ อ่านมั่ว) → ถอดเสียงพากย์กลับมาเทียบกับบท ไม่ผ่านก็พากย์ใหม่
    if line.get("check_text") and settings.dub_check and not settings.mock_pipeline:
        from .transcribe import heard, match_score
        text = heard(voice, SAMPLE_RATE, line["target_lang"])
        tries = [(match_score(speak_text, text), text, voice)]
        for _ in range(settings.dub_check_retries):
            if tries[-1][0] >= settings.dub_check_min:
                break
            log.info("line %s: dub sounds off (%.2f, heard %r), retrying", line["id"], tries[-1][0], tries[-1][1])
            v = once()
            text = heard(v, SAMPLE_RATE, line["target_lang"])
            tries.append((match_score(speak_text, text), text, v))
        score, text, voice = max(tries, key=lambda x: x[0])
        if checks is not None:
            checks[line["id"]] = [round(score, 3), text]
    return voice


def synthesize_core(vocals: Path, lines: list[dict], steps: int, speed: float, refs: dict[str, Path],
                    ref_dir: Path, on_progress: Optional[Callable[[float], None]] = None,
                    checks: Optional[dict] = None) -> dict[str, np.ndarray]:
    """พากย์ทุกช่วงใน lines คืน id → เสียง 24 kHz (ยังไม่ตัดความเงียบ) ผลตรวจเสียงพากย์ใส่ใน checks
    เสียงตัวอย่าง: line["ref"] = คีย์ใน refs (เสียงในคลัง) หรือ ref_start/ref_end = ช่วงที่ตัดจาก vocals"""
    from .tts import SAMPLE_RATE

    *_, synthesize = _models()
    out = {}
    for i, line in enumerate(lines):
        if line.get("ref"):
            ref_path = refs[line["ref"]]
        else:
            start, end = line["ref_start"], line["ref_end"]
            ref_path = ref_dir / f"ref_{round(start * 1000):08d}_{round(end * 1000):08d}.wav"
            if not ref_path.exists():
                audio.cut_clip(vocals, start, end, ref_path, SAMPLE_RATE)
        out[line["id"]] = speak_line(synthesize, ref_path, line, steps, speed, checks)
        if on_progress:
            on_progress((i + 1) / len(lines))
    return out


# ================================================================ ฝั่ง Modal (modal_app.py เรียก)
def _flac(src: Path, sr: int) -> bytes:
    """แปลงไฟล์เสียงเป็น FLAC mono (ไฟล์เล็กกว่า WAV ราวครึ่ง ไม่เสียคุณภาพ)"""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audio.flac"
        audio.run(["ffmpeg", "-y", "-i", src, "-ac", 1, "-ar", sr, "-c:a", "flac", out])
        return out.read_bytes()


def _encode(wav: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(wav, -1.0, 1.0), sr, format="FLAC", subtype="PCM_16")
    return buf.getvalue()


def _decode(data: bytes) -> tuple[np.ndarray, int]:
    return sf.read(io.BytesIO(data), dtype="float32")


def serve_analyze(audio_flac: bytes, source_lang: Optional[str], num_speakers: Optional[int],
                  report: Stage, voice_ref: bool = False, denoise: bool = False,
                  preseparated: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        mixed = work / "audio.flac"
        mixed.write_bytes(audio_flac)
        if voice_ref:  # เตรียมเสียงในคลัง (library.prepare)
            from .library import clean_voice
            r = clean_voice(mixed, work, report, denoise)
            return {"ref_flac": _encode(r["wav"], r["sr"]), "text": r["text"], "pitch_hz": r["pitch_hz"],
                    "quality": r["quality"], "emb": None if r["emb"] is None else r["emb"].tolist(),
                    "stats": r.get("stats")}
        res = analyze_core(mixed, work, source_lang, num_speakers, report, preseparated=preseparated)
        report("transcribe", 0.5)
        features = features_core(res["utterances"], res["vocals"], res["lang"])
        return {
            "vocals_flac": _flac(res["vocals"], SOURCE_SR),
            "bgm_flac": _flac(res["bgm"], SOURCE_SR),
            "turns": [t.__dict__ for t in res["turns"]],
            "words": [w.__dict__ for w in res["words"]],
            "detected_lang": res["lang"],
            "utterances": [u.model_dump() for u in res["utterances"]],
            "speakers": res["speakers"],
            "features": features,
            "recheck": res.get("recheck"),
        }


def serve_synthesize(vocals_flac: bytes, lines: list[dict], steps: int, speed: float,
                     refs: Optional[dict[str, bytes]], report: Stage) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        vocals = work / "vocals.flac"
        vocals.write_bytes(vocals_flac)
        ref_paths = {}
        for i, (key, data) in enumerate((refs or {}).items()):
            wav, sr = _decode(data)
            ref_paths[key] = work / f"library_{i}.wav"
            sf.write(ref_paths[key], wav, sr)
        checks: dict = {}
        out = synthesize_core(vocals, lines, steps, speed, ref_paths, work, lambda f: report("tts", round(f, 3)), checks)
        return {**{key: _encode(wav, REF_SR) for key, wav in out.items()}, CHECKS_KEY: json.dumps(checks).encode()}


# ================================================================ ฝั่งเครื่องนี้ (เรียก Modal)
def _run(name: str, calls: list[tuple[tuple, dict]], on_progress=None,
         check_cancel: Optional[Callable[[], None]] = None,
         config_override: Optional[dict] = None) -> list:
    """เรียกฟังก์ชันบน Modal หลายชุดพร้อมกัน (spawn) แล้วรอผล ระหว่างรออ่านความคืบหน้าและเช็กการยกเลิก
    ยกเลิกหรือล้มเหลวกลางทาง → ยกเลิกชุดที่ยังรันอยู่บน Modal ด้วย จะได้ไม่เสียเครดิตเปล่า"""
    # MODAL_TOKEN_ID= ที่เว้นว่างใน .env จะทับคีย์จาก modal setup → ลบทิ้ง
    for var in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        if not os.environ.get(var, "x").strip():
            del os.environ[var]
    try:
        import modal
    except ImportError as exc:
        raise RuntimeError("WORKER=modal ต้องติดตั้ง modal ก่อน: pip install modal") from exc

    fn = modal.Function.from_name(settings.modal_app, name)
    board = modal.Dict.from_name(PROGRESS_DICT, create_if_missing=True)
    try:
        from ..knobs import ensure_applied, get as knob
        ensure_applied()
        config = {k: getattr(settings, k) for k in REMOTE_FIELDS}
        for key in ("whisper_vad_threshold", "whisper_fill_gap_sec", "dub_check_min"):
            if key in config:
                config[key] = knob(key, config[key])
    except Exception:  # noqa: BLE001
        config = {k: getattr(settings, k) for k in REMOTE_FIELDS}
    if config_override:
        config.update({k: v for k, v in config_override.items() if k in REMOTE_FIELDS})
    keys = [uuid.uuid4().hex for _ in calls]
    handles, results, finished = [], [None] * len(calls), [False] * len(calls)
    try:
        for (args, kwargs), key in zip(calls, keys):
            try:
                handles.append(fn.spawn(*args, **kwargs, config=config, progress_key=key))
            except modal.exception.NotFoundError as exc:
                raise RuntimeError(f"ไม่พบ {settings.modal_app}/{name} บน Modal รัน modal deploy modal_app.py ก่อน") from exc
        while not all(finished):
            if check_cancel:
                check_cancel()
            for i, h in enumerate(handles):
                if not finished[i]:
                    try:
                        results[i] = h.get(timeout=0)
                        finished[i] = True
                    except TimeoutError:  # ยังไม่เสร็จ
                        pass
            if all(finished):
                break
            if on_progress:
                on_progress([None if f else board.get(k) for k, f in zip(keys, finished)], finished)
            time.sleep(POLL_SEC)
    except BaseException:
        for h, f in zip(handles, finished):
            if not f:
                try:
                    h.cancel()
                except Exception as exc:  # noqa: BLE001
                    log.warning("cancel Modal call failed: %s", exc)
        raise
    finally:
        for key in keys:
            try:
                board.pop(key, None)
            except Exception:  # noqa: BLE001
                pass
    return results


def _follow(stage: Stage):
    """ส่งต่อความคืบหน้า [ชื่อขั้น, ค่า] ที่ Modal รายงาน ให้ stage ของงาน"""
    last = [None]

    def on_progress(states, _finished):
        state = states[0]
        if state and state != last[0]:
            last[0] = state
            stage(state[0], state[1])
    return on_progress


def _follow_chunks(stage: Stage, n: int):
    """เฉลี่ยความคืบหน้าหลายชิ้น → ขั้นรวม (0.1–0.85)"""
    lasts = [None] * n

    def on_progress(states, finished):
        total = 0.0
        name = "separate_vocals"
        for i, (state, done) in enumerate(zip(states, finished)):
            if done:
                total += 1.0
                continue
            if state:
                lasts[i] = state
                name = state[0]
                total += float(state[1] or 0)
            elif lasts[i]:
                name = lasts[i][0]
                total += float(lasts[i][1] or 0)
        frac = total / max(n, 1)
        stage(name, round(0.1 + 0.75 * frac, 3))
    return on_progress


def _analyze_fast_config() -> Optional[dict]:
    """โหมดเร็วสำหรับคลิปยาว: สลับ Whisper เป็นรุ่นเล็กกว่า"""
    if not settings.analyze_fast:
        return None
    model = (settings.analyze_fast_whisper or "").strip()
    if not model or model == settings.whisper_model:
        return None
    log.info("analyze fast mode: whisper_model %s → %s", settings.whisper_model, model)
    return {"whisper_model": model}


def _flac_slice(src: Path, start: float, end: float, sr: int = SOURCE_SR) -> bytes:
    """ตัดช่วงเสียงเป็น FLAC mono สำหรับส่ง Modal"""
    dur = max(0.05, end - start)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audio.flac"
        audio.run([
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
            "-i", src, "-ac", "1", "-ar", sr, "-c:a", "flac", out,
        ])
        return out.read_bytes()


def _write_features(work: Path, features: dict) -> None:
    lines = features.get("lines") or {}
    payload = {
        "lines": {str(k): v for k, v in lines.items()},
        "speech": features.get("speech") or [],
    }
    (work / ANALYSIS_FILE).write_text(json.dumps(payload), encoding="utf-8")


def _plan_analyze_windows(mixed: Path, preseparated: bool):
    from . import chunks as chunking

    if preseparated or settings.analyze_chunk_sec <= 0 or settings.analyze_chunk_min_sec <= 0:
        return []
    try:
        duration = audio.probe_duration(mixed)
    except Exception as exc:  # noqa: BLE001
        log.warning("probe_duration failed (%s); skip chunk analyze", exc)
        return []
    return chunking.plan_windows(
        duration,
        chunk_sec=settings.analyze_chunk_sec,
        overlap_sec=settings.analyze_chunk_overlap_sec,
        min_total_sec=settings.analyze_chunk_min_sec,
    )


def _analyze_chunked_remote(
    mixed: Path, work: Path, windows, source_lang: Optional[str], num_speakers: Optional[int],
    stage: Stage, check_cancel: Optional[Callable[[], None]],
) -> dict:
    from . import chunks as chunking

    stage("separate_vocals", 0.1)
    overlap = settings.analyze_chunk_overlap_sec
    calls = []
    for win in windows:
        data = _flac_slice(mixed, win.start, win.end)
        log.info(
            "analyze chunk %d/%d: %.1f–%.1f s (upload %.1f MB)",
            win.index + 1, len(windows), win.start, win.end, len(data) / 1e6,
        )
        calls.append(((data, source_lang, num_speakers), {}))

    # จำกัดจำนวน spawn พร้อมกันตาม MODAL_MAX_JOBS
    max_jobs = max(1, settings.modal_max_jobs)
    results: list = [None] * len(calls)
    fast = _analyze_fast_config()
    for batch_start in range(0, len(calls), max_jobs):
        batch = calls[batch_start: batch_start + max_jobs]
        batch_idx = list(range(batch_start, batch_start + len(batch)))

        def _progress(states, finished, _idx=batch_idx):
            # วาง state ของแบตช์ลงช่องรวมทั้งคลิป
            full_states = [None] * len(calls)
            full_fin = [bool(results[i]) for i in range(len(calls))]
            for j, i in enumerate(_idx):
                full_states[i] = states[j]
                full_fin[i] = finished[j] or full_fin[i]
            _follow_chunks(stage, len(calls))(full_states, full_fin)

        batch_res = _run(
            "analyze_audio", batch, _progress, check_cancel, config_override=fast,
        )
        for i, res in zip(batch_idx, batch_res):
            results[i] = res

    merged = chunking.merge_chunk_results(windows, results)

    def _as_2d(x: np.ndarray) -> np.ndarray:
        return x[:, None] if x.ndim == 1 else x

    vocals_parts, bgm_parts = [], []
    for win, res in zip(windows, results):
        v, vsr = _decode(res["vocals_flac"])
        b, bsr = _decode(res["bgm_flac"])
        vocals_parts.append((win, _as_2d(v), vsr))
        bgm_parts.append((win, _as_2d(b), bsr))
    v_wav, v_sr = chunking.stitch_wavs(vocals_parts, overlap)
    b_wav, b_sr = chunking.stitch_wavs(bgm_parts, overlap)
    out = {"vocals": work / "vocals.wav", "bgm": work / "bgm.wav"}
    sf.write(out["vocals"], v_wav, v_sr)
    sf.write(out["bgm"], b_wav, b_sr)
    _write_features(work, merged["features"])
    stage("transcribe", 0.9)
    return {
        **out,
        "turns": merged["turns"],
        "words": merged["words"],
        "lang": merged["lang"],
        "utterances": merged["utterances"],
        "speakers": merged["speakers"],
        "recheck": merged.get("recheck"),
    }


def _analyze_chunked_local(
    mixed: Path, work: Path, windows, source_lang: Optional[str], num_speakers: Optional[int],
    stage: Stage,
) -> dict:
    """เครื่องนี้: วิเคราะห์ทีละชิ้น (กัน OOM) แล้วรวม — ใช้โหมดเร็วถ้าเปิด"""
    from . import chunks as chunking

    overlap = settings.analyze_chunk_overlap_sec
    fast = _analyze_fast_config()
    old_whisper = settings.whisper_model
    if fast and "whisper_model" in fast:
        object.__setattr__(settings, "whisper_model", fast["whisper_model"])
    parts = []
    vocals_parts, bgm_parts = [], []
    try:
        for i, win in enumerate(windows):
            stage("separate_vocals", round(0.1 + 0.7 * i / len(windows), 3))
            chunk_dir = work / f"_chunk_{win.index:02d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            sliced = chunk_dir / "mixed.wav"
            audio.run([
                "ffmpeg", "-y", "-ss", f"{win.start:.3f}", "-t", f"{win.duration:.3f}",
                "-i", mixed, "-ac", "2", "-ar", str(SOURCE_SR), "-c:a", "pcm_s16le", sliced,
            ])
            res = analyze_core(sliced, chunk_dir, source_lang, num_speakers, stage)
            features = features_core(res["utterances"], res["vocals"], res["lang"])
            parts.append({
                "turns": [t.__dict__ for t in res["turns"]],
                "words": [w.__dict__ for w in res["words"]],
                "utterances": [u.model_dump() for u in res["utterances"]],
                "speakers": res["speakers"],
                "detected_lang": res["lang"],
                "features": features,
                "recheck": res.get("recheck"),
            })
            v, vsr = _mono(res["vocals"])
            b, bsr = _mono(res["bgm"])
            vocals_parts.append((win, v[:, None], vsr))
            bgm_parts.append((win, b[:, None], bsr))
    finally:
        if fast and "whisper_model" in fast:
            object.__setattr__(settings, "whisper_model", old_whisper)

    merged = chunking.merge_chunk_results(windows, parts)
    v_wav, v_sr = chunking.stitch_wavs(vocals_parts, overlap)
    b_wav, b_sr = chunking.stitch_wavs(bgm_parts, overlap)
    out = {"vocals": work / "vocals.wav", "bgm": work / "bgm.wav"}
    sf.write(out["vocals"], v_wav, v_sr)
    sf.write(out["bgm"], b_wav, b_sr)
    _write_features(work, merged["features"])
    return {
        **out,
        "turns": merged["turns"],
        "words": merged["words"],
        "lang": merged["lang"],
        "utterances": merged["utterances"],
        "speakers": merged["speakers"],
        "recheck": merged.get("recheck"),
    }


def analyze(mixed: Path, work: Path, source_lang: Optional[str], num_speakers: Optional[int],
            stage: Stage, check_cancel: Optional[Callable[[], None]] = None,
            preseparated: bool = False) -> dict:
    """คืน vocals, bgm (ไฟล์ใน work), turns, words, lang, utterances, speakers
    preseparated=True: แทร็กคนละคนแล้ว (ไทม์ไลน์) ข้ามแยกพูด/เพลงและแยกผู้พูด
    คลิปยาวเกินเกณฑ์ → ตัดชิ้น + วิเคราะห์ขนาน (Modal) / ทีละชิ้น (local)"""
    windows = _plan_analyze_windows(mixed, preseparated)
    if windows:
        log.info("analyze chunked: %d windows (%.0f–%.0f s each, overlap %.0f s)",
                 len(windows), settings.analyze_chunk_sec, settings.analyze_chunk_sec,
                 settings.analyze_chunk_overlap_sec)
        if remote():
            return _analyze_chunked_remote(
                mixed, work, windows, source_lang, num_speakers, stage, check_cancel,
            )
        return _analyze_chunked_local(mixed, work, windows, source_lang, num_speakers, stage)

    if not remote():
        return analyze_core(mixed, work, source_lang, num_speakers, stage, preseparated=preseparated)

    stage("transcribe" if preseparated else "separate_vocals", 0.1)
    data = _flac(mixed, SOURCE_SR)
    log.info("analyze on Modal: upload %.1f MB%s", len(data) / 1e6, " (preseparated)" if preseparated else "")
    # ส่ง preseparated เฉพาะตอนเปิด — ฟังก์ชันบน Modal รุ่นก่อนไม่รู้จักค่านี้
    kwargs = {"preseparated": True} if preseparated else {}
    [res] = _run("analyze_audio", [((data, source_lang, num_speakers), kwargs)], _follow(stage), check_cancel)
    out = {"vocals": work / "vocals.wav", "bgm": work / "bgm.wav"}
    for name, key in (("vocals", "vocals_flac"), ("bgm", "bgm_flac")):
        wav, sr = _decode(res[key])
        sf.write(out[name], wav, sr)
    (work / ANALYSIS_FILE).write_text(json.dumps(res["features"]), encoding="utf-8")
    return {**out, "turns": [Turn(**t) for t in res["turns"]], "words": [Word(**w) for w in res["words"]],
            "lang": res["detected_lang"], "utterances": [Utterance.model_validate(u) for u in res["utterances"]],
            "speakers": res["speakers"], "recheck": res.get("recheck")}  # Modal รุ่นเก่าไม่มี recheck


def resplit_turns(vocals: Path, work: Path, utterances: list[Utterance], words: list[Word],
                  proposals: dict[int, list[str]], lang: str, num_speakers: Optional[int], stage: Stage,
                  check_cancel: Optional[Callable[[], None]] = None) -> tuple[list[Utterance], int]:
    """ตัดท่อนตามจุดเปลี่ยนคนที่เสนอจากบท (ตรวจด้วยลายเสียง) แล้วจัดกลุ่มผู้พูดใหม่ (turns.py)
    วัดค่าต่อท่อนใหม่ทั้งชุด (คะแนนความสะอาด ลายเสียง) ทับ ANALYSIS_FILE ให้ตรงกับท่อนที่ตัดแล้ว
    คืน (ท่อนใหม่, จำนวนจุดที่ตัด)"""
    if not remote():
        from .turns import resplit_core
        wav, sr = _mono(vocals)
        out, cuts = resplit_core(utterances, words, proposals, wav, sr, num_speakers)
        release("voices")
        return out, cuts
    data = _flac(vocals, 16000)
    call = ((data, [u.model_dump() for u in utterances], [w.__dict__ for w in words],
             {str(k): v for k, v in proposals.items()}, lang, num_speakers), {})
    [res] = _run("resplit_turns", [call], _follow(stage), check_cancel)
    if res["cuts"]:
        (work / ANALYSIS_FILE).write_text(json.dumps(res["features"]), encoding="utf-8")
    return [Utterance.model_validate(u) for u in res["utterances"]], res["cuts"]


def serve_resplit(audio_flac: bytes, utterances: list[dict], words: list[dict], proposals: dict[str, list[str]],
                  lang: str, num_speakers: Optional[int], report: Stage) -> dict:
    from .turns import resplit_core

    with tempfile.TemporaryDirectory() as tmp:
        vocals = Path(tmp) / "vocals.flac"
        vocals.write_bytes(audio_flac)
        wav, sr = _mono(vocals)
        report("split_turns", 0.5)
        out, cuts = resplit_core([Utterance.model_validate(u) for u in utterances], [Word(**w) for w in words],
                                 {int(k): v for k, v in proposals.items()}, wav, sr, num_speakers)
        features = features_core(out, vocals, lang) if cuts else None
        return {"utterances": [u.model_dump() for u in out], "cuts": cuts, "features": features}


def prepare_voice(raw: Path, work: Path, stage: Stage, denoise: bool = False) -> dict:
    """ทำความสะอาดและตัดเสียงในคลัง คืน wav, sr, text, pitch_hz, quality, emb (library.clean_voice)
    denoise: ลดเสียงรบกวนหลังแยกเพลง"""
    if not remote():
        from .library import clean_voice
        return clean_voice(raw, work, stage, denoise)
    # ส่ง denoise เฉพาะตอนเปิด ฟังก์ชันบน Modal รุ่นก่อนหน้าไม่รู้จักค่านี้
    kwargs = {"voice_ref": True, **({"denoise": True} if denoise else {})}
    [res] = _run("analyze_audio", [((_flac(raw, SOURCE_SR), "th", None), kwargs)], _follow(stage))
    wav, sr = _decode(res["ref_flac"])
    emb = None if res["emb"] is None else np.asarray(res["emb"], dtype=np.float32)
    return {"wav": wav, "sr": sr, "text": res["text"], "pitch_hz": res["pitch_hz"], "quality": res["quality"],
            "emb": emb, "stats": res.get("stats")}


def _ref_track(lines: list[dict], orig: np.ndarray, sr: int, gap: float = 0.5) -> bytes:
    """ต่อเฉพาะช่วงเสียงตัวอย่างที่ชุดนี้ใช้เป็นแทร็กเดียว (คั่นด้วยความเงียบ) แล้วแก้ ref_start/ref_end ให้ชี้ตำแหน่งใหม่
    อัปโหลดแค่ไม่กี่วินาทีต่อประโยค แทนเสียงพูดทั้งคลิปทุกชุด"""
    silence = np.zeros(int(gap * sr), dtype=np.float32)
    pieces, where, pos = [silence], {}, len(silence)
    for start, end in sorted({(x["ref_start"], x["ref_end"]) for x in lines if not x.get("ref")}):
        seg = orig[int(start * sr): int(end * sr)]
        where[(start, end)] = (pos / sr, (pos + len(seg)) / sr)
        pieces += [seg, silence]
        pos += len(seg) + len(silence)
    for x in lines:
        if not x.get("ref"):
            x["ref_start"], x["ref_end"] = where[(x["ref_start"], x["ref_end"])]
    with tempfile.TemporaryDirectory() as tmp:
        track = Path(tmp) / "refs.wav"
        sf.write(track, np.concatenate(pieces), sr)
        return _flac(track, REF_SR)


def synthesize_lines(vocals: Path, lines: list[dict], steps: int, speed: float, refs: dict[str, Path],
                     ref_dir: Path, on_progress: Optional[Callable[[float], None]] = None,
                     check_cancel: Optional[Callable[[], None]] = None,
                     checks: Optional[dict] = None) -> dict[str, np.ndarray]:
    """พากย์ทั้งชุด คืน id → เสียง 24 kHz โหมด modal แบ่งเป็นชุดละ MODAL_TTS_BATCH ประโยค ส่งพร้อมกัน
    checks: ใส่ผลตรวจเสียงพากย์ id → [คะแนน, ที่ได้ยิน]"""
    if not remote():
        return synthesize_core(vocals, lines, steps, speed, refs, ref_dir, checks=checks)
    if not lines:
        return {}
    orig, sr = _mono(vocals)
    size = max(1, settings.modal_tts_batch)
    calls = []
    for i in range(0, len(lines), size):
        batch = [dict(x) for x in lines[i: i + size]]
        track = _ref_track(batch, orig, sr)
        library = {key: _flac(refs[key], REF_SR) for key in {x["ref"] for x in batch if x.get("ref")}}
        calls.append(((track, batch, steps, speed), {"refs": library}))
    sizes = [len(c[0][1]) for c in calls]
    log.info("synthesize %d lines on Modal in %d batches", len(lines), len(calls))

    def progress(states, finished):
        if on_progress:
            done = sum(n * (1.0 if f else (s[1] if s else 0.0)) for n, s, f in zip(sizes, states, finished))
            on_progress(done / sum(sizes))

    out = {}
    for res in _run("synthesize_lines", calls, progress, check_cancel):
        found = json.loads(res.pop(CHECKS_KEY, b"{}"))
        if checks is not None:
            checks.update(found)
        for key, data in res.items():
            out[key] = _decode(data)[0]
    return out


# ================================================================ ค่าที่ขั้นพากย์ใช้
def saved_lines(job_dir: Path, utterances: list[Utterance]) -> Optional[dict[int, dict]]:
    """ค่าต่อท่อนที่ Modal คำนวณไว้ตอนวิเคราะห์ (เฉพาะท่อนที่เวลายังตรงกัน) ใช้ในโหมด modal"""
    try:
        lines = json.loads((job_dir / ANALYSIS_FILE).read_text(encoding="utf-8"))["lines"]
    except (OSError, ValueError, KeyError):
        log.warning("no %s (job analyzed with WORKER=local?), skipping quality/voice checks", ANALYSIS_FILE)
        return None
    out = {}
    for u in utterances:
        x = lines.get(str(u.id))
        if x and abs(x["start"] - u.start) < 1e-3 and abs(x["end"] - u.end) < 1e-3:
            out[u.id] = x
    return out


def ref_quality(job_dir: Path, utterances: list[Utterance], orig: np.ndarray, sr: int) -> Optional[dict[int, float]]:
    """id → คะแนนความสะอาดของเสียงต้นฉบับ (ใช้คัดเสียงตัวอย่าง)"""
    if remote():
        saved = saved_lines(job_dir, utterances)
        q = {i: x["quality"] for i, x in (saved or {}).items() if x.get("quality") is not None}
        return q or None
    from . import quality
    q = {u.id: round(quality.score(orig[int(u.start * sr): int(u.end * sr)], sr), 2) for u in utterances}
    release("quality")
    return q


def voice_profiles(job_dir: Path, utterances: list[Utterance], orig: np.ndarray, sr: int) -> Optional[dict]:
    """id → ลายเสียง (voices.Voice) ของแต่ละท่อน"""
    from . import voices

    if remote():
        saved = saved_lines(job_dir, utterances)
        out = {i: voices.Voice(None if x["emb"] is None else np.asarray(x["emb"], dtype=np.float32),
                               float("nan") if x["pitch"] is None else x["pitch"])
               for i, x in (saved or {}).items() if "emb" in x}
        return out or None
    out = voices.profile(utterances, orig, sr)
    release("voices")
    return out


def speech_filter(job_dir: Path, source_lang: str) -> tuple[list[tuple[float, float]], Optional[Callable]]:
    """สำหรับ mix.nonspeech: (ช่วงที่รู้แล้วว่าเป็นคำพูดที่ถอดตกไป, ฟังก์ชันตรวจว่าเสียงเป็นคำพูดไหม)"""
    if remote():
        try:
            speech = json.loads((job_dir / ANALYSIS_FILE).read_text(encoding="utf-8"))["speech"]
        except (OSError, ValueError, KeyError):
            speech = []
        return [tuple(x) for x in speech], None

    import librosa

    from .transcribe import words_in

    def is_speech(seg: np.ndarray, seg_sr: int) -> bool:
        words = words_in(librosa.resample(seg, orig_sr=seg_sr, target_sr=16000), source_lang or None)
        if words:
            log.info("skip untranscribed speech in original vocals: %r", words)
        return bool(words)
    return [], is_speech
