"""ชนิดข้อมูลกลางที่ใช้ร่วมกันระหว่างแต่ละขั้น"""
from dataclasses import dataclass


@dataclass
class Turn:
    """ช่วงเวลาที่ผู้พูดคนหนึ่งพูด ได้จาก pyannote"""
    start: float
    end: float
    speaker: str


@dataclass
class Word:
    """คำหนึ่งคำจาก Whisper พร้อมเวลา"""
    start: float
    end: float
    text: str
    segment: int


def rename_speakers(turns: list[Turn]) -> list[Turn]:
    """เปลี่ยนชื่อผู้พูดเป็น speaker_01, speaker_02 ... ตามลำดับที่โผล่มาก่อน"""
    mapping: dict[str, str] = {}
    for t in sorted(turns, key=lambda t: t.start):
        if t.speaker not in mapping:
            mapping[t.speaker] = f"speaker_{len(mapping) + 1:02d}"
    return [Turn(t.start, t.end, mapping[t.speaker]) for t in turns]
