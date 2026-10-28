"""ร้อยทุกขั้นเข้าด้วยกัน

run_analyze    : (ดาวน์โหลดลิงก์) → ดึงเสียง → แยกเสียงพูด/เพลง → แยกผู้พูด → ถอดเสียง → แปล → ย่อบท
run_synthesize : พากย์ทีละประโยค (ใช้เสียงเดิมกับประโยคที่ไม่ได้แก้) → ผสมเสียง → รวมวิดีโอ → ซับ
run_render     : ฝังซับลงวิดีโอใหม่อย่างเดียว (หลังเปลี่ยนรูปแบบซับ)
"""
import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from .. import runtime_settings
from ..config import settings
from ..jobs import JobStore
from ..schemas import SynthStats
from . import audio, mix, pauses, subs, tts
from .diarize import export_speaker_stems, load_turns, overlap_ratio, save_turns

log = logging.getLogger("dubbing.runner")


def _impl():
    """คืนชุดฟังก์ชันจริง หรือชุดทดสอบเมื่อเปิด MOCK_PIPELINE"""
    if settings.mock_pipeline:
        from . import mock
        return mock.separate_vocals, mock.diarize, mock.transcribe, \
            mock.translate_utterances, mock.fit_lengths, mock.synthesize
    from . import diarize, transcribe, translate
    return audio.separate_vocals, diarize.diarize, transcribe.transcribe, \
        translate.translate_utterances, translate.fit_lengths, tts.synthesize


def _free_vram(*names: str) -> None:
    """โหมด LOW_VRAM: ปล่อยโมเดลที่ใช้เสร็จแล้วออกจากการ์ดจอ ก่อนโหลดตัวถัดไป"""
    if not settings.low_vram or settings.mock_pipeline:
        return
    import gc
    import importlib

    for name in names:
        importlib.import_module(f"{__package__}.{name}").unload()
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _stage(store: JobStore, job_id: str):
    def update(name: str, progress: float) -> None:
        store.check_cancel(job_id)
        store.update(job_id, stage=name, progress=round(progress, 3))
    return update


# ---------------------------------------------------------------- analyze
def run_analyze(store: JobStore, job_id: str) -> None:
    from .transcribe import assign_speakers

    separate, diarize, transcribe, translate, fit_lengths, _ = _impl()
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
    store.update(job_id, duration=round(audio.probe_duration(video), 2))

    stage("extract_audio", 0.06)
    mixed = audio.extract_audio(video, d / "audio.wav")

    stage("separate_vocals", 0.1)
    _free_vram("tts")  # เผื่อโมเดลพากย์จากงานก่อนยังค้างอยู่
    vocals, _bgm = separate(mixed, d, settings.demucs_model, settings.device)
    wav16k = audio.to_mono(vocals, d / "vocals16k.wav", 16000)

    stage("diarize", 0.25)
    turns = diarize(wav16k, job.num_speakers)
    _free_vram("diarize")
    # ไม่ได้ระบุจำนวนคน → ตรวจผลด้วยลายเสียง แยกคนที่ถูกรวมกัน และรวมคนเดียวที่ถูกแยก
    if not job.num_speakers and settings.diar_refine and settings.hf_token and not settings.mock_pipeline:
        from . import voices
        wav, wsr = sf.read(wav16k, dtype="float32")
        turns = voices.refine_turns(turns, wav, wsr)
        _free_vram("voices")
    export_speaker_stems(vocals, turns, d / "stems")
    save_turns(turns, d / "turns.json")
    store.update(job_id, speakers=sorted({t.speaker for t in turns}))

    stage("transcribe", 0.4)
    words, lang = transcribe(wav16k, job.source_lang)
    _free_vram("transcribe")
    if not words:
        raise RuntimeError("ไม่พบคำพูดในคลิป")
    # เก็บเวลาของแต่ละคำไว้ เผื่อแบ่งท่อนใหม่ภายหลัง
    (d / "words.json").write_text(json.dumps([w.__dict__ for w in words], ensure_ascii=False), encoding="utf-8")
    utterances = assign_speakers(words, turns, lang=lang)
    if settings.voice_match and settings.hf_token and not settings.mock_pipeline:
        from . import voices
        wav, wsr = sf.read(wav16k, dtype="float32")
        # ท่อนเดียวที่มีหลายคนพูดต่อกัน (pyannote จับไม่ทัน) → แบ่งตรงจุดจบประโยคย่อยที่เสียงต่างกันชัด
        before = len(utterances)
        utterances = voices.split_lines(utterances, words, wav, wsr)
        if len(utterances) != before:
            log.info("split %d lines with more than one voice", len(utterances) - before)
        # ระบบแยกผู้พูดรวมเด็กกับผู้ใหญ่ (หรือชายกับหญิง) เป็นคนเดียว → แยกตามระดับเสียงและลายเสียง
        renamed = voices.split_speakers(utterances, voices.profile(utterances, wav, wsr),
                                         taken={t.speaker for t in turns})
        _free_vram("voices")
        if renamed:
            log.info("split speakers by voice: %s", renamed)
            store.update(job_id, speakers=sorted({u.speaker for u in utterances}))
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


