"""วางเสียงพากย์ตามเวลา ผสมกับเพลงเดิม รวมกลับเข้าวิดีโอ และทำซับไตเติล"""
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from .audio import run


def _loud_runs(x: np.ndarray, sr: int, level: float = 0.02, min_len: float = 0.2,
               bridge: float = 0.3) -> list[tuple[int, int]]:
    """ช่วงที่มีเสียง (ตำแหน่ง sample) เฟรมละ 50 ms ช่วงที่ห่างกันไม่ถึง bridge วินาทีนับเป็นช่วงเดียว"""
    hop = int(sr * 0.05)
    f = len(x) // hop
    if f == 0:
        return []
    loud = np.append(np.sqrt((x[: f * hop].reshape(f, hop) ** 2).mean(axis=1)) > level, False)
    runs, s = [], None
    for i, v in enumerate(loud):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if runs and (s - runs[-1][1]) * 0.05 < bridge:
                runs[-1] = (runs[-1][0], i)
            else:
                runs.append((s, i))
            s = None
    return [(a * hop, b * hop) for a, b in runs if (b - a) * 0.05 >= min_len]


def minus(spans: list[tuple[float, float]], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """ช่วงเวลา spans ที่เจาะ holes ออก"""
    out = []
    for a, b in spans:
        cur = [(a, b)]
        for ha, hb in holes:
            cur = [piece for x, y in cur
                   for piece in ([(x, y)] if hb <= x or ha >= y else [(x, ha), (hb, y)]) if piece[1] > piece[0]]
        out += cur
    return out


def nonspeech(orig: np.ndarray, orig_sr: int, speech: list[tuple[float, float]], total_sec: float, sr: int,
              is_speech: Optional[Callable[[np.ndarray, int], bool]] = None,
              pad: float = 0.15, ramp: float = 0.05) -> np.ndarray:
    """เสียงจากแทร็กเสียงพูดต้นฉบับเฉพาะช่วงที่ไม่มีบท (กรี๊ด ร้อง อุทาน หอบ หัวเราะ)

    Whisper ถอดเฉพาะคำพูด เสียงพวกนี้จึงไม่มีในบทและหายไปจากเสียงพากย์ทั้งหมด
    เก็บเสียงเดิมไว้ทุกช่วง ยกเว้นช่วงที่มีบทหรือมีเสียงพากย์ (เผื่อขอบ pad วินาที เฟดเข้าออก ramp วินาที)
    is_speech(เสียง, sr): ตรวจซ้ำว่าช่วงที่เหลือเป็นคำพูดที่ถอดตกไปหรือไม่ ถ้าใช่ก็ไม่ใส่ กันภาษาต้นฉบับโผล่
    """
    import librosa

    n = int(total_sec * sr)
    out = np.zeros(n, dtype=np.float32)
    if len(orig) == 0:
        return out
    track = librosa.resample(np.asarray(orig, dtype=np.float32), orig_sr=orig_sr, target_sr=sr)[:n]
    keep = np.ones(n, dtype=np.float32)
    for a, b in speech:
        keep[max(0, int((a - pad) * sr)): max(0, int((b + pad) * sr))] = 0
    if is_speech:
        p = int(pad * sr)
        for a, b in _loud_runs(track * keep[: len(track)], sr):
            if is_speech(track[a:b], sr):
                keep[max(0, a - p): b + p] = 0
    k = max(1, int(ramp * sr))
    keep = np.convolve(keep, np.ones(k, dtype=np.float32) / k, mode="same")
    out[: len(track)] = track * keep[: len(track)]
    return out


def match_loudness(clips: list[tuple[float, np.ndarray]], spans: list[tuple[float, float]], sr: int,
                   orig: np.ndarray, orig_sr: int, follow: bool = True, max_boost: float = 6.0,
                   max_cut: float = 10.0) -> list[tuple[float, np.ndarray]]:
    """ปรับความดังเสียงพากย์ให้เท่าเสียงพูดต้นฉบับ

    ระดับรวม: ให้ค่ากลางเท่าเสียงพูดต้นฉบับ (เสียงพากย์ดิบดังกว่าราว 5 dB จึงลอยอยู่บนดนตรี)
    follow: ปรับแต่ละประโยคให้ขึ้นลงตามนักแสดงด้วย (ตะโกนดัง กระซิบเบา)
    F5-TTS ให้เสียงดังพอ ๆ กันทุกประโยค จึงวัดว่าแต่ละประโยคของต้นฉบับดังหรือเบากว่าค่ากลางของทั้งคลิปกี่ dB
    """
    from .emotion import active_db

    src = [active_db(orig[int(a * orig_sr): int(b * orig_sr)], orig_sr) for a, b in spans]
    dub = [active_db(v, sr) for _, v in clips]
    ok = [i for i in range(len(clips)) if src[i] is not None and dub[i] is not None]
    if len(ok) < 3:
        return clips
    src_mid = float(np.median([src[i] for i in ok]))
    dub_mid = float(np.median([dub[i] for i in ok]))
    out = list(clips)
    for i in ok:
        if follow:
            gain = src_mid + float(np.clip(src[i] - src_mid, -max_cut, max_boost)) - dub[i]
        else:
            gain = src_mid - dub_mid
        v = clips[i][1] * 10 ** (gain / 20)
        peak = float(np.abs(v).max())
        if peak > 0.98:  # ดังจนแตก → ลดลงพอดีขอบ (ตัวจำกัดความดังตอนผสมจะช่วยอีกชั้น)
            v *= 0.98 / peak
        out[i] = (clips[i][0], v.astype(np.float32))
    return out


def room(track: np.ndarray, sr: int, wet: float = 0.2, rt60: float = 0.4, seed: int = 0) -> np.ndarray:
    """ใส่เสียงก้องของห้องแบบสเตอริโอ คืนเสียง 2 ช่อง (n, 2)

    TTS ให้เสียงแห้งเหมือนอัดในห้องเก็บเสียง ส่วนเสียงพูดในหนังมีเสียงก้องของฉากติดมา เสียงพากย์จึงฟังลอยไม่เข้ากับฉาก
    สร้างเสียงก้องจากสัญญาณสุ่มที่ค่อย ๆ จางลง (rt60 วินาทีจางไป 60 dB) ซ้ายขวาไม่เหมือนกัน เสียงจึงกว้างแบบห้องจริง
    ตัดย่านเสียงสูงของหางเสียงก้องลง เพราะผนังห้องดูดเสียงแหลมมากกว่าเสียงทุ้ม
    """
    from scipy.signal import fftconvolve, lfilter

    dry = np.stack([track, track], axis=1)
    if wet <= 0 or len(track) == 0:
        return dry
    rng = np.random.default_rng(seed)
    n = int(sr * rt60 * 1.2)
    t = np.arange(n) / sr
    decay = 10 ** (-3 * t / rt60)  # -60 dB ที่ rt60
    pre = int(sr * 0.012)  # เสียงสะท้อนแรกมาหลังเสียงตรงเล็กน้อย
    out = np.empty_like(dry)
    for ch in range(2):
        ir = rng.standard_normal(n) * decay
        ir = lfilter([0.6], [1, -0.4], ir)  # low-pass ขั้นเดียว ราว 3.5 kHz ที่ 24 kHz
        ir = np.concatenate([np.zeros(pre), ir])
        ir /= np.sqrt(np.sum(ir ** 2))
        out[:, ch] = track + wet * fftconvolve(track, ir)[: len(track)]
    return out.astype(np.float32)


def place_clips(clips: list[tuple[float, np.ndarray]], total_sec: float, sr: int, out_wav: Path,
                bed: Optional[np.ndarray] = None, reverb: float = 0.0, rt60: float = 0.4) -> Path:
    """bed: เสียงที่ปูไว้ใต้เสียงพากย์ (เสียงร้องหรืออุทานของต้นฉบับ ซึ่งมีเสียงก้องของฉากอยู่แล้ว)
    reverb: ความดังเสียงก้องที่ใส่ให้เสียงพากย์ (0 = ไม่ใส่)"""
    n = int(total_sec * sr)
    track = np.zeros(n + sr, dtype=np.float32)
    for start, audio in clips:
        a = int(start * sr)
        b = min(len(track), a + len(audio))
        if b > a:
            track[a:b] += audio[: b - a]
    out = room(track, sr, reverb, rt60)[:n]
    if bed is not None:
        out[: len(bed)] += bed[: len(out), None]
    sf.write(out_wav, np.clip(out, -1.0, 1.0), sr)
    return out_wav


def mix_tracks(voice_wav: Path, bgm_wav: Optional[Path], out_wav: Path,
               voice_gain: float = 1.0, bgm_gain: float = 1.0) -> Path:
    voice = f"[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={voice_gain}[v]"
    if bgm_wav and bgm_wav.exists():
        graph = (f"{voice};[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={bgm_gain}[b];"
                 "[v][b]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[out]")
        run(["ffmpeg", "-y", "-i", voice_wav, "-i", bgm_wav, "-filter_complex", graph,
             "-map", "[out]", "-c:a", "pcm_s16le", out_wav])
    else:
        run(["ffmpeg", "-y", "-i", voice_wav, "-filter_complex", voice.replace("[v]", "[out]"),
             "-map", "[out]", "-c:a", "pcm_s16le", out_wav])
    return out_wav


def mux_video(video: Path, audio_wav: Path, out_mp4: Path) -> Path:
    base = ["ffmpeg", "-y", "-i", video, "-i", audio_wav, "-map", "0:v:0", "-map", "1:a:0"]
    tail = ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4]
    reencode = base + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"] + tail
    # มือถือ (โดยเฉพาะ iPhone) เล่น VP9/AV1 ใน mp4 ไม่ได้ ก๊อปตรง ๆ ได้เฉพาะ H.264 8 บิต
    probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,pix_fmt", "-of", "csv=p=0", video])
    if probe.strip().split("\n")[0].split(",")[:2] != ["h264", "yuv420p"]:
        run(reencode)
        return out_mp4
    try:
        run(base + ["-c:v", "copy"] + tail)
    except RuntimeError:  # ถ้าวิดีโอต้นฉบับใส่ใน mp4 ตรง ๆ ไม่ได้ ให้เข้ารหัสใหม่
        run(reencode)
    return out_mp4
