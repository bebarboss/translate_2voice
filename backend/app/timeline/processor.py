"""ประมวลผลงานไทม์ไลน์: วางเสียงของแต่ละแทร็กตามไทม์ไลน์ → ถอดเสียงทีละผู้พูด → แปล (แล้วพากย์ด้วยขั้นปกติของ runner)

แต่ละแทร็กเรนเดอร์เป็นไฟล์ยาวเท่าไทม์ไลน์ (ตัดจาก source in/out ของคลิป วางที่จุดเริ่มบนไทม์ไลน์) เวลาที่ถอดได้จึงเป็น
เวลาบนไทม์ไลน์ทันที ไม่ต้องแปลงกลับ ผู้พูดหนึ่งคนอาจมีหลายแทร็ก (รวมเสียงก่อนถอด) ถอดด้วย gpu.analyze
แบบระบุ 1 คน (บน Modal หรือเครื่องนี้) ซึ่งแยกเพลง/เสียงรบกวนออกจากแทร็กด้วย
ประโยคที่คร่อมรอยต่อคลิปถูกแบ่งตรงรอยต่อ เสียงพากย์ของแต่ละประโยคจึงไม่ล้นออกนอกคลิปเดิม
"""
import json
import logging
import subprocess
from collections import Counter
from math import gcd
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ..schemas import Utterance
from .model import TimelineInfo, TimelineTrack, load, save

log = logging.getLogger("dubbing.timeline")

WORK = "timeline"  # โฟลเดอร์ในงาน: ไฟล์ไทม์ไลน์ ไฟล์สื่อ (media/) เสียงที่เรนเดอร์ (render/) ผลวิเคราะห์ (analysis/)


def root(job_dir: Path) -> Path:
    return job_dir / WORK


# ---------------------------------------------------------------- ไฟล์สื่อ
def probe(path: Path) -> dict:
    """sample rate, จำนวนช่อง, ความยาว และเวลาเริ่มของไฟล์ (timecode ฝังในไฟล์ หรือ BWF time_reference) เป็นวินาที"""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate,channels:stream_tags=timecode:format=duration:format_tags=timecode,time_reference",
                          "-of", "json", str(path)], capture_output=True, text=True)
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or [{}]
    s = streams[0]
    fmt = data.get("format") or {}
    sr = int(s.get("sample_rate") or 0)
    tags = {**(fmt.get("tags") or {}), **(s.get("tags") or {})}
    start = None
    if tags.get("time_reference") and sr:  # BWF: จำนวน sample นับจากเที่ยงคืน
        start = int(tags["time_reference"]) / sr
    return {"sample_rate": sr, "channels": int(s.get("channels") or 0), "duration": float(fmt.get("duration") or 0),
            "timecode": tags.get("timecode"), "start": start, "has_audio": bool(data.get("streams"))}


def project_sample_rate(info: TimelineInfo, base: Path) -> int:
    """sample rate ของโปรเจกต์ (XML บอกไว้) ไม่บอก (EDL/OTIO) ใช้ของไฟล์เสียงแรก ไม่มีใช้ 48 kHz"""
    if info.sample_rate:
        return info.sample_rate
    for t in info.tracks:
        for c in t.clips:
            if c.file:
                sr = probe(base / c.file)["sample_rate"]
                if sr:
                    return sr
    return 48000


