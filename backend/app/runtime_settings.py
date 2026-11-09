"""ค่าตั้งค่าที่ปรับจากหน้าเว็บได้ เก็บเป็น data/settings.json หรือตาราง app_settings ของ Supabase (DB_BACKEND=supabase)

ค่าเริ่มต้นมาจาก audio_constants.py (VOICE_GAIN, BGM_GAIN, MAX_SPEEDUP, F5_STEPS) แล้วค่อยทับด้วยค่าที่บันทึกไว้
โหมด Supabase ยังเขียน settings.json ไว้ด้วยเป็นสำรอง อ่านฐานข้อมูลไม่ได้ตอนเริ่มจะใช้ไฟล์แทน
"""
import json
import logging
import threading

from . import supabase_db as db
from .config import settings
from .schemas import RuntimeSettings, RuntimeSettingsUpdate

log = logging.getLogger("dubbing.settings")

_lock = threading.Lock()
_path = settings.data_dir / "settings.json"
_current: RuntimeSettings | None = None


def _defaults() -> RuntimeSettings:
    return RuntimeSettings(
        voice_gain=settings.voice_gain, bgm_gain=settings.bgm_gain,
        max_speedup=settings.max_speedup, f5_steps=settings.f5_steps)


def _stored() -> dict:
    if db.enabled():
        try:
            rows = db.select("app_settings", select="data", id="eq.1")
            return rows[0]["data"] if rows else {}
        except db.DBError as e:
            log.warning("อ่านค่าตั้งจาก Supabase ไม่ได้ ใช้ settings.json แทน: %s", e)
    if _path.exists():
        try:
            return json.loads(_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def get() -> RuntimeSettings:
    global _current
    with _lock:
        if _current is None:
            base = _defaults().model_dump()
            base.update(_stored())
            try:
                _current = RuntimeSettings(**base)
            except ValueError:
                _current = _defaults()
        return _current.model_copy()


def update(patch: RuntimeSettingsUpdate) -> RuntimeSettings:
    global _current
    merged = get().model_dump()
    merged.update(patch.model_dump(exclude_none=True))
    new = RuntimeSettings(**merged)
    with _lock:
        if db.enabled():
            db.update("app_settings", {"data": new.model_dump(mode="json")}, id="eq.1")
        _path.parent.mkdir(parents=True, exist_ok=True)
        _path.write_text(new.model_dump_json(indent=2), encoding="utf-8")
        _current = new
    return new.model_copy()
