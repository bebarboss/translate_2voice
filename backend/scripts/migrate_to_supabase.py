"""คัดลอกค่าตั้ง + คลังเสียงจาก data/ ขึ้น Postgres (SUPABASE_DB_URL)

รันซ้ำได้ (ทับแถวเดิมด้วย id เดียวกัน) ไม่ลบไฟล์ใน data/
    python scripts/migrate_to_supabase.py            # ดูว่าจะคัดลอกอะไร
    python scripts/migrate_to_supabase.py --apply    # คัดลอกจริง
ต้องตั้ง DB_BACKEND=supabase และ SUPABASE_DB_URL
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from app import supabase_db as db  # noqa: E402
from app.config import settings  # noqa: E402
from app.schemas import LibraryVoice  # noqa: E402
from app.voice_library import push  # noqa: E402


def main(apply: bool) -> None:
    data = settings.data_dir
    print(f"data: {data}  →  {settings.supabase_db_url or '(ยังไม่ตั้ง SUPABASE_DB_URL)'}  "
          f"({'คัดลอกจริง' if apply else 'ทดลอง ไม่เขียน'})")

    path = data / "settings.json"
    if path.exists():
        values = json.loads(path.read_text(encoding="utf-8"))
        print(f"ค่าตั้งระบบ: {len(values)} ค่า")
        if apply:
            db.update("app_settings", {"data": values}, id="eq.1")

    for f in sorted((data / "voices").glob("*/voice.json")):
        v = LibraryVoice.model_validate_json(f.read_text(encoding="utf-8"))
        emb_path = f.parent / "embedding.npy"
        emb = np.load(emb_path) if emb_path.exists() else None
        print(f"เสียง {v.id} {v.name!r}: {v.status.value}, อารมณ์ {len(v.moods)}, ลายเสียง {'มี' if emb is not None else 'ไม่มี'}")
        if apply:
            push(v)
            if emb is not None:
                db.update("voices", {"embedding": db.vector(emb)}, id=f"eq.{v.id}")

    if apply:
        n = len(db.select("voices", select="id"))
        print(f"เสร็จ ใน Supabase มีเสียง {n} เสียง")


if __name__ == "__main__":
    main("--apply" in sys.argv)
