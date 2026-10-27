"""แยกว่าใครพูดตอนไหน (pyannote) และส่งออกเลเยอร์เสียงของแต่ละคน"""
import json
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ..config import settings
from .common import Turn, rename_speakers

_pipeline = None


def _load():
    global _pipeline
    if _pipeline is None:
        import torch
        from pyannote.audio import Pipeline

        if not settings.hf_token:
            raise RuntimeError("ต้องตั้งค่า HF_TOKEN และกดยอมรับเงื่อนไขโมเดล pyannote บน Hugging Face ก่อน")
        try:  # pyannote 4.x
            pipe = Pipeline.from_pretrained(settings.diarization_model, token=settings.hf_token)
        except TypeError:  # pyannote 3.x
            pipe = Pipeline.from_pretrained(settings.diarization_model, use_auth_token=settings.hf_token)
        if pipe is None:
            raise RuntimeError(f"โหลด {settings.diarization_model} ไม่ได้ ตรวจว่ากดยอมรับเงื่อนไขบน Hugging Face แล้ว")
        if settings.device.startswith("cuda") and torch.cuda.is_available():
            pipe.to(torch.device(settings.device))
        _pipeline = pipe
    return _pipeline


def unload() -> None:
    global _pipeline
    _pipeline = None


def diarize(wav16k: Path, num_speakers: Optional[int] = None) -> list[Turn]:
    import torch

    pipe = _load()
    audio, sr = sf.read(wav16k, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    data = {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": sr}
    kwargs = {"num_speakers": num_speakers} if num_speakers else {}
    output = pipe(data, **kwargs)
    annotation = getattr(output, "speaker_diarization", output)  # 4.x คืนเป็น object
    turns = [Turn(round(seg.start, 3), round(seg.end, 3), str(label))
             for seg, _, label in annotation.itertracks(yield_label=True)]
    if not turns:
        raise RuntimeError("ไม่พบเสียงพูดในคลิป")
    return rename_speakers(turns)


def save_turns(turns: list[Turn], path: Path) -> None:
    path.write_text(json.dumps([t.__dict__ for t in turns]), encoding="utf-8")


def load_turns(job_dir: Path) -> list[Turn]:
    """ช่วงพูดของแต่ละคน งานเก่าที่ไม่ได้เก็บไว้ อ่านจากไฟล์เสียงแยกรายคน (ช่วงที่คนอื่นพูดเงียบ)"""
    path = job_dir / "turns.json"
    if path.exists():
        return [Turn(**t) for t in json.loads(path.read_text(encoding="utf-8"))]
    turns: list[Turn] = []
    for stem in sorted((job_dir / "stems").glob("speaker_*.wav")):
        audio, sr = sf.read(stem, dtype="float32", always_2d=True)
        hop = sr // 20
        n = len(audio) // hop
        on = np.append(np.abs(audio[: n * hop]).max(axis=1).reshape(n, hop).max(axis=1) > 1e-5, False)
        start = None
        for i, v in enumerate(on):
            if v and start is None:
                start = i
            elif not v and start is not None:
                turns.append(Turn(round(start * 0.05, 3), round(i * 0.05, 3), stem.stem))
                start = None
    return sorted(turns, key=lambda t: t.start)


def overlap_ratio(start: float, end: float, turns: list[Turn]) -> float:
    """สัดส่วนเวลาในช่วงนี้ที่มีคนพูดพร้อมกันตั้งแต่สองคนขึ้นไป"""
    if end <= start:
        return 0.0
    t = np.arange(start, end, 0.05)
    active = np.zeros(len(t), dtype=int)
    for tr in turns:
        if tr.end > start and tr.start < end:
            active += (t >= tr.start) & (t < tr.end)
    return float(np.mean(active >= 2))


def export_speaker_stems(vocals_wav: Path, turns: list[Turn], out_dir: Path) -> dict[str, Path]:
    """สร้างไฟล์เสียงแยกของแต่ละคน ยาวเท่าคลิปเดิม ช่วงที่คนอื่นพูดจะเงียบ"""
    out_dir.mkdir(parents=True, exist_ok=True)
    audio, sr = sf.read(vocals_wav, dtype="float32", always_2d=True)
    fade_n = int(sr * 0.02)
    result: dict[str, Path] = {}
    for speaker in sorted({t.speaker for t in turns}):
        mask = np.zeros(len(audio), dtype=np.float32)
        for t in (t for t in turns if t.speaker == speaker):
            a, b = int(t.start * sr), min(len(audio), int(t.end * sr))
            if b <= a:
                continue
            seg = np.ones(b - a, dtype=np.float32)
            n = min(fade_n, (b - a) // 2)
            if n:
                seg[:n] = np.linspace(0, 1, n)
                seg[-n:] = np.linspace(1, 0, n)
            mask[a:b] = np.maximum(mask[a:b], seg)
        path = out_dir / f"{speaker}.wav"
        sf.write(path, audio * mask[:, None], sr)
        result[speaker] = path
    return result
