from fractions import Fraction

import pytest

from app.timeline import timecode as tc

NTSC30 = Fraction(30000, 1001)


@pytest.mark.parametrize("frames,expected", [
    (0, "00:00:00;00"),
    (1799, "00:00:59;29"),
    (1800, "00:01:00;02"),  # เลข ;00 ;01 ของนาทีที่ 1 ถูกข้าม
    (17982, "00:10:00;00"),  # นาทีที่หารด้วย 10 ลงตัว ไม่ข้าม
    (107892, "01:00:00;00"),
])
def test_drop_frame_29_97(frames, expected):
    assert tc.to_timecode(frames, NTSC30, drop=True) == expected
    assert tc.from_timecode(expected, NTSC30) == frames


def test_drop_frame_59_94():
    r = Fraction(60000, 1001)
    assert tc.to_timecode(3600, r, drop=True) == "00:01:00;04"
    assert tc.from_timecode("00:01:00;04", r) == 3600


def test_drop_frame_round_trip_every_frame():
    for f in range(0, 40000, 7):
        assert tc.from_timecode(tc.to_timecode(f, NTSC30, True), NTSC30) == f


def test_non_drop():
    assert tc.to_timecode(90000, Fraction(25)) == "01:00:00:00"
    assert tc.to_timecode(1800, NTSC30, drop=False) == "00:01:00:00"
    # 23.976 ทำ drop-frame ไม่ได้ ใช้ : เสมอ
    assert tc.to_timecode(1440, Fraction(24000, 1001), drop=True) == "00:01:00:00"


def test_exact_rate():
    assert tc.exact_rate(29.97) == NTSC30
    assert tc.exact_rate(23.976) == Fraction(24000, 1001)
    assert tc.exact_rate(59.94) == Fraction(60000, 1001)
    assert tc.exact_rate(25) == 25
    assert not tc.can_drop(Fraction(25))


def test_seconds_use_exact_rate():
    # หนึ่งชั่วโมงตาม drop-frame = 107892 เฟรม = 3599.9964 วินาทีจริง (ไม่ใช่ 3600)
    assert tc.seconds(107892, NTSC30) == pytest.approx(3599.9964, abs=1e-4)
    assert tc.frames_at(tc.seconds(107892, NTSC30), NTSC30) == 107892
