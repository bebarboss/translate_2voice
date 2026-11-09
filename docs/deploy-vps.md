# Deploy Pakdee บน VPS

รัน API (และถ้าต้องการ หน้าเว็บ) บน VPS ด้วย Docker Compose + Caddy (HTTPS อัตโนมัติ)  
ขั้น GPU ยังใช้ **Modal** (`WORKER=modal`) — VPS ไม่ต้องมี การ์ดจอ

## ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
| --- | --- |
| `deploy/docker-compose.yml` | api + **Postgres (pgvector)** + caddy (+ web optional) |
| `deploy/db/init/` | schema ครั้งแรกเมื่อ volume ว่าง |
| `deploy/Caddyfile` | reverse proxy โดเมน API |
| `deploy/Caddyfile.web` | API + หน้าเว็บ |
| `deploy/frontend.Dockerfile` | build Next.js standalone จาก `frontend/` |
| `deploy/.env.vps.example` | โดเมน / CORS / Postgres |
| `deploy/up.sh` | สคริปต์ขึ้นบริการ |
| `.env` (รากโปรเจกต์) | คีย์ Modal, Typhoon, HF, API_KEY ฯลฯ |

## สิ่งที่ต้องมีบน VPS

- Ubuntu 22.04+ (หรือ Debian ใกล้เคียง)
- Docker Engine + Compose plugin
- โดเมนชี้ A/AAAA มาที่ IP ของ VPS (เช่น `api.yourdomain.com`)
- เปิดพอร์ต **80** และ **443**
- บัญชี [Modal](https://modal.com) + `modal deploy modal_app.py` จากเครื่องที่มีคีย์แล้วอย่างน้อยหนึ่งครั้ง

## ขั้นตอนติดตั้ง

### 1) โคลนโค้ด

```bash
git clone https://github.com/bebarboss/translate_2voice.git pakdee
cd pakdee
git checkout main
```

### 2) ตั้งค่า API

```bash
cp .env.example .env
nano .env
```

ใส่อย่างน้อย:

- `WORKER=modal`
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`
- `HF_TOKEN`, `TYPHOON_API_KEY`
- `API_KEY` (สุ่มยาว ๆ)

ค่าคอนฟิกทั่วไป (ขีดอัปโหลด โมเดล คิว ฯลฯ) แก้ใน `backend/app/defaults.py` และ `backend/app/audio_constants.py` ไม่ใส่ใน `.env`

ฐานข้อมูล production อยู่บน VPS — ตั้ง Postgres ใน `deploy/.env` (ขั้นถัดไป)

อย่า commit ไฟล์ `.env`

### 3) ตั้งค่าโดเมน + Postgres บน VPS

```bash
cp deploy/.env.vps.example deploy/.env
nano deploy/.env
```

ตัวอย่าง:

```env
API_DOMAIN=api.yourdomain.com
ACME_EMAIL=you@yourdomain.com
CORS_ORIGINS=https://www.yourdomain.com,https://your-app.vercel.app
WORKER=modal

POSTGRES_USER=pakdee
POSTGRES_PASSWORD=<สุ่มยาว-URL-safe>
POSTGRES_DB=pakdee
DB_BACKEND=postgres
DATABASE_URL=postgresql://pakdee:<รหัสผ่านเดียวกัน>@db:5432/pakdee?sslmode=disable
```

รหัสผ่านใน URL กับ `POSTGRES_PASSWORD` ต้องตรงกัน และควรเป็นตัวอักษร/ตัวเลข (หลีกเลี่ยง `@ : / # ?`)

DNS: สร้างเรคอร์ด `A` ของ `api.yourdomain.com` → IP VPS รอให้ resolve ก่อนขึ้น Caddy

Postgres **ไม่เปิดพอร์ตสู่สาธารณะ** — เข้าได้แค่จาก container `api` ที่โฮสต์ `db`

### 4) ขึ้น API + HTTPS

```bash
chmod +x deploy/up.sh
bash deploy/up.sh
# หรือ
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

ตรวจ:

```bash
curl -sS https://api.yourdomain.com/health
# {"status":"ok",...}
```

### 5) Frontend บน VPS

ใน `deploy/.env` ตั้ง (มีตัวอย่างใน `deploy/.env.vps.example`):

```env
WEB_DOMAIN=www.yourdomain.com
CADDYFILE=./Caddyfile.web
PUBLIC_BACKEND_URL=https://api.yourdomain.com
DIRECT_UPLOAD=1
CORS_ORIGINS=https://www.yourdomain.com
# WEB_API_KEY=   # ว่างได้ — up.sh จะคัดจาก API_KEY ใน .env ราก
```

DNS: เรคอร์ด `A` ของ `www` (และ apex ถ้าใช้) → IP VPS

```bash
bash deploy/up.sh --web
# ตรวจ
curl -sS https://api.yourdomain.com/health
# เปิดเบราว์เซอร์ที่ https://www.yourdomain.com
```

Compose จะ build `frontend/` เป็น container `web` แล้ว Caddy เสิร์ฟโดเมนเว็บ → `web:3000` และโดเมน API → `api:8000`

อัปเดตรหัสหน้าเว็บ: `git pull` แล้ว `bash deploy/up.sh --web` อีกครั้ง

ถ้ายังใช้ Vercel แทน: Root Directory = `frontend`, ตั้ง `BACKEND_URL` / `API_KEY` / `DIRECT_UPLOAD=1` — ไม่ต้องเปิด `--web`

### 6) Modal

บนเครื่องที่มี Modal login แล้ว (หรือบน VPS หลัง `pip install modal`):

```bash
# จากโฟลเดอร์ backend/ ที่ใส่ MODAL_TOKEN_* ใน environment แล้ว
cd backend
modal deploy modal_app.py
```

แก้โค้ดใน `backend/app/pipeline/` แล้วต้อง deploy Modal ใหม่ทุกครั้ง

## อัปเดตเวอร์ชัน

```bash
cd pakdee
git pull
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
# ถ้าใช้เว็บบน VPS
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile web up -d --build
# หรือ
bash deploy/remote-update.sh
```

ข้อมูลงานอยู่ใน `./data` (volume bind) ไม่หายตอน rebuild

### Auto-deploy จาก GitHub Actions

ไฟล์ `.github/workflows/deploy-vps.yml` จะ SSH เข้า VPS แล้วรัน `deploy/remote-update.sh` ทุกครั้งที่ push `main`

1. บน VPS ใส่ public key ของ deploy key ใน `~/.ssh/authorized_keys` ของ user ที่รัน Docker ได้
2. ใน GitHub repo → **Settings → Secrets and variables → Actions** เพิ่ม:

| Secret | ตัวอย่าง |
| --- | --- |
| `VPS_HOST` | `119.10.143.47` |
| `VPS_USER` | `khaimook` |
| `VPS_SSH_KEY` | private key ทั้งก้อน |
| `VPS_PATH` | `/home/khaimook/translate_2voice` |

3. Push ขึ้น `main` หรือกด **Actions → Deploy VPS → Run workflow**

สร้างคีย์แยกสำหรับ deploy (แนะนำ ไม่ใช้คีย์เครื่องส่วนตัว):

```bash
ssh-keygen -t ed25519 -f deploy-vps -C "github-deploy" -N ""
# ใส่ deploy-vps.pub ใน VPS authorized_keys
# ใส่เนื้อหา deploy-vps ทั้งไฟล์เป็น secret VPS_SSH_KEY
```

## Postgres บน VPS

Compose ขึ้น service `db` (image `pgvector/pgvector:pg16`) พร้อม volume `pg_data`  
ครั้งแรกที่ volume ว่าง จะรัน SQL ใน `deploy/db/init/` (schema `studio` + ตาราง `public` ที่แอปใช้)

ตรวจว่า DB ขึ้น:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps db
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec db \
  psql -U pakdee -d pakdee -c '\dt studio.*'
```

### ย้ายข้อมูลจาก Supabase คลาวด์เดิม

1. จากเครื่องที่มี network ถึง Supabase (ใช้ Connection string แบบ **Session** หรือ direct ที่มี IPv4):

```bash
# แทนที่ SOURCE ด้วย connection string จาก Dashboard → Connect
pg_dump "$SOURCE" \
  --format=custom --no-owner --no-acl \
  --schema=studio \
  -f studio.dump

pg_dump "$SOURCE" \
  --format=custom --no-owner --no-acl \
  -t app_settings -t voices -t voice_moods \
  -t translation_memory -t job_quality -t quality_lines \
  -t job_metric_scores -t job_metric_daily \
  -f public_app.dump
```

2. คัดลอกไฟล์ dump ไป VPS แล้ว restore เข้า container (หลัง `up` ครั้งแรกที่ schema ว่าง หรือใช้ DB ใหม่):

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env cp studio.dump db:/tmp/studio.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env cp public_app.dump db:/tmp/public_app.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl /tmp/studio.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl /tmp/public_app.dump
```

ถ้าชน constraint เพราะ init สร้างตารางว่างแล้ว: ใช้ `--clean --if-exists` บน `pg_restore` (ระวังลบข้อมูลบน VPS)

ทางเลือก: สคริปต์ `scripts/copy_accounts.py` / `scripts/copy_jobs.py` ชี้ต้นทาง–ปลายทาง

3. ตรวจจำนวนแถว:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec db \
  psql -U pakdee -d pakdee -c "select count(*) from studio.users; select count(*) from studio.jobs; select count(*) from voices;"
```

4. ใน `.env` / `deploy/.env` ชี้ `DATABASE_URL` ไปที่ `db:5432` แล้วรีสตาร์ท API

สำรอง Postgres:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_dump -U pakdee -d pakdee --format=custom -f /tmp/pakdee.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env cp db:/tmp/pakdee.dump ./backups/pakdee-$(date +%F).dump
```

## Cloudflare R2 (เก็บไฟล์สื่องาน)

ระหว่างวิเคราะห์/พากย์ยังเขียนที่ `data/jobs/<id>/` บน VPS เหมือนเดิม  
เมื่องานถึง `done` API จะอัปไฟล์สื่อใหญ่ขึ้น R2 — ดาวน์โหลดผ่าน endpoint เดิม (`/result`, `/export`, `/source`, …) ถ้าไฟล์ local หายจะดึงจาก R2 ให้

ใน `.env` (รากโปรเจกต์):

```env
R2_ENABLED=1
R2_ACCOUNT_ID=<cloudflare_account_id>
R2_ACCESS_KEY_ID=<r2_access_key>
R2_SECRET_ACCESS_KEY=<r2_secret>
R2_BUCKET=pakdee-jobs
# R2_ENDPOINT=   # ว่าง = https://{account_id}.r2.cloudflarestorage.com
R2_PURGE_LOCAL=0   # 1 = ลบสื่อบนดิสก์หลังอัปสำเร็จ (JSON/SRT ยังอยู่)
```

สร้าง bucket + API token:

1. Cloudflare Dashboard → **R2** → Create bucket (เช่น `pakdee-jobs`)
2. **Manage R2 API Tokens** → Create API token  
   - Permissions: Object Read & Write บน bucket นั้น  
   - คัดลอก Access Key ID / Secret Access Key
3. Account ID อยู่ที่หน้า R2 overview ขวาสุด

ย้ายงาน `done` เก่าขึ้น R2:

```bash
# ใน container หรือ venv ที่มี boto3 + .env
python scripts/r2_sync_jobs.py --dry-run
python scripts/r2_sync_jobs.py
python scripts/r2_sync_jobs.py --purge   # หลังมั่นใจว่าอัปครบแล้ว
```

ใส่โดเมน R2 ใน egress ถ้ามี firewall ออกนอก (endpoint `*.r2.cloudflarestorage.com`)

## สำรองข้อมูล

- ตั้ง `BACKUP_HOURS` / `BACKUP_KEEP` ใน `.env`
- ตั้ง `BACKUP_PATH` ใน `deploy/.env` เป็นดิสก์หรือโฟลเดอร์ที่ซิงก์คลาวด์
- ไฟล์เสียง/วิดีโออยู่ใน `data/jobs/` — หรือบน R2 เมื่อเปิด `R2_ENABLED` / `R2_PURGE_LOCAL`
- สำรองแยกด้วย `rsync` ตามความต้องการ (JSON/SRT ยังอยู่บนดิสก์เสมอ)

## สิ่งที่ไม่ควรทำบน VPS ชุดนี้

- อย่าเปิดพอร์ต `8000` สู่สาธารณะโดยตรง (ให้ผ่าน Caddy 443 เท่านั้น)
- อย่า mount `./app` แบบเครื่อง dev — image ต้อง build ใหม่เมื่อแก้โค้ด
- อย่าใส่ `API_KEY` ว่างบน production ถ้าเปิดให้คนนอกใช้

## แก้ปัญหาเร็ว

| อาการ | ตรวจ |
| --- | --- |
| Caddy ไม่ได้ใบรับรอง | DNS ยังไม่ชี้มาที่ VPS / พอร์ต 80 ถูกบล็อก |
| หน้าเว็บเรียก API ไม่ได้ | `CORS_ORIGINS`, `BACKEND_URL`, `API_KEY` |
| อัปโหลดใหญ่ล้ม | `MAX_UPLOAD_MB` ใน `defaults.py`, timeout ใน Caddyfile |
| งานค้างที่ analyze/TTS | `modal app list`, token Modal, `docker compose logs api` |
| ดิสก์เต็ม | เปิด R2 + `R2_PURGE_LOCAL=1` / ล้าง `data/jobs` งานเก่า / ขยายวอลุ่ม |
| ดาวน์โหลดผลงาน 404 หลัง purge | ตรวจ `r2_manifest.json`, คีย์ R2, `docker compose logs api` |
| API ต่อ DB ไม่ได้ | `DATABASE_URL` โฮสต์ต้องเป็น `db`, รหัสผ่านตรง `POSTGRES_PASSWORD`, `docker compose logs db` |
| ตารางหายหลัง recreate | volume `pg_data` ถูกลบ — restore จาก dump |

ดูภาพรวมระบบเพิ่มที่ [project-overview.md](project-overview.md)
