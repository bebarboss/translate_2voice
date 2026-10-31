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
PROGRESS_DICT = "dubbing-progress"  # modal.Dict ที่ฝั่ง Modal เขียนความคืบหน้าให้ฝั่งนี้อ่าน
POLL_SEC = 2.0
SOURCE_SR = 44100  # เสียงที่ส่งไปแยกเสียงพูด
REF_SR = 24000  # เสียงตัวอย่างของ F5-TTS (tts.SAMPLE_RATE)

# ค่าตั้งค่าที่ส่งไปใช้บน Modal ทุกครั้งที่เรียก ไม่ต้อง deploy ใหม่เมื่อแก้ .env
# ไม่ส่งค่าเฉพาะเครื่อง (DEVICE, LOW_VRAM, F5_FP32, WHISPER_COMPUTE_TYPE, F5_CACHE_DIR) และ HF_TOKEN (อยู่ใน Secret)
REMOTE_FIELDS = (
    "demucs_model", "diarization_model", "whisper_model", "f5_model", "f5_en_model", "f5_cfg",
    "ref_min_sec", "ref_max_sec", "ref_min_quality", "max_line_sec",
    "voice_match", "voice_min_sim", "voice_max_pitch_diff", "voice_split_pitch",
    "diar_refine", "diar_split_coherence", "diar_merge_sim", "voice_drift", "voice_retries",
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
def analyze_core(mixed: Path, work: Path, source_lang: Optional[str], num_speakers: Optional[int],
                 stage: Stage) -> dict:
    """แยกเสียงพูด/เพลง → แยกผู้พูด → ถอดเสียง → แบ่งประโยคตามผู้พูด เขียน vocals.wav, bgm.wav ลง work"""
    from .transcribe import assign_speakers

    separate, diarize, transcribe, _ = _models()
    voice_ok = bool(settings.hf_token) and not settings.mock_pipeline

    stage("separate_vocals", 0.1)
    release("tts")  # เผื่อโมเดลพากย์จากงานก่อนยังค้างอยู่
    vocals, bgm = separate(mixed, work, settings.demucs_model, settings.device)
    wav16k = audio.to_mono(vocals, work / "vocals16k.wav", 16000)

    stage("diarize", 0.25)
    turns = diarize(wav16k, num_speakers)
    release("diarize")
    # ไม่ได้ระบุจำนวนคน → ตรวจผลด้วยลายเสียง แยกคนที่ถูกรวมกัน และรวมคนเดียวที่ถูกแยก
    if not num_speakers and settings.diar_refine and voice_ok:
        from . import voices
        wav, wsr = sf.read(wav16k, dtype="float32")
        turns = voices.refine_turns(turns, wav, wsr)
        release("voices")
    speakers = sorted({t.speaker for t in turns})

    stage("transcribe", 0.4)
    words, lang = transcribe(wav16k, source_lang)
    if not settings.mock_pipeline:  # ช่วงที่มีคนพูดแต่ถอดไม่ออก (เพลงดังทับ) → ถอดซ้ำเฉพาะช่วงนั้น
        from .transcribe import fill_gaps
        words = fill_gaps(wav16k, words, turns, lang)
    release("transcribe")
    if not words:
        raise RuntimeError("ไม่พบคำพูดในคลิป")
    utterances = assign_speakers(words, turns, lang=lang)
    if settings.voice_match and voice_ok:
        from . import voices
        wav, wsr = sf.read(wav16k, dtype="float32")
        # ท่อนเดียวที่มีหลายคนพูดต่อกัน (pyannote จับไม่ทัน) → แบ่งตรงจุดจบประโยคย่อยที่เสียงต่างกันชัด
        before = len(utterances)
        utterances = voices.split_lines(utterances, words, wav, wsr)
        if len(utterances) != before:
            log.info("split %d lines with more than one voice", len(utterances) - before)
        # ระบบแยกผู้พูดรวมเด็กกับผู้ใหญ่ (หรือชายกับหญิง) เป็นคนเดียว → แยกตามระดับเสียงและลายเสียง
        renamed = voices.split_speakers(utterances, voices.profile(utterances, wav, wsr),
                                         taken={t.speaker for t in turns})
        release("voices")
        if renamed:
            log.info("split speakers by voice: %s", renamed)
            speakers = sorted({u.speaker for u in utterances})
    return {"vocals": vocals, "bgm": bgm, "turns": turns, "words": words, "lang": lang,
            "utterances": utterances, "speakers": speakers}


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


def speak_line(synthesize, ref_path: Path, line: dict, steps: int, speed: float) -> np.ndarray:
    """พากย์หนึ่งช่วง โมเดลปรับจังหวะพูดให้พอดีฉากเองตอนสร้างเสียง ไม่ต้องเร่งความเร็วทีหลัง"""
    from .tts import SAMPLE_RATE

    # F5-TTS สุ่มได้เสียงเงียบเป็นครั้งคราว → สร้างใหม่ (สูงสุด 3 รอบ)
    def once():
        for _ in range(3):
            v = synthesize(ref_path, line["ref_text"], line["text"], speed, steps, line["target_lang"],
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
    return voice


def synthesize_core(vocals: Path, lines: list[dict], steps: int, speed: float, refs: dict[str, Path],
                    ref_dir: Path, on_progress: Optional[Callable[[float], None]] = None) -> dict[str, np.ndarray]:
    """พากย์ทุกช่วงใน lines คืน id → เสียง 24 kHz (ยังไม่ตัดความเงียบ)
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
        out[line["id"]] = speak_line(synthesize, ref_path, line, steps, speed)
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
                  report: Stage, voice_ref: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        mixed = work / "audio.flac"
        mixed.write_bytes(audio_flac)
        if voice_ref:  # เตรียมเสียงในคลัง (library.prepare)
            from .library import clean_voice
            r = clean_voice(mixed, work, report)
            return {"ref_flac": _encode(r["wav"], r["sr"]), "text": r["text"], "pitch_hz": r["pitch_hz"],
                    "quality": r["quality"], "emb": None if r["emb"] is None else r["emb"].tolist()}
        res = analyze_core(mixed, work, source_lang, num_speakers, report)
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
        out = synthesize_core(vocals, lines, steps, speed, ref_paths, work, lambda f: report("tts", round(f, 3)))
        return {key: _encode(wav, REF_SR) for key, wav in out.items()}


# ================================================================ ฝั่งเครื่องนี้ (เรียก Modal)
def _run(name: str, calls: list[tuple[tuple, dict]], on_progress=None,
         check_cancel: Optional[Callable[[], None]] = None) -> list:
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
    config = {k: getattr(settings, k) for k in REMOTE_FIELDS}
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


def analyze(mixed: Path, work: Path, source_lang: Optional[str], num_speakers: Optional[int],
            stage: Stage, check_cancel: Optional[Callable[[], None]] = None) -> dict:
    """คืน vocals, bgm (ไฟล์ใน work), turns, words, lang, utterances, speakers"""
    if not remote():
        return analyze_core(mixed, work, source_lang, num_speakers, stage)

    stage("separate_vocals", 0.1)
    data = _flac(mixed, SOURCE_SR)
    log.info("analyze on Modal: upload %.1f MB", len(data) / 1e6)
    [res] = _run("analyze_audio", [((data, source_lang, num_speakers), {})], _follow(stage), check_cancel)
    out = {"vocals": work / "vocals.wav", "bgm": work / "bgm.wav"}
    for name, key in (("vocals", "vocals_flac"), ("bgm", "bgm_flac")):
        wav, sr = _decode(res[key])
        sf.write(out[name], wav, sr)
    (work / ANALYSIS_FILE).write_text(json.dumps(res["features"]), encoding="utf-8")
    return {**out, "turns": [Turn(**t) for t in res["turns"]], "words": [Word(**w) for w in res["words"]],
            "lang": res["detected_lang"], "utterances": [Utterance.model_validate(u) for u in res["utterances"]],
            "speakers": res["speakers"]}


def prepare_voice(raw: Path, work: Path, stage: Stage) -> dict:
    """ทำความสะอาดและตัดเสียงในคลัง คืน wav, sr, text, pitch_hz, quality, emb (library.clean_voice)"""
    if not remote():
        from .library import clean_voice
        return clean_voice(raw, work, stage)
    [res] = _run("analyze_audio", [((_flac(raw, SOURCE_SR), "th", None), {"voice_ref": True})], _follow(stage))
    wav, sr = _decode(res["ref_flac"])
    emb = None if res["emb"] is None else np.asarray(res["emb"], dtype=np.float32)
    return {"wav": wav, "sr": sr, "text": res["text"], "pitch_hz": res["pitch_hz"], "quality": res["quality"],
            "emb": emb}


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
                     check_cancel: Optional[Callable[[], None]] = None) -> dict[str, np.ndarray]:
    """พากย์ทั้งชุด คืน id → เสียง 24 kHz โหมด modal แบ่งเป็นชุดละ MODAL_TTS_BATCH ประโยค ส่งพร้อมกัน"""
    if not remote():
        return synthesize_core(vocals, lines, steps, speed, refs, ref_dir)
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
