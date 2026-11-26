import numpy as np

from app.pipeline import mix

SR = 16000


def tone(sec, amp):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def orig_with(loud_a, loud_b):
    # ต้นฉบับ 10 วิ: คน A พูด 0–4 วินาที, คน B พูด 3–7 วินาที (ซ้อน 3–4)
    o = np.zeros(10 * SR, dtype=np.float32)
    o[0: 3 * SR] = tone(3, loud_a)
    o[3 * SR: 7 * SR] = tone(4, loud_b)
    return o


def test_quieter_source_is_ducked_only_in_overlap():
    clips = [(0.0, tone(4, 0.5)), (3.0, tone(4, 0.5))]
    spans = [(0.0, 4.0), (3.0, 7.0)]
    out = mix.duck_overlaps(clips, spans, SR, orig_with(0.5, 0.05), SR, depth_db=6.0)
    assert np.allclose(out[0][1], clips[0][1])  # คนที่ดังกว่าไม่ถูกแตะ
    b = out[1][1]
    assert np.abs(b[SR // 8: SR // 2]).max() < 0.3  # ช่วงซ้อน (1 วินาทีแรกของ B) ถูกลด
    assert np.isclose(np.abs(b[2 * SR:]).max(), 0.5, atol=0.01)  # หลังช่วงซ้อนกลับเป็นปกติ


def test_equal_loudness_ducks_the_interrupter():
    clips = [(0.0, tone(4, 0.4)), (3.0, tone(4, 0.4))]
    spans = [(0.0, 4.0), (3.0, 7.0)]
    out = mix.duck_overlaps(clips, spans, SR, orig_with(0.4, 0.4), SR, depth_db=6.0)
    assert np.allclose(out[0][1], clips[0][1])
    assert np.abs(out[1][1][SR // 8: SR // 2]).max() < 0.3


def test_no_overlap_or_disabled_is_untouched():
    clips = [(0.0, tone(2, 0.4)), (5.0, tone(2, 0.4))]
    spans = [(0.0, 2.0), (5.0, 7.0)]
    assert mix.duck_overlaps(clips, spans, SR, orig_with(0.4, 0.4), SR, depth_db=6.0) is clips or \
        all(np.array_equal(a[1], b[1]) for a, b in zip(mix.duck_overlaps(clips, spans, SR, orig_with(0.4, 0.4), SR, 6.0), clips))
    ov = [(0.0, tone(4, 0.4)), (3.0, tone(4, 0.4))]
    assert mix.duck_overlaps(ov, [(0, 4), (3, 7)], SR, orig_with(0.4, 0.4), SR, depth_db=0) is ov


def test_clash_only_when_dub_overlaps_much_longer_than_source():
    spans = [(0.0, 4.0), (3.0, 7.0)]  # ต้นฉบับซ้อน 1 วินาที
    ok = [(0.0, tone(4, 0.4)), (3.0, tone(4, 0.4))]
    assert mix.overlap_clashes(ok, spans, SR) == []
    long_ = [(0.0, tone(6, 0.4)), (3.0, tone(4, 0.4))]  # พากย์ A ยาวถึง 6 → ซ้อน 3 วินาที
    assert mix.overlap_clashes(long_, spans, SR) == [(0, 1, 3.0, 1.0)]
