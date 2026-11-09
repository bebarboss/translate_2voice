import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.schemas import Utterance
from app.timeline import exporter, importer, processor
from app.timeline.model import save

TTS_SR = 24000


def _job(base: Path, name: str, dub: dict[str, list[tuple[float, float]]]):
    """งานที่พากย์เสร็จแล้ว: เสียงพากย์ของแต่ละผู้พูดเป็น tone ในช่วงที่กำหนด (วินาทีบนไทม์ไลน์)"""
    job_dir = base.parent
    tl = base / name
    _, info = importer.read(tl)
    info.source = name
    importer.resolve_media(info, base, exclude=tl)
    info.sample_rate = processor.project_sample_rate(info, base)
    save(job_dir, info)
    (base / "dub").mkdir()
    n = round(info.seconds * TTS_SR)
    mix = np.zeros(n, dtype=np.float32)
    for spk, runs in dub.items():
        x = np.zeros(n, dtype=np.float32)
        for a, b in runs:
            t = np.arange(round(a * TTS_SR), round(b * TTS_SR))
            x[t] = 0.3 * np.sin(2 * np.pi * 440 * t / TTS_SR)
        mix += x
        sf.write(base / "dub" / f"{spk}.wav", x, TTS_SR)
    sf.write(job_dir / "final_audio.wav", np.stack([mix, mix], axis=1), TTS_SR)
    utts = [Utterance(id=1, speaker="speaker_01", start=0.2, end=4.0, source="hi", target="สวัสดี"),
            Utterance(id=2, speaker="speaker_02", start=5.5, end=9.0, source="yo", target="ว่าไง /ครับ")]
    return job_dir, info, utts


def test_premiere_package(premiere: Path):
    job_dir, info, utts = _job(premiere, "premiere_interview.xml",
                               {"speaker_01": [(0.2, 4.0), (10.2, 14.5)], "speaker_02": [(5.5, 9.0)]})
    names = {"speaker_01": "พิธีกร", "speaker_02": "แขกรับเชิญ"}
    z = exporter.build(job_dir, info, utts, names)
    with zipfile.ZipFile(z) as f:
        listing = sorted(f.namelist())
        f.extractall(job_dir / "unz")
    assert listing == sorted(["README.md", "TH_01_พิธีกร.wav", "TH_02_แขกรับเชิญ.wav", "TH_mixdown.wav",
                              "TH_subtitles.srt", "TH_subtitles_tc.srt", "timeline_TH.xml", "timeline_TH.fcpxml"])
    out = job_dir / "unz"

    # WAV: 48 kHz 24-bit ยาวเท่าไทม์ไลน์พอดี (480 เฟรม ที่ 29.97 = 16.016 วินาที)
    n = round(info.seconds * 48000)
    for name in ("TH_01_พิธีกร.wav", "TH_02_แขกรับเชิญ.wav", "TH_mixdown.wav"):
        meta = sf.info(out / name)
        assert (meta.samplerate, meta.frames, meta.subtype) == (48000, n, "PCM_24")
    x, _ = sf.read(out / "TH_02_แขกรับเชิญ.wav")
    assert not x[: int(5.4 * 48000)].any() and np.abs(x[int(6 * 48000):int(6.1 * 48000)]).max() > 0.2

    # Final Cut Pro XML: เปิดด้วย OTIO ได้ แทร็กเดิมครบ + แทร็กพากย์ไทยวางตรงเฟรม
    import opentimelineio as otio
    tl = otio.adapters.read_from_file(str(out / "timeline_TH.xml"), "fcp_xml")
    audio = tl.audio_tracks()
    assert len(audio) == 4
    th = audio[-1]
    clips = list(th.find_clips())
    assert clips[0].name == "TH_02_แขกรับเชิญ.wav"  # xmeml ไม่มีชื่อแทร็ก (Premiere ก็ไม่เก็บ) ดูจากชื่อคลิป
    start = clips[0].range_in_parent().start_time.value
    assert start == pytest.approx(5.5 * 30000 / 1001 - 2, abs=1.01)  # ขยายหน้า 2 เฟรม
    assert clips[0].source_range.start_time.value == start  # source in = ตำแหน่งบนไทม์ไลน์
    assert clips[0].media_reference.target_url == \
        "file://localhost/D%3A/Projects/Interview/Audio/TH_dub/TH_02_%E0%B9%81%E0%B8%82%E0%B8%81%E0%B8%A3%E0%B8%B1%E0%B8%9A%E0%B9%80%E0%B8%8A%E0%B8%B4%E0%B8%8D.wav"
    root = ET.parse(out / "timeline_TH.xml").getroot()
    seq = root.find(".//sequence")
    assert seq.find("timecode/displayformat").text == "DF"
    assert seq.find("timecode/string").text == "01:00:00;00"
    assert seq.find("rate/ntsc").text.upper() == "TRUE" and seq.find("rate/timebase").text == "30"

    # FCPXML: อัตราเฟรม 1001/30000s, drop-frame, เริ่ม 01:00:00;00, แทร็กไทยอยู่ lane ถัดจากแทร็กเดิม
    root = ET.parse(out / "timeline_TH.fcpxml").getroot()
    assert root.find("resources/format").get("frameDuration") == "1001/30000s"
    seq = root.find(".//sequence")
    assert (seq.get("tcFormat"), seq.get("audioRate")) == ("DF", "48k")
    assert seq.get("tcStart") == "107999892/30000s"  # 107892 เฟรม × 1001/30000
    clips = seq.findall(".//asset-clip")
    host = [c for c in clips if c.get("lane") == "-1"]
    assert host[0].get("start") == exporter._t(30, info.rate)  # source in ของคลิปเดิม
    th = [c for c in clips if c.get("lane") == "-4"]
    assert th and th[0].get("name") == "TH_02_แขกรับเชิญ.wav" and th[0].get("audioRole") == "dialogue.TH"

    # ซับ: เครื่องหมายหยุดหายใจ (/) ไม่ติดไปในซับ ไฟล์ _tc เลื่อนตาม timecode เริ่ม
    srt = (out / "TH_subtitles.srt").read_text(encoding="utf-8")
    assert "00:00:00,200 --> 00:00:04,000" in srt and "ว่าไง ครับ" in srt and "/" not in srt
    # timecode 01:00:00;00 ที่ 29.97 = 3599.9964 วินาทีจริง
    assert "01:00:00,196 --> 01:00:03,996" in (out / "TH_subtitles_tc.srt").read_text(encoding="utf-8")
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "29.97 fps drop-frame" in readme and "01:00:00;00" in readme and "Premiere Pro" in readme


