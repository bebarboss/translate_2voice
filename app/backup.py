"""สำรองข้อมูลอัตโนมัติ: ฐานข้อมูลบัญชี (accounts.db) และไฟล์ JSON ทั้งหมดใน data/ (งาน บท คลังเสียง ค่าตั้ง)
ไม่รวมไฟล์เสียงและวิดีโอ (ใหญ่ และสร้างใหม่จากต้นฉบับได้)

BACKUP_DIR = โฟลเดอร์ปลายทาง (ใน Docker คือ /app/backups ผูกกับ BACKUP_PATH บนเครื่อง ดู docker-compose.yml)
ตั้ง BACKUP_PATH เป็นโฟลเดอร์ที่ซิงก์ขึ้นคลาวด์ (OneDrive, Google Drive) หรือดิสก์อีกลูก ข้อมูลจะไม่หายเมื่อดิสก์นี้เสีย
BACKUP_HOURS = ทุกกี่ชั่วโมง (0 = ปิด), BACKUP_KEEP = เก็บกี่ชุดล่าสุด
"""
import logging
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)
TH = timezone(timedelta(hours=7))
PREFIX = "backup-"


def _dest() -> Path:
    return settings.backup_dir


def list_backups() -> list[dict]:
    d = _dest()
    files = sorted(d.glob(f"{PREFIX}*.tar.gz"), reverse=True) if d.exists() else []
    return [{"name": f.name, "bytes": f.stat().st_size, "created_at": f.stat().st_mtime} for f in files]


def run() -> Path:
    """สร้างไฟล์สำรองหนึ่งชุด ลบชุดเก่าที่เกิน BACKUP_KEEP คืน path ไฟล์ที่สร้าง"""
    data, dest = settings.data_dir, _dest()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{PREFIX}{datetime.now(TH):%Y%m%d-%H%M%S}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "accounts.db"
        db = data / "accounts.db"
        if db.exists():  # backup API ได้สำเนาที่สมบูรณ์แม้มีคนเขียนอยู่ (ไม่ใช่ copy ไฟล์ตรง ๆ ที่อาจได้ครึ่งธุรกรรม)
            src, dst = sqlite3.connect(db), sqlite3.connect(snap)
            try:
                src.backup(dst)
            finally:
                src.close(), dst.close()
        part = out.with_suffix(".part")
        with tarfile.open(part, "w:gz") as tar:
            if snap.exists():
                tar.add(snap, "accounts.db")
            for f in sorted(data.rglob("*.json")):
                if dest not in f.parents:
                    tar.add(f, f.relative_to(data).as_posix())
        part.replace(out)
    for old in sorted(dest.glob(f"{PREFIX}*.tar.gz"), reverse=True)[max(settings.backup_keep, 1):]:
        old.unlink(missing_ok=True)
    log.info("backup %s (%.1f MB)", out, out.stat().st_size / 1e6)
    return out


def _loop() -> None:
    every = settings.backup_hours * 3600
    while True:
        last = list_backups()
        if not last or time.time() - last[0]["created_at"] >= every:
            try:
                run()
            except Exception:
                log.exception("backup failed")
        time.sleep(600)


def start() -> None:
    """เริ่มเธรดสำรองข้อมูลตามรอบ (ตอน API เริ่ม) ถ้าครบรอบแล้วสำรองทันที"""
    if settings.backup_hours > 0:
        threading.Thread(target=_loop, name="backup", daemon=True).start()
