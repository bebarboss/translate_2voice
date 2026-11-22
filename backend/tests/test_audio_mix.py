"""คุณภาพเสียงขั้นผสม: ไม่ตัดแข็งที่ voice bus, คงสเตอริโอผ่าน FLAC, ปรับความดังรวม (loudnorm 2 รอบ)"""
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app import audio_constants as ac
from app.pipeline import mix
from app.pipeline.chunks import Window, stitch_wavs

SR = 24000
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _voice(sec: float = 2.0, peak: float = 0.98, sr: int = SR) -> np.ndarray:
    """เสียงฮาร์มอนิก 150 Hz คล้ายเสียงพูด ปรับ peak ไว้ที่ค่าเดียวกับ match_loudness (0.98)"""
    t = np.arange(int(sec * sr)) / sr
    x = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 8))
    return (x * peak / np.abs(x).max()).astype(np.float32)


def test_place_clips_overlap_no_hard_clip(tmp_path: Path):
    """สองประโยคซ้อนกัน + เสียงก้อง + bed: peak เกิน 1 ได้แต่ต้องไม่ถูกตัดแข็งตอนเขียนไฟล์"""
    v = _voice()
    bed = np.full(int(3.0 * SR), 0.1, dtype=np.float32)
    out = mix.place_clips([(0.0, v), (0.5, v)], 3.0, SR, tmp_path / "dub.wav", bed, reverb=0.2, rt60=0.4)
    info = sf.info(out)
    assert info.subtype == "FLOAT"
    assert info.channels == 2
    got, _ = sf.read(out, dtype="float32")
    assert np.abs(got).max() > 1.5  # ซ้อนกันจริง และไม่ถูกตัดที่ 1.0
    assert np.sum(np.abs(got) == 1.0) == 0  # ไม่มี sample ค้างที่ขอบ ±1 (ลักษณะของ hard clip)

    # เทียบกับค่าที่คำนวณเอง: ต้องตรงทุก sample
    track = np.zeros(int(3.0 * SR) + SR, dtype=np.float32)
    track[: len(v)] += v
    track[int(0.5 * SR): int(0.5 * SR) + len(v)] += v
    want = mix.room(track, SR, 0.2, 0.4)[: int(3.0 * SR)]
    want[: len(bed)] += bed[:, None]
    np.testing.assert_allclose(got, want, atol=1e-6)


