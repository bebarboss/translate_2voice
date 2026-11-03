"""นำเข้าไทม์ไลน์จากโปรแกรมตัดต่อ: Final Cut Pro XML (Premiere / Resolve), FCPXML (Resolve / Final Cut Pro), EDL, OTIO

อ่านโครงสร้างด้วย OpenTimelineIO แล้วอ่านค่าโปรเจกต์ที่ OTIO ไม่เก็บ (sample rate, drop-frame, timecode เริ่ม,
ไฟล์ของ asset ใน FCPXML) จากไฟล์ตรง ๆ EDL แปลงเองเป็นไทม์ไลน์ OTIO เพราะตัวอ่าน cmx_3600 ของ OTIO 0.18
วางคลิปของแทร็ก A2 ขึ้นไปผิดที่ (ไม่นับช่วงว่างก่อนคลิปแรกของแทร็ก)
ผลลัพธ์เป็น TimelineInfo เวลาทุกค่าเป็นเลขเฟรมตามอัตราเฟรมจริงของโปรเจกต์
"""
import logging
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
from urllib.parse import unquote, urlparse

from . import timecode as tc
from .model import TimelineClip, TimelineInfo, TimelineTrack

log = logging.getLogger("dubbing.timeline")

TIMELINE_EXT = {".xml": "fcp_xml", ".fcpxml": "fcpx_xml", ".edl": "edl", ".otio": "otio"}
MAX_ZIP_FILES = 2000


class TimelineError(Exception):
    """ไฟล์ไทม์ไลน์ใช้ไม่ได้ ข้อความแสดงให้ผู้ใช้เห็นได้เลย"""


