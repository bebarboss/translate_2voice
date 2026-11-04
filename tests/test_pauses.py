"""การเว้นจังหวะตามต้นฉบับ (app/pipeline/pauses.py): ตัดบทพากย์ตรงจุด / ที่ตรงกับจุดที่นักแสดงหยุด
เสียงจำลอง = เสียงพูด (sine) สลับช่วงเงียบ ตามเวลาที่กำหนด"""
import numpy as np

from app.pipeline import pauses
from app.pipeline.common import Word
from app.schemas import Utterance

SR = 16000


def speech(parts: list[tuple[float, bool]]) -> np.ndarray:
    """[(วินาที, มีเสียงพูด)] → เสียง"""
    out = []
    for sec, voiced in parts:
        n = int(sec * SR)
        t = np.arange(n) / SR
        out.append(0.3 * np.sin(2 * np.pi * 220 * t) if voiced else np.zeros(n))
    return np.concatenate(out).astype(np.float32)


def words_at(times: list[tuple[float, float]]) -> list[Word]:
    return [Word(start=a, end=b, text=f"w{i}", segment=0) for i, (a, b) in enumerate(times)]


def utt(target: str, start: float, end: float) -> Utterance:
    return Utterance(id=1, speaker="speaker_01", start=start, end=end, source="x", target=target)


def test_short_marked_chunk_is_kept():
    # เรียกชื่อสั้น ๆ 0.6 วินาที หยุด 0.6 วินาที แล้วพูดต่อ: ท่อนแรกสั้นกว่า 0.8 แต่ตัดตาม / จึงต้องคงไว้
    audio = speech([(0.6, True), (0.6, False), (2.0, True)])
    words = words_at([(0.0, 0.6), (1.2, 1.8), (1.8, 2.5), (2.5, 3.2)])
    u = utt("ท่านพี่! / ข้าขอเรียกท่านว่าท่านพี่", 0.0, 3.2)
    chunks = pauses.plan([u], audio, SR, 0.3, words=words)
    assert [c.text for c in chunks] == ["ท่านพี่!", "ข้าขอเรียกท่านว่าท่านพี่"]
    assert chunks[0].end <= 0.7 and chunks[1].start >= 1.1


def test_short_auto_chunk_still_merged():
    # ไม่มี / : ช่วงสั้นที่ระบบตัดเองจากความเงียบยังยุบรวมตามเดิม
    audio = speech([(0.6, True), (0.6, False), (2.0, True)])
    words = words_at([(0.0, 0.6), (1.2, 1.8), (1.8, 2.5), (2.5, 3.2)])
    u = utt("ท่านพี่ ข้าขอเรียกท่านว่าท่านพี่", 0.0, 3.2)
    assert len(pauses.plan([u], audio, SR, 0.3, words=words)) == 1


def test_fewer_marks_than_pauses_matched_by_position():
    # นักแสดงหยุด 2 ครั้ง (ราว 45% และ 80% ของประโยค) ผู้แปลวาง / จุดเดียวตรงครึ่งแรก → ใช้จุดนั้น ไม่ทิ้งทั้งประโยค
    audio = speech([(2.7, True), (0.9, False), (1.4, True), (0.6, False), (0.6, True)])
    words = words_at([(0.0, 1.3), (1.3, 2.7), (3.6, 4.3), (4.3, 5.0), (5.6, 6.2)])
    u = utt("หม่อมฉันรู้ทุกสิ่งที่เกิดขึ้นในวังหลวง / ฝ่าบาทเองก็ทรงรู้อยู่แก่ใจไม่ใช่หรือเพคะ", 0.0, 6.2)
    chunks = pauses.plan([u], audio, SR, 0.3, words=words)
    assert chunks[0].text == "หม่อมฉันรู้ทุกสิ่งที่เกิดขึ้นในวังหลวง"
    assert abs(chunks[0].end - 2.7) < 0.1 and abs(chunks[1].start - 3.6) < 0.1


def test_match_marks_drops_far_pairs():
    # / อยู่ต้นบท (10%) แต่นักแสดงหยุดเกือบท้าย (85%) → ไม่จับคู่ (ห่างเกิน MAX_MARK_GAP)
    u = utt("x", 0.0, 10.0)
    assert pauses.match_marks([3], 30, [(8.3, 8.7, 5), (9.0, 9.2, 6)], u) == []
    # จำนวนเท่ากัน คู่กันตามลำดับ
    assert pauses.match_marks([5, 20], 30, [(2.0, 2.5, 1), (7.0, 7.5, 3)], u) == [(5, (2.0, 2.5)), (20, (7.0, 7.5))]
    # / มากกว่าจุดหยุด: เลือก / ที่ตำแหน่งใกล้จุดหยุดที่สุด
    assert pauses.match_marks([5, 15, 25], 30, [(4.8, 5.2, 2)], u) == [(15, (4.8, 5.2))]


def test_tidy_marks_moves_mark_before_connector():
    from app.pipeline.pauses import tidy_marks
    assert tidy_marks("ฉันจัดให้ได้ ถ้า / เราตั้งชื่อว่า บีสต์") == "ฉันจัดให้ได้ / ถ้าเราตั้งชื่อว่า บีสต์"
    assert tidy_marks("เดี๋ยว / ระวังตัว") == "เดี๋ยว / ระวังตัว"
    assert tidy_marks("24/7 ตลอด") == "24/7 ตลอด"
