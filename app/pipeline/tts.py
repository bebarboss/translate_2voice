"""พากย์เสียงด้วย F5-TTS โดยใช้เสียงต้นฉบับของตัวละครเป็นตัวอย่าง

- พากย์ไทย   : F5-TTS รุ่นภาษาไทย (แพ็กเกจ f5-tts-th)
- พากย์อังกฤษ : F5-TTS รุ่นหลัก (แพ็กเกจ f5-tts) ซึ่งเทรนด้วยภาษาอังกฤษและจีน
"""
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ..config import settings
from ..schemas import Utterance

SAMPLE_RATE = 24000
_tts_th = None
_tts_en = None


def _load_th():
    global _tts_th
    if _tts_th is None:
        from f5_tts_th.tts import TTS
        _tts_th = TTS(model=settings.f5_model, hf_cache_dir=settings.f5_cache_dir or None)
        if settings.f5_fp32:  # ไลบรารีบังคับ float16 ไว้
            _tts_th.f5_model.float()
    return _tts_th


def _load_en():
    global _tts_en
    if _tts_en is None:
        from f5_tts.api import F5TTS
        _tts_en = F5TTS(model=settings.f5_en_model)
        if settings.f5_fp32:
            _tts_en.ema_model.float()
    return _tts_en


def unload() -> None:
    global _tts_th, _tts_en
    _tts_th = _tts_en = None


def _end_punct(text: str) -> str:
    text = text.strip()
    if text and text[-1] not in ".!?…":
        text += "."
    return text


def _quiet(*_args, **_kwargs) -> None:
    pass


def _fit(natural: float, slot: float, max_speedup: float, max_slowdown: float) -> float:
    """ความยาวเสียงที่ให้ F5-TTS พูด: เต็มฉากพอดี แต่ไม่เร็วหรือช้ากว่าความเร็วปกติเกินที่ตั้งไว้"""
    return max(0.3, min(max(slot, natural / max_speedup), natural * max_slowdown))


def thai_seconds(text: str) -> float:
    """เวลาพูดปกติของบทไทย นับพยางค์ (คำละตินนับตามกลุ่มสระ) หารด้วยความเร็วพูดปกติ

    สูตรเดิมของไลบรารีนับตัวอักษร IPA ซึ่งรวมวรรณยุกต์และเครื่องหมายเสียงยาว บทสั้นจึงได้เวลายาวเกินจริง
    (เช่น "ก็แค่นั้นแหละ หนึ่ง สอง กระโดด" 8 พยางค์ ได้ 2.1 วินาที) โมเดลก็ยืดเสียงหรือพูดคำซ้ำให้เต็มเวลา
    """
    import re
    from f5_tts_th.normalize import normalize_text
    from pythainlp.tokenize import syllable_tokenize

    text = normalize_text(text)  # ตัวเลข → คำอ่าน, ๆ → คำซ้ำ แบบเดียวกับที่โมเดลพูดจริง
    n = 0
    for tok in syllable_tokenize(text):
        if re.search(r"[ก-๛]", tok):
            n += 1
        elif tok.strip():
            n += max(1, len(re.findall(r"[aeiouy]+", tok.lower())))
    return max(0.3, n / settings.thai_syllables_per_sec)


