"""วัดคุณภาพจากที่ผู้ใช้แก้: เทียบบทที่ AI ทำ (ตอนแปลเสร็จ) กับบทที่ใช้พากย์จริง ทุกครั้งที่พากย์เสร็จ
ใช้ดูว่าระบบพลาดตรงไหนบ่อย (คำแปล ผู้พูด เวลา) และใช้วัดผลหลังปรับ prompt หรือเปลี่ยนโมเดล

เก็บใน Supabase (supabase/migrations/20261104010000_quality.sql)
- job_quality: งานละแถว นับบรรทัดที่แก้แต่ละแบบ (ไม่มีเนื้อหาบท ลบงานแล้วยังเก็บไว้ทำสถิติ)
- quality_lines: บรรทัดที่ผู้ใช้แก้ ต้นฉบับ บทของ AI และบทที่แก้ (ชุดทดสอบ) ลบตามงานและตามเจ้าของ
DB_BACKEND ไม่ใช่ supabase หรือยังไม่ได้สร้างตาราง = ไม่บันทึก (log เตือน งานทำต่อได้ตามปกติ)
"""
import difflib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import supabase_db as sdb
from .pipeline.pauses import strip_marks

log = logging.getLogger("dubbing.quality")
AI_FILE = "ai_lines.json"  # บทที่ AI ทำ: ต้นฉบับ คำแปล ผู้พูด เวลา (เขียนใหม่ทุกครั้งที่แปลทั้งเรื่อง)
JOBS, LINES = "job_quality", "quality_lines"
TIME_TOL = 0.05  # เลื่อนเวลาเกินนี้ (วินาที) ถึงนับว่าแก้เวลา


def snapshot(job_dir: Path, utterances: list) -> None:
    """เรียกหลังแปลเสร็จ: จำบทของ AI ไว้เทียบตอนพากย์เสร็จ (นับจำนวนครั้งที่แปลทั้งเรื่องด้วย)"""
    path = job_dir / AI_FILE
    try:
        n = json.loads(path.read_text(encoding="utf-8")).get("translations", 0)
    except (OSError, ValueError, AttributeError):
        n = 0
    lines = {u.id: {"source": u.source, "target": u.target, "speaker": u.speaker, "start": u.start, "end": u.end}
             for u in utterances}
    path.write_text(json.dumps({"translations": n + 1, "lines": lines}, ensure_ascii=False), encoding="utf-8")


def _clean(text: str) -> str:
    return strip_marks(text or "").strip()


def compare(ai: dict[int, dict], utterances: list) -> tuple[dict, list[dict]]:
    """(ตัวเลขของงาน, บรรทัดที่แก้) เทียบบทของ AI กับบทตอนนี้"""
    final = {u.id: u for u in utterances}
    common = [i for i in final if i in ai]
    stats = {"lines_ai": len(ai), "lines_final": len(final), "added": sum(1 for i in final if i not in ai),
             "removed": sum(1 for i in ai if i not in final), "text_edited": 0, "speaker_changed": 0, "retimed": 0}
    lines, dist = [], 0.0
    for i in common:
        a, u = ai[i], final[i]
        kinds = []
        at, ft = _clean(a["target"]), _clean(u.target)
        if at != ft:
            kinds.append("text")
            dist += 1 - difflib.SequenceMatcher(None, at, ft, autojunk=False).ratio()
        if a["speaker"] != u.speaker:
            kinds.append("speaker")
        if abs(a["start"] - u.start) > TIME_TOL or abs(a["end"] - u.end) > TIME_TOL:
            kinds.append("time")
        for k, key in (("text", "text_edited"), ("speaker", "speaker_changed"), ("time", "retimed")):
            stats[key] += k in kinds
        if kinds:
            lines.append({"line_id": i, "source": u.source.strip() or a["source"], "ai_target": at, "final_target": ft,
                          "ai_speaker": a["speaker"], "final_speaker": u.speaker, "kinds": ",".join(kinds)})
    # ระยะแก้เฉลี่ยต่อบรรทัด (0 = ไม่แก้เลย 1 = เขียนใหม่ทั้งบรรทัด) นับทุกบรรทัดที่มีทั้งสองฝั่ง
    stats["edit_distance"] = round(dist / len(common), 4) if common else 0.0
    return stats, lines


