import numpy as np
import soundfile as sf

from app.pipeline.peaks import compute_peaks, peaks_for


def _wav(tmp_path, data, rate=16000):
    p = tmp_path / "a.wav"
    sf.write(str(p), data, rate)
    return p


def test_peaks_follow_loudness(tmp_path):
    rate = 16000
    sig = np.concatenate([np.zeros(rate), 0.5 * np.ones(rate)]).astype("float32")  # เงียบ 1 วิ แล้วดัง 1 วิ
    r = compute_peaks(_wav(tmp_path, sig, rate), 100)
    assert r["duration"] == 2.0
    assert len(r["peaks"]) == 100
    assert max(r["peaks"][:49]) == 0
    assert min(r["peaks"][51:]) == 50


def test_peaks_clamped_and_stereo(tmp_path):
    sig = np.ones((8000, 2), dtype="float32") * 0.9
    r = compute_peaks(_wav(tmp_path, sig), 10_000_000)
    assert len(r["peaks"]) <= 4000 and max(r["peaks"]) == 90


def test_peaks_tiny_file_and_cache(tmp_path):
    p = _wav(tmp_path, np.full(20, 0.2, dtype="float32"))
    assert len(compute_peaks(p, 1500)["peaks"]) == 20
    assert peaks_for(p, 1500) is peaks_for(p, 1500)