# ---------------------------------------------------------------- zip
def extract_zip(zip_path: Path, dest: Path, max_bytes: int) -> list[Path]:
    """แตก zip ลง dest อย่างปลอดภัย (ไม่ยอมให้ชื่อไฟล์ออกนอก dest ไม่เกินขนาดที่กำหนด) คืนไฟล์ทั้งหมดที่ได้"""
    out = []
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise TimelineError("ไฟล์ zip เสียหรือไม่ใช่ zip") from None
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_FILES:
            raise TimelineError(f"zip มีไฟล์เกิน {MAX_ZIP_FILES} ไฟล์")
        if sum(i.file_size for i in infos) > max_bytes:
            raise TimelineError(f"ไฟล์ใน zip รวมกันใหญ่เกิน {max_bytes // 2**20} MB")
        root = dest.resolve()
        for i in infos:
            parts = PurePosixPath(i.filename.replace("\\", "/")).parts
            if not parts or parts[0] == "__MACOSX" or parts[-1].startswith("._") or parts[-1] == ".DS_Store":
                continue
            target = (root / Path(*parts)).resolve()
            if root not in target.parents:
                raise TimelineError(f"ชื่อไฟล์ใน zip ไม่ปลอดภัย: {i.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(target)
    return out


def find_timeline(files: list[Path], name: Optional[str] = None) -> Path:
    """หาไฟล์ไทม์ไลน์ในไฟล์ที่แตกจาก zip (name = เลือกเองเมื่อมีหลายไฟล์)"""
    found = [f for f in files if f.suffix.lower() in TIMELINE_EXT and _sniff(f)]
    if name:
        found = [f for f in found if f.name == name]
    if not found:
        raise TimelineError(f"ไม่พบไฟล์ไทม์ไลน์ ({', '.join(sorted(TIMELINE_EXT))}) ใน zip" + (f" ชื่อ {name}" if name else ""))
    if len(found) > 1:
        raise TimelineError("zip มีไฟล์ไทม์ไลน์หลายไฟล์ ระบุชื่อไฟล์ที่ต้องการใน timeline_name: "
                            + ", ".join(sorted(f.name for f in found)))
    return found[0]


def _sniff(path: Path) -> bool:
    """.xml ทั่วไป (เช่น metadata ของกล้อง) ไม่ใช่ไทม์ไลน์ ดูว่ามีแท็ก xmeml"""
    if path.suffix.lower() != ".xml":
        return True
    with path.open("rb") as f:
        return b"<xmeml" in f.read(4096)


# ---------------------------------------------------------------- อ่านไฟล์
def detect_format(path: Path) -> str:
    fmt = TIMELINE_EXT.get(path.suffix.lower())
    if fmt is None:
        raise TimelineError(f"ไม่รองรับไฟล์ {path.suffix} รองรับ {', '.join(sorted(TIMELINE_EXT))}")
    if fmt == "fcp_xml":
        head = path.read_bytes()[:4096]
        if b"<fcpxml" in head:
            return "fcpx_xml"
        if b"<xmeml" not in head:
            raise TimelineError("ไฟล์ .xml นี้ไม่ใช่ Final Cut Pro XML (ไม่พบแท็ก xmeml)")
    return fmt


def read(path: Path, fps: Optional[float] = None, drop_frame: Optional[bool] = None) -> tuple[object, TimelineInfo]:
    """คืน (ไทม์ไลน์ OTIO, ข้อมูลไทม์ไลน์) ยังไม่หาไฟล์สื่อ (resolve_media)
    fps: จำเป็นสำหรับ EDL ที่ไม่ได้บอกอัตราเฟรม, drop_frame: บังคับ drop-frame (None = ดูจากไฟล์)"""
    import opentimelineio as otio

    fmt = detect_format(path)
    meta: dict = {}
    try:
        if fmt == "edl":
            timeline, meta = read_edl(path.read_text(encoding="utf-8-sig", errors="replace"), fps)
        else:
            adapter = {"fcp_xml": "fcp_xml", "fcpx_xml": "fcpx_xml", "otio": "otio_json"}[fmt]
            timeline = otio.adapters.read_from_file(str(path), adapter)
            if isinstance(timeline, otio.schema.SerializableCollection):
                found = list(timeline.find_children(descended_from_type=otio.schema.Timeline))
                if not found:
                    raise TimelineError("ไม่พบไทม์ไลน์ (sequence) ในไฟล์")
                if len(found) > 1:
                    log.warning("%s has %d timelines, using the first", path.name, len(found))
                timeline = found[0]
            meta = _xml_meta(path, fmt)
    except TimelineError:
        raise
    except Exception as e:  # noqa: BLE001  ไฟล์เสีย หรือรูปแบบที่ OTIO อ่านไม่ได้
        raise TimelineError(f"อ่านไฟล์ไทม์ไลน์ไม่ได้: {e}") from None
    return timeline, build_info(timeline, fmt, path.name, meta, fps, drop_frame)


def _seconds_attr(v: Optional[str]) -> Optional[Fraction]:
    """ค่าเวลาของ FCPXML เช่น "90000/25s", "10s", "1001/30000s" """
    if not v:
        return None
    v = v.strip().rstrip("s")
    try:
        return Fraction(v)
    except (ValueError, ZeroDivisionError):
        return None


def _xml_meta(path: Path, fmt: str) -> dict:
    """ค่าที่ OTIO ไม่เก็บไว้ อ่านจาก XML ตรง ๆ"""
    if fmt == "otio":
        return {}
    root = ET.parse(path).getroot()
    seq = root.find(".//sequence")
    meta: dict = {}
    if seq is None:
        return meta
    if fmt == "fcp_xml":
        sr = seq.find("media/audio/format/samplecharacteristics/samplerate")
        if sr is not None and (sr.text or "").strip().isdigit():
            meta["sample_rate"] = int(sr.text)
        df = seq.find("timecode/displayformat")
        if df is not None:
            meta["drop_frame"] = (df.text or "").strip().upper() == "DF"
        return meta
    # FCPXML: อัตราเฟรมจาก format, timecode เริ่ม, ไฟล์ของ asset
    formats = {f.get("id"): f for f in root.iter("format")}
    f = formats.get(seq.get("format"))
    dur = _seconds_attr(f.get("frameDuration")) if f is not None else None
    if dur:
        meta["rate"] = 1 / dur
    start = _seconds_attr(seq.get("tcStart"))
    if start is not None:
        meta["start_sec"] = start
    total = _seconds_attr(seq.get("duration"))
    if total is not None:
        meta["duration_sec"] = total
    meta["drop_frame"] = (seq.get("tcFormat") or "").upper() == "DF"
    rate = (seq.get("audioRate") or "").lower().rstrip("k")
    try:
        meta["sample_rate"] = int(float(rate) * 1000) if rate else None
    except ValueError:
        pass
    assets = {}
    for a in root.iter("asset"):
        rep = a.find("media-rep")
        src = rep.get("src") if rep is not None else a.get("src")
        if src:
            assets[a.get("name") or ""] = src
            assets[a.get("id") or ""] = src
    meta["assets"] = assets
    return meta


# ---------------------------------------------------------------- EDL (CMX 3600)
_EVENT = re.compile(r"^(\d{1,6})\s+(\S+)\s+(\S+)\s+([CDW]\S*|K\s*B?|K\s*O)\s+(\d+\s+)?"
                    r"(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s+(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s+"
                    r"(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s+(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s*$")


def _edl_channels(field: str) -> list[int]:
    """ช่องเสียงของ event: A = A1, A2, AA = A1+A2, A/V, AA/V, NONE/V = ไม่มีเสียง"""
    f = field.upper()
    out = []
    for part in f.split("/"):
        if part == "A":
            out.append(1)
        elif part == "AA":
            out += [1, 2]
        elif m := re.fullmatch(r"A(\d+)", part):
            out.append(int(m.group(1)))
    return sorted(set(out))


def read_edl(text: str, fps: Optional[float]) -> tuple[object, dict]:
    """แปลง EDL เป็นไทม์ไลน์ OTIO เฉพาะแทร็กเสียง (A, A2, ...) เวลาบันทึก (record) เป็นที่วางบนไทม์ไลน์"""
    import opentimelineio as otio

    drop = "DROP FRAME" in text.upper() and "NON-DROP FRAME" not in text.upper()
    if fps is None:
        if not drop:
            raise TimelineError("EDL ไม่ได้บอกอัตราเฟรม ระบุ fps ด้วย (เช่น 23.976, 24, 25, 29.97)")
        fps = 29.97
    rate = tc.exact_rate(fps)
    title, events = "", []
    for line in text.splitlines():
        line = line.rstrip()
        if line.upper().startswith("TITLE:"):
            title = line.split(":", 1)[1].strip()
            continue
        m = _EVENT.match(line.strip())
        if m:
            _, reel, chan, _, _, s_in, s_out, r_in, r_out = m.groups()
            channels = _edl_channels(chan)
            if channels:
                events.append({"reel": reel, "channels": channels, "src": (tc.from_timecode(s_in, rate), tc.from_timecode(s_out, rate)),
                               "rec": (tc.from_timecode(r_in, rate), tc.from_timecode(r_out, rate)), "name": reel, "file": ""})
            else:
                events.append(None)  # event ภาพอย่างเดียว คอมเมนต์ที่ตามมาไม่ใช้
            continue
        c = line.strip()
        if events and events[-1] is not None and c.startswith("*"):
            key, _, value = c[1:].partition(":")
            key, value = key.strip().upper(), value.strip()
            if key == "FROM CLIP NAME":
                events[-1]["name"] = value
            elif key in ("SOURCE FILE", "SOURCE FILE NAME"):
                events[-1]["file"] = value
    events = [e for e in events if e]
    if not events:
        raise TimelineError("EDL ไม่มี event ของเสียง (ช่อง A, A2, AA ...)")
    start = min(e["rec"][0] for e in events)
    end = max(e["rec"][1] for e in events)
    r = float(rate)
    timeline = otio.schema.Timeline(name=title)
    timeline.global_start_time = otio.opentime.RationalTime(start, r)
    for ch in sorted({c for e in events for c in e["channels"]}):
        track = otio.schema.Track(name=f"A{ch}", kind=otio.schema.TrackKind.Audio)
        cursor = start
        for e in sorted((e for e in events if ch in e["channels"]), key=lambda e: e["rec"][0]):
            a, b = e["rec"]
            if a < cursor:  # ทับคลิปก่อนหน้า (EDL ที่มีการเปลี่ยนภาพแบบ dissolve) ตัดหัวคลิปนี้
                e = {**e, "src": (e["src"][0] + cursor - a, e["src"][1])}
                a = cursor
            if b <= a:
                continue
            if a > cursor:
                track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(
                    duration=otio.opentime.RationalTime(a - cursor, r))))
            ref = otio.schema.ExternalReference(target_url=e["file"] or e["name"])
            clip = otio.schema.Clip(name=e["name"], media_reference=ref, source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(e["src"][0], r), otio.opentime.RationalTime(b - a, r)))
            clip.metadata["edl"] = {"reel": e["reel"], "channel": ch}
            track.append(clip)
            cursor = b
        timeline.tracks.append(track)
    return timeline, {"rate": rate, "drop_frame": drop, "start": start, "duration": end - start, "edl": True}


