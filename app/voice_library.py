"""คลังเสียงภาษาไทย: เก็บใน data/voices/<id>/ (voice.json, original.*, ref.wav, embedding.npy)"""
import logging
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

from .jobs import _atomic_write
from .schemas import LibraryVoice, VoiceStatus, now

log = logging.getLogger("dubbing.voices")


class VoiceStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "voices"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._voices: dict[str, LibraryVoice] = {}
        for f in self.root.glob("*/voice.json"):
            try:
                v = LibraryVoice.model_validate_json(f.read_text(encoding="utf-8"))
            except Exception:
                log.warning("skip broken voice file %s", f)
                continue
            if v.status == VoiceStatus.processing:
                v.status, v.error = VoiceStatus.failed, "เซิร์ฟเวอร์รีสตาร์ตระหว่างเตรียมเสียง กดลองใหม่ได้เลย"
                self._write(v)
            self._voices[v.id] = v

    def _write(self, v: LibraryVoice) -> None:
        _atomic_write(self.dir(v.id) / "voice.json", v.model_dump_json(indent=2))

    def dir(self, voice_id: str) -> Path:
        return self.root / voice_id

    def ref_path(self, voice_id: str) -> Path:
        """เสียงตัวอย่างที่ทำความสะอาดและตัดแล้ว (24 kHz mono) ใช้ฟังและส่งให้ F5-TTS"""
        return self.dir(voice_id) / "ref.wav"

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def add(self, v: LibraryVoice) -> LibraryVoice:
        with self._lock:
            self.dir(v.id).mkdir(parents=True, exist_ok=True)
            self._voices[v.id] = v
            self._write(v)
            return v

    def get(self, voice_id: str) -> Optional[LibraryVoice]:
        with self._lock:
            v = self._voices.get(voice_id)
            return v.model_copy(deep=True) if v else None

    def all(self) -> list[LibraryVoice]:
        with self._lock:
            return sorted((v.model_copy(deep=True) for v in self._voices.values()),
                          key=lambda v: v.created_at, reverse=True)

    def update(self, voice_id: str, **fields) -> Optional[LibraryVoice]:
        """คืน None ถ้าเสียงถูกลบไปแล้ว (ลบระหว่างรอคิว)"""
        with self._lock:
            v = self._voices.get(voice_id)
            if v is None:
                return None
            for key, value in fields.items():
                setattr(v, key, value)
            v.updated_at = now()
            self._write(v)
            return v.model_copy(deep=True)

    def delete(self, voice_id: str) -> None:
        with self._lock:
            self._voices.pop(voice_id, None)
            shutil.rmtree(self.dir(voice_id), ignore_errors=True)

    def save_embedding(self, voice_id: str, emb: Optional[np.ndarray]) -> None:
        path = self.dir(voice_id) / "embedding.npy"
        if emb is None:
            path.unlink(missing_ok=True)
        else:
            np.save(path, emb.astype(np.float32))

    def embedding(self, voice_id: str) -> Optional[np.ndarray]:
        path = self.dir(voice_id) / "embedding.npy"
        return np.load(path) if path.exists() else None
