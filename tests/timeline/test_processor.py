from pathlib import Path

import numpy as np
import pytest

from app.pipeline.common import Word
from app.schemas import Utterance
from app.timeline import importer, processor


def _info(base: Path, name: str):
    tl = base / name
    _, info = importer.read(tl)
    importer.resolve_media(info, base, exclude=tl)
    assert not info.missing
    return info


def test_render_premiere_track_lands_on_frames(premiere: Path):
    info = _info(premiere, "premiere_interview.xml")
    sr = processor.project_sample_rate(info, premiere)
    assert sr == 48000
    a1 = processor.render_track(info, info.tracks[0], premiere, sr)
    assert len(a1) == round(info.seconds * sr)  # ยาวเท่าไทม์ไลน์พอดี
    # คลิปแรก: วางที่เฟรม 0 เริ่มจาก source in เฟรม 30 (1.001 วินาทีในไฟล์) ไฟล์ ramp ค่า = วินาที ÷ 100
    assert a1[0] == pytest.approx(1.001 / 100, abs=2e-5)
    # คลิปที่สอง: วางที่เฟรม 300 (10.01 วินาที) source in เฟรม 600 (20.02 วินาที)
    k = round(info.sec(300) * sr) + 10
    assert a1[k] == pytest.approx((info.sec(600) + 10 / sr) / 100, abs=2e-5)
    # ช่วงระหว่างคลิปเงียบ
    assert not a1[round(info.sec(160) * sr): round(info.sec(290) * sr)].any()


def test_render_fcpxml_and_edl(resolve_fcpxml: Path, resolve_edl: Path):
    info = _info(resolve_fcpxml, "resolve_podcast.fcpxml")
    ben = processor.render_track(info, info.tracks[1], resolve_fcpxml, 48000)
    assert not ben[: 4 * 48000 - 10].any() and ben[4 * 48000 + 5] == pytest.approx(5 / 48000 / 100, abs=2e-5)

    info = _info(resolve_edl, "resolve_scene.edl")
    sr = processor.project_sample_rate(info, resolve_edl)  # EDL ไม่บอก sample rate ใช้ของไฟล์
    assert sr == 48000
    mary = processor.render_track(info, info.tracks[0], resolve_edl, sr)
    # EDL เขียน source in เป็น 00:00:10;00 และไฟล์ไม่มี timecode → 10 วินาทีจากต้นไฟล์ (เฟรม 300 ที่ 29.97 = 10.01 วิ)
    assert mary[5] == pytest.approx((info.sec(300) + 5 / sr) / 100, abs=2e-5)
    k = round(info.sec(1798) * sr) + 5
    assert mary[k] == pytest.approx((info.sec(600) + 5 / sr) / 100, abs=2e-5)


def test_stereo_channel_pick(tmp_path: Path):
    from .conftest import ramp
    f = ramp(tmp_path / "st.wav", 2, channels=2)  # ช่อง 2 = ค่าสองเท่าของช่อง 1
    left = processor.decode(f, 48000, 1.0, 0.1, channel=1, channels=2)
    right = processor.decode(f, 48000, 1.0, 0.1, channel=2, channels=2)
    assert right[0] == pytest.approx(2 * left[0], rel=1e-3)


def test_speaker_spans_merge_tracks():
    from app.timeline.model import TimelineClip, TimelineInfo, TimelineTrack
    clip = lambda a, b: TimelineClip(name="x", start=a, end=b, source_in=0, source_out=b - a)  # noqa: E731
    info = TimelineInfo(format="edl", source="x.edl", rate_num=25, duration=1000, tracks=[
        TimelineTrack(index=1, name="A1", speaker="speaker_01", clips=[clip(0, 50), clip(100, 150)]),
        TimelineTrack(index=2, name="A2", speaker="speaker_01", clips=[clip(50, 75)]),  # ต่อชิดคลิปแรก = ช่วงเดียว
        TimelineTrack(index=3, name="A3", speaker="speaker_02", clips=[clip(200, 250)], enabled=False),
    ])
    assert processor.speaker_spans(info) == {"speaker_01": [(0.0, 3.0), (4.0, 6.0)]}


def test_split_line_at_clip_cut():
    spans = [(0.0, 2.0), (2.5, 5.0)]
    words = [Word(0.2, 0.6, " hello", 0), Word(0.7, 1.9, " there", 0), Word(2.6, 3.0, " good", 0), Word(3.1, 3.6, " bye", 0)]
    u = Utterance(id=1, speaker="speaker_01", start=0.2, end=3.6, source="hello there good bye")
    a, b = processor.split_at_clips([u], words, spans)
    assert (a.start, a.end, a.source) == (0.2, 1.9, "hello there")
    assert (b.start, b.end, b.source) == (2.6, 3.6, "good bye")
    # ประโยคที่ล้นออกนอกคลิปเล็กน้อย (Whisper ให้เวลาคำยาวเกิน) ถูกบีบให้อยู่ในคลิป
    v = Utterance(id=2, speaker="speaker_01", start=2.4, end=5.3, source="x")
    [c] = processor.split_at_clips([v], [Word(2.55, 5.2, " x", 0)], spans)
    assert (c.start, c.end) == (2.5, 5.0)


def test_dub_part_keeps_clips_apart(premiere: Path):
    info = _info(premiere, "premiere_interview.xml")
    part = processor.dub_part(info)
    u = lambda s, a, b: Utterance(id=1, speaker=s, start=a, end=b, source="x")  # noqa: E731
    assert part(u("speaker_01", 0.5, 1.0)) == part(u("speaker_01", 2.0, 4.0))  # คลิปเดียวกัน
    assert part(u("speaker_01", 0.5, 1.0)) != part(u("speaker_01", 10.5, 11.0))  # คนละคลิป
    spans = processor.speaker_spans(info)
    assert processor.clip_end(info, spans, "speaker_01", 1.0) == pytest.approx(info.sec(150))


def test_fit_and_resample():
    x = np.ones(24000, dtype=np.float32)
    y = processor.resample(x, 24000, 48000)
    assert len(y) == 48000
    assert len(processor.fit_length(y, 50000)) == 50000 and len(processor.fit_length(y, 100)) == 100
