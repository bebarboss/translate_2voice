"""เตรียมเสียงในคลังและจับคู่เสียงในคลังกับตัวละคร

prepare : คลิปเสียงไทยที่อัปโหลด → แยกเพลง/เสียงรบกวนออก (Demucs) → ถอดข้อความพร้อมเวลาแต่ละคำ (Whisper)
          → ตัดท่อนพูดต่อเนื่องที่สะอาดที่สุดยาว 3–10 วินาที (ตัดตรงช่วงหยุดหายใจ ไม่ตัดกลางคำ) → ปรับความดัง
          → วัดระดับเสียงและลายเสียงไว้ใช้แนะนำ
suggest : ให้คะแนนความใกล้เคียงระหว่างเสียงตัวละครกับเสียงในคลัง
          ระดับเสียงบอกเพศและวัยได้ดีแม้ต่างภาษา จึงให้น้ำหนักมากกว่า ลายเสียงช่วยแยกเนื้อเสียงที่ระดับใกล้กัน
"""
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ..config import settings
from ..schemas import Utterance, VoiceStatus
from ..voice_library import VoiceStore
from . import audio
from .voices import EMBED_MODEL, Voice, _pitch

log = logging.getLogger("dubbing.library")

MIN_SEC = 3.0  # เสียงตัวอย่างสั้นกว่านี้ F5-TTS เก็บน้ำเสียงได้ไม่ดี
MAX_INPUT_SEC = 300  # ใช้แค่ 5 นาทีแรกของไฟล์ที่อัปโหลด พอให้หาท่อนดี ๆ ได้ และไม่กินเวลาแยกเสียงนาน
MALE_BELOW_HZ = 165.0  # เส้นแบ่งคร่าว ๆ ระหว่างเสียงผู้ชายกับผู้หญิง

_embedder = None
_embed_lock = threading.Lock()


# ---------------------------------------------------------------- ลายเสียง (CPU)
def _embed(seg: np.ndarray, sr: int) -> Optional[np.ndarray]:
    """ลายเสียง (normalized) ด้วยโมเดลเดียวกับ voices.py แต่รันบน CPU
    เรียกจากคำขอของหน้าเว็บได้ระหว่างที่งานพากย์ใช้การ์ดจออยู่ โมเดลเล็ก (ราว 25 MB) ไม่เปลือง RAM"""
    global _embedder
    if not settings.hf_token or settings.mock_pipeline or len(seg) < sr:
        return None
    import librosa
    import torch

    with _embed_lock:
        if _embedder is None:
            from pyannote.audio import Inference, Model
            _embedder = Inference(Model.from_pretrained(EMBED_MODEL, token=settings.hf_token),
                                  window="whole", device=torch.device("cpu"))
        w = librosa.resample(np.asarray(seg, dtype=np.float32), orig_sr=sr, target_sr=16000)
        v = np.asarray(_embedder({"waveform": torch.from_numpy(w)[None], "sample_rate": 16000})).reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 and np.isfinite(v).all() else None


def _semitone(hz: Optional[float]) -> float:
    return float(12 * np.log2(hz)) if hz else float("nan")


def _hz(st: float) -> Optional[float]:
    return round(float(2 ** (st / 12)), 1) if np.isfinite(st) else None


def guess_gender(pitch_hz: Optional[float]) -> str:
    if not pitch_hz:
        return ""
    return "male" if pitch_hz < MALE_BELOW_HZ else "female"


# ---------------------------------------------------------------- เตรียมเสียงในคลัง
def _windows(words: list, lo: float, hi: float, gap: float) -> list[tuple[int, int]]:
    """ช่วงคำติดกัน (i, j) ยาว lo–hi วินาที ที่เริ่มและจบตรงช่วงหยุดอย่างน้อย gap วินาที
    แต่ละจุดเริ่มเอาช่วงที่ยาวที่สุด F5-TTS ได้น้ำเสียงครบกว่าเมื่อเสียงตัวอย่างยาว"""
    n = len(words)
    pause_after = lambda j: j == n - 1 or words[j + 1].start - words[j].end >= gap  # noqa: E731
    out = []
    for i in range(n):
        if i > 0 and words[i].start - words[i - 1].end < gap:
            continue
        best = None
        for j in range(i, n):
            span = words[j].end - words[i].start
            if span > hi:
                break
            if span >= lo and pause_after(j):
                best = j
        if best is not None:
            out.append((i, best))
    return out


