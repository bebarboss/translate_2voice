"""ลายเสียงของแต่ละท่อน ใช้กันไม่ให้เสียงพากย์ผิดคน (เด็กได้เสียงผู้ใหญ่ ผู้หญิงได้เสียงผู้ชาย)

ระบบแยกผู้พูดมักรวมหลายคนเป็นคนเดียวเมื่อมีเพลงประกอบดัง (ตัวอย่างหนังทั้งเรื่องอาจถูกนับเป็นคนเดียว)
F5-TTS ลอกเสียงจากเสียงตัวอย่าง ถ้ายืมเสียงตัวอย่างข้ามคน เสียงพากย์ก็ผิดคนทั้งวัยและเพศ
จึงวัดสองอย่างต่อท่อน: ลายเสียง (wespeaker ตัวเดียวกับที่ pyannote ใช้ สัญญาอนุญาต CC-BY-4.0)
และระดับเสียง (เด็ก ผู้หญิง ผู้ชาย คนแก่ ต่างกันหลายเซมิโทน) แล้วยืมเฉพาะท่อนที่เสียงเข้ากันจริง
"""
from typing import NamedTuple, Optional

import numpy as np

from ..config import settings

_model = None
EMBED_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"


class Voice(NamedTuple):
    emb: Optional[np.ndarray]  # ลายเสียง (normalized) ไม่มีถ้าท่อนสั้นเกินจะวัดได้แม่น
    pitch: float  # ระดับเสียงกลาง (เซมิโทนเทียบ 1 Hz) nan ถ้าวัดไม่ได้


def _load():
    global _model
    if _model is None:
        import torch
        from pyannote.audio import Inference, Model

        model = Model.from_pretrained(EMBED_MODEL, token=settings.hf_token)
        device = torch.device(settings.device if torch.cuda.is_available() else "cpu")
        _model = Inference(model, window="whole", device=device)
    return _model


def unload() -> None:
    global _model
    _model = None


def _pitch(seg: np.ndarray, sr: int) -> float:
    import parselmouth

    f0 = parselmouth.Sound(seg.astype(np.float64), sr).to_pitch(
        time_step=0.01, pitch_floor=75.0, pitch_ceiling=600.0).selected_array["frequency"]
    f0 = f0[f0 > 0]
    return float(12 * np.log2(np.median(f0))) if len(f0) >= 10 else float("nan")


def profile(utts: list, orig: np.ndarray, sr: int, min_sec: float = 1.0) -> dict[int, Voice]:
    """id → ลายเสียงของท่อนนั้น"""
    import librosa
    import torch

    model = _load()
    out = {}
    for u in utts:
        seg = orig[int(u.start * sr): int(u.end * sr)]
        emb = None
        if len(seg) >= sr * min_sec:
            w = librosa.resample(seg, orig_sr=sr, target_sr=16000)
            v = np.asarray(model({"waveform": torch.from_numpy(w)[None], "sample_rate": 16000})).reshape(-1)
            n = float(np.linalg.norm(v))
            emb = v / n if n > 0 and np.isfinite(v).all() else None
        out[u.id] = Voice(emb, _pitch(seg, sr) if len(seg) >= sr * 0.3 else float("nan"))
    return out


def of_run(run: list, voices: Optional[dict[int, Voice]]) -> Optional[Voice]:
    """ลายเสียงรวมของท่อนที่ติดกัน (เฉลี่ยถ่วงตามความยาว)"""
    if not voices:
        return None
    vs = [(voices[x.id], x.duration) for x in run if x.id in voices]
    embs = [v.emb * w for v, w in vs if v.emb is not None]
    pitches = [(v.pitch, w) for v, w in vs if np.isfinite(v.pitch)]
    emb = None
    if embs:
        s = np.sum(embs, axis=0)
        emb = s / (np.linalg.norm(s) or 1.0)
    pitch = (sum(p * w for p, w in pitches) / sum(w for _, w in pitches)) if pitches else float("nan")
    return Voice(emb, pitch)


