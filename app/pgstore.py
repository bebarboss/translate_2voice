"""เชื่อม Postgres ของ Supabase สำหรับบัญชี (schema studio)

คำสั่ง SQL ใน accounts.py / actors.py / consent.py เขียนแบบ SQLite (`?`, INSERT OR REPLACE)
ตัวนี้แปลให้พอใช้กับ Postgres

ใช้ connection ร่วมในโปรเซส (accounts/_lock กันอยู่แล้ว) + พอร์ต transaction pooler (6543)
เพื่อไม่ให้เธรดละ connection ชนเพดาน session pool (15)
"""
import re
import threading
from typing import Optional
from urllib.parse import quote, unquote, urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row

from .config import settings

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_conn_lock = threading.Lock()
_shared: Optional[psycopg.Connection] = None
_in_tx = False


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

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self) -> list[Row]:
        return self._rows

    def fetchone(self) -> Optional[Row]:
        return self._rows[0] if self._rows else None


# โฮสต์ db.<ref>.supabase.co เป็น IPv6 ล้วน คอนเทนเนอร์ Docker ต่อไม่ถึง
# พูลเลอร์โหมดเซสชันของโปรเจกต์นี้อยู่ eu-west-1 และมี IPv4
_POOLER_HOST = "aws-0-eu-west-1.pooler.supabase.com"
# โหมด transaction (6543) แชร์ backend ได้หลาย client — session (5432) จำกัด pool_size=15
_POOLER_PORT = 6543


def _dsn() -> str:
    url = (settings.supabase_db_url or "").strip()
    if not url:
        raise RuntimeError("ตั้ง SUPABASE_DB_URL ก่อนใช้บัญชีบน Supabase")
    parts = urlparse(url)
    host = parts.hostname or ""
    port = parts.port
    user = parts.username or "postgres"
    password = quote(unquote(parts.password or ""), safe="")
    if host.startswith("db.") and host.endswith(".supabase.co"):
        ref = host.split(".", 2)[1]
        if "." not in user:
            user = f"{user}.{ref}"
        host = _POOLER_HOST
        port = _POOLER_PORT
    elif host == _POOLER_HOST or host.endswith(".pooler.supabase.com"):
        # .env ชี้อ session :5432 อยู่ → ย้ายไป transaction เพื่อไม่ชน EMAXCONNSESSION
        port = _POOLER_PORT
    user = quote(user, safe=".")
    netloc = f"{user}:{password}@{host}:{port or _POOLER_PORT}"
    url = urlunparse(parts._replace(netloc=netloc))
    q = []
    if "sslmode=" not in url:
        q.append("sslmode=require")
    if "options=" not in url:
        q.append("options=-csearch_path%3Dstudio")
    if q:
        url += ("&" if "?" in url else "?") + "&".join(q)
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

    @property
    def closed(self) -> bool:
        return self.raw.closed

    def execute(self, sql: str, params=()) -> Result:
        global _in_tx
        head = sql.strip().rstrip(";").upper()
        if head.startswith("PRAGMA"):
            return self._pragma(head)
        if head.startswith("BEGIN"):
            if not _in_tx:
                self.raw.execute("BEGIN")
                _in_tx = True
            return Result([])
        if head == "COMMIT":
            self.raw.commit()
            _in_tx = False
            return Result([])
        if head == "ROLLBACK":
            self.raw.rollback()
            _in_tx = False
            return Result([])
        in_tx = _in_tx
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
            if not _in_tx:
                self.raw.commit()
            return Result(rows)
        if head.startswith("PRAGMA USER_VERSION"):
            return Result([Row({"user_version": 1})])
        return Result([])


def _open() -> psycopg.Connection:
    # prepare_threshold=None: โหมด transaction pooler ไม่เก็บ prepared statement ข้าม transaction
    raw = psycopg.connect(
        _dsn(), autocommit=False, row_factory=dict_row, connect_timeout=10, prepare_threshold=None,
    )
    raw.execute("SET search_path TO studio")
    raw.commit()
    return raw


def connect() -> Conn:
    """connection เดียวต่อโปรเซส — accounts._lock / jobstore lock กันใช้พร้อมกัน"""
    global _shared
    with _conn_lock:
        if _shared is None or _shared.closed:
            _shared = _open()
        return Conn(_shared)


def is_pg(db) -> bool:
    return isinstance(db, Conn)
