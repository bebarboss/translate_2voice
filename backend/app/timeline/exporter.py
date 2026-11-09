"""ส่งออกงานไทม์ไลน์กลับเข้าโปรแกรมตัดต่อ: zip ที่มี
- Final Cut Pro XML (Premiere / Resolve): ไทม์ไลน์เดิมทั้งหมด + แทร็กพากย์ไทยหนึ่งแทร็กต่อผู้พูด (เขียนด้วย OTIO fcp_xml)
- FCPXML 1.9 (Resolve / Final Cut Pro): คลิปเสียงเดิม + แทร็กพากย์ไทย (เขียนเอง ตัวเขียนของ OTIO ใช้กับไทม์ไลน์ที่ไม่ได้มาจาก FCP X ไม่ได้)
- เสียงพากย์แยกผู้พูด WAV ที่ sample rate ของโปรเจกต์ ยาวเท่าไทม์ไลน์พอดี, เสียงรวม, ซับ SRT, README วิธี import

แทร็กพากย์ไทยในไฟล์ไทม์ไลน์ เป็นคลิปเฉพาะช่วงที่มีเสียง อ้างไฟล์เสียงแยกผู้พูดไฟล์เดียว (source in = ตำแหน่งบนไทม์ไลน์)
ไฟล์เสียงชี้ไปที่โฟลเดอร์ TH_dub ข้างไฟล์สื่อเดิม: แตก zip ไว้ตรงนั้น เปิดไทม์ไลน์แล้วไฟล์ขึ้นทันที ไม่ต้อง relink
"""
import copy
import logging
import math
import re
import shutil
import zipfile
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

import numpy as np
import soundfile as sf

from . import timecode as tc
from .model import TimelineInfo
from .processor import fit_length, resample

log = logging.getLogger("dubbing.timeline")

FORMATS = ("xml", "fcpxml", "stems", "mix", "srt")
DUB_DIR = "TH_dub"


# ---------------------------------------------------------------- ชื่อและที่อยู่ไฟล์
def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" ._")
    return name[:60] or "speaker"


def stem_name(speaker: str, label: str) -> str:
    n = speaker.rsplit("_", 1)[-1]
    return f"TH_{n}_{safe_name(label)}.wav"


def _local_path(media: str) -> Optional[str]:
    """ที่อยู่ไฟล์บนเครื่องของผู้ตัดต่อ จากที่ไทม์ไลน์อ้าง (file:// URL หรือ path) ชื่อไฟล์เปล่า = None"""
    m = media.strip()
    if m.lower().startswith("file:"):
        p = unquote(urlparse(m).path)
        if re.match(r"^/[A-Za-z]:", p):  # /D:/x → D:/x
            p = p[1:]
        return p
    if re.match(r"^[A-Za-z]:[\\/]", m) or m.startswith("/"):
        return m.replace("\\", "/")
    return None


def dub_folder(info: TimelineInfo, media_dir: Optional[str] = None) -> Optional[str]:
    """โฟลเดอร์ที่ไฟล์เสียงพากย์จะอยู่บนเครื่องผู้ตัดต่อ: ที่ผู้ใช้ระบุ หรือ TH_dub ข้างไฟล์เสียงบทพูดไฟล์แรก"""
    if media_dir:
        return media_dir.replace("\\", "/").rstrip("/")
    for t in info.dialogue():
        for c in t.clips:
            p = _local_path(c.media)
            if p:
                parent = str(PureWindowsPath(p).parent if re.match(r"^[A-Za-z]:", p) else PurePosixPath(p).parent)
                return parent.replace("\\", "/").rstrip("/") + "/" + DUB_DIR
    return None


def file_url(path: str, style: str) -> str:
    """xmeml (Premiere): file://localhost/D%3a/x.wav, fcpxml: file:///D:/x.wav"""
    p = path.replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    if style == "xmeml":
        return "file://localhost" + quote(p, safe="/")
    return "file://" + quote(p, safe="/:")


def media_url(media: str, style: str) -> str:
    p = _local_path(media)
    return file_url(p, style) if p else media