def similarity(a: Optional[Voice], b: Optional[Voice]) -> Optional[float]:
    if a is None or b is None or a.emb is None or b.emb is None:
        return None
    return float(a.emb @ b.emb)


def same_voice(a: Optional[Voice], b: Optional[Voice]) -> bool:
    """น่าจะเป็นคนเดียวกันไหม วัดไม่ได้ถือว่าใช่ (ไม่มีหลักฐานว่าต่าง)
    ระดับเสียงต่างกันเกินเกณฑ์ = ต่างวัยหรือต่างเพศ (ตะโกนทำให้เสียงสูงขึ้นได้ราว 3-4 เซมิโทน จึงเผื่อไว้)"""
    if a is None or b is None:
        return True
    if np.isfinite(a.pitch) and np.isfinite(b.pitch) and abs(a.pitch - b.pitch) > settings.voice_max_pitch_diff:
        return False
    sim = similarity(a, b)
    return sim is None or sim >= settings.voice_min_sim


def split_lines(utts: list, words: list, audio: np.ndarray, sr: int, min_piece: float = 0.8) -> list:
    """แบ่งท่อนที่มีหลายคนพูดต่อกัน (เช่น "Billy! Mom? Run!") ตรงจุดจบประโยคย่อยที่เสียงสองฝั่งต่างกันชัด

    pyannote จับการเปลี่ยนคนที่เร็วกว่าราวครึ่งวินาทีไม่ทัน ทั้งท่อนจึงได้เสียงพากย์คนเดียว
    ชิ้นใหม่ได้ชื่อผู้พูดที่ลายเสียงใกล้ที่สุด ถ้าไม่มีใครใกล้กว่าคนเดิมก็คงชื่อเดิมไว้ (split_speakers แยกต่อทีหลัง)
    คืนรายการท่อนใหม่ที่เรียงเลข id ใหม่แล้ว
    """
    from ..schemas import Utterance
    from .transcribe import SENTENCE_END

    base = profile(utts, audio, sr)
    centroids = {s: of_run([u for u in utts if u.speaker == s], base) for s in {u.speaker for u in utts}}
    out = []
    for u in utts:
        ws = [w for w in words if u.start - 0.01 <= (w.start + w.end) / 2 <= u.end + 0.01]
        # ชิ้นย่อยตามจุดจบประโยค ชิ้นที่สั้นเกินจะวัดเสียงไม่แม่น ต่อเข้ากับชิ้นถัดไป
        pieces, cur = [], []
        for w in ws:
            cur.append(w)
            if w.text.strip().endswith(SENTENCE_END) and cur[-1].end - cur[0].start >= min_piece:
                pieces.append(cur)
                cur = []
        if cur:
            if pieces and cur[-1].end - cur[0].start < min_piece:
                pieces[-1] += cur
            else:
                pieces.append(cur)
        if len(pieces) < 2:
            out.append(u)
            continue
        fake = [Utterance(id=k, speaker=u.speaker, start=p[0].start, end=p[-1].end, source="")
                for k, p in enumerate(pieces)]
        pv = profile(fake, audio, sr)
        # รวมชิ้นติดกันที่เสียงเข้ากันเป็นกลุ่มเดียว ตัดเฉพาะจุดที่ต่างกันชัด
        groups = [[0]]
        for k in range(1, len(pieces)):
            if clearly_different(of_run([fake[i] for i in groups[-1]], pv), pv[k]):
                groups.append([k])
            else:
                groups[-1].append(k)
        if len(groups) == 1:
            out.append(u)
            continue
        for g in groups:
            ws_g = [w for k in g for w in pieces[k]]
            v = of_run([fake[k] for k in g], pv)
            speaker = u.speaker
            scores = {s: similarity(v, c) for s, c in centroids.items() if same_voice(v, c)}
            scores = {s: x for s, x in scores.items() if x is not None}
            if scores and max(scores, key=scores.get) != u.speaker \
                    and scores[max(scores, key=scores.get)] > (scores.get(u.speaker) or -1) + 0.05:
                speaker = max(scores, key=scores.get)
            out.append(Utterance(id=0, speaker=speaker, start=round(ws_g[0].start, 3),
                                 end=round(ws_g[-1].end, 3), source="".join(w.text for w in ws_g).strip()))
    for i, u in enumerate(out):
        u.id = i + 1
    return out


