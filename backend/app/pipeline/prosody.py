"""ปรับระดับและการขึ้นลงของเสียงพากย์ให้ตามต้นฉบับ (Praat PSOLA ผ่าน parselmouth)

F5-TTS ภาษาไทยเทรนจากเสียงอ่าน พอเจอฉากตะคอกหรือร้องไห้ เสียงพากย์จะต่ำและเรียบกว่าต้นฉบับมาก
จึงเลื่อนระดับเสียงเฉลี่ยไปหาต้นฉบับ และขยายช่วงขึ้นลงตามความเข้มอารมณ์ของต้นฉบับ
ขยายรอบค่ากลางของเสียงพากย์เอง รูปวรรณยุกต์ไทยจึงยังอยู่ แค่ชัดขึ้นหรือเบาลง ไม่ได้ลอกทำนองภาษาต้นฉบับมาทับ
"""
import logging

import numpy as np

log = logging.getLogger("dubbing.prosody")

FLOOR, CEILING = 75.0, 600.0


def _pitch_stats(f0: np.ndarray) -> tuple[float, float] | None:
    """คืน (log2 ค่ากลาง, ส่วนเบี่ยงเบนเป็นเซมิโทน) ของเฟรมที่มีเสียง"""
    f0 = f0[f0 > 0]
    if len(f0) < 10:
        return None
    med = float(np.median(np.log2(f0)))
    return med, float(np.std(12 * (np.log2(f0) - med)))


def match(dub: np.ndarray, sr: int, orig: np.ndarray, orig_sr: int,
          max_shift: float = 4.0, max_range: float = 1.6) -> np.ndarray:
    """dub: เสียงพากย์, orig: เสียงต้นฉบับช่วงเดียวกัน
    max_shift: เลื่อนระดับเสียงได้มากสุดกี่เซมิโทน, max_range: ขยายช่วงขึ้นลงได้มากสุดกี่เท่า"""
    import parselmouth
    from parselmouth.praat import call

    if len(dub) < sr * 0.3 or len(orig) < orig_sr * 0.3:
        return dub
    o = _pitch_stats(parselmouth.Sound(orig.astype(np.float64), orig_sr)
                     .to_pitch(time_step=0.01, pitch_floor=FLOOR, pitch_ceiling=CEILING).selected_array["frequency"])
    sound = parselmouth.Sound(dub.astype(np.float64), sr)
    d = _pitch_stats(sound.to_pitch(time_step=0.01, pitch_floor=FLOOR, pitch_ceiling=CEILING)
                     .selected_array["frequency"])
    if o is None or d is None or d[1] < 0.1:
        return dub
    shift = float(np.clip(12 * (o[0] - d[0]), -max_shift, max_shift))
    k = float(np.clip(o[1] / d[1], 1 / max_range, max_range))
    if abs(shift) < 0.3 and abs(k - 1) < 0.05:
        return dub

    manip = call(sound, "To Manipulation", 0.01, FLOOR, CEILING)
    tier = call(manip, "Extract pitch tier")
    call(tier, "Formula", f"2^({d[0]} + (log2(self) - {d[0]}) * {k} + {shift} / 12)")
    call([tier, manip], "Replace pitch tier")
    out = call(manip, "Get resynthesis (overlap-add)").values[0].astype(np.float32)
    log.debug("prosody shift %.1f st, range x%.2f", shift, k)
    # PSOLA อาจทำให้ยอดเสียงเกินเล็กน้อย คงความดังเดิมไว้
    peak = float(np.abs(out).max())
    return out * min(1.0, float(np.abs(dub).max()) / peak) if peak > 0 else dub