# ---------------------------------------------------------------- โครงสร้าง
def _rate_of(timeline) -> Optional[float]:
    for clip in timeline.find_clips():
        if clip.source_range is not None:
            return clip.source_range.duration.rate
    d = timeline.duration()
    return d.rate if d.value else None


def _frames(rt, rate: Fraction) -> int:
    if abs(rt.rate - float(rate)) < 0.01:
        return round(rt.value)
    return round(Fraction(rt.to_seconds()).limit_denominator(10**7) * rate)


def build_info(timeline, fmt: str, source: str, meta: dict, fps: Optional[float] = None,
               drop_frame: Optional[bool] = None) -> TimelineInfo:
    import opentimelineio as otio

    rate = meta.get("rate") or (tc.exact_rate(fps) if fps else None)
    if rate is None:
        r = _rate_of(timeline)
        if not r:
            raise TimelineError("หาอัตราเฟรมของไทม์ไลน์ไม่ได้ ระบุ fps ด้วย")
        rate = tc.exact_rate(r)
    rate = Fraction(rate)
    if fps and abs(float(rate) - fps) > 0.01:
        log.warning("fps %s differs from timeline rate %s, using the timeline's", fps, float(rate))
    drop = meta.get("drop_frame", False) if drop_frame is None else drop_frame
    drop = bool(drop) and tc.can_drop(rate)

    # จุดเริ่มของไทม์ไลน์: FCPXML เขียนตำแหน่งคลิปรวม tcStart ไว้ด้วย ต้องหักออก
    offset = 0
    if "start_sec" in meta:
        start = tc.frames_at(float(meta["start_sec"]), rate)
        offset = start
    elif "start" in meta:
        start = meta["start"]
    elif timeline.global_start_time is not None:
        start = _frames(timeline.global_start_time, rate)
    else:
        start = 0
    if "duration_sec" in meta:
        duration = tc.frames_at(float(meta["duration_sec"]), rate)
    elif "duration" in meta:
        duration = meta["duration"]
    else:
        duration = _frames(timeline.duration(), rate) - offset

    info = TimelineInfo(format=fmt, source=source, name=timeline.name or "", rate_num=rate.numerator,
                        rate_den=rate.denominator, drop_frame=drop, sample_rate=meta.get("sample_rate") or 0,
                        start=start, duration=max(duration, 0))
    assets = meta.get("assets") or {}
    audio = [t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Audio]
    for n, track in enumerate(audio, 1):
        name = (track.name or "").strip()
        if not name or re.fullmatch(r"-?\d+", name):  # FCPXML ตั้งชื่อแทร็กเป็นเลข lane
            name = f"A{n}"
        t = TimelineTrack(index=n, name=name)
        for item in track:
            if isinstance(item, otio.schema.Stack):
                info.warnings.append(f"แทร็ก {name}: มีคลิปซ้อน (nested sequence/compound clip) ข้ามไป กรุณาแตกออกก่อนส่งออก")
                continue
            if not isinstance(item, otio.schema.Clip) or not item.enabled:
                continue
            rr = item.range_in_parent()
            a = _frames(rr.start_time, rate) - offset
            b = a + _frames(rr.duration, rate)
            sr = item.source_range or item.trimmed_range()
            s_in = _frames(sr.start_time, rate)
            ref = item.media_reference
            media, media_start = "", None
            if isinstance(ref, otio.schema.ExternalReference):
                media = ref.target_url or ""
                if ref.available_range is not None:
                    media_start = _frames(ref.available_range.start_time, rate)
            if not media:
                media = assets.get(item.name, "") or item.name
            if any(isinstance(e, otio.schema.LinearTimeWarp) or isinstance(e, otio.schema.FreezeFrame)
                   for e in item.effects):
                info.warnings.append(f"แทร็ก {name}: คลิป {item.name} มีการปรับความเร็ว ระบบใช้ความเร็วปกติ")
            fcp = item.metadata.get("fcp_xml") or {}
            channel = None
            st = fcp.get("sourcetrack") if hasattr(fcp, "get") else None  # OTIO เก็บเป็น AnyDictionary ไม่ใช่ dict
            if hasattr(st, "get") and str(st.get("trackindex", "")).isdigit():
                channel = int(st["trackindex"])
            t.clips.append(TimelineClip(name=item.name, media=media, start=a, end=b, source_in=s_in,
                                        source_out=s_in + (b - a), media_start=media_start, channel=channel))
        info.tracks.append(t)
    if not any(t.clips for t in info.tracks):
        raise TimelineError("ไทม์ไลน์ไม่มีคลิปเสียง")
    _mark_duplicates(info)
    _default_speakers(info)
    return info


