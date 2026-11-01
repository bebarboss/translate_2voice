"""ต่อฐานข้อมูล Supabase ผ่าน REST (PostgREST) ด้วย service_role key (ข้าม RLS ได้ ใช้ฝั่งเซิร์ฟเวอร์เท่านั้น)

เปิดด้วย DB_BACKEND=supabase คู่กับ SUPABASE_URL และ SUPABASE_SERVICE_ROLE_KEY
สคีมาอยู่ใน supabase/migrations/ ไฟล์เสียงและวิดีโอยังอยู่ใน data/ เหมือนเดิม
"""
import json
import logging
import threading
from typing import Any, Optional

import numpy as np
import requests

from .config import settings

log = logging.getLogger("dubbing.db")

_local = threading.local()


class DBError(RuntimeError):
    pass


def enabled() -> bool:
    return settings.db_backend == "supabase"


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise DBError("DB_BACKEND=supabase ต้องตั้ง SUPABASE_URL และ SUPABASE_SERVICE_ROLE_KEY")
        s = requests.Session()
        s.headers.update({"apikey": settings.supabase_key, "Authorization": f"Bearer {settings.supabase_key}",
                          "Content-Type": "application/json"})
        _local.session = s
    return s


def _call(method: str, table: str, params: Optional[dict] = None, body: Any = None,
          prefer: str = "return=minimal") -> Any:
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}"
    try:
        r = _session().request(method, url, params=params, headers={"Prefer": prefer},
                               data=None if body is None else json.dumps(body, default=str), timeout=15)
    except requests.RequestException as e:
        raise DBError(f"{method} {table}: {e}") from e
    if r.status_code >= 400:
        raise DBError(f"{method} {table}: {r.status_code} {r.text[:300]}")
    return r.json() if r.content else None


def select(table: str, **params) -> list[dict]:
    return _call("GET", table, params, prefer="") or []


def upsert(table: str, rows: dict | list[dict], on_conflict: str) -> None:
    _call("POST", table, {"on_conflict": on_conflict}, rows, "resolution=merge-duplicates,return=minimal")


def update(table: str, data: dict, **filters) -> None:
    _call("PATCH", table, filters, data)


def delete(table: str, **filters) -> None:
    _call("DELETE", table, filters)


def vector(emb: Optional[np.ndarray]) -> Optional[str]:
    """numpy → รูปแบบ pgvector '[0.1,0.2,...]'"""
    return None if emb is None else "[" + ",".join(f"{x:.7g}" for x in np.asarray(emb, dtype=np.float32).ravel()) + "]"


def from_vector(value: Optional[str]) -> Optional[np.ndarray]:
    return None if value is None else np.asarray(json.loads(value), dtype=np.float32)