def _load_cached(tts_dir: Path, uid: int, key: str):
    meta, wav = tts_dir / f"{uid:04d}.json", tts_dir / f"{uid:04d}.wav"
    if not (meta.exists() and wav.exists()):
        return None
    try:
        if json.loads(meta.read_text(encoding="utf-8")).get("key") != key:
            return None
        data, _ = sf.read(wav, dtype="float32")
        return data
    except (ValueError, OSError, RuntimeError):
        return None


def _speech_groups(utts: list, max_gap: float = 0.6, max_span: float = 12.0,
                   voices_: Optional[dict] = None) -> list[list]:
    """รวมท่อนที่พูดต่อกันเป็นประโยคเดียว (คนเดิม เว้นไม่เกิน max_gap และท่อนก่อนยังไม่จบประโยค) แล้วพากย์รวดเดียว

    ถ้าพากย์ทีละท่อน ทุกท่อนจะลงเสียงเหมือนจบประโยคและขาดเป็นช่วง ๆ ฟังไม่ต่อเนื่อง
    จำกัดความยาวรวมไว้ เพราะ F5-TTS พูดยาวเกินไปจะเพี้ยนและใช้หน่วยความจำการ์ดจอมาก
    voices_: ไม่รวมท่อนที่เสียงต่างกันชัด (ระบบแยกผู้พูดอาจรวมเด็กกับผู้ใหญ่เป็นคนเดียว) ไม่งั้นทั้งคู่จะได้เสียงตัวอย่างเดียวกัน
    """
    from .transcribe import SENTENCE_END
    from .voices import clearly_different, of_run

    groups: list[list] = []
    for u in utts:
        g = groups[-1] if groups else None
        if (g and u.speaker == g[-1].speaker and u.start - g[-1].end <= max_gap
                and u.end - g[0].start <= max_span and not g[-1].source.strip().endswith(SENTENCE_END)
                and not clearly_different(of_run([g[-1]], voices_), of_run([u], voices_))):
            g.append(u)
        else:
            groups.append([u])

    # ท่อนสั้นมาก (คำเดียว) F5-TTS พากย์เดี่ยว ๆ แล้วมักได้เสียงมั่ว และมักเป็นหัวหรือหางประโยคที่ถูกแยกผู้พูดผิด
    # → ต่อเข้ากับประโยคที่ติดกัน ยกเว้นเสียงต่างกันชัด (อีกคนพูดแทรก เช่น "Mom!") ให้พากย์ด้วยเสียงตัวเอง
    differ = lambda a, b: clearly_different(of_run(a, voices_), of_run(b, voices_))  # noqa: E731
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


def _library_refs(job, voice_store, target: str) -> dict[str, tuple[Path, str, float, list]]:
    """ผู้พูด → (ไฟล์เสียงตัวอย่าง, ข้อความในเสียงนั้น, ระดับเสียง, ส่วนของคีย์แคช) ของเสียงในคลังที่ผู้ใช้เลือก
    เสียงที่ถูกลบหรือยังไม่พร้อม ใช้เสียงต้นฉบับแทน"""
    out = {}
    for speaker, voice_id in job.voice_map.items():
        v = voice_store.get(voice_id) if voice_store else None
        path = voice_store.ref_path(voice_id) if v else None
        if v is None or v.status != "ready" or not path.exists():
            log.warning("speaker %s: library voice %s unavailable, using original voice", speaker, voice_id)
            continue
        pitch = float(12 * np.log2(v.pitch_hz)) if v.pitch_hz else float("nan")
        # เสียงในคลังเป็นภาษาไทย พากย์อังกฤษต้องเขียนข้อความเป็นอักษรละติน
        out[speaker] = (path, tts.reference_text(v.text, "th", target), pitch, ["library", voice_id, v.text])
    return out