def synthesize(ref_audio: Path, ref_text: str, gen_text: str, speed: float = 1.0,
               steps: int = 32, target_lang: str = "th", slot: Optional[float] = None,
               max_speedup: float = 1.35, max_slowdown: float = 1.2) -> np.ndarray:
    """พากย์ประโยคเดียว ถ้าให้ slot มา โมเดลจะปรับจังหวะพูดให้พอดีเวลาฉากเอง (fix_duration)
    ได้เสียงที่เป็นธรรมชาติกว่าการเร่งความเร็วหรือตัดเสียงทีหลัง"""
    gen_text = _end_punct(gen_text)
    if target_lang == "en":
        from f5_tts.infer.utils_infer import preprocess_ref_audio_text

        # ไลบรารีเก็บผลไว้ในแคช infer() ด้านล่างจึงไม่ต้องทำซ้ำ
        ref_file, ref_text_p = preprocess_ref_audio_text(str(ref_audio), ref_text.strip(), show_info=_quiet)
        fix = None
        if slot:
            ref_sec = sf.info(ref_file).duration
            natural = ref_sec * len(gen_text.encode()) / max(len(ref_text_p.encode()), 1) / speed
            fix = ref_sec + _fit(natural, slot, max_speedup, max_slowdown)
        wav, sr, _ = _load_en().infer(
            ref_file=str(ref_audio), ref_text=ref_text.strip(), gen_text=gen_text, show_info=_quiet,
            nfe_step=steps, cfg_strength=settings.f5_cfg, speed=speed, fix_duration=fix)
        wav = np.asarray(wav, dtype=np.float32).reshape(-1)
        if sr != SAMPLE_RATE:
            import librosa
            wav = librosa.resample(wav, orig_sr=sr, target_sr=SAMPLE_RATE)
        return wav

    # เรียก infer_process เองแทน TTS.infer เพื่อรู้ความยาวเสียงตัวอย่างหลังตัดความเงียบ และปิดการตัดบทเป็นท่อน
    # (f5-tts-th ใช้ fix_duration เดียวกันทุกท่อน ถ้าแบ่งสองท่อนเสียงจะยาวเป็นสองเท่า)
    from f5_tts_th.utils_infer import infer_process, preprocess_ref_audio_text

    model = _load_th()
    ref_file, ref_text_p = preprocess_ref_audio_text(str(ref_audio), ref_text.strip(), show_info=_quiet)
    fix = None
    if slot:
        fix = sf.info(ref_file).duration + _fit(thai_seconds(gen_text) / speed, slot, max_speedup, max_slowdown)
    wav, _, _ = infer_process(
        ref_file, ref_text_p, gen_text, model.f5_model, model.vocoder, mel_spec_type=model.vocoder_name,
        show_info=_quiet, nfe_step=steps, cfg_strength=settings.f5_cfg, speed=speed, fix_duration=fix,
        set_max_chars=10_000, use_ipa=model.model_type != "v1")
    return np.asarray(wav, dtype=np.float32).reshape(-1)


def romanize(text: str, lang: str, latin_only: bool = False) -> str:
    """เขียนประโยคต้นฉบับด้วยอักษรที่ F5-TTS รู้จัก (ไทยรู้จักอักษรไทยและละติน รุ่นอังกฤษรู้จักแค่ละติน)

    F5-TTS ใช้ ref_text บอกว่าเสียงตัวอย่างพูดอะไร ถ้าข้อความสั้นกว่าเสียงจริง โมเดลจะเริ่มพูดบทใหม่
    ตั้งแต่ในช่วงเสียงตัวอย่างซึ่งถูกตัดทิ้ง คำแรกของเสียงพากย์จึงหาย ต้องแปลงแบบตายตัวให้ความยาวตรงกับเสียง
    """
    from unidecode import unidecode

    if lang == "th":
        if not latin_only:
            return text
        # unidecode อ่านไทยทีละตัวอักษร สระหน้า (เ แ ไ) จึงผิดลำดับ ต้องตัดคำแล้วถอดเสียงทีละคำ
        from pythainlp.tokenize import word_tokenize
        from pythainlp.transliterate import romanize as th_romanize
        return " ".join(" ".join(th_romanize(w) for w in word_tokenize(text)).split())
    if lang in ("zh", "yue"):
        from pypinyin import lazy_pinyin
        text = " ".join(lazy_pinyin(text))
    return " ".join(unidecode(text).split())


def reference_text(source: str, source_lang: str, target_lang: str) -> str:
    """ข้อความที่พูดในเสียงตัวอย่าง ต้องเขียนในแบบที่โมเดลอ่านออก"""
    if target_lang == "en":
        # รุ่นหลักอ่านจีนและอังกฤษได้ ภาษาอื่นแปลงเป็นอักษรละติน
        # (ถ้าส่งข้อความว่าง F5-TTS จะโหลด Whisper อีกตัวมาถอดเสียงเอง การ์ดจอ 4 GB รับไม่ไหว)
        if source_lang in ("zh", "yue", "en"):
            return source
        return romanize(source, source_lang, latin_only=True)
    return romanize(source, source_lang)


def mean_arousal(run: list[Utterance], arousal: Optional[dict[int, float]]) -> float:
    """ความตื่นเต้นเฉลี่ยของท่อนที่ติดกัน ถ่วงตามความยาว"""
    if not arousal:
        return 0.0
    total = sum(x.duration for x in run) or 1.0
    return sum(arousal.get(x.id, 0.0) * x.duration for x in run) / total


