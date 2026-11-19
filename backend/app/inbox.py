"""แจ้งเตือนในแอป (กระดิ่ง) เก็บในตาราง notifications ของ schema studio (สร้างด้วย migration หรือ ensure ตอนใช้ครั้งแรก)

สร้างผ่าน notify.py จุดเดียว: ทุกเหตุการณ์เขียนแถวที่นี่ก่อน แล้วค่อยตัดสินใจส่งอีเมล
ผู้ใช้เห็นเฉพาะของตัวเอง ลบแถวเก่าเกิน KEEP_DAYS อัตโนมัติ เขียนไม่ได้แค่บันทึก log ไม่กระทบงาน
"""
import logging
import secrets
import time
from typing import Optional

from . import accounts

log = logging.getLogger("dubbing.inbox")
KEEP_DAYS = 90
DEDUPE_SEC = 600  # เหตุการณ์ชนิดเดียวกันของงานเดียวกันภายในช่วงนี้นับเป็นอันเดียว (กันงานลองใหม่ส่งซ้ำรัว ๆ)
LIST_LIMIT = 30

_DDL = (
    "CREATE TABLE IF NOT EXISTS notifications ("
    "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, "
    "body TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '', job_id TEXT NOT NULL DEFAULT '', "
    "created_at REAL NOT NULL, read_at REAL)"
)
_ready = False


def _ensure(db) -> None:
    global _ready
    if _ready:
        return
    db.execute(_DDL)
    try:
        db.execute("CREATE INDEX IF NOT EXISTS notifications_user_created ON notifications(user_id, created_at)")
    except Exception:  # noqa: BLE001
        pass
    _ready = True


def _out(row) -> dict:
    return {"id": row["id"], "kind": row["kind"], "title": row["title"], "body": row["body"] or "",
            "link": row["link"] or "", "job_id": row["job_id"] or "", "created_at": row["created_at"],
            "read": row["read_at"] is not None}


def add(uid: Optional[str], kind: str, title: str, body: str = "", link: str = "", job_id: str = "") -> Optional[dict]:
    """เพิ่มแจ้งเตือนให้ผู้ใช้ คืน None ถ้าไม่เขียน (ปิดระบบบัญชี ซ้ำ หรือผิดพลาด)"""
    if not uid or not accounts.auth_enabled():
        return None
    try:
        now = time.time()
        with accounts._tx() as db:
            _ensure(db)
            if job_id and db.execute(
                "SELECT 1 FROM notifications WHERE user_id = ? AND kind = ? AND job_id = ? AND created_at > ?",
                (uid, kind, job_id, now - DEDUPE_SEC),
            ).fetchone():
                return None
            nid = secrets.token_urlsafe(12)
            db.execute(
                "INSERT INTO notifications (id, user_id, kind, title, body, link, job_id, created_at, read_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (nid, uid, kind, title[:200], body[:500], link[:300], job_id[:80], now),
            )
            if secrets.randbelow(40) == 0:  # ลบของเก่านาน ๆ ครั้ง ไม่ต้องมี cron
                db.execute("DELETE FROM notifications WHERE created_at < ?", (now - KEEP_DAYS * 86400,))
            row = db.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone()
        return _out(row)
    except Exception:  # noqa: BLE001
        log.exception("inbox add failed for %s (%s)", uid, kind)
        return None


def list_for(uid: str, limit: int = LIST_LIMIT) -> dict:
    """รายการล่าสุดก่อน และจำนวนที่ยังไม่อ่านทั้งหมด (นับแยก ไม่ถูกตัดตาม limit)"""
    limit = max(1, min(int(limit), 100))
    with accounts._tx() as db:
        _ensure(db)
        rows = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                          (uid, limit)).fetchall()
        unread = db.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
                            (uid,)).fetchone()["n"]
    return {"items": [_out(r) for r in rows], "unread": int(unread)}


def unread_count(uid: str) -> int:
    with accounts._tx() as db:
        _ensure(db)
        return int(db.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
                              (uid,)).fetchone()["n"])


def mark_read(uid: str, nid: str) -> bool:
    """ทำเครื่องหมายอ่านแล้วเฉพาะของผู้ใช้คนนี้ คืน False ถ้าไม่พบ"""
    with accounts._tx() as db:
        _ensure(db)
        row = db.execute("SELECT id FROM notifications WHERE id = ? AND user_id = ?", (nid, uid)).fetchone()
        if row is None:
            return False
        db.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ? AND read_at IS NULL",
                   (time.time(), nid, uid))
    return True


def mark_all(uid: str) -> None:
    with accounts._tx() as db:
        _ensure(db)
        db.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (time.time(), uid))
