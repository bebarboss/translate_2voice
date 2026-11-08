"""cluster_lines ต้องแยกหลายคนเมื่อ pyannote รวมเป็นคนเดียว"""
import numpy as np

from app.pipeline.voices import Voice, cluster_lines
from app.schemas import Utterance


def _emb(seed: int, dim: int = 32) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def test_cluster_splits_when_diarization_said_one():
    # ทุกท่อนถูกป้าย speaker_01 เหมือนงาน 9191925b6aac
    utts = [
        Utterance(id=i, speaker="speaker_01", start=float(i * 4), end=float(i * 4 + 3.5),
                  source=f"line{i}", target="")
        for i in range(1, 9)
    ]
    # คน A: บรรทัดคี่, คน B: บรรทัดคู่ — ลายเสียงคนละทิศ
    voices = {}
    for u in utts:
        seed = 1 if u.id % 2 else 99
        voices[u.id] = Voice(_emb(seed), pitch=12.0 if u.id % 2 else 18.0)

    labels = cluster_lines(utts, voices)
    assert labels is not None
    groups = {labels[u.id] for u in utts}
    assert len(groups) >= 2, labels


def test_cluster_keeps_two_when_voices_differ(monkeypatch):
    from app.pipeline import voices as vo
    from dataclasses import replace

    # ลดเกณฑ์ merge ไม่ให้รวมคนละเสียง
    monkeypatch.setattr(vo, "settings", replace(vo.settings, diar_merge_sim=0.9, voice_min_sim=0.9))
    utts = [
        Utterance(id=i, speaker="speaker_01", start=float(i * 3), end=float(i * 3 + 2.5),
                  source=f"x{i}", target="")
        for i in range(1, 7)
    ]
    voices = {
        u.id: Voice(_emb(10 if u.id <= 3 else 80), pitch=10.0 if u.id <= 3 else 20.0)
        for u in utts
    }
    labels = cluster_lines(utts, voices)
    assert labels is not None
    assert len({labels[i] for i in labels}) >= 2


def test_cluster_never_collapses_when_diar_said_one():
    """แม้ centroid คล้ายกันมาก ก็ไม่รวมกลับเหลือคนเดียวถ้า pyannote บอกคนเดียว"""
    utts = [
        Utterance(id=i, speaker="speaker_01", start=float(i * 4), end=float(i * 4 + 3.5),
                  source=f"line{i}", target="")
        for i in range(1, 7)
    ]
    # ลายเสียงใกล้กันมาก (noise นิดเดียว) — เกณฑ์ merge ปกติจะรวม แต่ force_multi ต้องกันไว้
    base = _emb(42)
    voices = {}
    for u in utts:
        jitter = _emb(100 + u.id) * 0.05
        v = base + jitter
        v = v / (np.linalg.norm(v) + 1e-9)
        voices[u.id] = Voice(v.astype(np.float32), pitch=12.0)
    labels = cluster_lines(utts, voices)
    assert labels is not None
    assert len({labels[i] for i in labels}) >= 2, labels
