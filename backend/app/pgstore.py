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


def dsn(*, schema: str = "studio") -> str:
    """สร้าง DSN จาก DATABASE_URL (หรือ SUPABASE_DB_URL ชื่อเก่า)

    Postgres บน VPS/local (`db`, `localhost`, …): พอร์ตใน URL (ค่าเริ่ม 5432)
    sslmode ตาม URL — ไม่มีใน URL → disable
    """
    url = (settings.supabase_db_url or "").strip()
    if not url:
        raise RuntimeError(
            "ตั้ง DATABASE_URL ก่อนใช้ Postgres "
            "(เช่น postgresql://pakdee:...@db:5432/pakdee?sslmode=disable)"
        )
    parts = urlparse(url)
    host = parts.hostname or ""
    port = parts.port
    user = parts.username or "postgres"
    password = quote(unquote(parts.password or ""), safe="")
    if "supabase.co" in host or host.endswith(".pooler.supabase.com"):
        raise RuntimeError(
            "ยกเลิกใช้ Supabase แล้ว — ตั้ง DATABASE_URL ชี้ Postgres บน VPS "
            "(เช่น postgresql://pakdee:...@db:5432/pakdee?sslmode=disable)"
        )
    default_ssl = "disable"
    default_port = 5432
    user = quote(user, safe=".")
    netloc = f"{user}:{password}@{host}:{port or default_port}"
    url = urlunparse(parts._replace(netloc=netloc))
    q = []
    if "sslmode=" not in url:
        q.append(f"sslmode={default_ssl}")
    if schema and "options=" not in url:
        q.append(f"options=-csearch_path%3D{quote(schema, safe='')}")
    if q:
        url += ("&" if "?" in url else "?") + "&".join(q)
    return url


def _dsn() -> str:
    return dsn(schema="studio")


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
    import socket

    # กัน DNS/`db` ค้างยาวเกิน connect_timeout ของ libpq บน Docker บางเครื่อง
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10)
    try:
        raw = psycopg.connect(
            dsn(schema="studio"),
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=10,
            prepare_threshold=None,
        )
    finally:
        socket.setdefaulttimeout(old_timeout)
    raw.execute("SET search_path TO studio")
    raw.execute("SET statement_timeout TO '15s'")
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


def _ensure_search_path(raw: psycopg.Connection) -> None:
    """transaction pooler อาจสลับ backend ระหว่างคำขอ — ต้องตั้ง search_path ใหม่ทุกครั้ง"""
    raw.execute("SET search_path TO studio")
    raw.commit()


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
    # search_path ตั้งตอน Conn.execute (pipeline SET LOCAL + คำสั่ง) — อย่า SET+COMMIT แยก
    # เพราะ transaction pooler ทำให้เสีย RTT เพิ่มทุกครั้งที่ borrow
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
        self._path_set = False

    @property
    def closed(self) -> bool:
        return self.raw.closed

    def _run(self, sql: str, params=()):
        """รัน SQL ใน schema studio — นอกธุรกรรมส่ง SET LOCAL คู่กับคำสั่งใน pipeline (1 RTT)"""
        q = _sql(sql)
        if self._in_tx:
            if not self._path_set:
                self.raw.execute("SET LOCAL search_path TO studio")
                self._path_set = True
            return self.raw.execute(q, params)
        with self.raw.pipeline():
            self.raw.execute("SET LOCAL search_path TO studio")
            return self.raw.execute(q, params)

    def execute(self, sql: str, params=()) -> Result:
        head = sql.strip().rstrip(";").upper()
        if head.startswith("PRAGMA"):
            return self._pragma(head)
        if head.startswith("BEGIN"):
            if not self._in_tx:
                self.raw.execute("BEGIN")
                self.raw.execute("SET LOCAL search_path TO studio")
                self._in_tx = True
                self._path_set = True
            return Result([])
        if head == "COMMIT":
            self.raw.commit()
            self._in_tx = False
            self._path_set = False
            return Result([])
        if head == "ROLLBACK":
            self.raw.rollback()
            self._in_tx = False
            self._path_set = False
            return Result([])
        in_tx = self._in_tx
        try:
            cur = self._run(sql, params)
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
            self._path_set = False
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
            in_tx = self._in_tx
            try:
                sql = ("SELECT column_name AS name FROM information_schema.columns "
                       "WHERE table_schema = 'studio' AND table_name = %s ORDER BY ordinal_position")
                if in_tx:
                    if not self._path_set:
                        self.raw.execute("SET LOCAL search_path TO studio")
                        self._path_set = True
                    cur = self.raw.execute(sql, (name,))
                else:
                    with self.raw.pipeline():
                        self.raw.execute("SET LOCAL search_path TO studio")
                        cur = self.raw.execute(sql, (name,))
                rows = [Row(r) for r in cur.fetchall()]
                if not in_tx:
                    self.raw.commit()
                return Result(rows)
            except Exception:
                try:
                    self.raw.rollback()
                except Exception:
                    pass
                self._in_tx = False
                self._path_set = False
                raise
        if head.startswith("PRAGMA USER_VERSION"):
            return Result([Row({"user_version": 1})])
        return Result([])


_trial_index_ensured = False


def connect() -> Conn:
    """connection สำหรับเขียนภายใต้ accounts._lock — คนละเส้นกับ pool อ่าน"""
    global _write_conn, _trial_index_ensured
    with _write_lock:
        if _write_conn is None or _write_conn.closed:
            _write_conn = _open()
        else:
            _clean(_write_conn)
            if _write_conn.closed:
                _write_conn = _open()
            else:
                try:
                    _ensure_search_path(_write_conn)
                except Exception:
                    try:
                        _write_conn.close()
                    except Exception:
                        pass
                    _write_conn = _open()
        conn = Conn(_write_conn)
        if not _trial_index_ensured:
            # ครั้งแรกของโปรเซส: สร้าง unique แพ็กทดลองถ้ายังไม่มีแถว kind=trial ซ้ำ
            # ไม่ลบข้อมูล ถ้าสร้างไม่ได้ แอปยังทำงานด้วยการเช็คใน claim_trial
            try:
                from .accounts import _ensure_trial_once_index
                _ensure_trial_once_index(conn)
            except Exception:
                import logging
                logging.getLogger("dubbing.pgstore").exception("ledger_trial_once ensure failed")
            _trial_index_ensured = True
        return conn


def is_pg(db) -> bool:
    return isinstance(db, Conn)
