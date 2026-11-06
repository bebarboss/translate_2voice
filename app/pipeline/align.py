"""จัดเวลาคำใหม่ให้แม่นด้วย wav2vec2 (forced alignment แบบ WhisperX)

เวลาคำของ Whisper คลาดได้ 0.1–0.3 วินาที คำตรงรอยต่อสองคนพูดจึงไปติดอีกคน
ขั้นนี้รู้ข้อความอยู่แล้ว จึงให้โมเดล CTC หาเฟรมที่ตัวอักษรแต่ละตัวถูกพูด (ละเอียดราว 0.02 วินาที)
แล้วใช้เฟรมแรก/สุดท้ายของคำเป็นเวลาคำ คำที่ไม่มีตัวอักษรในคลังของโมเดล (ตัวเลข สัญลักษณ์) ใช้เวลาเดิม
"""
import logging
from typing import Optional

import numpy as np

from .common import Word

log = logging.getLogger("dubbing.align")

# โมเดลชุดเดียวกับที่ WhisperX ใช้
MODELS = {
    "en": "facebook/wav2vec2-base-960h",
    "ja": "jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
    "zh": "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
    "ko": "kresnik/wav2vec2-large-xlsr-korean",
    "th": "airesearch/wav2vec2-large-xlsr-53-th",
    "fr": "jonatasgrosman/wav2vec2-large-xlsr-53-french",
    "de": "jonatasgrosman/wav2vec2-large-xlsr-53-german",
    "es": "jonatasgrosman/wav2vec2-large-xlsr-53-spanish",
    "ru": "jonatasgrosman/wav2vec2-large-xlsr-53-russian",
    "pt": "jonatasgrosman/wav2vec2-large-xlsr-53-portuguese",
}
SR = 16000
PAD_SEC = 0.5
MIN_CONF = 0.2  # ความน่าจะเป็นเฉลี่ยของตัวอักษรในคำ ต่ำกว่านี้ไม่เชื่อเวลาที่จัดได้  # เผื่อเสียงหัวท้ายท่อน เวลาของ Whisper อาจคลาดออกนอกช่วง
_loaded: dict = {}


def _load(lang: str):
    if lang not in _loaded:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        from ..config import settings

        name = MODELS[lang]
        proc = Wav2Vec2Processor.from_pretrained(name)
        model = Wav2Vec2ForCTC.from_pretrained(name).eval()
        dev = settings.device if settings.device.startswith("cuda") and torch.cuda.is_available() else "cpu"
        _loaded.clear()  # เก็บไว้ทีละภาษา
        _loaded[lang] = (proc, model.to(dev), dev)
    return _loaded[lang]


def unload() -> None:
    _loaded.clear()


def _tokens(text: str, vocab: dict, upper: bool) -> list[int]:
    text = text.strip().upper() if upper else text.strip().lower()
    return [vocab[c] for c in text if c in vocab and c != "|"]


