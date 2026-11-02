"""แยกว่าใครพูดตอนไหน (pyannote) และส่งออกเลเยอร์เสียงของแต่ละคน"""
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ..config import settings
from .common import Turn, rename_speakers

log = logging.getLogger("dubbing.diarize")

_pipeline = None
FALLBACK_MODEL = "pyannote/speaker-diarization-3.1"


def _from_pretrained(name: str):
    from pyannote.audio import Pipeline

    try:  # pyannote 4.x
        return Pipeline.from_pretrained(name, token=settings.hf_token)
    except TypeError:  # pyannote 3.x
        return Pipeline.from_pretrained(name, use_auth_token=settings.hf_token)


def _load():
    global _pipeline
    if _pipeline is None:
        import torch

        if not settings.hf_token:
            raise RuntimeError("ต้องตั้งค่า HF_TOKEN และกดยอมรับเงื่อนไขโมเดล pyannote บน Hugging Face ก่อน")
        names = list(dict.fromkeys([settings.diarization_model, FALLBACK_MODEL]))
        pipe = None
        for name in names:
            try:  # community-1 ต้องใช้ pyannote 4 และกดยอมรับเงื่อนไขของโมเดลนั้นแยกต่างหาก
                pipe = _from_pretrained(name)
            except Exception as exc:  # noqa: BLE001
                if name == names[-1]:
                    raise
                log.warning("load %s failed (%s), trying %s", name, exc, names[-1])
            if pipe is not None:
                log.info("diarization model: %s", name)
                break
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
    return diarize_both(wav16k, num_speakers)[0]


def diarize_both(wav16k: Path, num_speakers: Optional[int] = None) -> tuple[list[Turn], list[Turn]]:
    """(ช่วงพูดที่ซ้อนกันได้, ช่วงพูดแบบ exclusive ที่ทุกขณะมีคนพูดคนเดียว) ชื่อผู้พูดตรงกันทั้งสองชุด

    ชุด exclusive (pyannote 4 community-1) ทำมาให้จับคู่กับเวลาคำของ Whisper: ตอนพูดซ้อนเลือกคนที่น่าจะพูดจริง
    แทนการเดาเอาคนที่ช่วงสั้นกว่า ทดลองกับโดราเอมอนและ MrBeast ตัดกลางวลีน้อยลง
    ชุดที่ซ้อนกันได้ยังต้องใช้หาช่วงพูดพร้อมกัน (overlap.recover) โมเดลรุ่นเก่าไม่มีชุด exclusive ใช้ชุดเดิมแทน"""
    import torch

    pipe = _load()
    audio, sr = sf.read(wav16k, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    data = {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": sr}
    kwargs = {"num_speakers": num_speakers} if num_speakers else {}
    output = pipe(data, **kwargs)
    annotation = getattr(output, "speaker_diarization", output)  # 4.x คืนเป็น object
    exclusive = getattr(output, "exclusive_speaker_diarization", None) if settings.diar_exclusive else None

    def turns_of(ann) -> list[Turn]:
        return [Turn(round(seg.start, 3), round(seg.end, 3), str(label))
                for seg, _, label in ann.itertracks(yield_label=True)]

    turns = turns_of(annotation)
    if not turns:
        raise RuntimeError("ไม่พบเสียงพูดในคลิป")
    renamed = rename_speakers(turns)
    names = {t.speaker: r.speaker for t, r in zip(turns, renamed)}
    only = [Turn(t.start, t.end, names.get(t.speaker, t.speaker)) for t in turns_of(exclusive)] if exclusive else []
    return renamed, only or renamed


def relabel_turns(turns: list[Turn], utts: list) -> list[Turn]:
    """ตั้งชื่อผู้พูดของช่วงพูดตามประโยคที่จัดกลุ่มใหม่ (voices.cluster_lines)
    ช่วงพูดที่คร่อมหลายประโยคต่างคนกันถูกตัดตรงรอยต่อประโยค ช่วงที่ไม่มีประโยคทับเลยใช้ประโยคที่ใกล้ที่สุด"""
    if not utts:
        return turns
    out = []
    for t in turns:
        inside = sorted((u for u in utts if min(t.end, u.end) - max(t.start, u.start) > 0), key=lambda u: u.start)
        if not inside:
            near = min(utts, key=lambda u: abs((u.start + u.end) - (t.start + t.end)))
            out.append(Turn(t.start, t.end, near.speaker))
            continue
        cur = t.start
        for k, u in enumerate(inside):
            end = t.end if k == len(inside) - 1 else max(cur, min(t.end, inside[k + 1].start))
            if end > cur:
                if out and out[-1].speaker == u.speaker and abs(out[-1].end - cur) < 1e-6:
                    out[-1] = Turn(out[-1].start, end, u.speaker)
                else:
                    out.append(Turn(round(cur, 3), round(end, 3), u.speaker))
            cur = end
    return out


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