def run_synthesize(store: JobStore, job_id: str, voice_store=None) -> None:
    *_, synthesize = _impl()
    job = store.get(job_id)
    d = store.dir(job_id)
    stage = _stage(store, job_id)
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
        from . import quality
        ref_quality = {u.id: round(quality.score(orig[int(u.start * orig_sr): int(u.end * orig_sr)], orig_sr), 2)
                       for u in utterances}
        _free_vram("quality")
        # ท่อนที่มีคนอื่นพูดซ้อน ใช้เป็นเสียงตัวอย่างแล้ว F5-TTS จะได้เสียงผสมสองคน → หักคะแนน
        if turns:
            for u in utterances:
                ov = overlap_ratio(u.start, u.end, turns)
                if ov > 0.05:
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
    if settings.voice_match and settings.hf_token and not settings.mock_pipeline:
        from . import voices
        voice_map = voices.profile(utterances, orig, orig_sr)
        _free_vram("voices")
    groups = _speech_groups([u for u in utterances if u.target.strip()], voices_=voice_map)
    library_refs = _library_refs(job, voice_store, target)
    if library_refs:
        log.info("library voices: %s", {s: k[1] for s, (_, _, _, k) in library_refs.items()})
    clips, spans, redubbed, reused = [], [], 0, 0
    for i, g in enumerate(groups):
        stage("tts", 0.72 + 0.2 * i / len(groups))
        first, last = g[0], g[-1]

        speaker = _group_speaker(g)
        # ฉากตื่นเต้นยอมให้พูดเร็วขึ้นได้อีก ฉากเศร้าหรือเนิบยอมให้พูดช้าลงได้อีก (ไม่เกิน 15%)
        excite = tts.mean_arousal(g, ref_arousal)
        max_speedup = round(rs.max_speedup * (1 + 0.1 * min(max(excite, 0.0), 1.5)), 2)
        max_slowdown = round(settings.max_slowdown * (1 + 0.1 * min(max(-excite, 0.0), 1.5)), 2)
        if speaker in library_refs:  # ผู้ใช้เลือกเสียงจากคลังให้ตัวละครนี้
            ref_path, ref_text, ref_pitch, ref_key = library_refs[speaker]
            if voice_map is None:
                ref_pitch = float("nan")
        else:
            ref = tts.choose_reference(g, by_speaker[speaker], ref_quality, ref_arousal, voice_map)
            ref_key = [ref[0].id, ref[-1].id]
            ref_start = ref[0].start
            ref_end = min(ref[-1].end, ref_start + settings.ref_max_sec)
            ref_path = refs_dir / f"ref_{ref[0].id:04d}_{ref[-1].id:04d}.wav"
            if not ref_path.exists():
                audio.cut_clip(vocals, ref_start, ref_end, ref_path, sr)
            ref_text = tts.reference_text(" ".join(x.source for x in ref), source_lang, target)
            ref_pitch = float("nan")
            if voice_map is not None:
                ref_wav, ref_sr = sf.read(ref_path, dtype="float32")
                ref_pitch = voices._pitch(ref_wav, ref_sr)

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
        text_of = lambda: " ".join(u.target.strip() for u in g)  # noqa: E731

        def key_for(text: str) -> str:
            return _clip_key(text=text, speaker=speaker, start=first.start, end=last.end,
                             lines=[u.id for u in g], limit=round(limit_sec, 3), ref=ref_key,
                             ref_text=ref_text, target=target, steps=rs.f5_steps, speed=settings.f5_speed,
                             max_speedup=max_speedup, max_slowdown=max_slowdown,
                             fit="duration", model=settings.f5_model, mock=settings.mock_pipeline,
                             prosody=[match_prosody, settings.prosody_max_shift, settings.prosody_max_range],
                             pauses=[settings.pause_match, settings.min_pause_sec],
                             voice=[voice_map is not None, settings.voice_drift, settings.voice_retries])

        # ประโยคที่บท ตัวละคร และเวลาเหมือนรอบก่อน → ใช้เสียงเดิม ไม่ต้องพากย์ใหม่
        cached = _load_cached(tts_dir, first.id, key_for(text_of()))
        if cached is not None:
            clips.append((first.start, cached))
            spans.append((first.start, last.end))
            reused += len(g)
            continue

        def speak_chunk(text: str, start: float, end: float):
            # โมเดลปรับจังหวะพูดให้พอดีฉากเองตอนสร้างเสียง ไม่ต้องเร่งความเร็วทีหลัง
            # F5-TTS สุ่มได้เสียงเงียบเป็นครั้งคราว → สร้างใหม่ (สูงสุด 3 รอบ)
            def once():
                for _ in range(3):
                    v = synthesize(ref_path, ref_text, text, settings.f5_speed, rs.f5_steps, target,
                                   slot=max(end - start, 0.3), max_speedup=max_speedup,
                                   max_slowdown=max_slowdown)
                    if len(v) and np.isfinite(v).all() and np.abs(v).max() > 0.02:
                        break
                    log.warning("line %d: silent TTS output, retrying", first.id)
                return np.nan_to_num(v)

            voice = once()
            # บางรอบ F5-TTS พูดหลุดจากเสียงตัวอย่าง (ผู้หญิงกลายเป็นเสียงต่ำ เด็กกลายเป็นผู้ใหญ่)
            # → วัดระดับเสียงเทียบเสียงตัวอย่าง ห่างเกินเกณฑ์ก็พากย์ใหม่ แล้วเลือกรอบที่ใกล้ที่สุด
            if np.isfinite(ref_pitch):
                gap = lambda v: abs(voices._pitch(v, sr) - ref_pitch)  # noqa: E731  (nan → ไม่ลองใหม่)
                tries = [(gap(voice), voice)]
                for _ in range(settings.voice_retries):
                    if not tries[-1][0] > settings.voice_drift:
                        break
                    log.info("line %d: voice drifted %.1f st from reference, retrying", first.id, tries[-1][0])
                    v = once()
                    tries.append((gap(v), v))
                voice = min(tries, key=lambda x: x[0] if np.isfinite(x[0]) else 99)[1]
            if match_prosody:
                seg = orig[int(start * orig_sr): int(end * orig_sr)]
                voice = prosody.match(voice, sr, seg, orig_sr, settings.prosody_max_shift, settings.prosody_max_range)
            return audio.trim_silence(voice, sr)

        def speak():
            if not settings.pause_match or settings.mock_pipeline:
                return speak_chunk(text_of(), first.start, last.end)
            # พากย์ทีละช่วงตามจังหวะหยุดของต้นฉบับ วางแต่ละช่วงตรงเวลาที่นักแสดงพูด
            chunks = pauses.plan(g, orig, orig_sr, settings.min_pause_sec)
            out, cursor = np.zeros(0, dtype=np.float32), 0
            for c in chunks:
                v = speak_chunk(c.text, c.start, c.end)
                at = max(int((c.start - first.start) * sr), cursor + (int(0.08 * sr) if cursor else 0))
                out = np.concatenate([out, np.zeros(max(0, at - len(out)), dtype=np.float32), v])
                cursor = len(out)
            if len(chunks) > 1:
                log.info("line %d: %d chunks %s", first.id, len(chunks),
                         [(round(c.start, 1), round(c.end, 1)) for c in chunks])
            return out

        voice = speak()
        # พูดเร็วสุดที่ยอมได้แล้วยังยาวเกินฉาก → ให้ Typhoon ย่อบทแล้วพากย์ใหม่หนึ่งรอบ
        if can_shorten and len(voice) / sr > slot * 1.05:
            from .translate import shorten
            before = text_of()
            shorten(g, target, target_ratio=0.9)
            if text_of() != before:
                voice = speak()

        # ยังยาวอยู่ ยอมให้ล้นเข้าช่วงเงียบได้ แต่ไม่ทับประโยคถัดไป
        voice = audio.fade(voice[: int(limit_sec * sr)], sr)

        sf.write(tts_dir / f"{first.id:04d}.wav", voice, sr)
        (tts_dir / f"{first.id:04d}.json").write_text(json.dumps({"key": key_for(text_of())}), encoding="utf-8")
        clips.append((first.start, voice))
        spans.append((first.start, last.end))
        redubbed += len(g)

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
        is_speech = None
        if not settings.mock_pipeline:
            import librosa

            from .transcribe import words_in

            def is_speech(seg: np.ndarray, seg_sr: int) -> bool:
                words = words_in(librosa.resample(seg, orig_sr=seg_sr, target_sr=16000), source_lang or None)
                if words:
                    log.info("skip untranscribed speech in original vocals: %r", words)
                return bool(words)
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