def _mark_duplicates(info: TimelineInfo) -> None:
    """แทร็กที่คลิปเหมือนแทร็กก่อนหน้าทุกคลิป (ไฟล์ ช่องเสียง และเวลาเดียวกัน) = สำเนา เช่นเสียงสเตอริโอที่แยกเป็นสองแทร็ก
    ปิดไว้ก่อน ไม่งั้นถอดและพากย์ซ้ำสองรอบ ถ้าเป็นช่องซ้าย/ขวาคนละช่องไม่ถือว่าซ้ำ (มักเป็นไมค์คนละคน)"""
    def key(t: TimelineTrack):
        return [(c.media, c.start, c.end, c.source_in, c.channel) for c in t.clips]
    seen: dict = {}
    for t in info.tracks:
        if not t.clips:
            continue
        k = repr(key(t))
        if k in seen:
            t.duplicate_of, t.enabled = seen[k], False
        else:
            seen[k] = t.index


def _default_speakers(info: TimelineInfo) -> None:
    """ตั้งต้น: หนึ่งแทร็ก = หนึ่งผู้พูด (ผู้ใช้รวมหลายแทร็กเป็นคนเดียวได้ภายหลัง)"""
    n = 0
    for t in info.tracks:
        if t.clips and t.duplicate_of is None:
            n += 1
            t.speaker = f"speaker_{n:02d}"
        elif t.duplicate_of is not None:
            t.speaker = next(x.speaker for x in info.tracks if x.index == t.duplicate_of)


