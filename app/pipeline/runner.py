"""ร้อยทุกขั้นเข้าด้วยกัน

run_analyze    : (ดาวน์โหลดลิงก์) → ดึงเสียง → แยกเสียงพูด/เพลง → แยกผู้พูด → ถอดเสียง → แปล → ย่อบท
run_synthesize : พากย์ (ใช้เสียงเดิมกับประโยคที่ไม่ได้แก้) → ผสมเสียง → รวมวิดีโอ → ซับ
run_render     : ฝังซับลงวิดีโอใหม่อย่างเดียว (หลังเปลี่ยนรูปแบบซับ)

ขั้นที่ใช้การ์ดจอเรียกผ่าน gpu.py ซึ่งรันบนเครื่องนี้หรือบน Modal ตาม WORKER
"""
import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from .. import runtime_settings
from ..config import settings
from ..jobs import JobStore
from ..schemas import SynthStats
from . import audio, gpu, mix, pauses, subs, tts
from .diarize import export_speaker_stems, load_turns, overlap_ratio, save_turns

log = logging.getLogger("dubbing.runner")


def _impl():
    """คืนฟังก์ชันแปลจริง หรือชุดทดสอบเมื่อเปิด MOCK_PIPELINE (ขั้นที่ใช้การ์ดจออยู่ใน gpu.py)"""
    if settings.mock_pipeline:
        from . import mock
        return mock.translate_utterances, mock.fit_lengths
    from . import translate
    return translate.translate_utterances, translate.fit_lengths


_free_vram = gpu.release


def _stage(store: JobStore, job_id: str):
    def update(name: str, progress: float) -> None:
        store.check_cancel(job_id)
        store.update(job_id, stage=name, progress=round(progress, 3))
    return update


# ---------------------------------------------------------------- analyze
def run_analyze(store: JobStore, job_id: str) -> None:
    translate, fit_lengths = _impl()
    job = store.get(job_id)
    d = store.dir(job_id)
    stage = _stage(store, job_id)
    cancel = lambda: store.check_cancel(job_id)  # noqa: E731
    rs = runtime_settings.get()

    if job.source_url and not (job.input_path and Path(job.input_path).exists()):
        from .download import download
        stage("download", 0.01)
        path, title, _ = download(job.source_url, d, cancel,
                                  lambda f: store.update(job_id, progress=round(0.01 + 0.05 * f, 3)))
        store.update(job_id, input_path=str(path), filename=f"{title}.mp4")
        job = store.get(job_id)

    video = Path(job.input_path)
    duration = round(audio.probe_duration(video), 2)
    store.update(job_id, duration=duration)
    if job.owner:  # งานของผู้ใช้ที่ล็อกอิน: ตัดนาทีก่อนเริ่มใช้การ์ดจอ เมื่อเปิดระบบเก็บเงิน (ไม่พอ = งานล้มพร้อมบอกเหตุผล)
        from .. import accounts
        try:
            accounts.charge_job(job.owner, job_id, duration)
        except accounts.AccountError as e:
            raise RuntimeError(str(e)) from None

    stage("extract_audio", 0.06)
    mixed = audio.extract_audio(video, d / "audio.wav")

    # แยกเสียงพูด/เพลง → แยกผู้พูด → ถอดเสียง (บนเครื่องนี้หรือ Modal ตาม WORKER)
    res = gpu.analyze(mixed, d, job.source_lang, job.num_speakers, stage, cancel)
    turns, words, lang, utterances = res["turns"], res["words"], res["lang"], res["utterances"]
    export_speaker_stems(res["vocals"], turns, d / "stems")
    save_turns(turns, d / "turns.json")
    store.update(job_id, speakers=res["speakers"])
    # เก็บเวลาของแต่ละคำไว้ เผื่อแบ่งท่อนใหม่ภายหลัง
    (d / "words.json").write_text(json.dumps([w.__dict__ for w in words], ensure_ascii=False), encoding="utf-8")
    store.update(job_id, detected_lang=lang)
    store.save_transcript(job_id, utterances)

    stage("translate", 0.55)
    translate(utterances, lang, job.target_lang,
              on_progress=lambda f: stage("translate", 0.55 + 0.13 * f), check_cancel=cancel,
              title=Path(job.filename or "").stem)
    _free_vram("translate")
    store.save_transcript(job_id, utterances)

    stage("fit_lengths", 0.69)
    fit_lengths(utterances, job.target_lang, rs.max_speedup)
    store.save_transcript(job_id, utterances)
    stage("analyzed", 0.72)