def decode(path: Path, sr: int, offset: float, duration: float, channel: Optional[int] = None,
           channels: int = 1) -> np.ndarray:
    """ตัดเสียงช่วง [offset, offset+duration) ของไฟล์ เป็น mono float32 ที่ sr
    channel: ใช้ช่องเดียว (คลิปที่ใช้ช่องซ้ายหรือขวาของไฟล์สเตอริโอ) None = รวมทุกช่อง"""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(offset, 0):.6f}", "-t", f"{duration:.6f}", "-i", str(path), "-vn"]
    if channel and channels > 1 and channel <= channels:
        cmd += ["-af", f"pan=mono|c0=c{channel - 1}"]
    else:
        cmd += ["-ac", "1"]
    cmd += ["-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(f"อ่านไฟล์เสียง {path.name} ไม่ได้: {out.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def clip_offset(info: TimelineInfo, c, meta: dict) -> float:
    """source in ของคลิป → วินาทีนับจากต้นไฟล์
    source in เขียนเป็น timecode ของต้นฉบับ: หักเวลาเริ่มของไฟล์ (ไทม์ไลน์บอก หรือ timecode/BWF ในไฟล์)"""
    from . import timecode as tc

    if c.media_start is not None:
        start = info.sec(c.media_start)
    elif meta.get("timecode"):
        try:
            start = info.sec(tc.from_timecode(meta["timecode"], info.rate))
        except ValueError:
            start = 0.0
    elif meta.get("start") is not None:
        start = meta["start"]
    else:
        start = 0.0
    offset = info.sec(c.source_in) - start
    if offset < 0 or (meta.get("duration") and offset >= meta["duration"]):
        # timecode ไม่ตรงกับไฟล์ (เช่น EDL เขียน source เป็น 01:00:10:00 แต่ไฟล์ไม่มี timecode) → นับจากต้นไฟล์
        alt = info.sec(c.source_in)
        if meta.get("duration") and 0 <= alt < meta["duration"]:
            return alt
        log.warning("clip %s: source in %.2fs is outside %s, using 0", c.name, offset, c.file)
        return 0.0
    return offset


def render_track(info: TimelineInfo, track: TimelineTrack, base: Path, sr: int) -> np.ndarray:
    """เสียงของแทร็กยาวเท่าไทม์ไลน์ คลิปวางตรงเฟรมเริ่ม ช่วงที่ไม่มีคลิปเงียบ"""
    n = round(info.seconds * sr)
    out = np.zeros(n, dtype=np.float32)
    metas: dict[str, dict] = {}
    for c in track.clips:
        if not c.file:
            raise RuntimeError(f"ไม่พบไฟล์ {c.name}")
        path = base / c.file
        meta = metas.setdefault(c.file, probe(path))
        if not meta["has_audio"]:
            raise RuntimeError(f"ไฟล์ {c.name} ไม่มีเสียง")
        a = round(info.sec(c.start) * sr)
        b = min(n, round(info.sec(c.end) * sr))
        if b <= a:
            continue
        seg = decode(path, sr, clip_offset(info, c, meta), (b - a) / sr, c.channel, meta["channels"])[: b - a]
        out[a: a + len(seg)] += seg
    return out


def resample(x: np.ndarray, sr: int, to: int) -> np.ndarray:
    if sr == to:
        return x
    from scipy.signal import resample_poly
    g = gcd(sr, to)
    return resample_poly(x, to // g, sr // g, axis=0).astype(np.float32)


def fit_length(x: np.ndarray, n: int) -> np.ndarray:
    """ตัดหรือเติมเงียบให้ยาว n sample พอดี"""
    if len(x) >= n:
        return x[:n]
    pad = np.zeros((n - len(x),) + x.shape[1:], dtype=x.dtype)
    return np.concatenate([x, pad])


# ---------------------------------------------------------------- ช่วงคลิปและประโยค
def speaker_spans(info: TimelineInfo) -> dict[str, list[tuple[float, float]]]:
    """ผู้พูด → ช่วงคลิปบนไทม์ไลน์ (วินาที) รวมช่วงที่ซ้อนหรือชิดกัน"""
    out: dict[str, list] = {}
    for t in info.dialogue():
        out.setdefault(t.speaker, []).extend((info.sec(c.start), info.sec(c.end)) for c in t.clips)
    for s, spans in out.items():
        merged: list[list[float]] = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 1e-3:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out[s] = [(a, b) for a, b in merged]
    return out


def span_of(spans: list[tuple[float, float]], t: float) -> Optional[int]:
    """ลำดับช่วงคลิปที่มีเวลา t (หรือใกล้ที่สุด)"""
    if not spans:
        return None
    for i, (a, b) in enumerate(spans):
        if a <= t < b:
            return i
    return min(range(len(spans)), key=lambda i: min(abs(t - spans[i][0]), abs(t - spans[i][1])))


def split_at_clips(utterances: list[Utterance], words: list, spans: list[tuple[float, float]]) -> list[Utterance]:
    """แบ่งประโยคที่คร่อมหลายคลิปตรงรอยต่อ (ใช้เวลาของคำ) และบีบเวลาประโยคให้อยู่ในคลิป"""
    out = []
    for u in utterances:
        mid = (u.start + u.end) / 2
        own = [w for w in words if u.start - 0.01 <= (w.start + w.end) / 2 <= u.end + 0.01]
        parts: dict[int, list] = {}
        for w in own:
            parts.setdefault(span_of(spans, (w.start + w.end) / 2), []).append(w)
        if len(parts) <= 1:
            i = span_of(spans, mid)
            a, b = spans[i] if i is not None else (u.start, u.end)
            start, end = max(u.start, a), min(u.end, b)
            if end - start >= 0.05:
                out.append(u.model_copy(update={"start": round(start, 3), "end": round(end, 3)}))
            continue
        for i in sorted(parts):
            ws = parts[i]
            a, b = spans[i]
            text = "".join(w.text for w in ws).strip()
            start, end = max(ws[0].start, a), min(ws[-1].end, b)
            if text and end - start >= 0.05:
                out.append(u.model_copy(update={"start": round(start, 3), "end": round(end, 3), "source": text}))
    return out


def _sum_audio(paths: list[Path], extra: list[tuple[np.ndarray, int]] = ()) -> tuple[np.ndarray, int]:
    """รวมไฟล์เสียงหลายไฟล์ (sample rate ของไฟล์แรก ช่องเสียงรวมเป็น mono) ยาวเท่าไฟล์ที่ยาวที่สุด"""
    parts, sr = [], None
    for p in paths:
        x, xsr = sf.read(p, dtype="float32")
        x = x.mean(axis=1) if x.ndim > 1 else x
        sr = sr or xsr
        parts.append(resample(x, xsr, sr))
    for x, xsr in extra:
        sr = sr or xsr
        parts.append(resample(x, xsr, sr))
    n = max(len(p) for p in parts)
    return sum(fit_length(p, n) for p in parts), sr


# ---------------------------------------------------------------- ขั้นวิเคราะห์ของงานไทม์ไลน์
def run_analyze(store, job_id: str) -> None:
    """เรียกจาก runner.run_analyze เมื่อ job.timeline"""
    from .. import accounts
    from ..pipeline import gpu, hallucination, runner
    from ..pipeline.diarize import export_speaker_stems, save_turns

    job = store.get(job_id)
    d = store.dir(job_id)
    base = root(d)
    stage = runner._stage(store, job_id)
    cancel = lambda: store.check_cancel(job_id)  # noqa: E731
    info = load(d)
    if info.missing:
        raise RuntimeError("ไฟล์สื่อยังไม่ครบ: " + ", ".join(info.missing))
    if not info.dialogue():
        raise RuntimeError("ไม่ได้เลือกแทร็กบทพูดไว้เลย")
    duration = round(info.seconds, 2)
    store.update(job_id, duration=duration)
    if job.owner:
        try:
            accounts.charge_job(job.owner, job_id, duration)
        except accounts.AccountError as e:
            raise RuntimeError(str(e)) from None

    # ---- วางเสียงแต่ละแทร็กตามไทม์ไลน์ (sample rate ของโปรเจกต์)
    stage("timeline_render", 0.02)
    sr = info.sample_rate = project_sample_rate(info, base)
    save(d, info)
    render = base / "render"
    render.mkdir(parents=True, exist_ok=True)
    tracks: dict[int, np.ndarray] = {}
    used = [t for t in info.tracks if t.clips and t.duplicate_of is None]
    for k, t in enumerate(used):
        cancel()
        tracks[t.index] = render_track(info, t, base, sr)
        sf.write(render / f"A{t.index}.wav", tracks[t.index], sr, subtype="FLOAT")
        stage("timeline_render", 0.02 + 0.04 * (k + 1) / len(used))
    mixed = sum(tracks.values())
    sf.write(d / "audio.wav", np.clip(mixed, -1, 1), sr)
    store.update(job_id, input_path=str(d / "audio.wav"))

    # ---- ถอดเสียงทีละผู้พูด
    spans = speaker_spans(info)
    speakers = info.speakers()
    results = {}
    for k, spk in enumerate(speakers):
        own = [t for t in info.dialogue() if t.speaker == spk and t.index in tracks]
        wav = render / f"{spk}.wav"
        sf.write(wav, np.clip(sum(tracks[t.index] for t in own), -1, 1), sr)
        work = base / "analysis" / spk
        work.mkdir(parents=True, exist_ok=True)
        lo, hi = 0.06 + 0.46 * k / len(speakers), 0.06 + 0.46 * (k + 1) / len(speakers)

        def sub(name: str, p: float, lo=lo, hi=hi) -> None:
            stage(name, lo + (hi - lo) * min(p / 0.55, 1.0))
        try:
            # แทร็กไทม์ไลน์แยกคนไว้แล้ว — ข้าม Demucs / pyannote ไปถอดเสียง+แปลเลย
            res = gpu.analyze(wav, work, job.source_lang, 1, sub, cancel, preseparated=True)
        except RuntimeError as e:
            if "ไม่พบคำพูด" not in str(e):
                raise
            log.info("timeline %s: no speech for %s", job_id, spk)
            continue
        gpu.release("audio", "diarize", "transcribe")
        for u in res["utterances"]:
            u.speaker = spk
        for t in res["turns"]:
            t.speaker = spk
        res["utterances"] = split_at_clips(res["utterances"], res["words"], spans.get(spk, []))
        results[spk] = res
    if not results:
        raise RuntimeError("ไม่พบคำพูดในแทร็กที่เลือก")

    # ---- รวมผลทุกผู้พูด: เสียงพูด เพลง/เสียงประกอบ คำ ประโยค
    stage("timeline_merge", 0.53)
    vocals, vsr = _sum_audio([r["vocals"] for r in results.values()])
    sf.write(d / "vocals.wav", np.clip(vocals, -1, 1), vsr)
    # เพลงและเสียงประกอบ = ส่วนที่แยกออกจากแทร็กบทพูด + แทร็กที่ไม่ใช่บทพูดทั้งแทร็ก
    other = [(tracks[t.index], sr) for t in used if not t.enabled]
    bgm, bsr = _sum_audio([r["bgm"] for r in results.values()], other)
    sf.write(d / "bgm.wav", np.clip(bgm, -1, 1), bsr)

    langs = Counter()
    for r in results.values():
        langs[r["lang"]] += len(r["utterances"])
    lang = job.source_lang or langs.most_common(1)[0][0]
    words = sorted((w for r in results.values() for w in r["words"]), key=lambda w: w.start)
    turns = sorted((t for r in results.values() for t in r["turns"]), key=lambda t: t.start)
    utterances, origin = [], {}
    for spk, r in results.items():
        for u in r["utterances"]:
            origin[id(u)] = (spk, u.id)
            utterances.append(u)
    utterances.sort(key=lambda u: (u.start, u.end))
    renumber = {}
    for i, u in enumerate(utterances, 1):
        renumber[origin[id(u)]] = i
        u.id = i
    _merge_features(d, base, results, renumber)

    export_speaker_stems(d / "vocals.wav", turns, d / "stems")
    save_turns(turns, d / "turns.json")
    (d / "words.json").write_text(json.dumps([w.__dict__ for w in words], ensure_ascii=False), encoding="utf-8")
    names = {t.speaker: t.name for t in info.dialogue()}
    store.update(job_id, speakers=speakers, detected_lang=lang,
                 speaker_names={**names, **store.get(job_id).speaker_names})
    utterances = hallucination.clean(utterances)
    store.save_transcript(job_id, utterances)
    log.info("timeline %s: %d lines from %d speakers (%s)", job_id, len(utterances), len(results), lang)
    runner._translate_and_fit(store, job_id, utterances, lang, 0.55, 0.72)


def _merge_features(d: Path, base: Path, results: dict, renumber: dict) -> None:
    """ค่าที่ Modal คำนวณไว้ตอนวิเคราะห์ (gpu_analysis.json) ของแต่ละผู้พูด รวมเป็นไฟล์เดียวด้วยเลขประโยคใหม่
    ประโยคที่ถูกแบ่งตรงรอยต่อคลิปเวลาไม่ตรงแล้ว ขั้นพากย์จะข้ามไปเอง (gpu.saved_lines เช็กเวลา)"""
    from ..pipeline.gpu import ANALYSIS_FILE

    lines, speech, found = {}, [], False
    for spk in results:
        f = base / "analysis" / spk / ANALYSIS_FILE
        if not f.exists():
            continue
        found = True
        data = json.loads(f.read_text(encoding="utf-8"))
        for old, x in data.get("lines", {}).items():
            new = renumber.get((spk, int(old)))
            if new is not None:
                lines[str(new)] = x
        speech += data.get("speech", [])
    if found:
        (d / ANALYSIS_FILE).write_text(json.dumps({"lines": lines, "speech": speech}), encoding="utf-8")


# ---------------------------------------------------------------- ใช้ตอนพากย์
def dub_part(info: TimelineInfo):
    """ฟังก์ชันสำหรับ runner._speech_groups: ประโยคต่างคลิปหรือต่างผู้พูด ห้ามรวมเป็นเสียงพากย์เดียว"""
    spans = speaker_spans(info)
    return lambda u: (u.speaker, span_of(spans.get(u.speaker, []), (u.start + u.end) / 2))


def clip_end(info: TimelineInfo, spans: dict, speaker: str, t: float) -> Optional[float]:
    """เวลาจบของคลิปที่ประโยคนี้อยู่ เสียงพากย์ห้ามเกินนี้"""
    s = spans.get(speaker) or []
    i = span_of(s, t)
    return s[i][1] if i is not None else None
