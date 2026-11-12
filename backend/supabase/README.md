# สคีมาฐานข้อมูล

Production รัน **Postgres บน VPS** (`deploy/docker-compose.yml` service `db`)  
ไฟล์ init ที่ใช้จริงอยู่ที่ [`../../deploy/db/init/`](../../deploy/db/init/) — ไม่พึ่ง Supabase Auth / PostgREST

โฟลเดอร์ `migrations/` เก็บ SQL อ้างอิง / ประวัติ:

| ไฟล์ | ใช้ทำอะไร |
| --- | --- |
| `20261107000000_studio_accounts.sql` ฯลฯ | schema `studio` (บัญชี งาน โปรเจกต์) — คัดลอกไป `deploy/db/init/` แล้ว |
| `20261112000000_ledger_trial_once.sql` | unique แพ็กทดลองครั้งเดียวต่อผู้ใช้ — รันมือบนฐานที่มีข้อมูลแล้ว ไม่ลบแถวซ้ำ |
| `20261104000000_translation_memory.sql` ฯลฯ | ตาราง `public` (TM / quality / metrics) — คัดลอกไป `deploy/db/init/` แล้ว |

## ตั้งค่า

ดู [`../../docs/deploy-vps.md`](../../docs/deploy-vps.md)

```env
DB_BACKEND=supabase
SUPABASE_DB_URL=postgresql://pakdee:...@db:5432/pakdee?sslmode=disable
```

ย้ายข้อมูลจาก Supabase คลาวด์เดิม: `../scripts/migrate_supabase_to_vps.sh`  
คัดลอก settings/voices จากไฟล์ใน `data/`: `../scripts/migrate_to_supabase.py --apply`

ไฟล์เสียง/วิดีโอยังอยู่ที่ `data/` (+ R2 ตามต้องการ)
