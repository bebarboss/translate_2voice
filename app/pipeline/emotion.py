"""วัดความตื่นเต้นของแต่ละท่อน และความดังของเสียงพูด

ความตื่นเต้น (arousal) วัดจากลักษณะเสียงที่สัมพันธ์กับอารมณ์ทุกภาษา: ดังขึ้น เสียงสูงขึ้น เสียงแหลมขึ้น (พลังงานย่านสูงมาก)
เทียบกับเสียงปกติของตัวละครคนนั้นเอง (z-score ภายในผู้พูด) ผู้ชายเสียงต่ำที่ตะโกนจึงได้คะแนนสูงได้
ไม่ใช้โมเดลรู้จำอารมณ์ เพราะตัวที่แม่นส่วนใหญ่ห้ามใช้เชิงพาณิชย์
"""
from collections import defaultdict

import numpy as np

FLOOR, CEILING = 75.0, 600.0


def active_db(x: np.ndarray, sr: int) -> float | None:
    """ความดังเฉลี่ยเฉพาะช่วงที่มีเสียง (dBFS) ไม่นับช่วงเงียบระหว่างคำ"""
    hop = int(sr * 0.02)
    f = len(x) // hop
    if f < 5:
        return None
    rms = np.sqrt((x[: f * hop].reshape(f, hop) ** 2).mean(axis=1))
    on = rms[rms > 0.1 * np.percentile(rms, 95)]
    if len(on) == 0 or on.max() <= 1e-5:
        return None
    return float(10 * np.log10(np.mean(on ** 2) + 1e-12))


def _features(seg: np.ndarray, sr: int) -> list[float] | None:
    import librosa
    import parselmouth

    loud = active_db(seg, sr)
    if loud is None or len(seg) < sr * 0.3:
        return None
    f0 = parselmouth.Sound(seg.astype(np.float64), sr).to_pitch(
        time_step=0.01, pitch_floor=FLOOR, pitch_ceiling=CEILING).selected_array["frequency"]
    f0 = f0[f0 > 0]
    pitch = float(12 * np.log2(np.median(f0))) if len(f0) >= 10 else np.nan
    cent = librosa.feature.spectral_centroid(y=seg, sr=sr, hop_length=int(sr * 0.02))[0]
    rms = librosa.feature.rms(y=seg, hop_length=int(sr * 0.02))[0][: len(cent)]
    on = rms > 0.1 * np.percentile(rms, 95)
    bright = float(np.log2(np.median(cent[: len(rms)][on]) + 1)) if on.any() else np.nan
    return [loud, pitch, bright]


def arousal(utts: list, orig: np.ndarray, sr: int) -> dict[int, float]:
    """id → ความตื่นเต้น (0 = ปกติของตัวละครนั้น, +1 = ตื่นเต้นกว่าปกติหนึ่งส่วนเบี่ยงเบน)"""
    feats = {u.id: _features(orig[int(u.start * sr): int(u.end * sr)], sr) for u in utts}
    by_speaker = defaultdict(list)
    for u in utts:
        if feats[u.id] is not None:
            by_speaker[u.speaker].append(u.id)
    every = [i for ids in by_speaker.values() for i in ids]
    out = {u.id: 0.0 for u in utts}
    for ids in by_speaker.values():
        # ตัวละครที่พูดน้อยเกินไปหาค่าปกติไม่ได้ ใช้ค่าปกติของทั้งคลิปแทน
        base = ids if len(ids) >= 4 else every
        if len(base) < 2:
            continue
        m =np.array([feats[i] for i in base], dtype=float)
        mu, sd = np.nanmean(m, axis=0), np.nanstd(m, axis=0) + 1e-6
        for i in ids:
            z = (np.array(feats[i]) - mu) / sd
            out[i] = round(float(np.clip(np.nanmean(z), -3, 3)) if np.isfinite(z).any() else 0.0, 2)
    return out