# ---------------------------------------------------------------- เสียง
def voiced_runs(x: np.ndarray, sr: int, rate: Fraction, frames: int, gap: float = 0.5,
                level: float = 1e-4) -> list[tuple[int, int]]:
    """ช่วงที่มีเสียง (เฟรม) รวมช่วงที่เว้นไม่เกิน gap วินาที ขยายออกข้างละ 2 เฟรม"""
    if x.ndim > 1:
        x = np.abs(x).max(axis=1)
    on = np.flatnonzero(np.abs(x) > level)
    if not len(on):
        return []
    breaks = np.flatnonzero(np.diff(on) > gap * sr)
    starts = np.concatenate([[on[0]], on[breaks + 1]])
    ends = np.concatenate([on[breaks], [on[-1]]])
    runs = []
    for a, b in zip(starts, ends):
        fa = max(0, math.floor(Fraction(int(a), sr) * rate) - 2)
        fb = min(frames, math.ceil(Fraction(int(b) + 1, sr) * rate) + 2)
        if runs and fa <= runs[-1][1]:
            runs[-1] = (runs[-1][0], max(runs[-1][1], fb))
        else:
            runs.append((fa, fb))
    return runs


def write_stems(job_dir: Path, info: TimelineInfo, names: dict[str, str], out: Path) -> dict[str, dict]:
    """เสียงพากย์ของแต่ละผู้พูด → WAV 24-bit ที่ sample rate ของโปรเจกต์ ยาวเท่าไทม์ไลน์พอดี
    คืน ผู้พูด → {file, label, runs (ช่วงที่มีเสียง เป็นเฟรม)}"""
    sr = info.sample_rate or 48000
    n = round(info.seconds * sr)
    stems = {}
    for spk in info.speakers():
        src = job_dir / "timeline" / "dub" / f"{spk}.wav"
        if not src.exists():
            log.warning("no dub for %s", spk)
            continue
        x, xsr = sf.read(src, dtype="float32")
        x = fit_length(resample(x.mean(axis=1) if x.ndim > 1 else x, xsr, sr), n)
        label = names.get(spk) or spk
        name = stem_name(spk, label)
        sf.write(out / name, np.clip(x, -1, 1), sr, subtype="PCM_24")
        stems[spk] = {"file": name, "label": label, "runs": voiced_runs(x, sr, info.rate, info.duration)}
    return stems


def write_mix(job_dir: Path, info: TimelineInfo, out: Path) -> Optional[str]:
    src = job_dir / "final_audio.wav"
    if not src.exists():
        return None
    sr = info.sample_rate or 48000
    x, xsr = sf.read(src, dtype="float32")
    x = fit_length(resample(x, xsr, sr), round(info.seconds * sr))
    sf.write(out / "TH_mixdown.wav", np.clip(x, -1, 1), sr, subtype="PCM_24")
    return "TH_mixdown.wav"


def _srt_time(sec: float) -> str:
    ms = max(0, round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(utterances: list, path: Path, offset: float = 0.0) -> None:
    from ..pipeline.pauses import strip_marks
    lines, n = [], 0
    for u in sorted(utterances, key=lambda u: u.start):
        text = strip_marks(u.target or "").strip()
        if not text:
            continue
        n += 1
        lines += [str(n), f"{_srt_time(u.start + offset)} --> {_srt_time(u.end + offset)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- Final Cut Pro XML (OTIO)
def _strip_offset(timeline, offset: int, rate: Fraction) -> None:
    """ไทม์ไลน์จาก FCPXML: OTIO วางคลิปทุกแทร็กเลื่อนไปเท่า tcStart (ช่องว่างต้นแทร็ก) ตัดช่องว่างนั้นออก"""
    import opentimelineio as otio
    if offset <= 0:
        return
    for track in timeline.tracks:
        left = offset
        while left > 0 and len(track) and isinstance(track[0], otio.schema.Gap):
            g = track[0]
            d = round(g.source_range.duration.value)
            if d <= left:
                del track[0]
                left -= d
            else:
                g.source_range = otio.opentime.TimeRange(duration=otio.opentime.RationalTime(d - left, float(rate)))
                left = 0


def thai_track(info: TimelineInfo, label: str, url: str, runs: list[tuple[int, int]]):
    import opentimelineio as otio
    r = float(info.rate)
    rt = lambda f: otio.opentime.RationalTime(f, r)  # noqa: E731
    track = otio.schema.Track(name=f"TH - {label}", kind=otio.schema.TrackKind.Audio)
    name = url.rsplit("/", 1)[-1]
    cursor = 0
    for a, b in runs:
        if a > cursor:
            track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=rt(a - cursor))))
        ref = otio.schema.ExternalReference(target_url=url, available_range=otio.opentime.TimeRange(rt(0), rt(info.duration)))
        track.append(otio.schema.Clip(name=unquote(name), media_reference=ref,
                                      source_range=otio.opentime.TimeRange(rt(a), rt(b - a))))
        cursor = b
    return track


