"""เข้าถึงตาราง public บน Postgres โดยตรง

เปิดด้วย DB_BACKEND=postgres + DATABASE_URL (หรือ SUPABASE_DB_URL ชื่อเก่า)
รองรับ filter แบบ PostgREST ที่แอปใช้จริง: eq / neq / gte / not.in / order / limit / select
รวม nested `voice_moods(*)` สำหรับคลังเสียง
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Optional

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .config import using_postgres

log = logging.getLogger("dubbing.db")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NESTED = re.compile(r",?\s*(\w+)\(\*\)\s*,?")
_lock = threading.Lock()
_conn: Optional[psycopg.Connection] = None


class DBError(RuntimeError):
    pass


def enabled() -> bool:
    return using_postgres()


def _table(name: str) -> str:
    if not _IDENT.match(name):
        raise DBError(f"ชื่อตารางไม่ถูกต้อง: {name}")
    return name


def _col(name: str) -> str:
    if not _IDENT.match(name):
        raise DBError(f"ชื่อคอลัมน์ไม่ถูกต้อง: {name}")
    return name


def _connect() -> psycopg.Connection:
    from . import pgstore
    try:
        raw = psycopg.connect(
            pgstore.dsn(schema="public"),
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=10,
            prepare_threshold=None,
        )
        raw.execute("SET search_path TO public")
        return raw
    except Exception as e:  # noqa: BLE001
        raise DBError(f"เชื่อม Postgres ไม่ได้: {e}") from e


def _db() -> psycopg.Connection:
    global _conn
    with _lock:
        if _conn is None or _conn.closed:
            _conn = _connect()
        return _conn


def _parse_filter(raw: str) -> tuple[str, Any]:
    """แปลงค่า PostgREST filter → (op_sql, value) เช่น eq.x → ('=', 'x')"""
    if not isinstance(raw, str):
        return "=", raw
    if raw.startswith("eq."):
        return "=", raw[3:]
    if raw.startswith("neq."):
        return "<>", raw[4:]
    if raw.startswith("gte."):
        return ">=", raw[4:]
    if raw.startswith("gt."):
        return ">", raw[3:]
    if raw.startswith("lte."):
        return "<=", raw[4:]
    if raw.startswith("lt."):
        return "<", raw[3:]
    if raw.startswith("not.in."):
        body = raw[7:]
        if body.startswith("(") and body.endswith(")"):
            body = body[1:-1]
        items = [x for x in body.split(",") if x != ""]
        return "NOT IN", items
    if raw.startswith("in."):
        body = raw[3:]
        if body.startswith("(") and body.endswith(")"):
            body = body[1:-1]
        items = [x for x in body.split(",") if x != ""]
        return "IN", items
    return "=", raw


def _where(filters: dict) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    for key, raw in filters.items():
        if key in ("select", "order", "limit", "offset", "on_conflict"):
            continue
        col = _col(key)
        op, val = _parse_filter(raw if isinstance(raw, str) else f"eq.{raw}")
        if op in ("IN", "NOT IN"):
            if not val:
                clauses.append("FALSE" if op == "IN" else "TRUE")
                continue
            ph = ",".join(["%s"] * len(val))
            clauses.append(f"{col} {op} ({ph})")
            args.extend(val)
        else:
            clauses.append(f"{col} {op} %s")
            args.append(val)
    if not clauses:
        return "", args
    return " WHERE " + " AND ".join(clauses), args


def _parse_select(select: Optional[str]) -> tuple[str, Optional[str]]:
    """คืน (sql select list, nested child table หรือ None)"""
    if not select or select == "*":
        return "*", None
    nested = None
    m = _NESTED.search(select)
    if m:
        nested = m.group(1)
        select = _NESTED.sub(",", select)
    cols = [c.strip() for c in select.split(",") if c.strip()]
    if not cols or cols == ["*"]:
        return "*", nested
    for c in cols:
        _col(c)
    return ", ".join(cols), nested


def _parse_order(order: Optional[str]) -> str:
    if not order:
        return ""
    parts = []
    for bit in order.split(","):
        bit = bit.strip()
        if not bit:
            continue
        if "." in bit:
            col, direction = bit.rsplit(".", 1)
            direction = direction.upper()
            if direction not in ("ASC", "DESC"):
                raise DBError(f"order ไม่ถูกต้อง: {bit}")
            parts.append(f"{_col(col)} {direction}")
        else:
            parts.append(_col(bit))
    return (" ORDER BY " + ", ".join(parts)) if parts else ""


def _adapt(value: Any) -> Any:
    if isinstance(value, dict):
        return Json(value)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return Json(value)
    return value


def select(table: str, **params) -> list[dict]:
    t = _table(table)
    select_sql, nested = _parse_select(params.get("select"))
    where_sql, args = _where(params)
    order_sql = _parse_order(params.get("order"))
    limit = params.get("limit")
    limit_sql = ""
    if limit is not None and str(limit) != "":
        limit_sql = " LIMIT %s"
        args = list(args) + [int(limit)]
    sql = f"SELECT {select_sql} FROM {t}{where_sql}{order_sql}{limit_sql}"
    try:
        with _lock:
            cur = _db().execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
    except DBError:
        raise
    except Exception as e:  # noqa: BLE001
        raise DBError(f"SELECT {table}: {e}") from e
    if nested and rows:
        child = _table(nested)
        # FK มาตรฐาน: voices ← voice_moods.voice_id
        fk = "voice_id" if child == "voice_moods" else f"{t.rstrip('s')}_id"
        ids = [r.get("id") for r in rows if r.get("id") is not None]
        by_parent: dict[Any, list] = {i: [] for i in ids}
        if ids:
            ph = ",".join(["%s"] * len(ids))
            try:
                with _lock:
                    cur = _db().execute(f"SELECT * FROM {child} WHERE {_col(fk)} IN ({ph})", ids)
                    for m in cur.fetchall():
                        by_parent.setdefault(m[fk], []).append(dict(m))
            except Exception as e:  # noqa: BLE001
                raise DBError(f"SELECT {child}: {e}") from e
        for r in rows:
            r[nested] = by_parent.get(r.get("id"), [])
    return rows


def upsert(table: str, rows: dict | list[dict], on_conflict: str) -> None:
    t = _table(table)
    items = rows if isinstance(rows, list) else [rows]
    if not items:
        return
    conflict_cols = [c.strip() for c in on_conflict.split(",") if c.strip()]
    for c in conflict_cols:
        _col(c)
    cols = list(items[0].keys())
    for c in cols:
        _col(c)
    col_sql = ", ".join(cols)
    ph = ", ".join(["%s"] * len(cols))
    updates = [c for c in cols if c not in conflict_cols]
    if updates:
        set_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)
        conflict_sql = f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {set_sql}"
    else:
        conflict_sql = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
    sql = f"INSERT INTO {t} ({col_sql}) VALUES ({ph}) {conflict_sql}"
    try:
        with _lock:
            conn = _db()
            for row in items:
                conn.execute(sql, [_adapt(row[c]) for c in cols])
    except Exception as e:  # noqa: BLE001
        raise DBError(f"UPSERT {table}: {e}") from e


def update(table: str, data: dict, **filters) -> None:
    t = _table(table)
    if not data:
        return
    sets = []
    args: list[Any] = []
    for k, v in data.items():
        sets.append(f"{_col(k)} = %s")
        args.append(_adapt(v))
    where_sql, wargs = _where(filters)
    if not where_sql:
        raise DBError("update ต้องมีเงื่อนไข")
    sql = f"UPDATE {t} SET {', '.join(sets)}{where_sql}"
    try:
        with _lock:
            _db().execute(sql, args + wargs)
    except Exception as e:  # noqa: BLE001
        raise DBError(f"UPDATE {table}: {e}") from e


def delete(table: str, **filters) -> None:
    t = _table(table)
    where_sql, args = _where(filters)
    if not where_sql:
        raise DBError("delete ต้องมีเงื่อนไข")
    sql = f"DELETE FROM {t}{where_sql}"
    try:
        with _lock:
            _db().execute(sql, args)
    except Exception as e:  # noqa: BLE001
        raise DBError(f"DELETE {table}: {e}") from e


def vector(emb: Optional[np.ndarray]) -> Optional[str]:
    """numpy → รูปแบบ pgvector '[0.1,0.2,...]'"""
    return None if emb is None else "[" + ",".join(f"{x:.7g}" for x in np.asarray(emb, dtype=np.float32).ravel()) + "]"


def from_vector(value: Optional[str]) -> Optional[np.ndarray]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return np.asarray(value, dtype=np.float32)
    return np.asarray(json.loads(value), dtype=np.float32)
