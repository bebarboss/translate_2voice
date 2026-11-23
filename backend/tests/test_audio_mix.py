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


# ---------- ducking (ลดเพลงตอนเสียงพากย์ดัง) ----------

def _thr_db(af: str) -> float:
    return 20 * np.log10(float(re.search(r"threshold=([\d.]+)", af).group(1)))


def test_duck_filter_threshold_follows_voice_level():
    d = mix.Duck(depth_db=8, below_db=15, ratio=8, attack_ms=30, release_ms=450)
    assert _thr_db(mix.duck_filter(-20.0, d)) == pytest.approx(-35.0, abs=0.01)
    assert _thr_db(mix.duck_filter(-30.0, d)) == pytest.approx(-45.0, abs=0.01)
    # เสียงเบามากจน threshold ต่ำกว่าที่ ffmpeg รับ (-60.2 dB) → ตรึงไว้ที่ขอบ ไม่ให้ ffmpeg ล้ม
    assert _thr_db(mix.duck_filter(-70.0, d)) == pytest.approx(mix._SC_MIN_DB, abs=0.01)
    af = mix.duck_filter(-20.0, d)
    for part in ("sidechaincompress=", "ratio=8:", "attack=30:", "release=450:", "detection=rms"):
        assert part in af


def test_duck_filter_depth_caps_reduction_with_mix():
    """mix = 1 - 10^(-depth/20): ต่อให้บีบเต็มที่ เพลงก็ลดได้ไม่เกิน depth dB"""
    mix_of = lambda depth: float(re.search(r"mix=([\d.]+)", mix.duck_filter(-20, mix.Duck(depth_db=depth))).group(1))
    assert mix_of(8.0) == pytest.approx(1 - 10 ** (-8 / 20), abs=1e-4)
    assert 20 * np.log10(1 - mix_of(6.0)) == pytest.approx(-6.0, abs=0.01)
    assert mix_of(0.0) == 0.0


def test_mix_graph_shapes():
    plain = mix.mix_graph(True, 0.8)
    assert "sidechaincompress" not in plain and "volume=0.8" in plain
    assert plain.endswith("amix=inputs=2:duration=longest:normalize=0")
    assert "[1:a]" not in mix.mix_graph(False)
    ducked = mix.mix_graph(True, 1.0, "sidechaincompress=threshold=0.01")
    # เสียงพากย์แยกสองสาย (ผสม + คุม) สายคุมเข้าเป็นอินพุตที่สองของ sidechaincompress
    assert "asplit=2[v][sc0]" in ducked and "[sc0]apad[sc]" in ducked
    assert "[b0][sc]sidechaincompress=threshold=0.01[b]" in ducked
    assert ducked.endswith("[v][b]amix=inputs=2:duration=longest:normalize=0")


def test_active_level_db(tmp_path: Path):
    from app.pipeline.emotion import active_db

    v = np.concatenate([np.zeros(SR), _voice(2.0, 0.5), np.zeros(SR)])
    sf.write(tmp_path / "v.wav", np.stack([v, v], axis=1), SR, subtype="FLOAT")
    assert mix.active_level_db(tmp_path / "v.wav") == pytest.approx(active_db(v, SR), abs=0.5)
    sf.write(tmp_path / "s.wav", np.zeros((SR, 2), dtype=np.float32), SR, subtype="FLOAT")
    assert mix.active_level_db(tmp_path / "s.wav") is None


def _tone_level(x: np.ndarray, sr: int, hz: float, a: float, b: float) -> float:
    """ความดัง (dB) ของคลื่น hz Hz ในช่วง a–b วินาที (ช่องซ้าย) ใช้แยกระดับเพลงออกจากเสียงพากย์"""
    seg = x[int(a * sr): int(b * sr), 0]
    t = np.arange(len(seg)) / sr
    amp = 2 * np.hypot(np.mean(seg * np.sin(2 * np.pi * hz * t)), np.mean(seg * np.cos(2 * np.pi * hz * t)))
    return 20 * np.log10(amp + 1e-12)


def _duck_fixture(tmp_path: Path, voice_sec: float = 10.0, bgm_sec: float = 10.0) -> tuple[Path, Path]:
    """เสียงพากย์ (ฮาร์มอนิก ≤1.05 kHz) ช่วง 3–7 s + เพลงเป็นคลื่น 5 kHz คงที่ → วัดระดับเพลงแยกได้"""
    voice = mix.place_clips([(3.0, _voice(4.0, 0.3))], voice_sec, SR, tmp_path / "dub_voice.wav", None, reverb=0.0)
    t = np.arange(int(bgm_sec * 44100)) / 44100
    tone = 0.1 * np.sin(2 * np.pi * 5000 * t)
    sf.write(tmp_path / "bgm.wav", np.stack([tone, tone], axis=1).astype(np.float32), 44100, subtype="FLOAT")
    return voice, tmp_path / "bgm.wav"