def record(job, utterances: list, job_dir: Path) -> Optional[dict]:
    """พากย์เสร็จ: บันทึกตัวเลขของงานและบรรทัดที่แก้ (นับรอบพากย์ด้วย) คืนตัวเลขที่บันทึก"""
    if not sdb.enabled():
        return None
    try:
        snap = json.loads((job_dir / AI_FILE).read_text(encoding="utf-8"))
        ai = {int(k): v for k, v in snap["lines"].items()}
    except (OSError, ValueError, KeyError):
        return None  # งานเก่าที่ไม่มีบทของ AI หรือนำเข้า timeline (ไม่ได้แปลเอง)
    stats, lines = compare(ai, utterances)
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        prev = sdb.select(JOBS, select="synth_runs", job_id=f"eq.{job.id}")
        story = job.story or {}
        row = {"job_id": job.id, "owner": job.owner or "", "project_id": job.project_id or "",
               "source_lang": job.detected_lang or job.source_lang or "", "target_lang": job.target_lang,
               "genre": job.genre or story.get("genre") or "", "duration": round(job.duration or 0, 2),
               "translations": int(snap.get("translations") or 1),
               "synth_runs": (prev[0]["synth_runs"] if prev else 0) + 1, **stats, "updated_at": stamp}
        sdb.upsert(JOBS, row, "job_id")
        sdb.delete(LINES, job_id=f"eq.{job.id}")
        for i in range(0, len(lines), 500):
            sdb.upsert(LINES, [{**x, "job_id": job.id, "owner": job.owner or "", "target_lang": job.target_lang,
                                "updated_at": stamp} for x in lines[i:i + 500]], "job_id,line_id")
    except sdb.DBError as e:
        log.warning("quality not saved for job %s: %s", job.id, e)
        return None
    return row


def summary(days: int = 30) -> dict:
    """หน้าผู้ดูแล: สัดส่วนบรรทัดที่ผู้ใช้แก้แต่ละแบบ รวมทั้งช่วง แยกรายสัปดาห์ และแยกคู่ภาษา"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = sdb.select(JOBS, select="*", updated_at=f"gte.{since}", order="updated_at.desc", limit="10000")
    except sdb.DBError as e:
        log.warning("quality unavailable: %s", e)
        return {"available": False, "days": days, "total": _agg([]), "weeks": [], "langs": []}

    def week(r: dict) -> str:
        d = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")).date()
        return (d - timedelta(days=d.weekday())).isoformat()

    def groups(key) -> list[dict]:
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(key(r), []).append(r)
        return [{"key": k, **_agg(v)} for k, v in out.items()]

    return {"available": True, "days": days, "total": _agg(rows),
            "weeks": sorted(groups(week), key=lambda x: x["key"]),
            "langs": sorted(groups(lambda r: f'{r["source_lang"] or "?"}→{r["target_lang"]}'), key=lambda x: -x["jobs"])}


def _agg(rows: list[dict]) -> dict:
    lines = sum(r["lines_ai"] for r in rows)
    rate = lambda k: round(sum(r[k] for r in rows) / lines, 4) if lines else 0.0  # noqa: E731
    return {"jobs": len(rows), "lines": lines, "text_edited": rate("text_edited"), "speaker_changed": rate("speaker_changed"),
            "retimed": rate("retimed"), "added": rate("added"), "removed": rate("removed"),
            "edit_distance": round(sum(r["edit_distance"] * r["lines_ai"] for r in rows) / lines, 4) if lines else 0.0,
            "synth_runs": round(sum(r["synth_runs"] for r in rows) / len(rows), 2) if rows else 0.0,
            "translations": round(sum(r["translations"] for r in rows) / len(rows), 2) if rows else 0.0}


def edited_lines(days: int = 90, kind: str = "", limit: int = 5000) -> list[dict]:
    """บรรทัดที่ผู้ใช้แก้ (ชุดทดสอบ) ใหม่ก่อน kind = text / speaker / time หรือว่าง = ทุกแบบ"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    filters = {"kinds": f"like.*{kind}*"} if kind else {}
    try:
        return sdb.select(LINES, select="job_id,line_id,target_lang,source,ai_target,final_target,ai_speaker,final_speaker,kinds,updated_at",
                          updated_at=f"gte.{since}", order="updated_at.desc", limit=str(limit), **filters)
    except sdb.DBError as e:
        log.warning("quality lines unavailable: %s", e)
        return []


def forget_job(job_id: str) -> None:
    """ลบงาน: ลบเนื้อหาบท (ตัวเลขของงานเก็บไว้ทำสถิติ)"""
    if sdb.enabled():
        try:
            sdb.delete(LINES, job_id=f"eq.{job_id}")
        except sdb.DBError as e:
            log.warning("could not delete quality lines of %s: %s", job_id, e)


def forget_owner(owner: str) -> None:
    """ปิดบัญชี: ลบทั้งเนื้อหาบทและตัวเลขของผู้ใช้"""
    if sdb.enabled() and owner:
        for table in (LINES, JOBS):
            try:
                sdb.delete(table, owner=f"eq.{owner}")
            except sdb.DBError as e:
                log.warning("could not delete %s of %s: %s", table, owner, e)