def test_resolve_fcpxml_round_trip(resolve_fcpxml: Path):
    """FCPXML จาก Resolve: ส่งออกแล้วคลิปเดิมกลับมาอยู่ที่เดิม ไม่เลื่อนไปอีกหนึ่งชั่วโมง"""
    job_dir, info, utts = _job(resolve_fcpxml, "resolve_podcast.fcpxml",
                               {"speaker_01": [(0.1, 3.9)], "speaker_02": [(4.0, 5.9)]})
    z = exporter.build(job_dir, info, utts, {"speaker_01": "Anna", "speaker_02": "Ben"}, ("xml", "fcpxml"))
    with zipfile.ZipFile(z) as f:
        assert sorted(f.namelist()) == ["README.md", "TH_01_Anna.wav", "TH_02_Ben.wav", "timeline_TH.fcpxml",
                                        "timeline_TH.xml"]
        f.extractall(job_dir / "unz")
    out = job_dir / "unz"

    # อ่าน FCPXML ที่ส่งออกด้วยตัวนำเข้าของเราเอง: คลิปเดิมตรงเฟรมเดิม + แทร็กพากย์
    _, back = importer.read(out / "timeline_TH.fcpxml")
    assert back.rate == 25 and back.start == 90000 and back.duration == 250 and back.sample_rate == 48000
    assert [(c.start, c.end, c.source_in) for c in back.tracks[0].clips] == [(0, 100, 50), (150, 225, 400)]
    # 4.0 วินาที = เฟรม 100 ขยายหน้า 2 เฟรม (±1 จากการแปลง sample rate)
    assert back.tracks[2].clips[0].start == 0 and back.tracks[3].clips[0].start in (97, 98)
    assert back.tracks[3].clips[0].media == "file:///Volumes/Media/Podcast/TH_dub/TH_02_Ben.wav"

    # Final Cut Pro XML จาก FCPXML: ไม่มีช่องว่างหนึ่งชั่วโมงหน้าคลิป
    _, x = importer.read(out / "timeline_TH.xml")
    assert x.start == 90000 and [(c.start, c.end) for c in x.tracks[0].clips] == [(0, 100), (150, 225)]


def test_edl_package_relative_paths(resolve_edl: Path):
    """EDL ไม่มีที่อยู่ไฟล์เต็ม: ไฟล์ไทม์ไลน์อ้าง TH_dub/ แบบสัมพัทธ์ (relink ใน README)"""
    job_dir, info, utts = _job(resolve_edl, "resolve_scene.edl", {"speaker_01": [(0.0, 2.0)], "speaker_02": [(3.0, 4.5)]})
    z = exporter.build(job_dir, info, utts, {}, ("xml", "stems"))
    with zipfile.ZipFile(z) as f:
        xml = f.read("timeline_TH.xml").decode("utf-8")
        readme = f.read("README.md").decode("utf-8")
    assert "TH_dub/TH_01_speaker_01.wav" in xml and "<displayformat>DF</displayformat>" in xml
    assert "relink" in readme.lower()
    z = exporter.build(job_dir, info, utts, {}, ("stems",), media_dir="E:\\Edit\\Dub")
    with zipfile.ZipFile(z) as f:
        assert "E:/Edit/Dub/" in f.read("README.md").decode("utf-8")
        assert sorted(f.namelist()) == ["README.md", "TH_01_speaker_01.wav", "TH_02_speaker_02.wav"]


def test_unknown_format(premiere: Path):
    job_dir, info, utts = _job(premiere, "premiere_interview.xml", {"speaker_01": [(0.2, 1.0)]})
    with pytest.raises(ValueError, match="ไม่รู้จัก"):
        exporter.build(job_dir, info, utts, {}, ("aaf",))


def test_voiced_runs_frame_bounds():
    from fractions import Fraction
    x = np.zeros(48000 * 4, dtype=np.float32)
    x[48000: 72000] = 0.1  # 1.0–1.5 วินาที
    x[73000: 96000] = 0.1  # เว้น 0.02 วินาที = ช่วงเดียวกัน
    x[150000: 160000] = 0.1
    runs = exporter.voiced_runs(x, 48000, Fraction(25), 100)
    assert runs == [(23, 52), (76, 86)]
