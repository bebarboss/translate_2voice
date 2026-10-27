"""โหมดทดสอบ (MOCK_PIPELINE=1): ทำงานครบทุกขั้นโดยไม่โหลดโมเดล AI

ใช้ทดสอบ API, หน้าเว็บ หรือ flow การตรวจบท บนเครื่องที่ไม่มีการ์ดจอ
แต่ละขั้นหน่วงเวลาเล็กน้อย (MOCK_DELAY วินาที) ให้เห็นความคืบหน้าและลองกดยกเลิกได้
"""
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from ..schemas import Utterance
from .common import Turn, Word
from .translate import estimate_seconds

SAMPLE_RATE = 24000
DELAY = float(os.getenv("MOCK_DELAY", "0.6"))


def _wait() -> None:
    if DELAY > 0:
        time.sleep(DELAY)


def separate_vocals(audio_wav: Path, work_dir: Path, model: str, device: str) -> tuple[Path, Path]:
    _wait()
    vocals, bgm = work_dir / "vocals.wav", work_dir / "bgm.wav"
    shutil.copy(audio_wav, vocals)
    data, sr = sf.read(audio_wav, dtype="float32")
    sf.write(bgm, data * 0.2, sr)
    return vocals, bgm


def diarize(wav16k: Path, num_speakers: Optional[int] = None) -> list[Turn]:
    _wait()
    info = sf.info(wav16k)
    n = num_speakers or 3
    turns, t, i = [], 0.3, 0
    while t + 1.0 < info.duration:
        end = min(t + 2.6, info.duration - 0.2)
        turns.append(Turn(round(t, 3), round(end, 3), f"speaker_{i % n + 1:02d}"))
        t, i = end + 0.4, i + 1
    return turns


def transcribe(wav16k: Path, language: Optional[str] = None) -> tuple[list[Word], str]:
    _wait()
    turns = diarize(wav16k)
    words = []
    for seg, turn in enumerate(turns):
        t = turn.start
        while t + 0.5 <= turn.end:
            words.append(Word(t, t + 0.45, "你好", seg))
            t += 0.5
    return words, language or "zh"


def translate_utterances(utts: list[Utterance], lang: str, target: str = "th",
                         on_progress: Optional[Callable[[float], None]] = None,
                         check_cancel: Optional[Callable[[], None]] = None, title: str = "") -> None:
    for i, u in enumerate(utts):
        if check_cancel:
            check_cancel()
        u.target = f"Test dubbing line {u.id}" if target == "en" else f"บทพากย์ทดสอบประโยคที่ {u.id}"
        if on_progress:
            on_progress((i + 1) / len(utts))
    _wait()


def fit_lengths(utts: list[Utterance], target: str = "th", max_speedup: float = 1.35) -> None:
    return None


def synthesize(ref_audio: Path, ref_text: str, gen_text: str, speed: float = 1.0,
               steps: int = 32, target_lang: str = "th", slot: Optional[float] = None,
               max_speedup: float = 1.35, max_slowdown: float = 1.2) -> np.ndarray:
    time.sleep(DELAY / 4)
    seconds = max(0.4, estimate_seconds(gen_text, target_lang))
    if slot:
        seconds = min(max(slot, seconds / max_speedup), seconds * max_slowdown)
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    freq = 330 + (hash(gen_text) % 200)
    return (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
