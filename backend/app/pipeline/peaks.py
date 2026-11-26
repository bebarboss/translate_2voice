"""ยอดคลื่นเสียง (waveform) ของไฟล์ wav สำหรับวาดบนเส้นเวลา — อ่านทีละช่วง ไม่โหลดทั้งไฟล์เข้าหน่วยความจำ"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

MIN_BUCKETS, MAX_BUCKETS = 50, 4000


def compute_peaks(path: Path, buckets: int = 1500) -> dict:
    """คืน {duration, peaks} peaks = ค่าสูงสุดของแต่ละช่วง (0–100, ปัดเป็นจำนวนเต็ม) ช่วงละ duration/buckets วินาที"""
    n = min(max(int(buckets), MIN_BUCKETS), MAX_BUCKETS)
    with sf.SoundFile(str(path)) as f:
        total, rate = len(f), f.samplerate
        if total <= 0 or rate <= 0:
            return {"duration": 0.0, "peaks": []}
        n = min(n, total)
        edges = [total * i // n for i in range(n + 1)]
        out: list[int] = []
        for i in range(n):
            size = edges[i + 1] - edges[i]
            block = f.read(size, dtype="float32", always_2d=True)
            out.append(int(round(min(1.0, float(np.abs(block).max())) * 100)) if block.size else 0)
    return {"duration": round(total / rate, 3), "peaks": out}


@lru_cache(maxsize=64)
def _cached(path: str, mtime_ns: int, buckets: int) -> dict:
    return compute_peaks(Path(path), buckets)


def peaks_for(path: Path, buckets: int = 1500) -> dict:
    """เหมือน compute_peaks แต่จำผลไว้ (คีย์ตามเวลาแก้ไฟล์ พากย์ใหม่แล้วคำนวณใหม่)"""
    return _cached(str(path), path.stat().st_mtime_ns, min(max(int(buckets), MIN_BUCKETS), MAX_BUCKETS))