def write_fcp_xml(timeline, info: TimelineInfo, stems: dict, folder: Optional[str], path: Path) -> None:
    import opentimelineio as otio
    tl = copy.deepcopy(timeline)
    if info.format == "fcpx_xml":
        _strip_offset(tl, info.start, info.rate)
    tl.global_start_time = otio.opentime.RationalTime(info.start, float(info.rate))
    tl.name = f"{info.name or Path(info.source).stem} TH"
    _complete_refs(tl, info)
    for spk, s in stems.items():
        url = file_url(f"{folder}/{s['file']}", "xmeml") if folder else f"{DUB_DIR}/{s['file']}"
        tl.tracks.append(thai_track(info, s["label"], url, s["runs"]))
    xml = otio.adapters.write_to_string(tl, "fcp_xml")
    path.write_text(_fix_xmeml(xml, info), encoding="utf-8")


def _complete_refs(tl, info: TimelineInfo) -> None:
    """ตัวเขียน fcp_xml ต้องรู้ที่อยู่และความยาวของไฟล์ทุกคลิป: EDL ไม่บอกความยาว FCPXML ไม่บอกไฟล์ (OTIO ไม่อ่าน asset)"""
    import opentimelineio as otio
    r = float(info.rate)
    media = {c.name: c.media for t in info.tracks for c in t.clips}
    for clip in tl.find_clips():
        ref = clip.media_reference
        if not isinstance(ref, otio.schema.ExternalReference):
            ref = otio.schema.ExternalReference(target_url=media_url(media.get(clip.name, clip.name), "xmeml"))
            clip.media_reference = ref
        if ref.available_range is None:
            sr = clip.source_range or clip.trimmed_range()
            end = sr.end_time_exclusive().value
            ref.available_range = otio.opentime.TimeRange(otio.opentime.RationalTime(0, r),
                                                          otio.opentime.RationalTime(max(end, 1), r))


def _fix_xmeml(xml: str, info: TimelineInfo) -> str:
    """ค่าที่ตัวเขียนของ OTIO ไม่ใส่: drop-frame ของ timecode และ sample rate ของ sequence"""
    root = ET.fromstring(xml)
    for seq in root.iter("sequence"):
        tcode = seq.find("timecode")
        if tcode is not None:
            df = tcode.find("displayformat")
            if df is None:
                df = ET.SubElement(tcode, "displayformat")
            df.text = "DF" if info.drop_frame else "NDF"
            s = tcode.find("string")
            if s is not None:
                s.text = tc.to_timecode(info.start, info.rate, info.drop_frame)
        audio = seq.find("media/audio")
        if audio is not None and audio.find("format") is None:
            fmt = ET.Element("format")
            sc = ET.SubElement(fmt, "samplecharacteristics")
            ET.SubElement(sc, "depth").text = "24"
            ET.SubElement(sc, "samplerate").text = str(info.sample_rate or 48000)
            audio.insert(0, fmt)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body


# ---------------------------------------------------------------- FCPXML 1.9 (เขียนเอง)
def _t(frames: int, rate: Fraction) -> str:
    """เฟรม → เวลาแบบ FCPXML เช่น 1001/30000s, 4s (ตัวหารเป็นของอัตราเฟรม ไม่ทอนเศษส่วน แบบที่ Final Cut/Resolve เขียน)"""
    num, den = frames * rate.denominator, rate.numerator
    return f"{num // den}s" if num % den == 0 else f"{num}/{den}s"


