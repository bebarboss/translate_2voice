"""กู้ประโยคที่พูดซ้อนกัน: ช่วงที่สองคนพูดพร้อมกัน Whisper มักถอดได้แค่เสียงที่ดังกว่า อีกคนหายไปจากบท

ช่วงที่ pyannote บอกว่ามีคนพูดพร้อมกันแต่บทมีแค่ประโยคของคนเดียว → แยกเสียงช่วงนั้นเป็นสองเสียง (SepFormer)
ถอดเสียงทั้งสอง เสียงที่ข้อความไม่ตรงกับบทที่มีอยู่คือคนที่หายไป เพิ่มเป็นประโยคใหม่ของคนนั้น (เวลาซ้อนกับอีกคน)
ประโยคใหม่ถูกแปลและพากย์แยกเหมือนประโยคอื่น เสียงพากย์จะเล่นซ้อนกันตามต้นฉบับ
"""
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import settings
from ..schemas import Utterance
from .common import Turn, Word

log = logging.getLogger("dubbing.overlap")

MODEL = "speechbrain/sepformer-whamr16k"  # แยกสองเสียง 16 kHz ฝึกกับเสียงที่มีเสียงรบกวนและเสียงก้อง (Apache-2.0)
SR = 16000
STEP = 0.05
MIN_SEC = 0.5  # ช่วงซ้อนที่สั้นกว่านี้มักเป็นแค่เสียงรับคำ ไม่คุ้มแยก
PAD = 0.3

_model = None


def _load():
    global _model
    if _model is None:
        from speechbrain.inference.separation import SepformerSeparation

        home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache") / "speechbrain" / MODEL.split("/")[-1]
        _model = SepformerSeparation.from_hparams(source=MODEL, savedir=str(home), run_opts={"device": settings.device})
    return _model


def unload() -> None:
    global _model
    _model = None


def regions(turns: list[Turn], min_sec: float = MIN_SEC) -> list[tuple[float, float, list[str]]]:
    """ช่วงที่มีคนพูดพร้อมกันตั้งแต่สองคน → (เริ่ม, จบ, ผู้พูดในช่วงนั้นเรียงจากพูดนานสุด)"""
    if not turns:
        return []
    end = max(t.end for t in turns)
    grid = np.arange(0, end, STEP)
    names = sorted({t.speaker for t in turns})
    active = np.zeros((len(names), len(grid)), dtype=bool)
    for t in turns:
        active[names.index(t.speaker)] |= (grid >= t.start) & (grid < t.end)
    both = np.append(active.sum(axis=0) >= 2, False)
    runs, start = [], None
    for i, on in enumerate(both):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if runs and (start - runs[-1][1]) * STEP < 0.3:  # เว้นช่วงสั้น ๆ ถือเป็นช่วงซ้อนเดียวกัน
                runs[-1] = (runs[-1][0], i)
            else:
                runs.append((start, i))
            start = None
    out = []
    for i, j in runs:
        if (j - i) * STEP < min_sec:
            continue
        talk = active[:, i:j].sum(axis=1)
        who = [names[k] for k in np.argsort(-talk) if talk[k] * STEP >= 0.3]
        out.append((round(float(grid[i]), 3), round(float(grid[j - 1]) + STEP, 3), who))
    return out


def _plain(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def _similar(a: str, b: str) -> float:
    a, b = _plain(a), _plain(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def recover(wav: np.ndarray, turns: list[Turn], utterances: list[Utterance], words: list[Word],
            lang: Optional[str]) -> list[Utterance]:
    """ประโยคใหม่ของคนที่ถูกกลบในช่วงพูดซ้อน (ผู้พูดเป็นป้ายของ pyannote ใน turns, id = 0 ให้ผู้เรียกเรียงเลขใหม่)"""
    import torch

    from .transcribe import clip_text

    found: list[Utterance] = []
    for start, end, who in regions(turns):
        if len(who) < 2:
            continue
        covered = {u.speaker for u in utterances if min(u.end, end) - max(u.start, start) > 0.2 * (end - start)}
        missing = [s for s in who if s not in covered]
        if not missing or not covered:
            continue
        speaker = missing[0]
        a, b = max(0.0, start - PAD), end + PAD
        seg = wav[int(a * SR): int(b * SR)]
        if len(seg) < SR * MIN_SEC:
            continue
        with torch.no_grad():
            est = _load().separate_batch(torch.from_numpy(seg.astype(np.float32))[None].to(settings.device))
        sources = [est[0, :, k].detach().cpu().numpy() for k in range(est.shape[-1])]
        level = [float(np.sqrt(np.mean(s ** 2))) for s in sources]
        existing = " ".join(w.text for w in words if w.end > a and w.start < b)
        texts = [clip_text((s / (np.abs(s).max() + 1e-9) * 0.9).astype(np.float32), lang) for s in sources]
        sims = [_similar(t, existing) for t in texts]
        k = int(np.argmin(sims))
        text = texts[k].strip()
        # เสียงที่แยกได้ต้องดังพอ ข้อความต้องต่างจากบทเดิมชัด ๆ และอีกเสียงต้องตรงกับบทเดิมมากกว่า
        if len(_plain(text)) < 2 or level[k] < 0.15 * max(level) or sims[k] > 0.5 or sims[k] >= max(sims):
            log.info("overlap %.2f-%.2f: skip (%r sims=%s)", start, end, text, [round(s, 2) for s in sims])
            continue
        spans = [(max(t.start, a), min(t.end, b)) for t in turns if t.speaker == speaker and t.end > a and t.start < b]
        s0, s1 = (min(x for x, _ in spans), max(y for _, y in spans)) if spans else (start, end)
        log.info("overlap %.2f-%.2f: %s says %r", s0, s1, speaker, text)
        found.append(Utterance(id=0, speaker=speaker, start=round(s0, 3), end=round(s1, 3), source=text))
    return found


def map_speakers(lines: list[Utterance], turns: list[Turn], final: list[Utterance]) -> list[Utterance]:
    """ป้ายผู้พูดของ pyannote → ชื่อผู้พูดหลังจัดกลุ่มใหม่ (ดูว่าช่วงพูดของป้ายนั้นทับกับประโยคของใครนานสุด)
    คนที่พูดแต่ตอนซ้อนกับคนอื่น (ไม่มีประโยคของตัวเองเลย) ได้ชื่อใหม่
    ตัดประโยคที่กลายเป็นคนเดียวกับประโยคที่ซ้อนอยู่ (ไม่ใช่สองคนพูดพร้อมกันจริง)"""
    names = {u.speaker for u in final}
    fresh: dict[str, str] = {}
    out = []
    for line in lines:
        under = [u for u in final if min(u.end, line.end) - max(u.start, line.start) > 0]
        votes: dict[str, float] = {}
        for t in turns:
            if t.speaker != line.speaker:
                continue
            for u in final:
                d = min(t.end, u.end) - max(t.start, u.start)
                if d > 0 and u not in under:  # ไม่นับประโยคที่ซ้อนอยู่ ตรงนั้นเป็นเสียงของอีกคน
                    votes[u.speaker] = votes.get(u.speaker, 0.0) + d
        if votes:
            speaker = max(votes, key=votes.get)
        else:
            if line.speaker not in fresh:
                n = len(names) + 1
                while f"speaker_{n:02d}" in names:
                    n += 1
                fresh[line.speaker] = f"speaker_{n:02d}"
                names.add(fresh[line.speaker])
            speaker = fresh[line.speaker]
        if speaker in {u.speaker for u in under}:
            continue
        out.append(line.model_copy(update={"speaker": speaker}))
    return out