def _pick(words: list, vocals: np.ndarray, sr: int) -> tuple[float, float, str]:
    """ท่อนที่ใช้เป็นเสียงตัวอย่าง: ยาวพอและสะอาดที่สุด คืน (เริ่ม, จบ, ข้อความ)"""
    hi = settings.ref_max_sec
    cands = _windows(words, MIN_SEC, hi, 0.2) or _windows(words, MIN_SEC, hi, 0.0)
    if not cands:
        raise RuntimeError(f"ไม่พบช่วงพูดต่อเนื่อง {MIN_SEC:.0f}–{hi:.0f} วินาที ลองใช้คลิปที่พูดยาวกว่านี้")
    span = lambda c: words[c[1]].end - words[c[0]].start  # noqa: E731
    cands = sorted(cands, key=span, reverse=True)[:6]
    if len(cands) > 1 and not settings.mock_pipeline:
        from . import quality
        from .runner import _free_vram
        q = {c: quality.score(vocals[int(words[c[0]].start * sr): int(words[c[1]].end * sr)], sr) for c in cands}
        _free_vram("quality")
        log.info("voice windows: %s", {(round(words[i].start, 1), round(span((i, j)), 1)): round(s, 2)
                                       for (i, j), s in q.items()})
        # ความสะอาดมาก่อน ความยาวช่วยเล็กน้อย (ยาวกว่า 1 วินาที เท่ากับสะอาดกว่า 0.1)
        best = max(cands, key=lambda c: q[c] + 0.1 * span(c))
    else:
        best = cands[0]
    i, j = best
    # เผื่อหัวท้ายไว้ให้ลมหายใจและหางเสียง แต่ไม่ล้ำเข้าคำข้างเคียง
    start = max(0.0, words[i].start - 0.1, words[i - 1].end if i > 0 else 0.0)
    end = words[j].end + 0.2
    if j + 1 < len(words):
        end = min(end, words[j + 1].start)
    text = "".join(w.text for w in words[i: j + 1]).strip()
    return start, end, text


def _normalize(wav: np.ndarray, target_db: float = -20.0, peak: float = 0.95) -> np.ndarray:
    """ปรับความดังเฉลี่ยให้เท่ากันทุกเสียงในคลัง (ไม่ให้เกิน peak)"""
    rms = float(np.sqrt(np.mean(wav ** 2))) if len(wav) else 0.0
    if rms <= 1e-6:
        return wav
    gain = min(10 ** (target_db / 20) / rms, peak / max(float(np.abs(wav).max()), 1e-6))
    return (wav * gain).astype(np.float32)


def prepare(store: VoiceStore, voice_id: str) -> None:
    """ทำความสะอาด ตัดท่อน ถอดข้อความ วัดเสียง สถานะผิดพลาดบันทึกลงเสียงนั้นเอง ไม่โยนต่อ"""
    from . import tts
    from .runner import _free_vram

    v = store.get(voice_id)
    if v is None:  # ถูกลบระหว่างรอคิว
        return
    d = store.dir(voice_id)
    tmp = [d / "audio.wav", d / "vocals.wav", d / "bgm.wav", d / "vocals16k.wav"]
    try:
        src = next(d.glob("original.*"))
        store.update(voice_id, stage="clean")
        raw = tmp[0]
        audio.run(["ffmpeg", "-y", "-i", src, "-vn", "-t", MAX_INPUT_SEC, "-ac", "2", "-ar", 44100,
                   "-c:a", "pcm_s16le", raw])
        if settings.mock_pipeline:
            vocals = raw
        else:
            _free_vram("tts")
            vocals, _ = audio.separate_vocals(raw, d, settings.demucs_model, settings.device)

        store.update(voice_id, stage="transcribe")
        wav16k = audio.to_mono(vocals, tmp[3], 16000)
        clean, sr = sf.read(wav16k, dtype="float32")
        if settings.mock_pipeline:
            from .common import Word
            dur = len(clean) / sr
            words = [Word(0.0, min(dur, 8.0), "สวัสดีครับ นี่คือเสียงตัวอย่างสำหรับทดสอบ", 0)]
        else:
            from .transcribe import transcribe
            words, _ = transcribe(wav16k, "th")
            _free_vram("transcribe")
        if not words:
            raise RuntimeError("ไม่พบเสียงพูดในคลิปนี้")

        store.update(voice_id, stage="trim")
        start, end, text = _pick(words, clean, sr)
        ref = store.ref_path(voice_id)
        audio.cut_clip(vocals, start, end, ref, tts.SAMPLE_RATE)
        wav, rsr = sf.read(ref, dtype="float32")
        wav = _normalize(wav)
        sf.write(ref, wav, rsr)

        store.update(voice_id, stage="measure")
        pitch_hz = _hz(_pitch(wav, rsr))
        q = None
        if not settings.mock_pipeline:
            from . import quality
            q = round(quality.score(wav, rsr), 2)
            _free_vram("quality")
        store.save_embedding(voice_id, _embed(wav, rsr))
        v = store.get(voice_id)
        if v is None:
            return
        store.update(voice_id, status=VoiceStatus.ready, stage="ready", text=text,
                     duration=round(len(wav) / rsr, 2), pitch_hz=pitch_hz, quality=q,
                     gender=v.gender or guess_gender(pitch_hz), error=None)
        log.info("voice %s ready: %.1fs pitch=%s quality=%s text=%r", voice_id, len(wav) / rsr, pitch_hz, q, text)
    except Exception as exc:  # noqa: BLE001
        log.exception("voice %s failed", voice_id)
        store.update(voice_id, status=VoiceStatus.failed, error=str(exc)[:500])
    finally:
        for f in tmp:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------- เสียงของตัวละคร