def write_fcpxml(timeline, info: TimelineInfo, base: Path, stems: dict, folder: Optional[str], path: Path,
                 offsets: dict) -> None:
    """offsets: (track index, clip index) → เฟรมเริ่มในไฟล์ (หัก timecode ของไฟล์แล้ว)"""
    rate = info.rate
    sr = info.sample_rate or 48000
    start, dur = info.start, info.duration
    root = ET.Element("fcpxml", version="1.9")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r0", name=f"FFVideoFormat1080p{str(round(float(rate), 2)).replace('.', '')}",
                  frameDuration=_t(1, rate), width="1920", height="1080")
    assets: dict[str, str] = {}

    def asset(url: str, name: str, length: int, channels: int = 1) -> str:
        if url not in assets:
            aid = f"r{len(assets) + 1}"
            a = ET.SubElement(res, "asset", id=aid, name=name, start="0s", duration=_t(length, rate), hasAudio="1",
                              audioSources="1", audioChannels=str(channels), audioRate=str(sr))
            ET.SubElement(a, "media-rep", kind="original-media", src=url)
            assets[url] = aid
        return assets[url]

    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name=info.name or Path(info.source).stem)
    proj = ET.SubElement(ev, "project", name=f"{info.name or Path(info.source).stem} TH")
    seq = ET.SubElement(proj, "sequence", format="r0", duration=_t(dur, rate), tcStart=_t(start, rate),
                        tcFormat="DF" if info.drop_frame else "NDF", audioLayout="stereo", audioRate=f"{sr // 1000}k"
                        if sr % 1000 == 0 else f"{sr / 1000:g}k")
    spine = ET.SubElement(seq, "spine")
    gap = ET.SubElement(spine, "gap", name="Gap", offset=_t(start, rate), start=_t(start, rate), duration=_t(dur, rate))
    lane = 0
    for t in info.tracks:  # แทร็กเสียงเดิม
        if not t.clips:
            continue
        lane -= 1
        for k, c in enumerate(t.clips):
            url = media_url(c.media, "fcpxml")
            src_in = offsets.get((t.index, k), 0)
            aid = asset(url, Path(unquote(url)).name or c.name, max(src_in + c.end - c.start, 1))
            ET.SubElement(gap, "asset-clip", name=c.name, lane=str(lane), offset=_t(start + c.start, rate), ref=aid,
                          start=_t(src_in, rate), duration=_t(c.end - c.start, rate), audioRole="dialogue",
                          enabled="1" if t.enabled else "0")
    for spk, s in stems.items():  # แทร็กพากย์ไทย
        lane -= 1
        url = file_url(f"{folder}/{s['file']}", "fcpxml") if folder else f"{DUB_DIR}/{s['file']}"
        aid = asset(url, s["file"], dur)
        for a, b in s["runs"]:
            ET.SubElement(gap, "asset-clip", name=s["file"], lane=str(lane), offset=_t(start + a, rate),
                          ref=aid, start=_t(a, rate), duration=_t(b - a, rate), audioRole="dialogue.TH")
    ET.indent(root)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode"),
                    encoding="utf-8")


def clip_offsets(info: TimelineInfo, base: Path) -> dict:
    """เฟรมเริ่มในไฟล์ของทุกคลิป (หัก timecode ของไฟล์) ใช้เขียน FCPXML ที่อ้างไฟล์จากต้นไฟล์"""
    from .processor import clip_offset, probe
    metas: dict[str, dict] = {}
    out = {}
    for t in info.tracks:
        for k, c in enumerate(t.clips):
            if c.media_start is not None:
                out[(t.index, k)] = c.source_in - c.media_start
                continue
            meta = metas.setdefault(c.file, probe(base / c.file)) if c.file else {}
            out[(t.index, k)] = tc.frames_at(clip_offset(info, c, meta), info.rate)
    return out