@needs_ffmpeg
def test_mix_tracks_ducks_bgm_under_voice(tmp_path: Path):
    voice, bgm = _duck_fixture(tmp_path)
    d = mix.Duck()
    out = mix.mix_tracks(voice, bgm, tmp_path / "ducked.wav", normalize=False, duck=d)
    got, sr = sf.read(out, dtype="float32")
    before = _tone_level(got, sr, 5000, 1.0, 2.5)
    during = _tone_level(got, sr, 5000, 3.6, 6.8)
    after = _tone_level(got, sr, 5000, 8.5, 9.8)
    assert before == pytest.approx(-20.0, abs=0.5)  # ก่อนพูด เพลงเท่าเดิม
    assert -d.depth_db - 0.5 <= during - before <= -4.0  # ระหว่างพูดลดราว 5–8 dB ไม่เกิน depth
    assert after == pytest.approx(before, abs=0.5)  # หลังพูดกลับมาเท่าเดิม
    # ระหว่างพูดเพลงลดเกือบคงที่ (ไม่ pumping): ระดับเพลงทุกช่วง 0.4 s ต่างกันไม่เกิน 1.5 dB
    steps = [_tone_level(got, sr, 5000, a, a + 0.4) for a in np.arange(3.6, 6.5, 0.4)]
    assert max(steps) - min(steps) < 1.5

    plain = sf.read(mix.mix_tracks(voice, bgm, tmp_path / "plain.wav", normalize=False, duck=None),
                    dtype="float32")[0]
    assert _tone_level(plain, sr, 5000, 3.6, 6.8) == pytest.approx(before, abs=0.5)  # ปิด ducking = ไม่ลด


@needs_ffmpeg
@pytest.mark.parametrize("voice_sec,bgm_sec", [(6.0, 10.0), (10.0, 8.0)])
def test_mix_tracks_duck_keeps_longest_length(tmp_path: Path, voice_sec: float, bgm_sec: float):
    """เสียงพากย์สั้นกว่าเพลง (apad ที่สาย sidechain) หรือยาวกว่า: ผลยาวเท่าแทร็กที่ยาวสุด ไม่ค้าง ไม่ตัดท้าย"""
    voice, bgm = _duck_fixture(tmp_path, voice_sec, bgm_sec)
    out = mix.mix_tracks(voice, bgm, tmp_path / "o.wav", normalize=False)
    got, sr = sf.read(out, dtype="float32")
    assert abs(len(got) / sr - max(voice_sec, bgm_sec)) < 0.05
    if bgm_sec > voice_sec:
        assert _tone_level(got, sr, 5000, voice_sec + 1.0, bgm_sec - 0.5) == pytest.approx(-20.0, abs=0.5)


# ---------- เสียงก้องห้อง ----------

def test_room_width_controls_stereo_spread():
    v = np.concatenate([_voice(1.0), np.zeros(SR, dtype=np.float32)])
    mono = mix.room(v, SR, 0.2, 0.4, width=0.0)
    np.testing.assert_allclose(mono[:, 0], mono[:, 1], atol=1e-6)  # width 0: เสียงอยู่กลางพอดี
    wet = lambda w: mix.room(v, SR, 0.2, 0.4, width=w) - v[:, None]
    corr = lambda w: float(np.corrcoef(wet(w)[:, 0], wet(w)[:, 1])[0, 1])
    assert corr(1.0) < 0.3 < corr(ac.ROOM_WIDTH)  # ค่าเริ่มต้นแคบกว่าแบบเดิม (ซ้ายขวาไม่สัมพันธ์กันเลย)


def test_room_default_is_lighter():
    """ค่าเริ่มต้นใหม่ก้องบางกว่าเดิม (wet 0.2 / rt60 0.4) และ peak เกินเสียงแห้งน้อยลง"""
    assert ac.ROOM_REVERB < 0.2 and ac.ROOM_RT60 < 0.4
    v = np.concatenate([_voice(1.0), np.zeros(SR, dtype=np.float32)])
    old = mix.room(v, SR, 0.2, 0.4, width=1.0) - v[:, None]
    new = mix.room(v, SR) - v[:, None]
    assert 20 * np.log10(np.sqrt(np.mean(new ** 2)) / np.sqrt(np.mean(old ** 2))) < -4.0
    assert mix.room(v, SR, 0.0).shape == (len(v), 2)  # 0 = แห้ง ยังคืนสเตอริโอ
