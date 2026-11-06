"""ความจำคำแปลของโปรเจกต์: เก็บคู่ "ต้นฉบับ → บทพากย์ที่ใช้จริง" ของแต่ละตอน แล้วให้ผู้แปลดูเป็นตัวอย่างตอนแปลตอนถัดไป
ตอนต่อ ๆ ไปจึงใช้สรรพนาม คำเรียก และสำนวนประจำตัวละครตามที่ผู้ใช้แก้ไว้ (ไม่ได้ฝึกโมเดล แค่ส่งตัวอย่าง)

DB_BACKEND=supabase เก็บในตาราง translation_memory บน Supabase (supabase/migrations/20261104000000_translation_memory.sql)
ไม่งั้นเก็บใน data/accounts.db (SQLite) ยังไม่ได้สร้างตารางบน Supabase = ไม่มีความจำ (บันทึก log เตือน งานทำต่อได้ตามปกติ)
- edited = 1: ผู้ใช้แก้บทจากที่ AI แปล (เทียบกับ ai_targets.json ที่บันทึกตอนแปล) ใช้เป็นตัวอย่างได้
- edited = 0: บทที่ AI แปลแล้วผู้ใช้พากย์ไปโดยไม่แก้ ใช้แค่ตอนต้นฉบับตรงกันทุกคำ (ประโยคติดปาก คำทักทาย)
"""
import difflib
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import supabase_db as sdb
from .accounts import _read, _tx

log = logging.getLogger("dubbing.memory")
TABLE = "translation_memory"

SCHEMA = """
CREATE TABLE IF NOT EXISTS translation_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, job_id TEXT NOT NULL, line_id INTEGER NOT NULL,
  character_id TEXT NOT NULL DEFAULT '', speaker_name TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
  source_norm TEXT NOT NULL, target TEXT NOT NULL, target_lang TEXT NOT NULL, edited INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE (job_id, line_id));
CREATE INDEX IF NOT EXISTS translation_memory_project ON translation_memory(project_id, target_lang, edited);
"""
AI_FILE = "ai_targets.json"  # บทที่ AI แปล (หลังย่อให้พอดีเวลา) ไว้เทียบว่าผู้ใช้แก้บรรทัดไหน
MAX_ROWS = 4000  # อ่านความจำล่าสุดกี่แถวต่อโปรเจกต์ตอนแปล
MIN_SIM = 0.55  # ต้นฉบับคล้ายกันเท่านี้ขึ้นไปถึงใช้เป็นตัวอย่าง
_ready = False


def _init() -> None:
    global _ready
    if _ready or sdb.enabled():
        _ready = True  # โหมด Supabase เขียนผ่าน REST ไม่ใช้ตาราง SQLite
        return
    from .accounts import _db, _lock
    with _lock:
        _db().executescript(SCHEMA)
    _ready = True


