"""ค่าตั้งค่าที่ปรับจากหน้าเว็บได้ เก็บเป็น data/settings.json

ค่าเริ่มต้นมาจาก .env (VOICE_GAIN, BGM_GAIN, MAX_SPEEDUP, F5_STEPS) แล้วค่อยทับด้วยไฟล์นี้
"""
import json
import threading

from .config import settings
from .schemas import RuntimeSettings, RuntimeSettingsUpdate

_lock = threading.Lock()
_path = settings.data_dir / "settings.json"
_current: RuntimeSettings | None = None


def _defaults() -> RuntimeSettings:
    return RuntimeSettings(
        voice_gain=settings.voice_gain, bgm_gain=settings.bgm_gain,
        max_speedup=settings.max_speedup, f5_steps=settings.f5_steps)


def get() -> RuntimeSettings:
    global _current
    with _lock:
        if _current is None:
            base = _defaults().model_dump()
            if _path.exists():
                try:
                    base.update(json.loads(_path.read_text(encoding="utf-8")))
                except (ValueError, OSError):
                    pass
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
        _path.parent.mkdir(parents=True, exist_ok=True)
        _path.write_text(new.model_dump_json(indent=2), encoding="utf-8")
        _current = new
    return new.model_copy()
