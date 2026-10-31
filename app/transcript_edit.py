"""แก้โครงบท: แยกประโยค รวมประโยค และสร้างเสียงแยกรายตัวละครใหม่หลังย้ายตัวละคร

ใช้ตอนแยกผู้พูดอัตโนมัติผิด เช่น สองคนพูดต่อกันแต่ถูกรวมเป็นท่อนเดียว หรือคนเดียวถูกแตกเป็นสองตัวละคร
"""
from pathlib import Path
from typing import Optional

from .pipeline import pauses
from .pipeline.common import Turn
from .schemas import Utterance

MIN_PART = 0.2  # แต่ละส่วนหลังแยกต้องยาวอย่างน้อยเท่านี้ (วินาที)


def _cut(text: str, fraction: float) -> int:
    """ตำแหน่งตัดใน text ที่ตรงกับสัดส่วนเสียงที่พูดไปแล้ว เลือกเว้นวรรคหรือขอบคำที่ใกล้ที่สุด"""
    text = text.strip()
    target = pauses._position(text, fraction)
    bounds = pauses._bounds(text)
    if not bounds:
        return target
    return min(bounds, key=lambda b: abs(b - target) / max(len(text), 1) + bounds[b])


def split(u: Utterance, new_id: int, at: Optional[float], pos: Optional[int],
          words: Optional[list]) -> tuple[Utterance, Utterance]:
    """แยกประโยค u เป็นสองท่อนที่เวลา at และตัวอักษรที่ pos ของบทพากย์
    ส่งมาอย่างใดอย่างหนึ่งก็ได้ อีกค่าหาจากเวลาของแต่ละคำ (words.json)"""
    own = [w for w in words or [] if u.start - 0.05 <= w.start <= u.end + 0.05]
    target = u.target.strip()
    if at is None:
        if pos is None:
            raise ValueError("ต้องระบุเวลาหรือตำแหน่งที่จะแยก")
        frac = pauses._weight(target[:pos]) / max(pauses._weight(target), 1)
        total = sum(pauses._weight(w.text) for w in own)
        at, seen = u.start + frac * u.duration, 0
        for w in own:  # เริ่มท่อนหลังที่คำแรกซึ่งพูดหลังสัดส่วนนั้น
            if total and seen >= frac * total:
                at = w.start
                break
            seen += pauses._weight(w.text)
    elif own:  # ตัดที่ต้นคำที่ใกล้ที่สุด ไม่ตัดกลางคำ
        inner = [w.start for w in own if u.start + MIN_PART <= w.start <= u.end - MIN_PART]
        if inner:
            at = min(inner, key=lambda s: abs(s - at))
    at = round(at, 3)
    if not (u.start + MIN_PART <= at <= u.end - MIN_PART):
        raise ValueError("จุดแยกต้องอยู่ในประโยค และห่างหัวท้ายอย่างน้อย 0.2 วินาที")

    frac = pauses._spoken_fraction(u, at, words)
    if pos is None:
        pos = _cut(target, frac)
    source = u.source.strip()
    spos = _cut(source, frac)
    first = u.model_copy(update={"end": at, "target": target[:pos].strip(), "source": source[:spos].strip()})
    second = u.model_copy(update={"id": new_id, "start": at, "target": target[pos:].strip(),
                                  "source": source[spos:].strip()})
    return first, second


def merge(a: Utterance, b: Utterance) -> Utterance:
    """รวมท่อน b ต่อท้าย a (ใช้ตัวละครของ a)"""
    def join(x: str, y: str) -> str:
        return " ".join(s for s in (x.strip(), y.strip()) if s)
    return a.model_copy(update={"start": min(a.start, b.start), "end": max(a.end, b.end),
                                "target": join(a.target, b.target), "source": join(a.source, b.source)})


def export_stems(d: Path, utterances: list[Utterance], speakers: list[str]) -> None:
    """สร้างเสียงแยกรายตัวละครใหม่ตามป้ายผู้พูดในบท (หลังผู้ใช้ย้ายประโยคหรือเพิ่มลบตัวละคร)"""
    from .pipeline.diarize import export_speaker_stems, load_turns, save_turns

    vocals = d / "vocals.wav"
    if not vocals.exists():
        return
    # งานเก่าที่ไม่มี turns.json อ่านช่วงพูดจากเสียงแยกรายคน เก็บไว้ก่อนเขียนทับ (ใช้หาช่วงที่พูดซ้อนกัน)
    if not (d / "turns.json").exists():
        save_turns(load_turns(d), d / "turns.json")
    stems = d / "stems"
    for f in stems.glob("speaker_*.wav"):
        if f.stem not in speakers or not any(u.speaker == f.stem for u in utterances):
            f.unlink()
    export_speaker_stems(vocals, [Turn(u.start, u.end, u.speaker) for u in utterances], stems)
