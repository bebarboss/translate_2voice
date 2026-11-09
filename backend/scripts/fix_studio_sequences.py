"""รีเซ็ต identity/serial ของ schema studio หลังคัดลอกข้อมูล (กัน UniqueViolation ที่ ledger_pkey)"""
from app.pgstore import borrow

TABLES = [
    ("ledger", "id"),
    ("user_consents", "id"),
    ("actor_consents", "id"),
    ("actor_payouts", "id"),
]


def main() -> None:
    with borrow() as db:
        db.raw.execute("SET search_path TO studio")
        for table, col in TABLES:
            exists = db.raw.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema='studio' AND table_name=%s",
                (table,),
            ).fetchone()
            if not exists:
                continue
            row = db.raw.execute(f"SELECT COALESCE(MAX({col}), 0) AS mx FROM studio.{table}").fetchone()
            mx = int(row["mx"] if isinstance(row, dict) else row[0])
            seq = db.raw.execute("SELECT pg_get_serial_sequence(%s, %s) AS s", (f"studio.{table}", col)).fetchone()
            seq_name = (seq["s"] if isinstance(seq, dict) else seq[0]) if seq else None
            if not seq_name:
                print(f"{table}.{col} no sequence (max={mx})")
                continue
            db.raw.execute("SELECT setval(%s, %s, %s)", (seq_name, max(mx, 1), mx > 0))
            print(f"fixed {table}.{col} max={mx} -> {seq_name}")
        db.raw.commit()


if __name__ == "__main__":
    main()