_profile_lock = threading.Lock()


def speaker_profiles(job_dir: Path, utterances: list[Utterance], per_speaker: int = 8) -> dict[str, Voice]:
    """ลายเสียงและระดับเสียงของแต่ละตัวละคร จากท่อนที่ยาวที่สุดไม่เกิน per_speaker ท่อน
    เก็บผลไว้ใน speaker_voices.json คำนวณใหม่เมื่อป้ายผู้พูดหรือช่วงเวลาเปลี่ยน"""
    key = hashlib.sha1(json.dumps([(u.id, u.speaker, u.start, u.end) for u in utterances]).encode()).hexdigest()
    cache = job_dir / "speaker_voices.json"
    with _profile_lock:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("key") == key:
                return {s: Voice(np.array(p["emb"], dtype=np.float32) if p["emb"] else None,
                                 float("nan") if p["pitch"] is None else p["pitch"])
                        for s, p in data["speakers"].items()}
        except (OSError, ValueError, KeyError):
            pass

        vocals = job_dir / "vocals.wav"
        if not vocals.exists():
            return {}
        sr = sf.info(vocals).samplerate
        out: dict[str, Voice] = {}
        for speaker in sorted({u.speaker for u in utterances}):
            lines = sorted((u for u in utterances if u.speaker == speaker and u.duration >= 1.0),
                           key=lambda u: u.duration, reverse=True)[:per_speaker]
            embs, pitches = [], []
            for u in lines:
                # อ่านเฉพาะช่วงนั้น คลิปยาวทั้งเรื่องโหลดเข้า RAM ทั้งไฟล์ไม่ไหว
                seg, _ = sf.read(vocals, start=int(u.start * sr), stop=int(u.end * sr), dtype="float32")
                seg = seg.mean(axis=1) if seg.ndim > 1 else seg
                e = _embed(seg, sr)
                if e is not None:
                    embs.append(e * u.duration)
                p = _pitch(seg, sr)
                if np.isfinite(p):
                    pitches.append(p)
            emb = None
            if embs:
                s = np.sum(embs, axis=0)
                emb = s / (np.linalg.norm(s) or 1.0)
            out[speaker] = Voice(emb, float(np.median(pitches)) if pitches else float("nan"))
        cache.write_text(json.dumps({"key": key, "speakers": {
            s: {"emb": v.emb.tolist() if v.emb is not None else None,
                "pitch": v.pitch if np.isfinite(v.pitch) else None}
            for s, v in out.items()}}), encoding="utf-8")
        return out


def closeness(speaker: Voice, pitch_hz: Optional[float], emb: Optional[np.ndarray]) -> float:
    """ความใกล้เคียง 0–1: ระดับเสียง 60% (ต่างกัน 4 เซมิโทนได้ราว 0.37) ลายเสียง 40%"""
    gap = abs(speaker.pitch - _semitone(pitch_hz)) if pitch_hz else float("nan")
    p = float(np.exp(-((gap / 4) ** 2))) if np.isfinite(gap) else 0.5
    if speaker.emb is None or emb is None:
        return round(p, 3)
    e = float(np.clip(float(speaker.emb @ emb) / 0.6, 0.0, 1.0))
    return round(0.6 * p + 0.4 * e, 3)