def norm(text: str) -> str:
    """ต้นฉบับสำหรับเทียบ: ตัวพิมพ์เล็ก ไม่มีเครื่องหมายวรรคตอน / และช่องว่างซ้ำ"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _clean(target: str) -> str:
    return " ".join(re.sub(r"\s*(?<!\d)/(?!\d)\s*", " ", target).split())


def save_ai_targets(job_dir: Path, utterances: list) -> None:
    """เรียกหลังแปลเสร็จ: จำบทที่ AI แปลไว้ เทียบภายหลังว่าผู้ใช้แก้บรรทัดไหน"""
    (job_dir / AI_FILE).write_text(json.dumps({u.id: u.target for u in utterances}, ensure_ascii=False), encoding="utf-8")


def record_job(job, utterances: list, job_dir: Path) -> int:
    """บันทึกบทของงานในโปรเจกต์ลงความจำ (บรรทัดเดิมของงานเดิมเขียนทับ) คืนจำนวนบรรทัดที่บันทึก"""
    if not job.project_id:
        return 0
    _init()
    try:
        ai = {int(k): v for k, v in json.loads((job_dir / AI_FILE).read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        ai = None  # งานเก่าที่ไม่มีไฟล์ ไม่รู้ว่าแก้บรรทัดไหน ถือว่าไม่ได้แก้
    chars = {s: m.get("character", "") for s, m in (job.project_matches or {}).items() if m.get("sure") or m.get("confirmed")}
    now = time.time()
    rows = []
    for u in utterances:
        target = _clean(u.target)
        if not target or not u.source.strip():
            continue
        edited = ai is not None and (u.id not in ai or _clean(ai[u.id]) != target)
        rows.append((job.project_id, job.id, u.id, chars.get(u.speaker, ""), (job.speaker_names or {}).get(u.speaker, ""),
                     u.source.strip(), norm(u.source), target, job.target_lang, int(edited), now, now))
    if sdb.enabled():
        try:
            stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
            sdb.delete(TABLE, job_id=f"eq.{job.id}")
            for i in range(0, len(rows), 500):
                sdb.upsert(TABLE, [{"project_id": r[0], "job_id": r[1], "line_id": r[2], "owner": job.owner or "",
                                    "character_id": r[3], "speaker_name": r[4], "source": r[5], "source_norm": r[6],
                                    "target": r[7], "target_lang": r[8], "edited": bool(r[9]), "updated_at": stamp}
                                   for r in rows[i:i + 500]], "job_id,line_id")
        except sdb.DBError as e:
            log.warning("translation memory not saved for job %s: %s", job.id, e)
            return 0
        return len(rows)
    with _tx() as db:
        db.execute("DELETE FROM translation_memory WHERE job_id = ?", (job.id,))
        db.executemany("INSERT INTO translation_memory (project_id, job_id, line_id, character_id, speaker_name, source, "
                       "source_norm, target, target_lang, edited, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load(project_id: str, target_lang: str, exclude_job: Optional[str] = None) -> list[dict]:
    if sdb.enabled():
        try:
            rows = sdb.select(TABLE, select="id,character_id,speaker_name,source,source_norm,target,edited",
                              project_id=f"eq.{project_id}", target_lang=f"eq.{target_lang}",
                              job_id=f"neq.{exclude_job or ''}", order="updated_at.desc", limit=str(MAX_ROWS))
        except sdb.DBError as e:
            log.warning("translation memory unavailable: %s", e)
            return []
        return [{**r, "edited": int(bool(r["edited"]))} for r in rows]
    _init()
    rows = _read("SELECT * FROM translation_memory WHERE project_id = ? AND target_lang = ? AND job_id != ? "
                 "ORDER BY updated_at DESC LIMIT ?", project_id, target_lang, exclude_job or "", MAX_ROWS)
    return [dict(r) for r in rows]


def examples_for(memory: list[dict], lines: list, char_of: dict, limit: int = 8) -> tuple[list[dict], dict[int, str]]:
    """ตัวอย่างสำหรับชุดประโยคที่กำลังแปล
    คืน (ตัวอย่างจากบทที่ผู้ใช้แก้ เรียงจากคล้ายที่สุด, id ประโยค → บทเดิมที่ต้นฉบับตรงกันทุกคำ)
    char_of: ผู้พูด → id ตัวละครในโปรเจกต์ ตัวอย่างของตัวละครเดียวกันได้คะแนนเพิ่ม"""
    if not memory:
        return [], {}
    exact: dict[str, dict] = {}
    for m in memory:  # ใหม่ก่อน: ต้นฉบับซ้ำหลายตอนใช้บทล่าสุด บทที่ผู้ใช้แก้มาก่อนบทที่ไม่ได้แก้
        k = m["source_norm"]
        if k and (k not in exact or (m["edited"] and not exact[k]["edited"])):
            exact[k] = m
    fixed = {u.id: exact[norm(u.source)]["target"] for u in lines if norm(u.source) in exact}
    edited = [m for m in memory if m["edited"]]
    scored: dict[int, tuple[float, dict]] = {}
    for u in lines:
        q = norm(u.source)
        if not q or u.id in fixed:
            continue
        sm = difflib.SequenceMatcher(None, "", q, autojunk=False)  # b = ประโยคที่กำลังแปล (SequenceMatcher แคชฝั่ง b)
        cid = char_of.get(u.speaker, "")
        for m in edited:
            sm.set_seq1(m["source_norm"])
            if sm.real_quick_ratio() < MIN_SIM or sm.quick_ratio() < MIN_SIM:
                continue
            r = sm.ratio()
            if r < MIN_SIM:
                continue
            score = r + (0.1 if cid and m["character_id"] == cid else 0)
            if m["id"] not in scored or scored[m["id"]][0] < score:
                scored[m["id"]] = (score, m)
    # ตัวละครที่พูดในชุดนี้: ใส่บทที่แก้ล่าสุดของตัวละครนั้นอย่างน้อยหนึ่งบท (สรรพนามและคำเรียกประจำตัว)
    for cid in {char_of.get(u.speaker, "") for u in lines} - {""}:
        own = next((m for m in edited if m["character_id"] == cid), None)
        if own and own["id"] not in scored:
            scored[own["id"]] = (0.5, own)
    best = sorted(scored.values(), key=lambda x: -x[0])[:limit]
    return [{"speaker": m["speaker_name"], "source": m["source"], "translation": m["target"]} for _, m in best], fixed


def listing(project_id: str, limit: int = 200) -> dict:
    """สำหรับหน้าโปรเจกต์: จำนวนทั้งหมด จำนวนที่ผู้ใช้แก้ และบทที่แก้ล่าสุด (available = ใช้ความจำได้)"""
    if sdb.enabled():
        try:
            flags = sdb.select(TABLE, select="edited", project_id=f"eq.{project_id}", limit="100000")
            rows = sdb.select(TABLE, select="id,job_id,line_id,speaker_name,source,target,updated_at",
                              project_id=f"eq.{project_id}", edited="eq.true", order="updated_at.desc", limit=str(limit))
        except sdb.DBError as e:
            log.warning("translation memory unavailable: %s", e)
            return {"available": False, "total": 0, "edited": 0, "items": []}
        return {"available": True, "total": len(flags), "edited": sum(1 for f in flags if f["edited"]), "items": rows}
    _init()
    total = _read("SELECT COUNT(*) AS n, COALESCE(SUM(edited), 0) AS e FROM translation_memory WHERE project_id = ?", project_id)[0]
    rows = _read("SELECT id, job_id, line_id, speaker_name, source, target, updated_at FROM translation_memory "
                 "WHERE project_id = ? AND edited = 1 ORDER BY updated_at DESC LIMIT ?", project_id, limit)
    return {"available": True, "total": total["n"], "edited": total["e"], "items": [dict(r) for r in rows]}


def delete(project_id: str, mid: Optional[int] = None) -> None:
    """ลบบรรทัดเดียว (mid) หรือทั้งโปรเจกต์"""
    if sdb.enabled():
        sdb.delete(TABLE, project_id=f"eq.{project_id}", **({"id": f"eq.{mid}"} if mid is not None else {}))
        return
    _init()
    with _tx() as db:
        if mid is None:
            db.execute("DELETE FROM translation_memory WHERE project_id = ?", (project_id,))
        else:
            db.execute("DELETE FROM translation_memory WHERE project_id = ? AND id = ?", (project_id, mid))


def forget_projects(project_ids: list[str]) -> None:
    """ปิดบัญชี: ลบความจำของทุกโปรเจกต์ของผู้ใช้"""
    for pid in project_ids:
        try:
            delete(pid)
        except Exception as e:  # noqa: BLE001
            log.warning("could not delete translation memory of %s: %s", pid, e)
