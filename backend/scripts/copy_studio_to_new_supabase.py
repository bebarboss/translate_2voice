"""คัดลอก schema studio (+ ตาราง public ที่ใช้) จาก SUPABASE_DB_URL_OLD → SUPABASE_DB_URL"""
import os
from urllib.parse import quote, unquote, urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

TABLES = [
    "users", "sessions", "subscriptions", "ledger", "topups", "cards", "slip_uses", "user_consents",
    "actors", "actor_consents", "actor_payment", "actor_voices", "actor_moods", "actor_payouts", "voice_usage",
    "jobs", "transcripts", "projects",
]
PUBLIC = ["app_settings", "voices", "voice_moods", "translation_memory", "quality_lines", "job_quality"]


def dsn(url: str, port: int = 6543) -> str:
    parts = urlparse(url.strip())
    user = quote(parts.username or "", safe=".")
    pw = quote(unquote(parts.password or ""), safe="")
    host = parts.hostname
    out = urlunparse(parts._replace(netloc=f"{user}:{pw}@{host}:{port}"))
    if "sslmode=" not in out:
        out += ("&" if "?" in out else "?") + "sslmode=require"
    return out


def cols(conn, schema: str, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        (schema, table),
    ).fetchall()
    return [r["column_name"] for r in rows]


def copy_table(old, new, schema: str, table: str) -> int:
    oc, nc = cols(old, schema, table), cols(new, schema, table)
    use = [c for c in oc if c in nc]
    if not use:
        print(f"{schema}.{table} SKIP")
        return 0
    colsql = ", ".join(use)
    rows = old.execute(f"SELECT {colsql} FROM {schema}.{table}").fetchall()
    new.execute(f"TRUNCATE {schema}.{table} CASCADE")
    if not rows:
        new.commit()
        print(f"{schema}.{table} 0")
        return 0
    ph = ",".join(["%s"] * len(use))
    data = []
    for r in rows:
        vals = []
        for k in use:
            v = r[k]
            if isinstance(v, (dict, list)):
                v = Jsonb(v)
            vals.append(v)
        data.append(vals)
    sql = f"INSERT INTO {schema}.{table} ({colsql}) VALUES ({ph})"
    with new.cursor() as cur:
        cur.executemany(sql, data)
    new.commit()
    print(f"{schema}.{table} {len(rows)}")
    return len(rows)


def main() -> None:
    old_url = os.environ.get("SUPABASE_DB_URL_OLD") or ""
    new_url = os.environ["SUPABASE_DB_URL"]
    if not old_url:
        raise SystemExit("ต้องมี SUPABASE_DB_URL_OLD")
    old = psycopg.connect(dsn(old_url), connect_timeout=30, row_factory=dict_row)
    new = psycopg.connect(dsn(new_url), connect_timeout=30, row_factory=dict_row)
    for t in TABLES:
        copy_table(old, new, "studio", t)
    for t in PUBLIC:
        try:
            copy_table(old, new, "public", t)
        except Exception as e:
            new.rollback()
            print(f"public.{t} warn {str(e).splitlines()[0][:160]}")
    u = new.execute("SELECT count(*) FROM studio.users").fetchone()[0]
    j = new.execute("SELECT count(*) FROM studio.jobs").fetchone()[0]
    print(f"DONE users={u} jobs={j}")
    old.close()
    new.close()


if __name__ == "__main__":
    main()