def _viterbi(emission: np.ndarray, tokens: list[int], blank: int) -> Optional[np.ndarray]:
    """CTC forced alignment: คืนเฟรมที่ตกกับตัวอักษรแต่ละตัว (state ของแต่ละเฟรม, -1 = blank) หรือ None ถ้าเสียงสั้นกว่าข้อความ"""
    T, L = len(emission), len(tokens)
    if L == 0 or T < L:
        return None
    ext = np.full(2 * L + 1, blank, dtype=np.int64)
    ext[1::2] = tokens
    S = len(ext)
    skip = np.zeros(S, dtype=bool)  # ข้าม blank ได้เมื่อตัวอักษรสองตัวติดกันไม่ซ้ำกัน
    skip[3::2] = ext[3::2] != ext[1:-2:2]
    neg = -1e30
    alpha = np.full(S, neg)
    alpha[0] = emission[0, ext[0]]
    alpha[1] = emission[0, ext[1]]
    back = np.zeros((T, S), dtype=np.int8)
    for t in range(1, T):
        stay = alpha
        one = np.concatenate(([neg], alpha[:-1]))
        two = np.where(skip, np.concatenate(([neg, neg], alpha[:-2])), neg)
        cand = np.stack([stay, one, two])
        choice = cand.argmax(0)
        back[t] = choice
        alpha = cand[choice, np.arange(S)] + emission[t, ext]
    s = int(S - 1 if alpha[S - 1] >= alpha[S - 2] else S - 2)
    if alpha[s] <= neg / 2:
        return None
    path = np.empty(T, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= int(back[t, s])
    return np.where(path % 2 == 1, (path - 1) // 2, -1)


def align(words: list[Word], audio: np.ndarray, lang: str) -> list[Word]:
    """คืนรายการคำชุดเดิมที่เวลาจัดใหม่ (ภาษาที่ไม่มีโมเดลหรือจัดไม่ได้ คืนเวลาเดิม)"""
    if lang not in MODELS or not words:
        return words
    import torch

    proc, model, dev = _load(lang)
    vocab = proc.tokenizer.get_vocab()
    blank = proc.tokenizer.pad_token_id
    upper = any(k.isupper() for k in vocab)
    out = [Word(w.start, w.end, w.text, w.segment) for w in words]
    moved = 0
    for seg in sorted({w.segment for w in words}):
        idx = [i for i, w in enumerate(words) if w.segment == seg]
        a = max(0.0, words[idx[0]].start - PAD_SEC)
        b = min(len(audio) / SR, words[idx[-1]].end + PAD_SEC)
        chunk = audio[int(a * SR):int(b * SR)]
        if len(chunk) < SR * 0.2:
            continue
        toks, owner = [], []
        for i in idx:
            t = _tokens(words[i].text, vocab, upper)
            toks += t
            owner += [i] * len(t)
        if not toks:
            continue
        with torch.inference_mode():
            x = proc(chunk, sampling_rate=SR, return_tensors="pt").input_values.to(dev)
            em = torch.log_softmax(model(x).logits[0].float(), dim=-1).cpu().numpy()
        frames = _viterbi(em, toks, blank)
        if frames is None:
            continue
        step = (b - a) / len(em)
        span: dict[int, list[int]] = {}
        conf: dict[int, list[float]] = {}
        for f, k in enumerate(frames):
            if k >= 0:
                span.setdefault(owner[k], []).append(f)
                conf.setdefault(owner[k], []).append(float(em[f, toks[k]]))
        # คำที่โมเดลไม่มั่นใจ (เสียงการ์ตูน เพลงทับ ถอดผิด) ถูกบีบลงเฟรมใดก็ได้ ใช้เวลาเดิมของ Whisper
        ok = {i: fs for i, fs in span.items() if np.exp(np.mean(conf[i])) >= MIN_CONF}
        starts = {i: round(a + fs[0] * step, 3) for i, fs in ok.items()}
        for n, i in enumerate(idx):
            if i not in ok:
                continue
            # CTC ให้ตัวอักษรเป็นจุดสั้น ๆ เวลาจบของคำจึงยืดถึงความยาวเดิมของคำ แต่ไม่ทับคำถัดไป
            nxt = next((starts[j] for j in idx[n + 1:] if j in starts), None)
            spike_end = a + (ok[i][-1] + 1) * step
            end = max(spike_end, starts[i] + (words[i].end - words[i].start))
            if nxt is not None:
                end = min(end, nxt)
            if abs(starts[i] - out[i].start) > 0.05:
                moved += 1
            out[i].start, out[i].end = starts[i], round(max(end, starts[i] + 0.02), 3)
    # คำที่ไม่ได้จัด: เวลาเดิมแต่ไม่ให้ทับคำข้าง ๆ
    for i in range(1, len(out)):
        if out[i].start < out[i - 1].end:
            out[i - 1].end = max(out[i - 1].start + 0.02, out[i].start)
        if out[i].start < out[i - 1].start:
            out[i].start = out[i - 1].end
            out[i].end = max(out[i].end, out[i].start + 0.02)
    log.info("align %s: %d/%d words moved > 0.05s", lang, moved, len(words))
    return out
