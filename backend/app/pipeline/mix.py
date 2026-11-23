"""วางเสียงพากย์ตามเวลา ผสมกับเพลงเดิม รวมกลับเข้าวิดีโอ และทำซับไตเติล"""
import json
import logging
import math
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from .. import audio_constants as ac
from .audio import h264_video_args, run

log = logging.getLogger("dubbing.mix")


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


def room(track: np.ndarray, sr: int, wet: float = ac.ROOM_REVERB, rt60: float = ac.ROOM_RT60, seed: int = 0,
         width: float = ac.ROOM_WIDTH) -> np.ndarray:
    """ใส่เสียงก้องของห้องแบบสเตอริโอ คืนเสียง 2 ช่อง (n, 2)

    TTS ให้เสียงแห้งเหมือนอัดในห้องเก็บเสียง ส่วนเสียงพูดในหนังมีเสียงก้องของฉากติดมา เสียงพากย์จึงฟังลอยไม่เข้ากับฉาก
    สร้างเสียงก้องจากสัญญาณสุ่มที่ค่อย ๆ จางลง (rt60 วินาทีจางไป 60 dB)
    width: สัดส่วนหางเสียงก้องที่ซ้าย/ขวาต่างกัน (0 = เหมือนกัน เสียงอยู่กลาง, 1 = ต่างกันทั้งหมดแบบเดิม)
    ค่าเริ่มต้นใส่บาง ๆ (wet ต่ำ หางสั้น กว้างเล็กน้อย): F5-TTS โคลนก้องจาก ref มาแล้ว ใส่มากจะขุ่นและเสียงพูดไม่อยู่กลาง
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
    w = float(np.clip(width, 0.0, 1.0))
    common = rng.standard_normal(n)
    out = np.empty_like(dry)
    for ch in range(2):
        noise = np.sqrt(1 - w * w) * common + w * rng.standard_normal(n)
        ir = noise * decay
        ir = lfilter([0.6], [1, -0.4], ir)  # low-pass ขั้นเดียว ราว 3.5 kHz ที่ 24 kHz
        ir = np.concatenate([np.zeros(pre), ir])
        ir /= np.sqrt(np.sum(ir ** 2))
        out[:, ch] = track + wet * fftconvolve(track, ir)[: len(track)]
    return out.astype(np.float32)


def place_clips(clips: list[tuple[float, np.ndarray]], total_sec: float, sr: int, out_wav: Path,
                bed: Optional[np.ndarray] = None, reverb: float = 0.0, rt60: float = ac.ROOM_RT60,
                gain: float = 1.0, width: float = ac.ROOM_WIDTH) -> Path:
    """bed: เสียงที่ปูไว้ใต้เสียงพากย์ (เสียงร้องหรืออุทานของต้นฉบับ ซึ่งมีเสียงก้องของฉากอยู่แล้ว)
    reverb: ความดังเสียงก้องที่ใส่ให้เสียงพากย์ (0 = ไม่ใส่) width: ความกว้างซ้ายขวาของหางเสียงก้อง (ดู room)
    gain: ระดับเสียงพากย์ (voice_gain) คูณก่อนเขียนไฟล์

    เขียนเป็น WAV float32 และไม่ตัดที่ ±1: เสียงก้อง เสียง bed และประโยคที่ซ้อนกันทำให้ peak เกิน 1 ได้
    ถ้าตัดแข็งตรงนี้เสียงจะแตกถาวร (ลด voice_gain ทีหลังก็ไม่หาย) ปล่อยให้ขั้นผสมสุดท้ายคุมความดังและ true-peak แทน"""
    n = int(total_sec * sr)
    track = np.zeros(n + sr, dtype=np.float32)
    for start, audio in clips:
        a = int(start * sr)
        b = min(len(track), a + len(audio))
        if b > a:
            track[a:b] += audio[: b - a]
    out = room(track, sr, reverb, rt60, width=width)[:n]
    if bed is not None:
        out[: len(bed)] += bed[: len(out), None]
    if gain != 1.0:
        out *= gain
    sf.write(out_wav, out.astype(np.float32), sr, subtype="FLOAT")
    return out_wav


MIX_SR = 44100
_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def _measure_loudness(wav: Path, i: float, tp: float, lra: float) -> Optional[dict]:
    """รอบวัดของ loudnorm (คืน input_i, input_tp, input_lra, input_thresh, target_offset) หรือ None ถ้าวัดไม่ได้"""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav),
         "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        log.warning("loudnorm measure failed: %s", proc.stderr[-500:])
        return None
    m = _LOUDNORM_JSON.search(proc.stderr)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        vals = {k: float(data[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (ValueError, KeyError):
        return None
    # ทั้งไฟล์เงียบ (-inf) หรือสั้นจนวัดไม่ได้ → ไม่ปรับ
    return vals if all(math.isfinite(v) for v in vals.values()) else None


def loudnorm(src: Path, out_wav: Path, i: float = ac.LOUDNORM_I, tp: float = ac.LOUDNORM_TP,
             lra: float = ac.LOUDNORM_LRA) -> bool:
    """ปรับความดังรวมแบบ 2 รอบ (EBU R128): วัดก่อนแล้วปรับแบบ linear ให้ได้ I LUFS และ true-peak ไม่เกิน tp dBTP
    คืน False ถ้าวัดไม่ได้ (ไม่ได้เขียน out_wav)"""
    m = _measure_loudness(src, i, tp, lra)
    if m is None:
        return False
    af = (f"loudnorm=I={i}:TP={tp}:LRA={lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
          f"linear=true:print_format=summary,aresample={MIX_SR}")
    run(["ffmpeg", "-y", "-i", src, "-af", af, "-c:a", "pcm_f32le", out_wav])
    log.info("loudnorm: %.1f LUFS / %.1f dBTP → target %.1f LUFS / %.1f dBTP",
             m["input_i"], m["input_tp"], i, tp)
    return True


@dataclass(frozen=True)
class Duck:
    """ลดเพลงประกอบลงตอนเสียงพากย์ดัง (ค่าใน audio_constants.DUCK_*)"""
    depth_db: float = ac.DUCK_DEPTH_DB
    below_db: float = ac.DUCK_BELOW_DB
    ratio: float = ac.DUCK_RATIO
    attack_ms: float = ac.DUCK_ATTACK_MS
    release_ms: float = ac.DUCK_RELEASE_MS


def active_level_db(wav: Path, frame: float = 0.05) -> float | None:
    """ความดังเฉลี่ยของไฟล์เฉพาะช่วงที่มีเสียง (dBFS แบบ emotion.active_db) อ่านทีละก้อน ไม่โหลดทั้งไฟล์
    คืน None ถ้าเงียบทั้งไฟล์"""
    info = sf.info(wav)
    hop = max(1, int(info.samplerate * frame))
    ms = []
    for block in sf.blocks(wav, blocksize=hop * 400, dtype="float32", always_2d=True):
        x = block.mean(axis=1)
        f = len(x) // hop
        if f:
            ms.append((x[: f * hop].reshape(f, hop) ** 2).mean(axis=1))
    if not ms:
        return None
    rms = np.sqrt(np.concatenate(ms))
    if len(rms) < 3 or rms.max() <= 1e-5:
        return None
    on = rms[rms > 0.1 * np.percentile(rms, 95)]
    return float(10 * np.log10(np.mean(on ** 2) + 1e-12))


_SC_MIN_DB = 20 * math.log10(0.000976563)  # threshold ต่ำสุดที่ sidechaincompress รับ (-60.2 dB)


def duck_filter(voice_db: float, duck: Duck) -> str:
    """ตัวกรอง sidechaincompress สำหรับ bgm ([bgm][เสียงพากย์] → bgm ที่ลดลงตอนมีเสียงพูด)

    threshold ตั้งจากความดังของเสียงพากย์ในคลิปนี้ (voice_db - below_db) จึงลดเพลงเท่ากันทั้งคลิปที่ต้นฉบับพูดเบาและดัง
    ratio สูงทำให้ลดเต็มที่ตั้งแต่พูดเบา ๆ แล้ว mix จำกัดความลึกไว้ที่ depth_db: gain = mix*g + (1-mix) ≥ 1-mix
    ระหว่างพูดเพลงจึงลดเกือบคงที่ ไม่กระเพื่อมตามพยางค์ detection=rms + release ยาวกว่าช่องว่างระหว่างคำ"""
    thr_db = min(0.0, max(_SC_MIN_DB, voice_db - duck.below_db))
    mix_amt = 1 - 10 ** (-max(0.0, duck.depth_db) / 20)
    return (f"sidechaincompress=threshold={10 ** (thr_db / 20):.6f}:ratio={duck.ratio:g}:"
            f"attack={duck.attack_ms:g}:release={duck.release_ms:g}:knee=2.82843:"
            f"detection=rms:link=maximum:makeup=1:mix={mix_amt:.4f}")


def mix_graph(has_bgm: bool, bgm_gain: float = 1.0, duck_af: str = "") -> str:
    """filter_complex ของขั้นผสม (ไม่มีป้ายขาออก ต่อ [out] เอง)
    [0:a] เสียงพากย์, [1:a] เพลงประกอบ, duck_af: ตัวกรอง ducking (ว่าง = ไม่ลดเพลง)"""
    voice = f"[0:a]aresample={MIX_SR},aformat=channel_layouts=stereo"
    if not has_bgm:
        return voice
    bgm = f"[1:a]aresample={MIX_SR},aformat=channel_layouts=stereo,volume={bgm_gain}"
    if not duck_af:
        return f"{voice}[v];{bgm}[b];[v][b]amix=inputs=2:duration=longest:normalize=0"
    # เสียงพากย์แยกเป็นสองสาย: สายหนึ่งผสม อีกสายคุม sidechain (apad: ถ้าเสียงพากย์สั้นกว่าเพลง ให้ท้ายเพลงไม่ถูกตัด)
    return (f"{voice},asplit=2[v][sc0];[sc0]apad[sc];{bgm}[b0];[b0][sc]{duck_af}[b];"
            "[v][b]amix=inputs=2:duration=longest:normalize=0")


def mix_tracks(voice_wav: Path, bgm_wav: Optional[Path], out_wav: Path, bgm_gain: float = 1.0,
               normalize: bool = ac.LOUDNORM, duck: Duck | None = Duck()) -> Path:
    """ผสมเสียงพากย์ (ใส่ voice_gain มาแล้วใน place_clips) กับเพลงประกอบ แล้วปรับความดังรวม

    duck: ลดเพลงลงตอนเสียงพากย์ดัง (None = ไม่ลด) กลบเสียงพูดภาษาเดิมที่หลงเหลือใน bgm
    เขียนผลเป็น WAV float32 ระหว่างทาง ไม่ตัดแข็ง ขั้นสุดท้ายใช้ loudnorm 2 รอบ (audio_constants.LOUDNORM_*)
    ถ้าปิดหรือวัดไม่ได้ ใช้ alimiter กันแตกแบบเดิม"""
    has_bgm = bool(bgm_wav and bgm_wav.exists())
    duck_af = ""
    if has_bgm and duck is not None and duck.depth_db > 0:
        voice_db = active_level_db(voice_wav)
        if voice_db is not None:
            duck_af = duck_filter(voice_db, duck)
            log.info("duck bgm: voice %.1f dBFS, %s", voice_db, duck_af)
    inputs = ["-i", voice_wav, "-i", bgm_wav] if has_bgm else ["-i", voice_wav]
    graph = mix_graph(has_bgm, bgm_gain, duck_af)
    with tempfile.TemporaryDirectory() as tmp:
        premix = Path(tmp) / "premix.wav"
        run(["ffmpeg", "-y", *inputs, "-filter_complex", f"{graph}[out]",
             "-map", "[out]", "-c:a", "pcm_f32le", premix])
        if normalize and loudnorm(premix, out_wav):
            return out_wav
        run(["ffmpeg", "-y", "-i", premix, "-af", "alimiter=limit=0.95", "-c:a", "pcm_f32le", out_wav])
    return out_wav


def mux_video(video: Path, audio_wav: Path, out_mp4: Path, watermark: str = "") -> Path:
    # -threads 2 ก่อน -i คุมตัวถอดรหัสวิดีโอ (dav1d สร้างเธรดและบัฟเฟอร์เฟรมตามจำนวนคอร์)
    base = ["ffmpeg", "-y", "-threads", "2", "-i", video, "-i", audio_wav, "-map", "0:v:0", "-map", "1:a:0"]
    tail = ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4]
    # ลายน้ำมุมขวาล่าง (แพ็กทดลอง) — บังคับ encode วิดีโอใหม่
    vf = ""
    if watermark.strip():
        text = watermark.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        vf = (f"drawtext=text='{text}':fontsize=h/18:fontcolor=white@0.55:"
              f"borderw=2:bordercolor=black@0.35:x=w-tw-24:y=h-th-24")
    # เข้ารหัสใหม่เป็น H.264 Main + yuv420p (ค่าเริ่มต้นของ libx264 คือ High)
    reencode = base + h264_video_args()
    if vf:
        reencode += ["-vf", vf]
    reencode += tail
    # มือถือ (โดยเฉพาะ iPhone) เล่น VP9/AV1 ใน mp4 ไม่ได้ ก๊อปตรง ๆ ได้เฉพาะ H.264 8 บิต
    probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,pix_fmt", "-of", "csv=p=0", video])
    if vf or probe.strip().split("\n")[0].split(",")[:2] != ["h264", "yuv420p"]:
        run(reencode)
        return out_mp4
    try:
        run(base + ["-c:v", "copy"] + tail)
    except RuntimeError:  # ถ้าวิดีโอต้นฉบับใส่ใน mp4 ตรง ๆ ไม่ได้ ให้เข้ารหัสใหม่
        run(reencode)
    return out_mp4
