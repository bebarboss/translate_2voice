"""คลังเสียงภาษาไทย: เก็บใน data/voices/<id>/ (voice.json, original.*, ref.wav, embedding.npy)
เสียงตัวอย่างอารมณ์อื่นเก็บใน data/voices/<id>/moods/<mood>/ (original.*, ref.wav)

DB_BACKEND=supabase: ข้อมูลเสียงอ่านจากตาราง voices / voice_moods และบันทึกลงทั้งสองที่
(voice.json และ embedding.npy ยังเขียนไว้เป็นสำรอง ไฟล์เสียงอยู่ในเครื่องเหมือนเดิม)"""
import logging
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional, get_args

import numpy as np

from . import supabase_db as db
from .jobs import _atomic_write
from .schemas import LibraryVoice, Mood, VoiceMood, VoiceStatus, now

MOODS: tuple[str, ...] = get_args(Mood)

log = logging.getLogger("dubbing.voices")

# None = ยังไม่รู้, True/False = มี/ไม่มีตาราง voices บน Postgres (กัน error ซ้ำ)
_cloud_voices: Optional[bool] = None


def _mark_cloud(ok: bool, err: Optional[Exception] = None) -> None:
    global _cloud_voices
    _cloud_voices = ok
    if not ok and err is not None:
        log.warning("ปิด sync คลังเสียงกับ Supabase REST แล้ว ใช้ไฟล์ในเครื่อง: %s", err)


def _cloud_enabled() -> bool:
    return db.enabled() and _cloud_voices is not False


class VoiceStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "voices"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._voices: dict[str, LibraryVoice] = {}
        for v in self._load():
            stuck = [x for x in [v, *v.moods] if x.status == VoiceStatus.processing]
            for x in stuck:
                x.status, x.error = VoiceStatus.failed, "เซิร์ฟเวอร์รีสตาร์ตระหว่างเตรียมเสียง กดลองใหม่ได้เลย"
            if stuck:
                self._write(v)
            self._voices[v.id] = v

    def _load(self) -> list[LibraryVoice]:
        if _cloud_enabled():
            try:
                log.info("โหลดคลังเสียงจาก Postgres…")
                rows = [from_row(r) for r in db.select("voices", select=f"{VOICE_COLS},voice_moods(*)")]
                _mark_cloud(True)
                log.info("โหลดคลังเสียงจาก Postgres ได้ %s เสียง", len(rows))
                return rows
            except db.DBError as e:
                _mark_cloud(False, e)
        voices = []
        for f in self.root.glob("*/voice.json"):
            try:
                voices.append(LibraryVoice.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception:
                log.warning("skip broken voice file %s", f)
        return voices

    def _write(self, v: LibraryVoice) -> None:
        _atomic_write(self.dir(v.id) / "voice.json", v.model_dump_json(indent=2))
        if not _cloud_enabled():
            return
        try:
            push(v)
            _mark_cloud(True)
        except db.DBError as e:
            # ไฟล์ในเครื่องเป็นต้นฉบับอยู่แล้ว — อย่าทำให้ทั้งคำขอล้มเพราะ REST ขัดข้องชั่วคราว
            _mark_cloud(False, e)
            log.error("บันทึกคลังเสียงลง Supabase ไม่ได้ (ใช้ไฟล์ในเครื่องต่อ): %s", e)

    def dir(self, voice_id: str) -> Path:
        return self.root / voice_id

    def mood_dir(self, voice_id: str, mood: Optional[str]) -> Path:
        return self.dir(voice_id) / "moods" / mood if mood else self.dir(voice_id)

    def ref_path(self, voice_id: str, mood: Optional[str] = None) -> Path:
        """เสียงตัวอย่างที่ทำความสะอาดและตัดแล้ว (24 kHz mono) ใช้ฟังและส่งให้ F5-TTS"""
        return self.mood_dir(voice_id, mood) / "ref.wav"

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

    def set_mood(self, voice_id: str, m: VoiceMood) -> Optional[LibraryVoice]:
        """เพิ่มหรือแทนเสียงอารมณ์ m.mood"""
        with self._lock:
            v = self._voices.get(voice_id)
            if v is None:
                return None
            v.moods = sorted([x for x in v.moods if x.mood != m.mood] + [m], key=lambda x: MOODS.index(x.mood))
            v.updated_at = now()
            self._write(v)
            return v.model_copy(deep=True)

    def update_mood(self, voice_id: str, mood: str, **fields) -> Optional[VoiceMood]:
        """คืน None ถ้าเสียงหรืออารมณ์นั้นถูกลบไปแล้ว"""
        with self._lock:
            v = self._voices.get(voice_id)
            m = next((x for x in v.moods if x.mood == mood), None) if v else None
            if m is None:
                return None
            for key, value in fields.items():
                setattr(m, key, value)
            v.updated_at = now()
            self._write(v)
            return m.model_copy(deep=True)

    def delete_mood(self, voice_id: str, mood: str) -> None:
        with self._lock:
            v = self._voices.get(voice_id)
            if v is not None:
                v.moods = [x for x in v.moods if x.mood != mood]
                v.updated_at = now()
                self._write(v)
            shutil.rmtree(self.mood_dir(voice_id, mood), ignore_errors=True)

    def delete(self, voice_id: str) -> None:
        with self._lock:
            self._voices.pop(voice_id, None)
            if _cloud_enabled():
                try:
                    db.delete("voices", id=f"eq.{voice_id}")
                    _mark_cloud(True)
                except db.DBError as e:
                    _mark_cloud(False, e)
                    log.error("ลบคลังเสียงใน Supabase ไม่ได้: %s", e)
            shutil.rmtree(self.dir(voice_id), ignore_errors=True)

    def save_embedding(self, voice_id: str, emb: Optional[np.ndarray]) -> None:
        path = self.dir(voice_id) / "embedding.npy"
        if emb is None:
            path.unlink(missing_ok=True)
        else:
            np.save(path, emb.astype(np.float32))
        if not _cloud_enabled():
            return
        try:
            db.update("voices", {"embedding": db.vector(emb)}, id=f"eq.{voice_id}")
            _mark_cloud(True)
        except db.DBError as e:
            _mark_cloud(False, e)
            log.error("บันทึกลายเสียงลง Supabase ไม่ได้: %s", e)

    def embedding(self, voice_id: str) -> Optional[np.ndarray]:
        path = self.dir(voice_id) / "embedding.npy"
        return np.load(path) if path.exists() else None


# ---------------------------------------------------------------- แปลงกับแถวในตาราง voices / voice_moods
VOICE_COLS = ("id,name,gender,tone,description,categories,image,status,stage,error,source_name,ref_text,"
              "ref_duration,pitch_hz,quality,analysis,created_at,updated_at")


def _mood_row(voice_id: str, m: VoiceMood) -> dict:
    return {"voice_id": voice_id, "mood": m.mood, "status": m.status.value, "stage": m.stage, "error": m.error,
            "source_name": m.filename, "ref_text": m.text, "ref_duration": m.duration, "quality": m.quality,
            "analysis": m.analysis.model_dump() if m.analysis else None}


def to_row(v: LibraryVoice) -> dict:
    return {"id": v.id, "name": v.name, "gender": v.gender, "tone": v.tone, "description": v.description,
            "categories": v.categories, "image": v.image, "status": v.status.value, "stage": v.stage,
            "error": v.error, "source_name": v.filename, "ref_text": v.text, "ref_duration": v.duration,
            "pitch_hz": v.pitch_hz, "quality": v.quality,
            "analysis": v.analysis.model_dump() if v.analysis else None,
            "created_at": v.created_at.isoformat(), "updated_at": v.updated_at.isoformat()}


def from_row(r: dict) -> LibraryVoice:
    moods = [VoiceMood(mood=m["mood"], status=m["status"], stage=m["stage"], error=m["error"],
                       filename=m["source_name"], text=m["ref_text"], duration=m["ref_duration"],
                       quality=m["quality"], analysis=m["analysis"]) for m in r.get("voice_moods") or []]
    return LibraryVoice(
        id=r["id"], name=r["name"], gender=r["gender"], tone=r["tone"], description=r["description"],
        categories=r["categories"], image=r["image"], status=r["status"], stage=r["stage"], error=r["error"],
        filename=r["source_name"], text=r["ref_text"], duration=r["ref_duration"], pitch_hz=r["pitch_hz"],
        quality=r["quality"], analysis=r["analysis"], created_at=r["created_at"], updated_at=r["updated_at"],
        moods=sorted(moods, key=lambda m: MOODS.index(m.mood)))


def push(v: LibraryVoice) -> None:
    """บันทึกเสียงและเสียงอารมณ์ทั้งหมดลง Supabase (อารมณ์ที่ไม่อยู่ใน v.moods ถูกลบ)"""
    db.upsert("voices", to_row(v), on_conflict="id")
    if v.moods:
        db.upsert("voice_moods", [_mood_row(v.id, m) for m in v.moods], on_conflict="voice_id,mood")
        db.delete("voice_moods", voice_id=f"eq.{v.id}", mood=f"not.in.({','.join(m.mood for m in v.moods)})")
    else:
        db.delete("voice_moods", voice_id=f"eq.{v.id}")
