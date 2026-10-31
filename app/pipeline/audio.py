"""งานเสียงพื้นฐาน: ดึงเสียงจากวิดีโอ แยกเสียงพูด (BS-RoFormer หรือ Demucs) ตัดคลิป ยืดหดเวลา"""
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

log = logging.getLogger("dubbing.audio")


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
    """แยกเป็น vocals.wav (เสียงพูด) กับ bgm.wav (เพลงและเสียงประกอบ)
    ใช้ BS-RoFormer ถ้าตั้ง SEPARATOR=roformer (เสียงพูดสะอาดกว่า Demucs มาก ลายเสียงและการถอดเสียงแม่นขึ้นตาม)
    แยกไม่สำเร็จด้วยเหตุใดก็ตาม ใช้ Demucs แทน งานไม่ล้ม"""
    from ..config import settings

    if settings.separator == "roformer":
        try:
            return _separate_roformer(audio_wav, work_dir, settings.separator_model)
        except Exception as exc:  # noqa: BLE001
            log.warning("roformer separation failed (%s), using demucs", exc)
    return _separate_demucs(audio_wav, work_dir, model, device)


_separator = None


def _separate_roformer(audio_wav: Path, work_dir: Path, model: str) -> tuple[Path, Path]:
    global _separator
    import os

    from audio_separator.separator import Separator

    from ..config import settings

    out_dir = work_dir / "_roformer"
    out_dir.mkdir(parents=True, exist_ok=True)
    key = (model, settings.separator_overlap)
    if _separator is None or getattr(_separator, "dub_key", None) != key:
        cache = os.path.join(os.environ.get("TORCH_HOME", os.path.expanduser("~/.cache")), "audio-separator")
        # use_autocast: คำนวณแบบ fp16 บนการ์ดจอ เร็วขึ้นราวเท่าตัว
        sep = Separator(model_file_dir=cache, output_dir=str(out_dir), output_format="WAV", sample_rate=44100,
                        use_autocast=True,
                        mdxc_params={"segment_size": 256, "override_model_segment_size": False, "batch_size": 1,
                                     "overlap": settings.separator_overlap, "pitch_shift": 0})
        sep.load_model(model_filename=model)
        sep.dub_key = key
        _separator = sep
    _separator.output_dir = str(out_dir)
    if getattr(_separator, "model_instance", None) is not None:
        _separator.model_instance.output_dir = str(out_dir)
    files = _separator.separate(str(audio_wav), custom_output_names={"Vocals": "vocals", "Instrumental": "bgm"})
    found = {Path(f).stem.lower(): out_dir / Path(f).name for f in files}
    if "vocals" not in found or "bgm" not in found:
        raise RuntimeError(f"ไม่พบไฟล์ที่แยกได้: {files}")
    vocals, bgm = work_dir / "vocals.wav", work_dir / "bgm.wav"
    shutil.move(str(found["vocals"]), vocals)
    shutil.move(str(found["bgm"]), bgm)
    shutil.rmtree(out_dir, ignore_errors=True)
    return vocals, bgm


def unload() -> None:
    global _separator
    _separator = None


def _separate_demucs(audio_wav: Path, work_dir: Path, model: str, device: str) -> tuple[Path, Path]:
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
