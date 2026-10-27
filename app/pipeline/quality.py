"""ให้คะแนนความสะอาดของเสียงพูด (ประมาณค่า PESQ 1–4.5 ด้วย torchaudio SQUIM ไม่ต้องมีเสียงอ้างอิง)

ใช้คัดเสียงตัวอย่างให้ F5-TTS: ท่อนที่มีเพลงหรือเสียงประกอบปนหนัก โมเดลจะเลียนเสียงรบกวนนั้นมาด้วย
"""
import numpy as np

_model = None


def _load():
    global _model
    if _model is None:
        import torch
        from torchaudio.pipelines import SQUIM_OBJECTIVE

        _model = SQUIM_OBJECTIVE.get_model().eval()
        if torch.cuda.is_available():
            _model = _model.cuda()
    return _model


def unload() -> None:
    global _model
    _model = None


def score(audio: np.ndarray, sr: int) -> float:
    """คะแนนความสะอาด ยิ่งสูงยิ่งดี เสียงสั้นกว่า 0.5 วินาทีให้ 0"""
    import librosa
    import torch

    if len(audio) < sr * 0.5:
        return 0.0
    w = librosa.resample(np.asarray(audio, dtype=np.float32), orig_sr=sr, target_sr=16000)
    model = _load()
    x = torch.from_numpy(w)[None].to(next(model.parameters()).device)
    with torch.no_grad():
        _, pesq, _ = model(x)
    return float(pesq)