# ---------------------------------------------------------------- synthesize
def _clip_key(**parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _take_file(tts_dir: Path, uid: int, key: str) -> Path:
    """สำเนาเสียงพากย์ของแต่ละรอบ (ตามคีย์) ผู้ใช้สุ่มใหม่แล้วอยากกลับไปใช้รอบก่อน จะได้ไม่ต้องพากย์ซ้ำ"""
    return tts_dir / f"{uid:04d}.{key[:12]}.wav"


def _load_cached(tts_dir: Path, uid: int, key: str):
    meta, wav = tts_dir / f"{uid:04d}.json", tts_dir / f"{uid:04d}.wav"
    try:
        if not (meta.exists() and wav.exists() and json.loads(meta.read_text(encoding="utf-8")).get("key") == key):
            wav = _take_file(tts_dir, uid, key)
            if not wav.exists():
                return None
        data, _ = sf.read(wav, dtype="float32")
        return data
    except (ValueError, OSError, RuntimeError):
        return None


def _load_words(d: Path) -> Optional[list]:
    """เวลาของแต่ละคำในเสียงต้นฉบับที่ขั้นวิเคราะห์เก็บไว้ งานเก่าที่ไม่มีไฟล์คืน None"""
    from .common import Word
    try:
        return [Word(**w) for w in json.loads((d / "words.json").read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return None


def _pause_holes(g: list, p, orig: np.ndarray, sr: int, words: Optional[list]) -> list[tuple[float, float]]:
    """ช่วงหยุดระหว่างช่วงพูดของประโยค (ตามที่ตัดไว้ตอนพากย์ ประโยคที่ใช้เสียงเดิมจากแคชคำนวณใหม่ ผลเท่ากัน)"""
    chunks = getattr(p, "chunks", None) or pauses.plan(g, orig, sr, settings.min_pause_sec, words=words)
    return [(a.end, b.start) for a, b in zip(chunks, chunks[1:]) if b.start > a.end]


def _speech_groups(utts: list, max_gap: float = 0.6, max_span: float = 12.0,
                   voices_: Optional[dict] = None, pinned: frozenset = frozenset(),
                   mood=lambda u: "") -> list[list]:
    """รวมท่อนที่พูดต่อกันเป็นประโยคเดียว (คนเดิม เว้นไม่เกิน max_gap และท่อนก่อนยังไม่จบประโยค) แล้วพากย์รวดเดียว

    ถ้าพากย์ทีละท่อน ทุกท่อนจะลงเสียงเหมือนจบประโยคและขาดเป็นช่วง ๆ ฟังไม่ต่อเนื่อง
    จำกัดความยาวรวมไว้ เพราะ F5-TTS พูดยาวเกินไปจะเพี้ยนและใช้หน่วยความจำการ์ดจอมาก
    voices_: ไม่รวมท่อนที่เสียงต่างกันชัด (ระบบแยกผู้พูดอาจรวมเด็กกับผู้ใหญ่เป็นคนเดียว) ไม่งั้นทั้งคู่จะได้เสียงตัวอย่างเดียวกัน
    pinned: ผู้พูดที่ผู้ใช้เลือกเสียงจากคลังให้ ท่อนของคนนี้ห้ามไปรวมกับคนอื่น (และกลับกัน) ไม่งั้นได้เสียงผิดตัว
    mood: อารมณ์ที่ใช้พากย์ของแต่ละท่อน ท่อนต่างอารมณ์ใช้เสียงตัวอย่างคนละอัน จึงไม่รวมกัน
    """
    from .transcribe import SENTENCE_END
    from .voices import clearly_different, of_run

    groups: list[list] = []
    for u in utts:
        g = groups[-1] if groups else None
        if (g and u.speaker == g[-1].speaker and u.start - g[-1].end <= max_gap
                and u.end - g[0].start <= max_span and not g[-1].source.strip().endswith(SENTENCE_END)
                and mood(u) == mood(g[-1])
                and not clearly_different(of_run([g[-1]], voices_), of_run([u], voices_))):
            g.append(u)
        else:
            groups.append([u])

    # ท่อนสั้นมาก (คำเดียว) F5-TTS พากย์เดี่ยว ๆ แล้วมักได้เสียงมั่ว และมักเป็นหัวหรือหางประโยคที่ถูกแยกผู้พูดผิด
    # → ต่อเข้ากับประโยคที่ติดกัน ยกเว้นเสียงต่างกันชัด (อีกคนพูดแทรก เช่น "Mom!") ให้พากย์ด้วยเสียงตัวเอง
    def differ(a, b) -> bool:
        if a[0].speaker != b[0].speaker and (a[0].speaker in pinned or b[0].speaker in pinned):
            return True
        if mood(a[0]) != mood(b[0]):
            return True
        return clearly_different(of_run(a, voices_), of_run(b, voices_))
    merged: list[list] = []
    for i, g in enumerate(groups):
        if len(g) == 1 and g[0].duration < 0.8:
            nxt = groups[i + 1] if i + 1 < len(groups) else None
            if nxt and nxt[0].start - g[0].end <= 0.3 and not differ(g, nxt):
                nxt.insert(0, g[0])
                continue
            if merged and g[0].start - merged[-1][-1].end <= 0.3 and not differ(g, merged[-1]):
                merged[-1].append(g[0])
                continue
        merged.append(g)
    return merged


def _group_speaker(g: list) -> str:
    """ผู้พูดหลักของประโยค (ท่อนสั้นที่ต่อเข้ามาอาจถูกแยกผู้พูดผิด)"""
    return max(g, key=lambda u: u.duration).speaker


def _library_refs(job, voice_store, target: str) -> dict[str, dict[str, tuple[str, Path, str, list]]]:
    """ผู้พูด → อารมณ์ ("" = ปกติ) → (คีย์เสียงตัวอย่าง, ไฟล์, ข้อความในเสียงนั้น, ส่วนของคีย์แคช) ของเสียงในคลังที่ผู้ใช้เลือก
    เสียงที่ถูกลบหรือยังไม่พร้อม ใช้เสียงต้นฉบับแทน อารมณ์ที่ยังไม่พร้อมไม่มีในรายการ (ประโยคนั้นใช้เสียงปกติ)"""
    out = {}
    for speaker, voice_id in job.voice_map.items():
        v = voice_store.get(voice_id) if voice_store else None
        path = voice_store.ref_path(voice_id) if v else None
        if v is None or v.status != "ready" or not path.exists():
            log.warning("speaker %s: library voice %s unavailable, using original voice", speaker, voice_id)
            continue
        # เสียงในคลังเป็นภาษาไทย พากย์อังกฤษต้องเขียนข้อความเป็นอักษรละติน
        refs = {"": (voice_id, path, tts.reference_text(v.text, "th", target), ["library", voice_id, v.text])}
        for m in v.moods:
            mpath = voice_store.ref_path(voice_id, m.mood)
            if m.status == "ready" and m.text and mpath.exists():
                refs[m.mood] = (f"{voice_id}:{m.mood}", mpath, tts.reference_text(m.text, "th", target),
                                ["library", voice_id, m.mood, m.text])
        out[speaker] = refs
    return out


@dataclass
class _Plan:
    """ประโยคหนึ่ง (ท่อนที่พูดต่อกันของคนเดียว) ที่ต้องพากย์"""
    i: int  # ลำดับในกลุ่มประโยคทั้งหมด
    g: list
    speaker: str
    slot: float
    limit_sec: float
    max_speedup: float
    max_slowdown: float
    ref: dict  # {"ref": id เสียงในคลัง} หรือ {"ref_start", "ref_end"} ช่วงที่ตัดจาก vocals
    ref_text: str
    ref_key: list
    chunks: list = field(default_factory=list)
    voice: Optional[np.ndarray] = None

    def text(self) -> str:
        return " ".join(u.target.strip() for u in self.g)


def run_synthesize(store: JobStore, job_id: str, voice_store=None) -> None:
    job = store.get(job_id)
    d = store.dir(job_id)
    stage = _stage(store, job_id)
    cancel = lambda: store.check_cancel(job_id)  # noqa: E731
    rs = runtime_settings.get()
    target = job.target_lang
    source_lang = job.detected_lang or job.source_lang or ""
    utterances = sorted(store.load_transcript(job_id), key=lambda u: u.start)
    if not utterances:
        raise RuntimeError("ไม่มีบทให้พากย์")

    video = Path(job.input_path)
    total = audio.probe_duration(video)
    vocals = d / "vocals.wav"
    refs_dir, tts_dir = d / "refs", d / "tts"
    refs_dir.mkdir(exist_ok=True)
    tts_dir.mkdir(exist_ok=True)
    sr = tts.SAMPLE_RATE

    by_speaker = defaultdict(list)
    for u in utterances:
        by_speaker[u.speaker].append(u)

    can_shorten = bool(settings.typhoon_api_key) and not settings.mock_pipeline
    match_prosody = settings.prosody_match and not settings.mock_pipeline
    orig, orig_sr = sf.read(vocals, dtype="float32")
    orig = orig.mean(axis=1) if orig.ndim > 1 else orig
    if match_prosody:
        from . import prosody

    # คะแนนความสะอาดของเสียงต้นฉบับแต่ละท่อน ใช้คัดเสียงตัวอย่าง
    ref_quality = None
    turns = load_turns(d)  # ช่วงพูดของแต่ละคน ใช้หาช่วงที่พูดซ้อนกัน
    if settings.ref_min_quality > 0 and not settings.mock_pipeline:
        ref_quality = gpu.ref_quality(d, utterances, orig, orig_sr)
        # ท่อนที่มีคนอื่นพูดซ้อน ใช้เป็นเสียงตัวอย่างแล้ว F5-TTS จะได้เสียงผสมสองคน → หักคะแนน
        if ref_quality and turns:
            for u in utterances:
                ov = overlap_ratio(u.start, u.end, turns)
                if ov > 0.05 and u.id in ref_quality:
                    ref_quality[u.id] = round(ref_quality[u.id] - 3 * ov, 2)
        log.info("ref quality: %s", ref_quality)
    # ความตื่นเต้นของแต่ละท่อนเทียบกับเสียงปกติของตัวละครนั้น ใช้เลือกเสียงตัวอย่างและขีดเร่ง/ยืด
    ref_arousal = None
    if settings.emotion_match and not settings.mock_pipeline:
        from . import emotion
        ref_arousal = emotion.arousal(utterances, orig, orig_sr)
        log.info("arousal: %s", ref_arousal)
    # ลายเสียงของแต่ละท่อน กันยืมเสียงตัวอย่างข้ามคน (เด็กได้เสียงผู้ใหญ่) และกันรวมประโยคของคนละคน
    voice_map = None
    if settings.voice_match and gpu.voice_tools():
        voice_map = gpu.voice_profiles(d, utterances, orig, orig_sr)
    library_refs = _library_refs(job, voice_store, target)

    def mood_of(u) -> str:
        """อารมณ์ที่ใช้พากย์จริง: เฉพาะตัวละครที่ใช้เสียงในคลังและเสียงนั้นมีอารมณ์ที่เลือก"""
        return u.mood if u.mood in library_refs.get(u.speaker, {}) else ""
    groups = _speech_groups([u for u in utterances if u.target.strip()], voices_=voice_map,
                            pinned=frozenset(library_refs), mood=mood_of)
    words = _load_words(d)
    if library_refs:
        log.info("library voices: %s", {s: sorted(k) for s, k in library_refs.items()})
    library_paths = {key: path for refs in library_refs.values() for key, path, _, _ in refs.values()}

    def key_for(p: _Plan, text: str) -> str:
        return _clip_key(text=text, speaker=p.speaker, start=p.g[0].start, end=p.g[-1].end,
                         lines=[u.id for u in p.g], limit=round(p.limit_sec, 3), ref=p.ref_key,
                         ref_text=p.ref_text, target=target, steps=rs.f5_steps, speed=settings.f5_speed,
                         max_speedup=p.max_speedup, max_slowdown=p.max_slowdown,
                         fit="duration", model=settings.f5_model, mock=settings.mock_pipeline,
                         prosody=[match_prosody, settings.prosody_max_shift, settings.prosody_max_range],
                         pauses=[settings.pause_match, settings.min_pause_sec, 2],
                         voice=[voice_map is not None, settings.voice_drift, settings.voice_retries],
                         # รอบที่ผู้ใช้กดสุ่มใหม่ ใส่เฉพาะเมื่อเคยสุ่ม คีย์ของประโยคอื่นจึงเหมือนเดิม ไม่ต้องพากย์ใหม่ทั้งคลิป
                         **({"take": [u.take for u in p.g]} if any(u.take for u in p.g) else {}))

    # ---- วางแผนทุกประโยค: เสียงตัวอย่าง ช่วงเวลา และใช้เสียงเดิมได้ไหม
    stage("tts", 0.72)
    plans: list[_Plan] = []
    done: dict[int, np.ndarray] = {}  # ลำดับกลุ่ม → เสียงพากย์ที่เสร็จแล้ว
    reused = 0
    for i, g in enumerate(groups):
        first, last = g[0], g[-1]
        speaker = _group_speaker(g)
        # ฉากตื่นเต้นยอมให้พูดเร็วขึ้นได้อีก ฉากเศร้าหรือเนิบยอมให้พูดช้าลงได้อีก (ไม่เกิน 15%)
        excite = tts.mean_arousal(g, ref_arousal)
        max_speedup = round(rs.max_speedup * (1 + 0.1 * min(max(excite, 0.0), 1.5)), 2)
        max_slowdown = round(settings.max_slowdown * (1 + 0.1 * min(max(-excite, 0.0), 1.5)), 2)
        if speaker in library_refs:  # ผู้ใช้เลือกเสียงจากคลังให้ตัวละครนี้
            ref_id, _, ref_text, ref_key = library_refs[speaker][mood_of(max(g, key=lambda u: u.duration))]
            ref = {"ref": ref_id}
        else:
            r = tts.choose_reference(g, by_speaker[speaker], ref_quality, ref_arousal, voice_map)
            ref_key = [r[0].id, r[-1].id]
            ref_start = r[0].start
            ref = {"ref_start": ref_start, "ref_end": min(r[-1].end, ref_start + settings.ref_max_sec)}
            ref_text = tts.reference_text(" ".join(x.source for x in r), source_lang, target)

        slot = max(last.end - first.start, 0.3)
        next_start = groups[i + 1][0].start if i + 1 < len(groups) else total
        limit_sec = max(slot, next_start - first.start)
        # ต้นฉบับพูดทับกัน (อีกคนพูดแทรกก่อนคนนี้พูดจบ) → ให้เสียงพากย์ซ้อนกันได้ถึงที่คนนี้หยุดพูดจริง ไม่ตัดหางประโยค
        if i + 1 < len(groups) and _group_speaker(groups[i + 1]) != speaker and turns:
            speaking = [t for t in turns if t.start <= last.end - 0.1 <= t.end]
            if speaking:
                until = min(min(speaking, key=lambda t: t.start).end, last.end + 1.5)
                if until - first.start > limit_sec:
                    log.info("line %d: overlaps next speaker, may run %.1fs past the cut", first.id,
                             until - first.start - limit_sec)
                    limit_sec = until - first.start

        p = _Plan(i, g, speaker, slot, limit_sec, max_speedup, max_slowdown, ref, ref_text, ref_key)
        # ประโยคที่บท ตัวละคร และเวลาเหมือนรอบก่อน → ใช้เสียงเดิม ไม่ต้องพากย์ใหม่
        cached = _load_cached(tts_dir, first.id, key_for(p, p.text()))
        if cached is not None:
            done[i] = cached
            reused += len(g)
        else:
            plans.append(p)

    def render(batch: list[_Plan], lo: float, hi: float) -> None:
        """พากย์ทั้งชุดผ่าน gpu.synthesize_lines แล้วต่อช่วงย่อยของแต่ละประโยคเป็นเสียงเดียว"""
        lines = []
        for p in batch:
            if not settings.pause_match or settings.mock_pipeline:
                p.chunks = [pauses.Chunk(p.g[0].start, p.g[-1].end, p.text())]
            else:  # พากย์ทีละช่วงตามจังหวะหยุดของต้นฉบับ
                p.chunks = pauses.plan(p.g, orig, orig_sr, settings.min_pause_sec, words=words)
            lines += [{"id": f"{p.g[0].id}:{k}", "text": c.text, **p.ref, "ref_text": p.ref_text,
                       "target_lang": target, "slot": max(c.end - c.start, 0.3), "max_speedup": p.max_speedup,
                       "max_slowdown": p.max_slowdown, "check_pitch": voice_map is not None}
                      for k, c in enumerate(p.chunks)]
        progress = (lambda f: stage("tts", lo + (hi - lo) * f)) if gpu.remote() else None
        voices_ = gpu.synthesize_lines(vocals, lines, rs.f5_steps, settings.f5_speed, library_paths, refs_dir,
                                       progress, cancel)
        for p in batch:
            first = p.g[0]
            out, cursor = np.zeros(0, dtype=np.float32), 0
            for k, c in enumerate(p.chunks):
                v = voices_[f"{first.id}:{k}"]
                if match_prosody:
                    seg = orig[int(c.start * orig_sr): int(c.end * orig_sr)]
                    v = prosody.match(v, sr, seg, orig_sr, settings.prosody_max_shift, settings.prosody_max_range)
                v = audio.trim_silence(v, sr)
                # วางแต่ละช่วงตรงเวลาที่นักแสดงพูด
                at = max(int((c.start - first.start) * sr), cursor + (int(0.08 * sr) if cursor else 0))
                out = np.concatenate([out, np.zeros(max(0, at - len(out)), dtype=np.float32), v])
                cursor = len(out)
            if len(p.chunks) > 1:
                log.info("line %d: %d chunks %s", first.id, len(p.chunks),
                         [(round(c.start, 1), round(c.end, 1)) for c in p.chunks])
            p.voice = out

    # ---- พากย์: บนเครื่องนี้ทีละประโยค (เสร็จแล้วเก็บแคชทันที) บน Modal ส่งทุกประโยคเป็นชุดพร้อมกัน
    batches = ([plans] if plans else []) if gpu.remote() else [[p] for p in plans]
    for batch in batches:
        if not gpu.remote():
            stage("tts", 0.72 + 0.2 * batch[0].i / len(groups))
        render(batch, 0.72, 0.88)
        # พูดเร็วสุดที่ยอมได้แล้วยังยาวเกินฉาก → ให้ Typhoon ย่อบทแล้วพากย์ใหม่หนึ่งรอบ (ส่งเฉพาะประโยคนั้น)
        again = []
        for p in batch:
            if can_shorten and len(p.voice) / sr > p.slot * 1.05:
                from .translate import shorten
                cancel()
                before = p.text()
                shorten(p.g, target, target_ratio=0.9)
                if p.text() != before:
                    again.append(p)
        if again:
            if gpu.remote():
                log.info("re-dub %d shortened lines", len(again))
            render(again, 0.88, 0.92)
        for p in batch:
            # ยังยาวอยู่ ยอมให้ล้นเข้าช่วงเงียบได้ แต่ไม่ทับประโยคถัดไป
            voice = audio.fade(p.voice[: int(p.limit_sec * sr)], sr)
            first = p.g[0]
            key = key_for(p, p.text())
            sf.write(tts_dir / f"{first.id:04d}.wav", voice, sr)
            sf.write(_take_file(tts_dir, first.id, key), voice, sr)
            (tts_dir / f"{first.id:04d}.json").write_text(json.dumps({"key": key}), encoding="utf-8")
            done[p.i] = voice

    clips = [(g[0].start, done[i]) for i, g in enumerate(groups)]
    plans_by_i = {p.i: p for p in plans}
    spans = [(g[0].start, g[-1].end) for g in groups]
    redubbed = sum(len(p.g) for p in plans)

    store.save_transcript(job_id, utterances)
    _free_vram("tts")
    store.update(job_id, synth_stats=SynthStats(redubbed=redubbed, reused=reused))

    stage("mix", 0.93)
    if not settings.mock_pipeline:
        clips = mix.match_loudness(clips, spans, sr, orig, orig_sr, settings.loudness_match,
                                   settings.loudness_max_boost, settings.loudness_max_cut)
    bed = None
    if settings.nonspeech_gain > 0:
        # ช่วงที่มีบท (แม้ไม่ได้แปล) และช่วงที่เสียงพากย์ล้นออกไป ไม่ใส่เสียงเดิม กันเสียงภาษาต้นฉบับโผล่
        speech = [(u.start, u.end) for u in utterances] + [(s, s + len(v) / sr) for s, v in clips]
        if settings.breath_keep and settings.pause_match:
            # ช่วงหยุดกลางประโยคที่เสียงพากย์เว้นไว้ ใส่เสียงเดิมของนักแสดง (หายใจ สูดลม ถอนใจ) ให้ฟังมีชีวิต
            # เปิดเฉพาะช่วงที่เสียงพากย์เงียบจริง ถ้าเสียงพากย์ล้นเข้าไปก็ไม่ใส่ ส่วนคำพูดที่ถอดตกไปยังโดน is_speech กรองอยู่
            holes = [h for i, g in enumerate(groups) for h in _pause_holes(g, plans_by_i.get(i), orig, orig_sr, words)]
            voiced = [(s + a / sr, s + b / sr) for s, v in clips for a, b in mix._loud_runs(v, sr, level=0.01)]
            speech = mix.minus([(u.start, u.end) for u in utterances], holes) + voiced
        is_speech = None
        if not settings.mock_pipeline:
            known, is_speech = gpu.speech_filter(d, source_lang)
            speech += known
        bed = mix.nonspeech(orig, orig_sr, speech, total, sr, is_speech) * settings.nonspeech_gain
        _free_vram("transcribe")
    mix.place_clips(clips, total, sr, d / "dub_voice.wav", bed, settings.room_reverb, settings.room_rt60)
    mix.mix_tracks(d / "dub_voice.wav", d / "bgm.wav", d / "final_audio.wav", rs.voice_gain, rs.bgm_gain)
    stage("mux_video", 0.95)
    mix.mux_video(video, d / "final_audio.wav", d / "output.mp4")
    subs.write_srt(utterances, d / "subtitles.srt")

    # วิดีโอฝังซับรุ่นเก่าใช้ไม่ได้แล้ว เพราะเสียงหรือบทเปลี่ยน
    (d / "output_subs.mp4").unlink(missing_ok=True)
    (d / "subs_style.json").unlink(missing_ok=True)
    job = store.get(job_id)
    if job.burn_subs:
        stage("burn_subs", 0.97)
        subs.burn(d / "output.mp4", utterances, effective_style(job), d / "output_subs.mp4")


# ---------------------------------------------------------------- render
def effective_style(job):
    return job.sub_style or runtime_settings.get().default_style(job.target_lang)


def run_render(store: JobStore, job_id: str) -> None:
    job = store.get(job_id)
    d = store.dir(job_id)
    if not (d / "output.mp4").exists():
        raise RuntimeError("ยังไม่มีวิดีโอที่พากย์แล้ว")
    _stage(store, job_id)("burn_subs", 0.5)
    utterances = sorted(store.load_transcript(job_id), key=lambda u: u.start)
    subs.burn(d / "output.mp4", utterances, effective_style(job), d / "output_subs.mp4")