def test_place_clips_single_line_room_over_one(tmp_path: Path):
    """ประโยคเดียว peak 0.98 + room() ก็เกิน 1 ได้ (ผลตรวจเดิม: ตัดไป 160 sample) — ต้องเก็บไว้ครบ"""
    v = _voice()
    out = mix.place_clips([(0.0, v)], 2.5, SR, tmp_path / "dub.wav", None, reverb=0.2, rt60=0.4)
    got, _ = sf.read(out, dtype="float32")
    want = mix.room(np.concatenate([v, np.zeros(SR + SR // 2, dtype=np.float32)]), SR, 0.2, 0.4)[: len(got)]
    assert np.abs(want).max() > 1.0
    np.testing.assert_allclose(got, want, atol=1e-6)


def test_place_clips_gain_before_write(tmp_path: Path):
    v = _voice()
    a = sf.read(mix.place_clips([(0.0, v), (0.3, v)], 2.5, SR, tmp_path / "a.wav", None, 0.2), dtype="float32")[0]
    b = sf.read(mix.place_clips([(0.0, v), (0.3, v)], 2.5, SR, tmp_path / "b.wav", None, 0.2, gain=0.5),
                dtype="float32")[0]
    np.testing.assert_allclose(b, a * 0.5, atol=1e-6)
    assert np.abs(b).max() < np.abs(a).max()  # ลด voice_gain แล้วยอดคลื่นลดตามจริง ไม่ใช่ค่าที่ถูกตัดไว้


def test_stitch_mixed_channels_upmixes_mono():
    w0, w1 = Window(0, 0.0, 2.0), Window(1, 1.0, 3.0)
    stereo = np.stack([np.ones(2 * 100), -np.ones(2 * 100)], axis=1).astype(np.float32)
    mono = np.full(2 * 100, 0.5, dtype=np.float32)
    out, sr = stitch_wavs([(w0, stereo, 100), (w1, mono, 100)], 1.0)
    assert sr == 100 and out.ndim == 2 and out.shape[1] == 2
    np.testing.assert_allclose(out[-1], [0.5, 0.5])
    np.testing.assert_allclose(out[0], [1.0, -1.0])


def _stereo_file(path: Path, sec: float = 2.0, sr: int = 44100) -> np.ndarray:
    t = np.arange(int(sec * sr)) / sr
    x = np.stack([0.5 * np.sin(2 * np.pi * 440 * t), 0.3 * np.sin(2 * np.pi * 660 * t)], axis=1).astype(np.float32)
    sf.write(path, x, sr)
    return x


@needs_ffmpeg
def test_flac_keeps_stereo_when_asked(tmp_path: Path):
    from app.pipeline import gpu

    src = tmp_path / "mix.wav"
    x = _stereo_file(src)
    st, sr = gpu._decode(gpu._flac(src, 44100, 2))
    assert sr == 44100 and st.ndim == 2 and st.shape[1] == 2
    np.testing.assert_allclose(st, x, atol=1e-3)
    mono, _ = gpu._decode(gpu._flac(src, 44100))  # ค่าเริ่มต้นยัง mono (vocals)
    assert mono.ndim == 1


@needs_ffmpeg
def test_flac_slice_keeps_stereo(tmp_path: Path):
    from app.pipeline import gpu

    src = tmp_path / "mix.wav"
    x = _stereo_file(src, 3.0)
    st, sr = gpu._decode(gpu._flac_slice(src, 1.0, 2.0))
    assert st.ndim == 2 and st.shape[1] == 2
    assert abs(len(st) - sr) < 50
    a = int(1.0 * sr)
    np.testing.assert_allclose(st[1000:2000], x[a + 1000: a + 2000], atol=2e-3)


def _ebur128(path: Path) -> tuple[float, float]:
    """(integrated LUFS, true-peak dBTP) จาก ffmpeg ebur128"""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = err[err.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary).group(1))
    tp = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary).group(1))
    return i, tp


@needs_ffmpeg
def test_mix_tracks_loudnorm_and_stereo_bgm(tmp_path: Path):
    """เสียงพากย์ดัง (ซ้อนกัน peak > 1) + เพลงสเตอริโอ → ได้ -16 LUFS, true-peak ≤ -1.5 dBTP, bgm ยังสเตอริโอ"""
    rng = np.random.default_rng(1)
    v = _voice(1.5)
    clips = [(s, v) for s in np.arange(0.0, 9.0, 1.0)]
    voice = mix.place_clips(clips, 10.0, SR, tmp_path / "dub_voice.wav", None, reverb=0.2)
    t = np.arange(10 * 44100) / 44100
    bgm = np.stack([0.3 * np.sin(2 * np.pi * 220 * t), 0.3 * np.sin(2 * np.pi * 330 * t)], axis=1)
    bgm += 0.02 * rng.standard_normal(bgm.shape)
    sf.write(tmp_path / "bgm.wav", bgm.astype(np.float32), 44100)

    out = mix.mix_tracks(voice, tmp_path / "bgm.wav", tmp_path / "final_audio.wav")
    info = sf.info(out)
    assert info.subtype == "FLOAT" and info.channels == 2 and info.samplerate == 44100
    i, tp = _ebur128(out)
    assert abs(i - ac.LOUDNORM_I) <= 1.0
    assert tp <= ac.LOUDNORM_TP + 0.3
    got, _ = sf.read(out, dtype="float32")
    assert np.abs(got[:, 0] - got[:, 1]).max() > 0.01  # ซ้าย/ขวาต่างกัน (ไม่ถูกรวมเป็น mono)


@needs_ffmpeg
def test_mix_tracks_silence_falls_back(tmp_path: Path):
    """เงียบทั้งไฟล์ วัดความดังไม่ได้ → ไม่ล้ม ใช้ alimiter แทน"""
    sf.write(tmp_path / "v.wav", np.zeros((SR, 2), dtype=np.float32), SR, subtype="FLOAT")
    out = mix.mix_tracks(tmp_path / "v.wav", None, tmp_path / "out.wav")
    got, _ = sf.read(out, dtype="float32")
    assert len(got) > 0 and np.abs(got).max() == 0.0
