"""แยกช่วงพูดตามบท: สองคนพูดต่อกันแต่ระบบแยกผู้พูดรวมเป็นท่อนเดียว

pyannote และลายเสียงแยกตัวละครที่เสียงคล้ายกันไม่ออก (เช่น โดราเอมอนกับโนบิตะ ระดับเสียงเท่ากัน)
แต่บทบอกได้ชัดว่าตรงไหนเปลี่ยนคน (ถาม/ตอบ คำรับอย่าง "えっ?") ขั้นนี้รับจุดตัดที่ Typhoon/Gemini เสนอจากบท
(translate.propose_turns) แล้วตัดจริงเฉพาะจุดที่ลายเสียงสองฝั่งต่างกัน จากนั้นจัดกลุ่มผู้พูดใหม่ทั้งงาน
ท่อนที่ตัดแล้วเหลือเสียงคนเดียว กลุ่มเสียงที่ได้จึงสะอาดกว่าจัดจากท่อนที่ปนสองคน
ทดลองกับการ์ตูนโดราเอมอน 6 นาที: 76 → 92 ประโยค จุดที่ตัดส่วนใหญ่ตรงจุดเปลี่ยนคนจริง
"""
import logging

import numpy as np

from ..config import settings
from ..schemas import Utterance
from .common import Word

log = logging.getLogger("dubbing.turns")

MIN_PIECE_SEC = 0.6  # ชิ้นสั้นกว่านี้วัดลายเสียงไม่ได้ ต่อเข้ากับชิ้นก่อนหน้า


def piece_times(u: Utterance, words: list[Word], pieces: list[str]) -> list[tuple[float, float, str]]:
    """เวลาเริ่ม/จบของแต่ละชิ้นข้อความ: จุดตัดคือเวลาเริ่มของคำแรกของชิ้นถัดไป (นับตัวอักษรไม่รวมช่องว่าง)"""
    ws = [w for w in words if u.start - 0.01 <= (w.start + w.end) / 2 <= u.end + 0.01]
    starts, pos = [], 0
    for w in ws:
        starts.append((pos, w.start))
        pos += len(w.text.replace(" ", ""))
    bounds, acc = [u.start], 0
    for p in pieces[:-1]:
        acc += len(p.replace(" ", ""))
        t = next((s for c, s in starts if c >= acc), None)
        if t is None or t <= bounds[-1]:
            return []  # หาเวลาไม่ได้ (คำไม่ตรงกับบท) ไม่ตัดท่อนนี้
        bounds.append(t)
    bounds.append(u.end)
    return [(bounds[k], bounds[k + 1], p.strip()) for k, p in enumerate(pieces)]


def resplit_core(utterances: list[Utterance], words: list[Word], proposals: dict[int, list[str]],
                 wav: np.ndarray, sr: int, num_speakers) -> tuple[list[Utterance], int]:
    """ตัดท่อนตามจุดที่เสนอซึ่งลายเสียงสองฝั่งต่างกัน (คล้ายกันต่ำกว่า TURN_SPLIT_SIM) แล้วจัดกลุ่มผู้พูดใหม่
    คืน (ท่อนใหม่เรียงเลข id แล้ว, จำนวนจุดที่ตัด)"""
    from . import voices

    out: list[Utterance] = []
    cuts = 0
    for u in sorted(utterances, key=lambda x: x.start):
        parts = piece_times(u, words, proposals.get(u.id) or []) if u.id in proposals else []
        if len(parts) < 2:
            out.append(u)
            continue
        fake = [Utterance(id=k, speaker="", start=a, end=b, source="") for k, (a, b, _) in enumerate(parts)]
        pv = voices.profile(fake, wav, sr, min_sec=MIN_PIECE_SEC)
        cur = [parts[0]]
        groups = []
        for k in range(1, len(parts)):
            sim = voices.similarity(pv[k - 1], pv[k])
            if sim is not None and sim < settings.turn_split_sim:
                groups.append(cur)
                cur = []
            cur.append(parts[k])
        groups.append(cur)
        cuts += len(groups) - 1
        for g in groups:
            out.append(u.model_copy(update={"start": round(g[0][0], 3), "end": round(g[-1][1], 3),
                                            "source": "".join(t for _, _, t in g).strip()}))
    for i, u in enumerate(out, 1):
        u.id = i
    if not cuts:
        return out, 0
    # จัดกลุ่มผู้พูดใหม่จากท่อนที่ตัดแล้ว (ระบุจำนวนคนมา = ไม่จัดใหม่ ท่อนที่ตัดได้ชื่อคนที่เสียงใกล้ที่สุด)
    profiles = voices.profile(out, wav, sr)
    labels = voices.cluster_lines(out, profiles) if not num_speakers and settings.diar_refine else None
    if labels:
        names: dict[str, str] = {}
        for u in out:
            u.speaker = names.setdefault(labels[u.id], f"speaker_{len(names) + 1:02d}")
    else:
        centroids = {s: voices.of_run([u for u in out if u.speaker == s], profiles) for s in {u.speaker for u in out}}
        for u in out:
            scores = {s: voices.similarity(profiles.get(u.id), c) for s, c in centroids.items()}
            scores = {s: x for s, x in scores.items() if x is not None}
            if scores:
                u.speaker = max(scores, key=scores.get)
    return out, cuts
