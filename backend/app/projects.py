"""โปรเจกต์: รวมคลิปหลายตอนของเรื่องเดียวกัน จำแนวเรื่อง ชื่อเฉพาะ และตัวละคร (ชื่อ บทบาท สรรพนาม เสียงพากย์ ลายเสียง)
คลิปที่ส่งเข้าโปรเจกต์ จับคู่ผู้พูดกับตัวละครด้วยลายเสียง แล้วตั้งชื่อและเสียงพากย์ให้เอง (เฉพาะที่มั่นใจ)
ผู้ใช้กด "บันทึกเข้าโปรเจกต์" จากงานไหน ตัวละครในโปรเจกต์ถึงจะเปลี่ยน (ไม่บันทึกเองอัตโนมัติ กันตอนที่แยกเสียงผิดไปกระทบทั้งเรื่อง)

เมื่อ DB_BACKEND=postgres เก็บบน Postgres (schema studio) ไม่เช่นนั้นเป็นไฟล์ JSON ใน data/projects/<id>.json
"""
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

from .config import settings, using_postgres
from .jobs import _atomic_write
from .schemas import Project, ProjectCharacter, now

log = logging.getLogger("dubbing.projects")

SURE_SIM = 0.65  # ลายเสียงคล้ายกันเท่านี้ขึ้นไป (และห่างตัวเลือกที่สองพอ) ตั้งชื่อและเสียงให้เลย
MAYBE_SIM = 0.5  # คล้ายพอให้แนะนำ ผู้ใช้ต้องยืนยัน (คนต่างคนเพศเดียวกันได้ราว 0.3–0.5)
SURE_MARGIN = 0.08
MAX_PITCH_GAP = 4.0  # เซมิโทน
MAX_SAMPLES = 20  # ลายเสียงของตัวละครเฉลี่ยจากกี่ตอนล่าสุด (ตอนใหม่มีน้ำหนักพอให้เสียงที่เปลี่ยนไปตามได้)


class ProjectStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "projects"
        self.root.mkdir(parents=True, exist_ok=True)
        self._pg = using_postgres()
        self._lock = threading.RLock()
        self._items: dict[str, Project] = {}
        loaded: list[Project] = []
        from_files = True
        if self._pg:
            from . import jobstore_pg
            try:
                loaded = jobstore_pg.load_projects()
                from_files = False
            except Exception:  # noqa: BLE001
                log.exception("โหลดโปรเจกต์จาก Supabase ไม่ได้ ลองจากไฟล์ในเครื่อง")
        if from_files:
            for f in self.root.glob("*.json"):
                try:
                    loaded.append(Project.model_validate_json(f.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    log.warning("skip broken project file %s", f)
        for p in loaded:
            self._items[p.id] = p

    def _write(self, p: Project) -> None:
        if self._pg:
            from . import jobstore_pg
            jobstore_pg.upsert_project(p)
            return
        _atomic_write(self.root / f"{p.id}.json", p.model_dump_json(indent=2))

    def all(self) -> list[Project]:
        with self._lock:
            return sorted((p.model_copy(deep=True) for p in self._items.values()), key=lambda p: p.updated_at, reverse=True)

    def get(self, pid: str) -> Optional[Project]:
        with self._lock:
            p = self._items.get(pid)
            return p.model_copy(deep=True) if p else None

    def add(self, p: Project) -> Project:
        with self._lock:
            self._items[p.id] = p
            self._write(p)
            return p.model_copy(deep=True)

    def save(self, p: Project) -> Project:
        with self._lock:
            p.updated_at = now()
            self._items[p.id] = p
            self._write(p)
            return p.model_copy(deep=True)

    def delete(self, pid: str) -> None:
        with self._lock:
            self._items.pop(pid, None)
            if self._pg:
                from . import jobstore_pg
                try:
                    jobstore_pg.delete_project(pid)
                except Exception:  # noqa: BLE001
                    log.exception("ลบโปรเจกต์ %s จาก Supabase ไม่สำเร็จ", pid)
                return
            (self.root / f"{pid}.json").unlink(missing_ok=True)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]


def _emb(c: ProjectCharacter) -> Optional[np.ndarray]:
    return np.asarray(c.embedding, dtype=np.float32) if c.embedding else None


def match_speakers(project: Project, profiles: dict) -> dict[str, dict]:
    """ผู้พูดของงาน → {character, score, sure} จับคู่หนึ่งต่อหนึ่ง เรียงจากคู่ที่คล้ายที่สุด
    profiles: ผู้พูด → library.Voice (emb ปรับขนาดแล้ว, pitch เป็นเซมิโทน)"""
    chars = [(c, _emb(c)) for c in project.characters]
    chars = [(c, e) for c, e in chars if e is not None]
    pairs = []
    best: dict[str, list[float]] = {}
    for s, v in profiles.items():
        if v.emb is None:
            continue
        for c, e in chars:
            sim = float(v.emb @ e)
            gap = abs(v.pitch - c.pitch) if c.pitch is not None and np.isfinite(v.pitch) else 0.0
            if gap > MAX_PITCH_GAP:
                continue
            pairs.append((sim, s, c.id))
            best.setdefault(s, []).append(sim)
    out: dict[str, dict] = {}
    used: set[str] = set()
    for sim, s, cid in sorted(pairs, reverse=True):
        if s in out or cid in used or sim < MAYBE_SIM:
            continue
        others = sorted(best[s], reverse=True)
        second = others[1] if len(others) > 1 else 0.0
        out[s] = {"character": cid, "score": round(sim, 3), "sure": sim >= SURE_SIM and sim - second >= SURE_MARGIN}
        used.add(cid)
    return out


def learn(project: Project, speaker: str, char_id: Optional[str], name: str, voice_id: Optional[str],
          profile, info: Optional[dict]) -> ProjectCharacter:
    """บันทึกผู้พูดของงานหนึ่งเข้าตัวละครในโปรเจกต์ (char_id = ตัวเดิม, None = ตัวใหม่)
    ลายเสียงเฉลี่ยกับของเดิมตามจำนวนตอน ชื่อ เสียงพากย์ และข้อมูลจากการวิเคราะห์เรื่องใช้ค่าล่าสุด"""
    c = next((x for x in project.characters if x.id == char_id), None) if char_id else None
    if c is None:
        c = ProjectCharacter(id=uuid.uuid4().hex[:8], name=name)
        project.characters.append(c)
    c.name = name or c.name
    c.voice_id = voice_id
    info = info or {}
    for k in ("gender", "role", "self", "addresses"):
        if info.get(k):
            setattr(c, k, info[k])
    if profile is not None and profile.emb is not None:
        old = _emb(c)
        n = min(c.samples, MAX_SAMPLES - 1)
        e = profile.emb if old is None else (old * n + profile.emb) / (n + 1)
        c.embedding = (e / (np.linalg.norm(e) or 1.0)).round(5).tolist()
        if np.isfinite(profile.pitch):
            c.pitch = round(float(profile.pitch if c.pitch is None else (c.pitch * n + profile.pitch) / (n + 1)), 2)
        c.samples = min(c.samples + 1, MAX_SAMPLES)
    c.updated_at = now()
    return c


def project_hints(project: Optional[Project], hints: dict) -> dict:
    """แนวเรื่อง ชื่อเฉพาะ และระดับภาษาของโปรเจกต์เป็นค่าตั้งต้นของงาน (ค่าที่ตั้งในงานมาก่อน)"""
    if project is None:
        return hints
    out = dict(hints)
    out["genre"] = hints.get("genre") or project.genre
    lines = [x for x in (hints.get("glossary") or "").splitlines() if x.strip()]
    known = {x.split("=")[0].strip().lower() for x in lines}
    lines += [x for x in project.glossary.splitlines() if x.strip() and x.split("=")[0].strip().lower() not in known]
    out["glossary"] = "\n".join(lines)
    if project.speech_style and not hints.get("register"):
        out["register"] = project.speech_style
    return out


def character_info(project: Optional[Project], matches: dict, names: dict) -> dict[str, dict]:
    """ผู้พูด → ข้อมูลตัวละครจากโปรเจกต์ (เฉพาะที่จับคู่แน่ใจ หรือผู้ใช้ยืนยันแล้ว) ให้ผู้แปลใช้เลือกสรรพนาม"""
    if project is None:
        return {}
    by_id = {c.id: c for c in project.characters}
    out = {}
    for s, m in (matches or {}).items():
        c = by_id.get(m.get("character"))
        if c and (m.get("sure") or m.get("confirmed")):
            out[s] = {k: v for k, v in {"gender": c.gender, "role": c.role, "self": c.self, "addresses": c.addresses}.items() if v}
    return out


def public(p: Project, episodes: int = 0) -> dict:
    """ส่งออกทาง API ไม่ส่งลายเสียง (ใหญ่ และไม่มีประโยชน์กับหน้าเว็บ)"""
    d = json.loads(p.model_dump_json())
    for c in d["characters"]:
        c["learned"] = bool(c.pop("embedding", None))
    d["episodes"] = episodes
    return d


_store: Optional[ProjectStore] = None
_store_lock = threading.Lock()


def get_store() -> ProjectStore:
    """ที่เก็บโปรเจกต์ตัวเดียวทั้งโปรเซส (API และขั้นวิเคราะห์ใช้ร่วมกัน)"""
    global _store
    with _store_lock:
        if _store is None:
            from .config import settings
            _store = ProjectStore(settings.data_dir)
        return _store
