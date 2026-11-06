"""เชื่อม Postgres ของ Supabase สำหรับบัญชี (schema studio)

คำสั่ง SQL ใน accounts.py / actors.py / consent.py เขียนแบบ SQLite (`?`, INSERT OR REPLACE)
ตัวนี้แปลให้พอใช้กับ Postgres และเปิดคนละการเชื่อมต่อต่อเธรด
"""
import re
import threading
from typing import Optional
from urllib.parse import quote, unquote, urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row

from .config import settings

_local = threading.local()
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Row(dict):
    """แถวที่อ่านได้ทั้งชื่อคอลัมน์และลำดับ เหมือน sqlite3.Row"""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Result:
    def __init__(self, rows: list[Row], rowcount: int = -1):
        self._rows = rows
        self.rowcount = rowcount

    def fetchall(self) -> list[Row]:
        return self._rows

    def fetchone(self) -> Optional[Row]:
        return self._rows[0] if self._rows else None


# โฮสต์ db.<ref>.supabase.co เป็น IPv6 ล้วน คอนเทนเนอร์ Docker ต่อไม่ถึง
# พูลเลอร์โหมดเซสชันของโปรเจกต์นี้อยู่ eu-west-1 และมี IPv4
_POOLER_HOST = "aws-0-eu-west-1.pooler.supabase.com"


def _dsn() -> str:
    url = (settings.supabase_db_url or "").strip()
    if not url:
        raise RuntimeError("ตั้ง SUPABASE_DB_URL ก่อนใช้บัญชีบน Supabase")
    parts = urlparse(url)
    host = parts.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        ref = host.split(".", 2)[1]
        user = parts.username or "postgres"
        if "." not in user:
            user = f"{user}.{ref}"
        # env ในคอนเทนเนอร์เก็บ %20 แบบตัวอักษร urlparse ไม่ได้ถอดรหัสให้ ต้องถอดครั้งเดียวก่อนใส่กลับ
        password = quote(unquote(parts.password or ""), safe="")
        user = quote(user, safe=".")
        url = urlunparse(parts._replace(netloc=f"{user}:{password}@{_POOLER_HOST}:5432"))
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _rewrite(sql: str) -> str:
    """INSERT OR IGNORE / OR REPLACE ของ SQLite → ON CONFLICT ของ Postgres"""
    ignore = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT", sql, count=1, flags=re.IGNORECASE)
    if ignore != sql:
        return ignore.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    match = re.match(r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*(.*)$", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return sql
    table, rest = match.group(1), match.group(2)
    body = f"INSERT INTO {table} {rest}".rstrip().rstrip(";")
    if table == "subscriptions":
        return (body + " ON CONFLICT (user_id) DO UPDATE SET plan_id = EXCLUDED.plan_id, "
                "minutes_left = EXCLUDED.minutes_left, started_at = EXCLUDED.started_at, expires_at = EXCLUDED.expires_at")
    if table == "actor_payment":
        cols = ("payee_name", "tax_id", "address", "bank", "account_no", "account_name", "updated_at")
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        return body + f" ON CONFLICT (user_id) DO UPDATE SET {sets}"
    if table == "actors":
        cols = ("stage_name", "gender", "bio", "contact", "status", "created_at")
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        return body + f" ON CONFLICT (user_id) DO UPDATE SET {sets}, note = '', reviewed_at = NULL, reviewed_by = NULL"
    raise RuntimeError(f"ยังไม่รองรับ INSERT OR REPLACE ของตาราง {table}")


def _sql(sql: str) -> str:
    return _rewrite(sql).replace("?", "%s")


class Conn:
    def __init__(self, raw: psycopg.Connection):
        self.raw = raw

    def execute(self, sql: str, params=()) -> Result:
        head = sql.strip().rstrip(";").upper()
        if head.startswith("PRAGMA"):
            return self._pragma(head)
        if head.startswith("BEGIN"):
            if not getattr(_local, "in_tx", False):
                self.raw.execute("BEGIN")
                _local.in_tx = True
            return Result([])
        if head == "COMMIT":
            self.raw.commit()
            _local.in_tx = False
            return Result([])
        if head == "ROLLBACK":
            self.raw.rollback()
            _local.in_tx = False
            return Result([])
        in_tx = getattr(_local, "in_tx", False)
        try:
            cur = self.raw.execute(_sql(sql), params)
            rows = [Row(r) for r in cur.fetchall()] if cur.description else []
            if not in_tx:
                self.raw.commit()
            return Result(rows, cur.rowcount)
        except Exception:
            if not in_tx:
                self.raw.rollback()
            raise

    def executemany(self, sql: str, seq) -> Result:
        for params in seq:
            self.execute(sql, params)
        return Result([])

    def executescript(self, _script: str) -> "Conn":
        """ตารางสร้างจาก migration แล้ว ไม่รัน DDL ของ SQLite ซ้ำ"""
        return self

    def close(self) -> None:
        self.raw.close()

    def _pragma(self, head: str) -> Result:
        if head.startswith("PRAGMA TABLE_INFO"):
            name = head.split("(", 1)[1].split(")", 1)[0].strip().lower()
            if not _IDENT.match(name):
                raise RuntimeError("ชื่อตารางไม่ถูกต้อง")
            cur = self.raw.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema = 'studio' AND table_name = %s ORDER BY ordinal_position", (name,))
            rows = [Row(r) for r in cur.fetchall()]
            if not getattr(_local, "in_tx", False):
                self.raw.commit()
            return Result(rows)
        if head.startswith("PRAGMA USER_VERSION"):
            return Result([Row({"user_version": 1})])
        return Result([])


def connect() -> Conn:
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        raw = psycopg.connect(_dsn(), autocommit=False, row_factory=dict_row, connect_timeout=15)
        raw.execute("SET search_path TO studio")
        raw.commit()
        conn = raw
        _local.conn = conn
    return Conn(conn)


def is_pg(db) -> bool:
    return isinstance(db, Conn)