# ---------------------------------------------------------------- README + zip
def readme(info: TimelineInfo, stems: dict, folder: Optional[str], files: list[str]) -> str:
    rate = f"{float(info.rate):.3f}".rstrip("0").rstrip(".")
    start = tc.to_timecode(info.start, info.rate, info.drop_frame)
    length = tc.to_timecode(info.duration, info.rate, info.drop_frame)
    where = (f"`{folder}/`" if folder else f"โฟลเดอร์ `{DUB_DIR}/` ข้างไฟล์ไทม์ไลน์")
    speakers = "\n".join(f"- `{s['file']}` — {s['label']}" for s in stems.values()) or "- (ไม่มี)"
    listing = "\n".join(f"- `{f}`" for f in files)
    return f"""# พากย์ไทย: {info.name or info.source}

| | |
|---|---|
| ไทม์ไลน์ต้นฉบับ | {info.source} |
| อัตราเฟรม | {rate} fps{" drop-frame" if info.drop_frame else ""} |
| timecode เริ่ม | {start} |
| ความยาว | {length} |
| sample rate | {info.sample_rate} Hz, 24-bit |

## ไฟล์ในชุดนี้
{listing}

เสียงพากย์แยกผู้พูด (ยาวเท่าไทม์ไลน์ เริ่มที่ {start} ทุกไฟล์ วางที่ต้นไทม์ไลน์แล้วตรงทุกประโยค):
{speakers}

## ก่อน import: วางไฟล์เสียงให้ตรงที่
ไฟล์ไทม์ไลน์ในชุดนี้อ้างไฟล์เสียงพากย์ที่ {where}
ย้ายไฟล์ `TH_*.wav` ไปไว้ที่นั่น โปรแกรมจะเจอไฟล์ทันที ถ้าวางที่อื่น ให้ relink (ชี้ไปที่โฟลเดอร์ที่วางไว้) ครั้งเดียว

## Premiere Pro
1. File > Import แล้วเลือก `timeline_TH.xml` จะได้ sequence ใหม่ชื่อ "... TH" มีแทร็กเดิมครบ + แทร็ก "TH - ชื่อผู้พูด"
2. ถ้าคลิปขึ้น Media Offline: คลิกขวาที่คลิป > Link Media แล้วเลือกไฟล์ `TH_*.wav`
3. ซับ: File > Import `TH_subtitles.srt` แล้วลากลงไทม์ไลน์ที่ต้นไทม์ไลน์

## DaVinci Resolve
1. File > Import > Timeline... เลือก `timeline_TH.fcpxml` (หรือ `timeline_TH.xml`)
2. ในหน้าต่างนำเข้า ติ๊ก "Automatically import source clips into media pool"
3. ไฟล์ขึ้นสีแดง (offline): คลิกขวาใน Media Pool > Relink Selected Clips แล้วเลือกโฟลเดอร์ที่วางไฟล์เสียง
4. ซับ: File > Import > Subtitle เลือก `TH_subtitles_tc.srt` (เวลาเริ่มที่ {start} ตรงกับไทม์ไลน์ของ Resolve)

## Final Cut Pro
1. File > Import > XML... เลือก `timeline_TH.fcpxml`
2. ไฟล์ offline: เลือกคลิป > File > Relink Files...

## ซับไตเติล
- `TH_subtitles.srt`: เวลานับจากต้นไทม์ไลน์ (00:00:00,000 = {start})
- `TH_subtitles_tc.srt`: เวลาตาม timecode ของไทม์ไลน์ (เริ่ม {start}) สำหรับโปรแกรมที่วางซับตาม timecode

## เสียงรวม
`TH_mixdown.wav` = เสียงพากย์ไทยทุกคน + เพลงและเสียงประกอบ (เสียงที่แยกออกจากแทร็กบทพูด และแทร็กที่ไม่ใช่บทพูด)
"""


def build(job_dir: Path, info: TimelineInfo, utterances: list, names: dict[str, str],
          formats: tuple[str, ...] = FORMATS, media_dir: Optional[str] = None) -> Path:
    """สร้าง zip ส่งออก คืนที่อยู่ไฟล์ zip"""
    from .importer import read
    from .processor import root

    bad = set(formats) - set(FORMATS)
    if bad:
        raise ValueError(f"ไม่รู้จักรูปแบบ {', '.join(sorted(bad))} เลือกได้ {', '.join(FORMATS)}")
    base = root(job_dir)
    out = base / "export"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    folder = dub_folder(info, media_dir)
    files: list[str] = []
    stems = write_stems(job_dir, info, names, out)
    if not stems:
        raise RuntimeError("ยังไม่มีเสียงพากย์ พากย์งานนี้ให้เสร็จก่อน")
    if "stems" in formats or "xml" in formats or "fcpxml" in formats:
        files += [s["file"] for s in stems.values()]
    if "mix" in formats and write_mix(job_dir, info, out):
        files.append("TH_mixdown.wav")
    if "srt" in formats:
        write_srt(utterances, out / "TH_subtitles.srt")
        write_srt(utterances, out / "TH_subtitles_tc.srt", info.sec(info.start))
        files += ["TH_subtitles.srt", "TH_subtitles_tc.srt"]
    if "xml" in formats or "fcpxml" in formats:
        timeline, _ = read(base / info.source, fps=info.fps, drop_frame=info.drop_frame)
        if "xml" in formats:
            write_fcp_xml(timeline, info, stems, folder, out / "timeline_TH.xml")
            files.append("timeline_TH.xml")
        if "fcpxml" in formats:
            write_fcpxml(timeline, info, base, stems, folder, out / "timeline_TH.fcpxml", clip_offsets(info, base))
            files.append("timeline_TH.fcpxml")
    (out / "README.md").write_text(readme(info, stems, folder, files), encoding="utf-8")
    zpath = base / f"{safe_name(Path(info.source).stem)}_TH.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(out / "README.md", "README.md", compress_type=zipfile.ZIP_DEFLATED)
        for f in files:
            z.write(out / f, f, compress_type=zipfile.ZIP_DEFLATED if f.endswith((".xml", ".fcpxml", ".srt")) else zipfile.ZIP_STORED)
    return zpath
