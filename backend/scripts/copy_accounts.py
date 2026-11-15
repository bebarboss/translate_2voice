"""สร้าง schema studio ตารางสถิติคุณภาพ แล้วคัดลอก data/accounts.db ขึ้น Supabase

รันซ้ำได้ (ล้างเฉพาะ schema studio แล้วใส่ใหม่ ไม่แตะคลังเสียง งาน หรือไฟล์ใน data/)
    python scripts/copy_accounts.py            # ดูจำนวนแถว
    python scripts/copy_accounts.py --apply    # คัดลอกจริง
ต้องตั้ง SUPABASE_DB_URL ใน .env
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.config import settings  # noqa: E402
from app.pgstore import _dsn  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
SQL_FILES = (
    "20261104010000_quality.sql",
    "20261107000000_studio_accounts.sql",
    "20261112010000_actor_pii_columns.sql",
)
TABLES = (
    "users", "sessions", "subscriptions", "ledger", "topups", "cards", "slip_uses",
    "user_consents", "actors", "actor_consents", "actor_voices", "actor_moods",
    "actor_payment", "actor_payouts", "voice_usage",
)
IDENTITY = ("ledger", "user_consents", "actor_consents", "actor_payouts")


def _statements(text: str):
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            yield "\n".join(buf)
            buf = []


def apply_sql(conn) -> None:
    for name in SQL_FILES:
        for statement in _statements((ROOT / name).read_text(encoding="utf-8")):
            conn.execute(statement)
    conn.commit()


def main(apply: bool) -> None:
    src_path = settings.data_dir / "accounts.db"
    if not src_path.exists():
        raise SystemExit(f"ไม่พบ {src_path}")
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    print(f"ต้นทาง {src_path}")
    for table in TABLES:
        if table not in have:
            print(f"{table}: ไม่มีใน SQLite")
            continue
        n = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {n} แถว")
    if not apply:
        print("ยังไม่เขียน ใส่ --apply เพื่อสร้างตารางและคัดลอก")
        return
    with psycopg.connect(_dsn(), row_factory=dict_row, connect_timeout=20) as conn:
        apply_sql(conn)
        conn.execute("SET search_path TO studio")
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY")
        for table in TABLES:
            if table not in have:
                continue
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
            pg_cols = {r["column_name"] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'studio' AND table_name = %s", (table,))}
            use = [c for c in cols if c in pg_cols]
            rows = [tuple(r) for r in src.execute(f"SELECT {', '.join(use)} FROM {table}")]
            if rows:
                marks = ", ".join(["%s"] * len(use))
                conn.executemany(
                    f"INSERT INTO {table} ({', '.join(use)}) VALUES ({marks})", rows)
        for table in IDENTITY:
            conn.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                "COALESCE((SELECT MAX(id) FROM " + table + "), 1), "
                "(SELECT MAX(id) FROM " + table + ") IS NOT NULL)",
                (f"studio.{table}",))
        conn.commit()
        print("คัดลอกแล้ว")


if __name__ == "__main__":
    main("--apply" in sys.argv)
