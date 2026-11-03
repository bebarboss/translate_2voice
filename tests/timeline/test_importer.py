import zipfile
from fractions import Fraction
from pathlib import Path

import pytest

from app.timeline import importer, timecode as tc
from app.timeline.importer import TimelineError

from .conftest import FIXTURES, ramp


def test_premiere_xml(premiere: Path):
    _, info = importer.read(premiere / "premiere_interview.xml")
    assert info.format == "fcp_xml"
    assert info.rate == Fraction(30000, 1001) and info.drop_frame
    assert info.sample_rate == 48000
    assert tc.to_timecode(info.start, info.rate, True) == "01:00:00;00"
    assert info.duration == 480
    a1, a2 = info.tracks
    assert [(c.start, c.end, c.source_in, c.source_out) for c in a1.clips] == [(0, 150, 30, 180), (300, 450, 600, 750)]
    assert [(c.start, c.end, c.source_in) for c in a2.clips] == [(160, 290, 0)]
    assert a1.clips[0].channel == 1 and a1.clips[0].media_start == 0
    assert importer.media_basename(a1.clips[0].media) == "host_take1.wav"
    assert (a1.speaker, a2.speaker) == ("speaker_01", "speaker_02")


def test_resolve_fcpxml(resolve_fcpxml: Path):
    _, info = importer.read(resolve_fcpxml / "resolve_podcast.fcpxml")
    assert info.format == "fcpx_xml"
    assert info.rate == 25 and not info.drop_frame
    assert info.sample_rate == 48000
    assert info.start == 90000 and info.duration == 250  # 01:00:00:00, 10 วินาที
    anna, ben = info.tracks
    # ตำแหน่งคลิปนับจากต้นไทม์ไลน์ (FCPXML เขียนรวม tcStart ไว้)
    assert [(c.start, c.end, c.source_in) for c in anna.clips] == [(0, 100, 50), (150, 225, 400)]
    assert [(c.start, c.end, c.source_in) for c in ben.clips] == [(100, 150, 0)]
    assert anna.clips[0].media == "file:///Volumes/Media/Podcast/anna_mic.wav"
    assert (anna.name, ben.name) == ("A1", "A2")


def test_resolve_edl_drop_frame(resolve_edl: Path):
    _, info = importer.read(resolve_edl / "resolve_scene.edl")
    assert info.format == "edl" and info.drop_frame and info.rate == Fraction(30000, 1001)
    assert tc.to_timecode(info.start, info.rate, True) == "01:00:00;00"
    a1, a2 = info.tracks
    # event 3 คร่อมนาทีที่ 1: 01:00:59;28 → 01:01:02;00 = 60 เฟรม (นับแบบ non-drop จะได้ 62)
    assert [(c.start, c.end, c.source_in) for c in a1.clips] == [(0, 60, 300), (1798, 1858, 600)]
    # แทร็ก A2 เริ่ม 01:00:03;00 (ตัวอ่าน cmx_3600 ของ OTIO วางไว้ที่ 0)
    assert [(c.start, c.end) for c in a2.clips] == [(90, 135)]
    assert info.duration == 1858
    assert a2.clips[0].media == "tom.wav"


def test_edl_needs_fps(tmp_path: Path):
    edl = tmp_path / "ndf.edl"
    edl.write_text("TITLE: x\nFCM: NON-DROP FRAME\n\n"
                   "001  AX       A     C        00:00:00:00 00:00:01:00 00:00:00:00 00:00:01:00\n")
    with pytest.raises(TimelineError, match="fps"):
        importer.read(edl)
    _, info = importer.read(edl, fps=24)
    assert info.rate == 24 and not info.drop_frame and info.tracks[0].clips[0].end == 24


def test_otio_json(premiere: Path, tmp_path: Path):
    import opentimelineio as otio
    timeline, _ = importer.read(premiere / "premiere_interview.xml")
    path = tmp_path / "copy.otio"
    otio.adapters.write_to_file(timeline, str(path))
    _, info = importer.read(path)
    assert info.format == "otio" and info.rate == Fraction(30000, 1001)
    assert [(c.start, c.end) for c in info.tracks[0].clips] == [(0, 150), (300, 450)]


def test_missing_media_listed(premiere: Path):
    tl = premiere / "premiere_interview.xml"
    (premiere / "media" / "Audio" / "guest.wav").unlink()
    _, info = importer.read(tl)
    importer.resolve_media(info, premiere, exclude=tl)
    assert info.missing == ["guest.wav"]
    assert info.tracks[0].clips[0].file == "media/Audio/Host_Take1.WAV"  # ไม่สนตัวพิมพ์ ค้นทุกโฟลเดอร์ย่อย
    ramp(premiere / "media" / "guest.wav", 30)
    importer.resolve_media(info, premiere, exclude=tl)
    assert info.missing == [] and info.tracks[1].clips[0].file == "media/guest.wav"


def test_zip_upload(tmp_path: Path):
    z = tmp_path / "project.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(FIXTURES / "resolve_podcast.fcpxml", "Podcast/resolve_podcast.fcpxml")
        f.writestr("Podcast/Audio/anna_mic.wav", b"x")
        f.writestr("__MACOSX/Podcast/._anna_mic.wav", b"x")
        f.writestr("Podcast/camera_metadata.xml", "<clip/>")  # .xml ที่ไม่ใช่ไทม์ไลน์
    files = importer.extract_zip(z, tmp_path / "out", 10**8)
    assert sorted(p.name for p in files) == ["anna_mic.wav", "camera_metadata.xml", "resolve_podcast.fcpxml"]
    tl = importer.find_timeline(files)
    _, info = importer.read(tl)
    importer.resolve_media(info, tmp_path / "out", exclude=tl)
    assert info.missing == ["ben_mic.wav"]


def test_zip_rejects_path_traversal(tmp_path: Path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../../escape.txt", b"x")
    with pytest.raises(TimelineError, match="ไม่ปลอดภัย"):
        importer.extract_zip(z, tmp_path / "out", 10**8)
    assert not (tmp_path / "escape.txt").exists()


def test_duplicate_stereo_track_disabled(tmp_path: Path):
    """Premiere แยกไฟล์สเตอริโอเป็นสองแทร็กที่คลิปเหมือนกันทุกอย่าง → ปิดแทร็กที่สองไว้ ไม่ถอดซ้ำ"""
    xml = (FIXTURES / "premiere_interview.xml").read_text(encoding="utf-8")
    start = xml.index("<track", xml.index("<audio>"))
    first = xml[start: xml.index("</track>", start) + len("</track>")]
    path = tmp_path / "dup.xml"
    path.write_text(xml.replace(first, first + first.replace('id="clipitem-2"', 'id="clipitem-9"')
                                .replace('id="clipitem-3"', 'id="clipitem-10"')), encoding="utf-8")
    _, info = importer.read(path)
    assert [(t.index, t.enabled, t.duplicate_of, t.speaker) for t in info.tracks] == [
        (1, True, None, "speaker_01"), (2, False, 1, "speaker_01"), (3, True, None, "speaker_02")]
    assert info.speakers() == ["speaker_01", "speaker_02"]


def test_not_a_timeline(tmp_path: Path):
    bad = tmp_path / "x.xml"
    bad.write_text("<root/>")
    with pytest.raises(TimelineError, match="xmeml"):
        importer.read(bad)
    with pytest.raises(TimelineError, match="ไม่รองรับ"):
        importer.read(tmp_path / "x.mov")