def choose_reference(group: list[Utterance], same_speaker: list[Utterance],
                     quality: Optional[dict[int, float]] = None,
                     arousal: Optional[dict[int, float]] = None,
                     voices: Optional[dict] = None) -> list[Utterance]:
    """เลือกช่วงเสียงต้นฉบับ (ท่อนที่ติดกัน) ที่ใช้เป็นเสียงตัวอย่าง

    F5-TTS เลียนทั้งเสียง อารมณ์ และเสียงรบกวนจากตัวอย่าง จึงใช้เสียงของประโยคนั้นเองก่อน ถ้ายาวเกินใช้ช่วงยาวสุดในประโยคที่พอดี
    ถ้าสั้นเกินค่อยยืมท่อนของตัวละครเดียวกันที่อารมณ์ใกล้กัน และอยู่ใกล้ฉากนั้น
    quality (id → คะแนนความสะอาด): ถ้าเสียงของประโยคเองมีเพลงปนหนัก ใช้ท่อนที่สะอาดของตัวละครเดียวกันแทน
    arousal (id → ความตื่นเต้น): ตอนยืมท่อนอื่น เลือกท่อนที่ตื่นเต้นพอ ๆ กับประโยคที่จะพากย์ ฉากตะโกนจะได้ไม่ได้เสียงเรียบ
    voices (id → ลายเสียง): ยืมได้เฉพาะท่อนที่เสียงเข้ากับประโยคนี้ ระบบแยกผู้พูดมักรวมหลายคนเป็นคนเดียว
    ถ้ายืมข้ามคน เด็กจะได้เสียงผู้ใหญ่ ผู้หญิงได้เสียงผู้ชาย เสียงตัวเองที่มีเพลงปนยังดีกว่าเสียงสะอาดของคนอื่น
    """
    from . import voices as vo

    lo, hi = settings.ref_min_sec, settings.ref_max_sec
    span = lambda run: run[-1].end - run[0].start  # noqa: E731
    t = (group[0].start + group[-1].end) / 2
    want = mean_arousal(group, arousal)
    # อารมณ์ต่างกันหนึ่งส่วนเบี่ยงเบน หักเท่ากับคะแนนความสะอาด 0.5 หรือระยะห่าง 50 วินาที
    mood = lambda run: settings.ref_emotion_weight * abs(mean_arousal(run, arousal) - want)  # noqa: E731
    runs = [group[i:j] for i in range(len(group)) for j in range(i + 1, len(group) + 1)]
    fits = [r for r in runs if lo <= span(r) <= hi]
    own_ids = {x.id for x in group}
    target = vo.of_run(group, voices)
    near = [x for x in same_speaker if lo <= x.duration <= hi
            and (x.id in own_ids or vo.same_voice(vo.of_run([x], voices), target))]
    # ผ่านเกณฑ์แล้วก็ยังเลือกตัวที่ระดับเสียงใกล้ที่สุด: ต่างกันหนึ่งเซมิโทน หักเท่ากับคะแนนความสะอาด 0.1 หรือระยะห่าง 10 วินาที
    def voice_gap(run) -> float:
        v = vo.of_run(run, voices)
        if v is None or target is None or not (np.isfinite(v.pitch) and np.isfinite(target.pitch)):
            return 0.0
        return 0.1 * abs(v.pitch - target.pitch)

    if quality:
        q = lambda run: min(quality.get(x.id, 0.0) for x in run)  # noqa: E731
        own = max(fits, key=lambda r: (q(r) >= settings.ref_min_quality, span(r)), default=None)
        if own and q(own) >= settings.ref_min_quality:
            return own
        # เสียงตัวเองไม่สะอาดพอ: เลือกท่อนที่สะอาดและอารมณ์ใกล้กัน ท่อนใกล้ฉากได้เปรียบเล็กน้อย (0.1 คะแนนต่อ 10 วินาที)
        # ยืมท่อนของคนอื่นได้เมื่อระดับเสียงห่างไม่เกิน 3 เซมิโทน ห่างกว่านั้นใช้เสียงตัวเองที่มีเพลงปนดีกว่า
        pool = fits + [[x] for x in near if x.id in own_ids or voice_gap([x]) <= 0.3]
        clean = [r for r in pool if q(r) >= settings.ref_min_quality]
        if clean:
            return max(clean, key=lambda r: q(r) - mood(r) - voice_gap(r)
                       - 0.01 * abs((r[0].start + r[-1].end) / 2 - t))
        if pool:
            best = max(pool, key=lambda r: q(r) - 0.01 * abs((r[0].start + r[-1].end) / 2 - t))
            if q(best) > (q(own) if own else 0.0):
                return best

    if fits:
        return max(fits, key=span)
    if near:
        # ท่อนสั้นกว่า 3 วินาทีเก็บน้ำเสียงได้ไม่ดี ให้ถือว่าไกลออกไปอีก 10 วินาที
        return [min(near, key=lambda x: abs((x.start + x.end) / 2 - t) + (10 if x.duration < 3 else 0)
                    + 100 * (mood([x]) + voice_gap([x])))]
    if voices:  # ไม่มีท่อนไหนเสียงเข้ากันเลย ใช้เสียงประโยคตัวเองแม้สั้นหรือยาวเกิน (ตัดเหลือ ref_max_sec ตอนตัดไฟล์)
        return group
    return [max(same_speaker, key=lambda x: x.duration)]
