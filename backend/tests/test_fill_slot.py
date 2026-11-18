"""เสียงพากย์พูดไม่เต็มช่อง (งาน e364a0bd2568: 67–68% ของช่อง ไม่ถูกขยายเพราะเกณฑ์เดิม 65%)"""
from app.pipeline.runner import keep_lengthened, should_lengthen


def test_long_slot_is_lengthened_below_eighty_percent():
    assert should_lengthen(7.94, 5.31)  # 67% (งานจริง)
    assert should_lengthen(7.84, 5.35)  # 68%
    assert not should_lengthen(5.72, 5.02)  # 88%
    assert not should_lengthen(4.0, 3.67)  # 92%


def test_short_slots_keep_the_old_threshold():
    assert not should_lengthen(1.5, 1.0)  # 67% ของช่องสั้น: ไม่ขยาย (เกณฑ์ 65% เดิม)
    assert should_lengthen(1.5, 0.9)  # 60%
    assert not should_lengthen(1.0, 0.1)  # ช่องสั้นกว่า 1.2 วินาทีไม่ขยาย


def test_keep_only_when_closer_and_not_overflowing():
    assert keep_lengthened(7.9, old_sec=5.3, new_sec=7.0)
    assert not keep_lengthened(7.9, old_sec=5.3, new_sec=8.5)  # ล้นช่อง
    assert not keep_lengthened(7.9, old_sec=5.3, new_sec=5.2)  # ไม่ใกล้ขึ้น
    assert not keep_lengthened(7.9, old_sec=7.7, new_sec=7.5)  # แย่ลง
