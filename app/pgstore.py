"""เชื่อม Postgres ของ Supabase สำหรับบัญชี (schema studio)

คำสั่ง SQL ใน accounts.py / actors.py / consent.py เขียนแบบ SQLite (`?`, INSERT OR REPLACE)
ตัวนี้แปลให้พอใช้กับ Postgres

ใช้พอร์ต transaction pooler (6543) + pool เล็กในโปรเซส
กันทั้ง EMAXCONNSESSION (เธรดละเส้น) และ InFailedSqlTransaction / คิวรอ connection เดียว
"""
import queue
import re
import threading
from contextlib import contextmanager
from typing import Iterator, Optional
from urllib.parse import quote, unquote, urlparse, urlunparse

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from .config import settings

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_POOL_SIZE = 8
_pool: queue.LifoQueue = queue.LifoQueue(maxsize=_POOL_SIZE)
_created = 0
_created_lock = threading.Lock()

# connection สำหรับ _tx / with _lock+_db() ฝั่ง accounts (เขียนเงินต้องคนละธุรกรรมชัด)
_write_lock = threading.Lock()
_write_conn: Optional[psycopg.Connection] = None


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


# Transaction pooler — region อยู่ในโฮสต์ของ SUPABASE_DB_URL (เช่น aws-0-ap-southeast-1.pooler...)
# ห้าม hardcode eu-west-1: ย้ายโปรเจกต์ไป Singapore แล้วแค่เปลี่ยน URL ใน .env
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
        # db.<ref>.supabase.co มักเป็น IPv6 และไม่บอก region ของ pooler
        raise RuntimeError(
            "ตั้ง SUPABASE_DB_URL เป็น Connection pooler จาก Dashboard → Connect "
            "(เช่น postgresql://postgres.<ref>:...@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres) "
            "ไม่ใช้โฮสต์ db.<ref>.supabase.co โดยตรง"
        )
    if host.endswith(".pooler.supabase.com"):
        # ใช้ region ตาม URL ที่มีอยู่ บังคับพอร์ต transaction mode
        port = _POOLER_PORT
        if "." not in (parts.username or "") and user == "postgres":
            # บาง URL เป็น postgres:pass@pooler — pooler ต้องการ postgres.<ref>
            pass
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


def _open() -> psycopg.Connection:
    raw = psycopg.connect(
        _dsn(), autocommit=False, row_factory=dict_row, connect_timeout=10, prepare_threshold=None,
    )
    raw.execute("SET search_path TO studio")
    raw.commit()
    return raw


def _clean(raw: psycopg.Connection) -> None:
    """เคลียร์ transaction ที่พัง — ไม่งั้นคำขอถัดไปได้ InFailedSqlTransaction"""
    try:
        if raw.closed:
            return
        if raw.info.transaction_status != TransactionStatus.IDLE:
            raw.rollback()
    except Exception:
        try:
            raw.close()
        except Exception:
            pass


def checkout() -> psycopg.Connection:
    global _created
    try:
        raw = _pool.get_nowait()
    except queue.Empty:
        create = False
        with _created_lock:
            if _created < _POOL_SIZE:
                _created += 1
                create = True
        if create:
            try:
                return _open()  # อย่าเปิดตอนถือ lock — ไม่งั้นเธรดอื่นรอ SSL ไป EU เป็นคิว
            except Exception:
                with _created_lock:
                    _created = max(0, _created - 1)
                raise
        raw = _pool.get(timeout=20)
    if raw.closed:
        try:
            return _open()
        except Exception:
            with _created_lock:
                _created = max(0, _created - 1)
            raise
    _clean(raw)
    if raw.closed:
        try:
            return _open()
        except Exception:
            with _created_lock:
                _created = max(0, _created - 1)
            raise
    return raw


def checkin(raw: psycopg.Connection) -> None:
    global _created
    if raw is None:
        return
    if raw.closed:
        with _created_lock:
            _created = max(0, _created - 1)
        return
    try:
        _clean(raw)
        if raw.closed:
            with _created_lock:
                _created = max(0, _created - 1)
            return
        _pool.put_nowait(raw)
    except queue.Full:
        try:
            raw.close()
        except Exception:
            pass
        with _created_lock:
            _created = max(0, _created - 1)


@contextmanager
def borrow() -> Iterator["Conn"]:
    raw = checkout()
    conn = Conn(raw)
    try:
        yield conn
    except Exception:
        _clean(raw)
        raise
    finally:
        checkin(raw)


class Conn:
    def __init__(self, raw: psycopg.Connection):
        self.raw = raw
        self._in_tx = False

    @property
    def closed(self) -> bool:
        return self.raw.closed

    def execute(self, sql: str, params=()) -> Result:
        head = sql.strip().rstrip(";").upper()
        if head.startswith("PRAGMA"):
            return self._pragma(head)
        if head.startswith("BEGIN"):
            if not self._in_tx:
                self.raw.execute("BEGIN")
                self._in_tx = True
            return Result([])
        if head == "COMMIT":
            self.raw.commit()
            self._in_tx = False
            return Result([])
        if head == "ROLLBACK":
            self.raw.rollback()
            self._in_tx = False
            return Result([])
        in_tx = self._in_tx
        try:
            cur = self.raw.execute(_sql(sql), params)
            rows = [Row(r) for r in cur.fetchall()] if cur.description else []
            if not in_tx:
                self.raw.commit()
            return Result(rows, cur.rowcount)
        except Exception:
            try:
                self.raw.rollback()
            except Exception:
                pass
            self._in_tx = False
            raise

    def executemany(self, sql: str, seq) -> Result:
        for params in seq:
            self.execute(sql, params)
        return Result([])

    def executescript(self, _script: str) -> "Conn":
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
            if not self._in_tx:
                self.raw.commit()
            return Result(rows)
        if head.startswith("PRAGMA USER_VERSION"):
            return Result([Row({"user_version": 1})])
        return Result([])


def connect() -> Conn:
    """connection สำหรับเขียนภายใต้ accounts._lock — คนละเส้นกับ pool อ่าน"""
    global _write_conn
    with _write_lock:
        if _write_conn is None or _write_conn.closed:
            _write_conn = _open()
        else:
            _clean(_write_conn)
            if _write_conn.closed:
                _write_conn = _open()
        return Conn(_write_conn)


def is_pg(db) -> bool:
    return isinstance(db, Conn)
