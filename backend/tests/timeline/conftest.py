"""ไฟล์ตัวอย่าง: ไทม์ไลน์ในรูปแบบที่ Premiere Pro และ DaVinci Resolve ส่งออก (fixtures/) และไฟล์เสียงสังเคราะห์
ไฟล์เสียงเป็นเสียงแบบ ramp (ค่าของ sample = วินาทีที่อยู่ในไฟล์ ÷ 100) ตรวจได้ว่าตัดตรงจุด source in จริง"""
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

FIXTURES = Path(__file__).parent / "fixtures"


def ramp(path: Path, seconds: float, sr: int = 48000, channels: int = 1) -> Path:
    t = np.arange(round(seconds * sr), dtype=np.float64) / sr / 100
    x = np.stack([t * (c + 1) for c in range(channels)], axis=1) if channels > 1 else t
    sf.write(path, x.astype(np.float32), sr, subtype="FLOAT")
    return path


@pytest.fixture
def premiere(tmp_path: Path) -> Path:
    """โฟลเดอร์โปรเจกต์: ไทม์ไลน์ Premiere + ไฟล์เสียงที่อ้างถึง (ไม่มี camera_a.mp4 ซึ่งเป็นแทร็กภาพ)"""
    base = tmp_path / "premiere" / "timeline"
    (base / "media" / "Audio").mkdir(parents=True)
    shutil.copy(FIXTURES / "premiere_interview.xml", base)
    ramp(base / "media" / "Audio" / "Host_Take1.WAV", 60)  # ชื่อตัวพิมพ์ต่างจากใน XML
    ramp(base / "media" / "Audio" / "guest.wav", 30)
    return base


@pytest.fixture
def resolve_fcpxml(tmp_path: Path) -> Path:
    base = tmp_path / "fcpxml" / "timeline"
    (base / "media").mkdir(parents=True)
    shutil.copy(FIXTURES / "resolve_podcast.fcpxml", base)
    ramp(base / "media" / "anna_mic.wav", 120)
    ramp(base / "media" / "ben_mic.wav", 120)
    return base


@pytest.fixture
def resolve_edl(tmp_path: Path) -> Path:
    base = tmp_path / "edl" / "timeline"
    (base / "media").mkdir(parents=True)
    shutil.copy(FIXTURES / "resolve_scene.edl", base)
    ramp(base / "media" / "mary.wav", 40)
    ramp(base / "media" / "tom.wav", 10)
    return base