def clearly_different(a: Optional[Voice], b: Optional[Voice]) -> bool:
    """หลักฐานชัดว่าเป็นคนละคน ใช้ตัดสินว่าไม่ควรรวมสองท่อนที่ติดกันเป็นประโยคเดียว"""
    if a is None or b is None:
        return False
    if np.isfinite(a.pitch) and np.isfinite(b.pitch) and abs(a.pitch - b.pitch) > settings.voice_split_pitch:
        return True
    sim = similarity(a, b)
    return sim is not None and sim < 0.0


def split_speakers(utts: list, voices: dict[int, Voice], taken: Optional[set] = None) -> dict[str, str]:
    """แยกผู้พูดที่ระบบแยกผู้พูดรวมมาเกินหนึ่งคน (เช่นเด็กกับผู้ใหญ่) เปลี่ยนชื่อผู้พูดในท่อนเหล่านั้น คืน {ชื่อเดิม: ชื่อใหม่}

    แยกแบบระวัง: แบ่งสองกลุ่มตามระดับเสียง ยอมแยกเมื่อสองกลุ่มห่างกันชัด (เกิน voice_split_pitch เซมิโทน)
    และลายเสียงในกลุ่มเดียวกันคล้ายกันมากกว่าข้ามกลุ่ม ท่อนที่วัดระดับเสียงไม่ได้คงชื่อเดิมไว้
    """
    from collections import defaultdict

    by_speaker = defaultdict(list)
    for u in utts:
        by_speaker[u.speaker].append(u)
    taken = {u.speaker for u in utts} | (taken or set())
    renamed: dict[str, str] = {}
    for speaker, lines in sorted(by_speaker.items()):
        known = [u for u in lines if np.isfinite(voices[u.id].pitch) and u.duration >= 1.0]
        if len(known) < 4:
            continue
        p = np.array([voices[u.id].pitch for u in known])
        # สองกลุ่มที่ห่างกันมากที่สุด: ลองทุกจุดตัดของระดับเสียงที่เรียงแล้ว
        order = np.sort(p)
        best = None
        for k in range(2, len(order) - 1):
            lo, hi = order[:k], order[k:]
            spread = np.concatenate([lo - lo.mean(), hi - hi.mean()]).std()
            score = (hi.mean() - lo.mean()) / (spread + 1e-6)
            if best is None or score > best[0]:
                best = (score, (order[k - 1] + order[k]) / 2, hi.mean() - lo.mean())
        if best is None or best[2] < settings.voice_split_pitch:
            continue
        cut = best[1]
        low = [u for u in known if voices[u.id].pitch < cut]
        high = [u for u in known if voices[u.id].pitch >= cut]
        within, across = [], []
        for i, a in enumerate(known):
            for b in known[i + 1:]:
                s = similarity(voices[a.id], voices[b.id])
                if s is None:
                    continue
                if (a in low) == (b in low):
                    within.append(s)
                else:
                    across.append(s)
        if within and across and np.mean(within) - np.mean(across) < 0.05:
            continue  # ลายเสียงไม่ได้บอกว่าเป็นคนละคน แค่ระดับเสียงต่างตามอารมณ์
        n = len(taken) + 1
        while f"speaker_{n:02d}" in taken:
            n += 1
        new = f"speaker_{n:02d}"
        taken.add(new)
        renamed[speaker] = new
        for u in high:
            u.speaker = new
    return renamed