# ---------------------------------------------------------------- ไฟล์สื่อ
def media_basename(media: str) -> str:
    """ชื่อไฟล์จากที่อยู่ในไทม์ไลน์: file://localhost/D%3a/x/A.wav, file:///Volumes/x/A.wav, D:\\x\\A.wav, A.wav"""
    m = media.strip()
    if m.lower().startswith("file:"):
        m = unquote(urlparse(m).path)
    else:
        m = unquote(m)
    return PureWindowsPath(m).name if "\\" in m else PurePosixPath(m).name


def resolve_media(info: TimelineInfo, root: Path, exclude: Optional[Path] = None) -> TimelineInfo:
    """จับคู่คลิปกับไฟล์ที่อัปโหลดมา (ชื่อไฟล์ ไม่สนตัวพิมพ์เล็กใหญ่ ค้นทุกโฟลเดอร์ย่อยใน root)
    ไฟล์ที่ไม่เจอเก็บใน info.missing"""
    index: dict[str, Path] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file() and f != exclude and f.suffix.lower() not in TIMELINE_EXT:
            index.setdefault(f.name.lower(), f)
    missing = []
    for t in info.tracks:
        for c in t.clips:
            names = [media_basename(c.media), c.name]
            hit = next((index[n.lower()] for n in names if n and n.lower() in index), None)
            c.file = str(hit.relative_to(root)).replace("\\", "/") if hit else None
            if hit is None:
                label = media_basename(c.media) or c.name
                if label not in missing:
                    missing.append(label)
    info.missing = missing
    return info
