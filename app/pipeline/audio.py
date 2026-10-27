"""งานเสียงพื้นฐาน: ดึงเสียงจากวิดีโอ แยกเสียงพูดด้วย Demucs ตัดคลิป ยืดหดเวลา"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


def run(cmd: list, cwd=None) -> str:
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(str(cmd[0])).name} ล้มเหลว: {proc.stderr[-1500:]}")
    return proc.stdout


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


def has_audio(path: Path) -> bool:
    out = run(["ffprobe", "-v", "error", "-select_streams", "a",
               "-show_entries", "stream=index", "-of", "csv=p=0", path])
    return bool(out.strip())


def extract_audio(video: Path, out_wav: Path, sr: int = 44100) -> Path:
    if not has_audio(video):
        raise RuntimeError("วิดีโอนี้ไม่มีเสียง")
    run(["ffmpeg", "-y", "-i", video, "-vn", "-ac", "2", "-ar", sr, "-c:a", "pcm_s16le", out_wav])
    return out_wav


def to_mono(in_wav: Path, out_wav: Path, sr: int = 16000) -> Path:
    run(["ffmpeg", "-y", "-i", in_wav, "-ac", "1", "-ar", sr, "-c:a", "pcm_s16le", out_wav])
    return out_wav


def separate_vocals(audio_wav: Path, work_dir: Path, model: str, device: str) -> tuple[Path, Path]:
    """แยกเป็น vocals.wav (เสียงพูด) กับ bgm.wav (เพลงและเสียงประกอบ)"""
    out_root = work_dir / "_demucs"
    run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", model,
         "-d", device, "-o", out_root, audio_wav])
    stem_dir = out_root / model / audio_wav.stem
    vocals, bgm = work_dir / "vocals.wav", work_dir / "bgm.wav"
    shutil.move(str(stem_dir / "vocals.wav"), vocals)
    shutil.move(str(stem_dir / "no_vocals.wav"), bgm)
    shutil.rmtree(out_root, ignore_errors=True)
    return vocals, bgm


def cut_clip(src_wav: Path, start: float, end: float, out_wav: Path, sr: int = 24000) -> Path:
    run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src_wav,
         "-ac", "1", "-ar", sr, "-c:a", "pcm_s16le", out_wav])
    return out_wav


def trim_silence(audio: np.ndarray, sr: int, threshold_db: float = -40, pad_ms: float = 120) -> np.ndarray:
    """ตัดความเงียบหัวท้ายที่ TTS มักแถมมา จะได้วางเสียงตรงจังหวะปาก (เหลือขอบไว้ให้เสียงหายใจและหางเสียง)"""
    if len(audio) == 0:
        return audio
    level = 10 ** (threshold_db / 20) * max(float(np.abs(audio).max()), 1e-6)
    loud = np.flatnonzero(np.abs(audio) > level)
    if len(loud) == 0:
        return audio
    pad = int(sr * pad_ms / 1000)
    return audio[max(0, loud[0] - pad): min(len(audio), loud[-1] + pad)]


def fade(audio: np.ndarray, sr: int, in_ms: float = 20, out_ms: float = 80) -> np.ndarray:
    """เฟดเข้าสั้น ๆ กันเสียงคลิก เฟดออกยาวกว่าให้หางเสียงจบนุ่ม ไม่ห้วน"""
    audio = audio.copy()
    for ms, head in ((in_ms, True), (out_ms, False)):
        n = min(len(audio) // 2, int(sr * ms / 1000))
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
            if head:
                audio[:n] *= ramp
            else:
                audio[-n:] *= ramp[::-1]
    return audio
