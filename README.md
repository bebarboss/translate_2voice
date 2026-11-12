# Pakdee

Pakdee (พากย์ดี) — ระบบพากย์คลิปละครต่างประเทศเป็นภาษาไทยหรืออังกฤษ ด้วยเสียงที่โคลนจากนักแสดงต้นฉบับ ตัวละครแบรนด์เป็นนกแก้ว แบ่งเป็นสองส่วน

**คู่มือผู้ใช้:** [docs/user-manual.md](docs/user-manual.md)  
**Deploy บน VPS:** [deploy/k8s/README.md](deploy/k8s/README.md) (k3s) · [docs/deploy-vps.md](docs/deploy-vps.md) (Docker Compose, ใช้ย้อนกลับ)

- **Backend** (`backend/`) — FastAPI รันโมเดลบนการ์ดจอเครื่องตัวเอง หรือส่งเฉพาะขั้นที่ใช้การ์ดจอไป Modal (`WORKER=modal`)
- **Frontend** (`frontend/`) — Next.js สำหรับอัปโหลด ตรวจบท และดาวน์โหลด

```
คลิปต้นฉบับ หรือลิงก์ (YouTube, TikTok, Facebook, Bilibili ผ่าน yt-dlp)
  → ดึงเสียง (FFmpeg)
  → แยกเสียงพูดกับเพลง (Demucs)            → bgm.wav เก็บไว้ผสมตอนท้าย
  → แยกว่าใครพูดตอนไหน (pyannote)          → stems/speaker_01.wav ... เลเยอร์เสียงของแต่ละคน
  → ถอดเสียงและตรวจภาษา (faster-whisper)
  → แปลเป็นไทยหรืออังกฤษ (Typhoon 2.5)
  → ย่อบทให้พอดีเวลา (Typhoon 2.5)
  → [ตัวเลือก] หยุดให้คนตรวจแก้บท
  → พากย์ทีละประโยค (F5-TTS ใช้เสียงต้นฉบับประโยคเดียวกันเป็นตัวอย่าง จึงได้อารมณ์ตามฉาก)
  → ผสมเสียงกับเพลงเดิม รวมวิดีโอ + ซับ .srt  [ตัวเลือก] ฝังซับลงวิดีโอ
```

## ฟีเจอร์

- ส่งคลิปได้ทั้งอัปโหลดไฟล์และวางลิงก์
- พากย์เป็นไทย (F5-TTS Thai) หรืออังกฤษ (F5-TTS รุ่นหลัก)
- ตรวจและแก้บททีละประโยค เปลี่ยนตัวละครของประโยคได้ วิดีโอกับบทเลื่อนตามกัน
- แก้บทหลังพากย์เสร็จ แล้วพากย์ใหม่เฉพาะประโยคที่เปลี่ยน
- ยกเลิกงานระหว่างทำ และลองใหม่จากขั้นที่ล้มเหลว
- ฝังซับในวิดีโอหรือไม่ก็ได้ ปรับฟอนต์ สี สีขอบ ขนาด ตำแหน่ง ส่งออกเป็น zip ที่มี MP4 + SRT เสมอ
- ดาวน์โหลดเลเยอร์เสียงแยก: เสียงแต่ละตัวละคร เพลงประกอบ เสียงพากย์ล้วน เสียงผสมสุดท้าย
- หน้าตั้งค่า: ค่าเริ่มต้นตอนส่งงาน ความดังเสียงพากย์และเพลง ความเร็วเสียงสูงสุด คุณภาพเสียง รูปแบบซับเริ่มต้น

## โครงสร้างโปรเจกต์

```
backend/                 API (Python / FastAPI)
  app/                   โค้ด API + pipeline
  tests/                 pytest
  scripts/               สคริปต์ดูแลระบบ / migrate
  supabase/              SQL อ้างอิง schema
  fixtures/              ชุด regression
  notebooks/             Colab ฯลฯ
  modal_app.py           Modal GPU (analyze_audio, synthesize_lines)
  Dockerfile             image ของ API
  requirements*.txt
frontend/                หน้าเว็บ Next.js (ดู frontend/README.md)
deploy/                  Docker Compose (rollback) และ manifests k3s (`deploy/k8s/`)
docs/                    คู่มือ
data/                    ไฟล์งาน runtime (ไม่ commit)
.env                     คีย์ API / Modal / DB (รากโปรเจกต์)
```

## ต้องมีก่อนรัน

- Python 3.10 หรือ 3.11, Node.js 20 ขึ้นไป, FFmpeg (Windows: `winget install ffmpeg`)
- การ์ดจอ NVIDIA VRAM 8 GB ขึ้นไปสำหรับโมเดลจริง (แนะนำ 12 GB+) ไม่มีการ์ดจอใช้โหมดทดสอบได้
- ถ้าจะฝังซับ ติดตั้งฟอนต์ **Noto Sans Thai** (และ Noto Sans สำหรับงานอังกฤษ) ลงเครื่องที่รัน API
- คีย์ฟรีสองตัว
  1. **Hugging Face token** สร้างที่ https://huggingface.co/settings/tokens แล้วกด *Agree* ที่หน้าโมเดล `pyannote/speaker-diarization-community-1`, `pyannote/speaker-diarization-3.1` และ `pyannote/segmentation-3.0`
  2. **Typhoon API key** สมัครที่ https://playground.opentyphoon.ai แล้วไปที่เมนู API Keys

## เริ่มเร็ว: ทดสอบทั้งระบบโดยไม่ใช้โมเดล (แนะนำให้ลองก่อน)

ใช้ได้กับทุกเครื่อง ไม่ต้องมีการ์ดจอ บทแปลและเสียงพากย์จะเป็นข้อมูลจำลอง

**หน้าต่างที่ 1 — API** (Windows PowerShell)

```powershell
cd E:\thai-dubbing-api_1\thai-dubbing-api
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
copy .env.example .env
# แก้ .env ให้ MOCK_PIPELINE=1
cd backend
python run.py
```

**หน้าต่างที่ 2 — Frontend**

```powershell
cd E:\thai-dubbing-api_1\thai-dubbing-api\frontend
npm install
copy .env.example .env.local
npm run dev
```

เปิด http://localhost:3000 แล้วลองอัปโหลดคลิปสั้น ๆ ได้เลย เอกสาร API อยู่ที่ http://localhost:8000/docs

## รันกับโมเดลจริง

```powershell
.venv\Scripts\activate
# ติดตั้ง PyTorch ให้ตรงกับ CUDA ก่อน ดูคำสั่งที่ https://pytorch.org เช่น
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r backend\requirements-ml.txt
# แก้ .env: MOCK_PIPELINE=0 แล้วใส่ HF_TOKEN และ TYPHOON_API_KEY
cd backend
python run.py
```

ครั้งแรกระบบจะดาวน์โหลดโมเดลรวมหลาย GB ครั้งเดียว

**การ์ดจอเล็ก (4–8 GB)** ตั้งใน `.env`: `WHISPER_MODEL=medium` หรือ `small`, `WHISPER_COMPUTE_TYPE=int8_float16` และตั้งคุณภาพเสียงเป็น "เร็ว (16 steps)" ในหน้าตั้งค่า ลองกับคลิปสั้น 2–3 นาทีก่อน

**ไม่มีการ์ดจอที่พอ** ใช้ `backend/notebooks/colab_server.ipynb` บน Colab หรือเช่า GPU รายชั่วโมง แล้วตั้ง `BACKEND_URL` ใน `frontend/.env.local` ให้ชี้ไปที่ API นั้น

## ส่งขั้นที่ใช้การ์ดจอไปรันบน Modal (ไม่ต้องมีการ์ดจอ)

ตั้ง `WORKER=modal` แล้ว API บนเครื่องตัวเองจะส่งเฉพาะขั้นที่ใช้การ์ดจอไปรันบน [Modal](https://modal.com) (GPU L4) ไฟล์งานทั้งหมด (คลิป บท เสียง วิดีโอ) ยังเก็บที่ `data/` บนเครื่องเหมือนเดิม

| ที่รัน | ขั้น |
|---|---|
| เครื่องตัวเอง (CPU) | ดาวน์โหลดลิงก์ (yt-dlp), ดึงเสียง (FFmpeg), ส่งออกเลเยอร์เสียงแต่ละตัวละคร, แปลและย่อบท (Typhoon API), ยืดหดเวลาเสียง, ผสมเสียง, รวมวิดีโอ, ฝังซับ, ทำ SRT |
| Modal `analyze_audio` | แยกเสียงพูดกับเพลง (Demucs), แยกผู้พูด (pyannote), ถอดเสียง (faster-whisper) |
| Modal `synthesize_lines` | พากย์ (F5-TTS ไทยและอังกฤษ) ทีละชุด ส่งไปเฉพาะประโยคที่ต้องพากย์ใหม่ |

ส่งขึ้น Modal แค่เสียง FLAC mono (44.1 kHz ตอนวิเคราะห์, ตอนพากย์ส่งแค่ช่วงเสียงตัวอย่าง 24 kHz) ไม่ส่งวิดีโอ ไม่มีไฟล์งานค้างบน Modal งานหลายงานส่งพร้อมกันได้ (`MODAL_MAX_JOBS`) ยกเลิกงานกลางทางแล้วงานบน Modal หยุดด้วย

**ติดตั้งครั้งแรก** (PowerShell ในโฟลเดอร์หลัก)

```powershell
.venv\Scripts\activate
pip install -r backend\requirements.txt
pip install modal
modal setup                                   # ล็อกอิน Modal (เปิดเบราว์เซอร์)
modal secret create dubbing-keys HF_TOKEN=hf_xxx   # token เดียวกับที่กดยอมรับเงื่อนไข pyannote แล้ว
modal volume create dubbing-models            # เก็บแคชโมเดลอย่างเดียว
cd backend
modal deploy modal_app.py                     # ครั้งแรกนานราว 10 นาที (สร้าง image ที่มี PyTorch)
```

แล้วแก้ `.env`: `WORKER=modal` (ใส่ `TYPHOON_API_KEY` ไว้เหมือนเดิม `HF_TOKEN` บนเครื่องไม่จำเป็นแล้ว) แล้ว `python run.py` จาก `backend/` เครื่องนี้ไม่ต้องติดตั้ง PyTorch หรือ `requirements-ml.txt`

- งานแรกหลัง deploy ช้ากว่าปกติ เพราะ Modal โหลดโมเดลหลาย GB ลง Volume ครั้งเดียว งานต่อ ๆ ไปเปิด container ใหม่ราว 30–60 วินาที
- container ปิดตัวเองเมื่อว่าง 3 นาที (`scaledown_window` ใน `modal_app.py`) ไม่เสียเครดิตตอนไม่มีงาน — คั่นขั้นแปลบน API แล้วยังได้ GPU เดิมตอนพากย์
- แก้ค่าโมเดลหรือเกณฑ์ใน `.env` มีผลทันที ไม่ต้อง deploy ใหม่ แต่ถ้าแก้โค้ดใน `backend/app/pipeline/` ต้อง `modal deploy modal_app.py` ใหม่
- ดู log และค่าใช้จ่ายที่ https://modal.com/apps (แอป `dubbing-gpu`)
- งานที่วิเคราะห์ตอน `WORKER=local` แล้วมาพากย์ตอน `WORKER=modal` ได้ แต่จะข้ามการคัดเสียงตัวอย่างตามความสะอาดและลายเสียง (ค่าพวกนี้ Modal วัดไว้ตอนวิเคราะห์)
- ไฟล์เพลงประกอบ (`bgm`) ที่ได้จาก Modal เป็นเสียง mono เพราะส่งเสียงต้นฉบับขึ้นไปเป็น mono

**ทดสอบด้วยคลิปสั้น 1 นาที**

```powershell
# ตัดคลิป 1 นาทีแรกจากคลิปที่มี
ffmpeg -i input.mp4 -t 60 -c copy test_1min.mp4
# ส่งงาน แล้วดูความคืบหน้า (หรืออัปโหลดผ่านหน้าเว็บ)
curl.exe -F "file=@test_1min.mp4" -F "target_lang=th" -F "review=true" http://localhost:8000/jobs
curl.exe http://localhost:8000/jobs/<id>
```

ระหว่างรอ `stage` จะเปลี่ยนตามขั้นบน Modal: `separate_vocals` → `diarize` → `transcribe` → `translate` → `fit_lengths` → `awaiting_review` แก้บทสักประโยคแล้ว `POST /jobs/<id>/synthesize` (`tts` → `mix` → `mux_video`) จากนั้นแก้บทอีกประโยคแล้วพากย์ซ้ำ `synth_stats` ควรเป็น `redubbed` เท่าจำนวนท่อนที่แก้ ที่เหลือ `reused` และใน log ของ Modal (`modal app logs dubbing-gpu`) จะเห็นว่าส่งไปแค่ประโยคนั้น

**Docker** ค่าเริ่มต้นของ `docker compose up -d --build` เป็นแบบนี้ (image ไม่มี PyTorch ไม่ต้องตั้งค่า GPU) ใส่ `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` จาก https://modal.com/settings/tokens ใน `.env` ส่วน `modal setup` / `secret` / `volume` / `deploy` รันจากเครื่องตัวเองครั้งเดียวตามด้านบน

## รันด้วย Docker + Cloudflare Tunnel และหน้าเว็บบน Vercel

API รันบนเครื่องตัวเองผ่าน Docker (ขั้นที่ใช้การ์ดจอส่งไป Modal ตามหัวข้อด้านบน) แล้วเปิดออกอินเทอร์เน็ตด้วย Cloudflare quick tunnel (ฟรี ไม่จำกัดปริมาณข้อมูล ไม่ต้องมีบัญชี) หน้าเว็บขึ้น Vercel แล้วเรียก API ผ่านลิงก์ `*.trycloudflare.com`

**ฝั่งเครื่อง (API)** ต้องมี Docker Desktop (WSL2) ถ้าจะรันโมเดลบนการ์ดจอเครื่องนี้แทน Modal ต้องมีไดรเวอร์ NVIDIA ล่าสุด แล้วใช้ `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` แทนคำสั่งในขั้นที่ 2

1. ใน `.env` ตั้ง `API_KEY` (สุ่มยาว ๆ เพราะ API จะเปิดออกอินเทอร์เน็ต) และ `MAX_UPLOAD_MB=95` เพราะ Cloudflare รับ request ได้ครั้งละไม่เกิน 100 MB โมเดลเก็บใน volume `hf-cache` / `f5-cache` ของ Docker (โหลดอัตโนมัติครั้งแรก) ไม่อ่านผ่านไดรฟ์ Windows เพราะไฟล์ใหญ่หลาย GB อ่านผ่าน 9p ตอน RAM ตึงแล้วพังได้
2. `docker compose up -d --build` (แบบใช้การ์ดจอเครื่องนี้ครั้งแรกนาน เพราะติดตั้ง PyTorch และโมเดล)
3. ดูลิงก์: `docker compose logs tunnel | grep trycloudflare` แล้วเช็ก `curl https://<ลิงก์>/health` ดู log: `docker compose logs -f api`

ลิงก์ quick tunnel **เปลี่ยนทุกครั้งที่ container `tunnel` เริ่มใหม่** (รีสตาร์ต Docker หรือเปิดเครื่องใหม่) ต้องไปแก้ `BACKEND_URL` บน Vercel แล้ว Redeploy ทุกครั้ง

ข้อมูลงานอยู่ที่ `./data` เหมือนเดิม งานเก่าที่สร้างตอนรันบน Windows เปิดต่อได้

**ฝั่ง Vercel (หน้าเว็บ)** Import repo นี้ ตั้ง *Root Directory* = `frontend` แล้วใส่ Environment Variables

- `BACKEND_URL` = ลิงก์ `https://xxxx.trycloudflare.com` จากขั้นที่ 3
- `API_KEY` = ค่าเดียวกับใน `.env` ของ API

Vercel รับ body ได้ไม่เกิน 4.5 MB หน้าเว็บจึงขอตั๋วจาก `/api/upload-ticket` แล้วให้เบราว์เซอร์อัปโหลดไฟล์ตรงไปที่ tunnel (คีย์จริงไม่ออกไปที่เบราว์เซอร์) ส่วนคำขออื่นและการเล่นวิดีโอยังผ่าน proxy `/api` เหมือนเดิม

**ใช้ ngrok แทน** ตั้ง `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` ใน `.env` แล้ว `docker compose stop tunnel && docker compose --profile ngrok up -d ngrok` ได้ลิงก์คงที่ แต่แบบฟรีได้ข้อมูลราว 1 GB ต่อเดือน เต็มแล้วจะตอบ `ERR_NGROK_725` จนขึ้นรอบเดือนใหม่

## API

| Method | Path | ทำอะไร |
|---|---|---|
| POST | `/jobs` | ส่งงาน form-data: `file` หรือ `url`, `source_lang`, `target_lang` (th/en), `num_speakers`, `review`, `burn_subs` |
| GET | `/jobs` | รายการงานทั้งหมด |
| GET | `/jobs/{id}` | สถานะ ขั้นตอน ความคืบหน้า ภาษาที่ตรวจพบ ผู้พูด สถิติการพากย์ |
| POST | `/jobs/{id}/cancel` | ยกเลิกงานที่รอคิวหรือกำลังทำ |
| POST | `/jobs/{id}/retry` | ลองใหม่จากขั้นที่ล้มเหลวหรือถูกยกเลิก |
| DELETE | `/jobs/{id}` | ลบงานและไฟล์ทั้งหมด |
| GET | `/jobs/{id}/transcript` | บทพร้อมเวลา ผู้พูด ข้อความต้นฉบับ และบทพากย์ (`target`) |
| PUT | `/jobs/{id}/transcript` | แก้บทหรือผู้พูด `[{"id": 3, "target": "...", "speaker": "speaker_02"}]` |
| POST | `/jobs/{id}/synthesize` | พากย์ (พากย์ใหม่เฉพาะประโยคที่เปลี่ยน) |
| PATCH | `/jobs/{id}/options` | ตั้ง `burn_subs` และ `sub_style` ของงานนี้ |
| POST | `/jobs/{id}/render` | ฝังซับใหม่ตามรูปแบบล่าสุด ไม่ต้องพากย์ใหม่ |
| GET | `/jobs/{id}/result?subs=true` | วิดีโอพากย์แล้ว (`subs=true` = รุ่นฝังซับ) |
| GET | `/jobs/{id}/export?subs=true` | zip ที่มี MP4 + SRT |
| GET | `/jobs/{id}/subtitles` | ซับ .srt |
| GET | `/jobs/{id}/source` | คลิปต้นฉบับ |
| GET | `/jobs/{id}/stems` และ `/stems/{name}` | เลเยอร์เสียง `speaker_01`, `vocals`, `bgm`, `dub_voice`, `final_audio` |
| GET/PUT | `/settings` | ค่าที่ปรับได้จากหน้าเว็บ |
| GET | `/system` | การ์ดจอ โมเดล คีย์ที่ตั้งไว้ และคิวงาน |
| GET | `/fonts` | ฟอนต์ไทยและอังกฤษที่ใช้ฝังซับได้ |
| GET | `/health` | เช็กว่าเซิร์ฟเวอร์ทำงาน |

สถานะงาน: `queued` → `running` → (`awaiting_review` ถ้า `review=true`) → `done` หรือ `failed` / `cancelled`

### นำเข้าไทม์ไลน์จากโปรแกรมตัดต่อ (`app/timeline/`)

ส่งไทม์ไลน์จาก Premiere Pro หรือ DaVinci Resolve พร้อมไฟล์เสียงแยกแทร็ก ได้แทร็กพากย์ไทยแยกคนกลับไปวางบนไทม์ไลน์เดิม
รองรับ Final Cut Pro XML (`.xml`), FCPXML (`.fcpxml`), EDL (`.edl`) และ OTIO (`.otio`) หรือ zip ที่รวมไทม์ไลน์กับไฟล์สื่อ

| Method | Path | ทำอะไร |
|---|---|---|
| POST | `/timeline` | form-data: `file` (ไทม์ไลน์หรือ zip), `media` (ไฟล์สื่อ หลายไฟล์ได้), `fps` (จำเป็นสำหรับ EDL ที่ไม่บอก), `drop_frame`, `source_lang`, `target_lang`, `review`, `start` คืนแทร็ก คลิป และ `missing` (ไฟล์ที่ขาด) |
| GET | `/jobs/{id}/timeline` | แทร็ก คลิป (timecode ตามไทม์ไลน์) ผู้พูด เสียงที่เลือก ไฟล์ที่ขาด |
| POST | `/jobs/{id}/timeline/media` | อัปโหลดไฟล์ที่ขาด (`files` หลายไฟล์หรือ zip) |
| PUT | `/jobs/{id}/timeline` | `{"tracks": [{"index": 1, "speaker_name": "พิธีกร", "voice_id": "...", "enabled": true}]}` ชื่อเดียวกัน = คนเดียวกัน, `enabled: false` = ไม่ใช่บทพูด (ใส่ในเสียงรวมอย่างเดียว) |
| POST | `/jobs/{id}/timeline/start` | เริ่มถอดเสียงทีละแทร็ก → แปล → (ตรวจบท) → พากย์ด้วย `/jobs/{id}/synthesize` ตามปกติ |
| GET | `/jobs/{id}/timeline/export?formats=xml,fcpxml,stems,mix,srt&media_dir=` | zip: ไทม์ไลน์ + แทร็กพากย์ไทยต่อคน, WAV แยกผู้พูดยาวเท่าไทม์ไลน์ (sample rate ของโปรเจกต์, 24-bit), เสียงรวม, SRT, README วิธี import |

- `importer.py` อ่านไทม์ไลน์ด้วย OpenTimelineIO (EDL แปลงเอง เพราะ `cmx_3600` ของ OTIO 0.18 วางแทร็ก A2 ขึ้นไปผิดที่) จับคู่ไฟล์สื่อตามชื่อไฟล์
- `processor.py` วางเสียงแต่ละแทร็กตามไทม์ไลน์ ถอดเสียงทีละผู้พูด (faster-whisper ตัวเดียวกับงานปกติ) แบ่งประโยคตรงรอยต่อคลิป และไม่ให้เสียงพากย์ล้นออกนอกคลิป
- `exporter.py` เขียน Final Cut Pro XML ด้วย OTIO และเขียน FCPXML 1.9 เอง (ตัวเขียนของ OTIO ใช้กับไทม์ไลน์ที่ไม่ได้มาจาก Final Cut ไม่ได้)
- `timecode.py` อัตราเฟรม NTSC ใช้เศษส่วนจริง (30000/1001) และ drop-frame ตาม SMPTE
- ทดสอบ: `pip install pytest` แล้ว `python -m pytest tests/timeline` (ไฟล์ตัวอย่างใน `tests/timeline/fixtures/` เขียนตามรูปแบบที่ Premiere และ Resolve ส่งออก)

## วัดจาก job จริง + ให้ระบบปรับเอง

คะแนนหลักมาจากไฟล์ในงานที่พากย์เสร็จแล้ว (ไม่พึ่งคนแก้บท ซึ่งอาจแก้ไม่ถูก):

| สัญญาณ | ต้นฉบับ | ผล |
| --- | --- | --- |
| `speech_coverage` | ช่วงมีเสียงบน `vocals.wav` | ช่วงใน `transcript.json` |
| `length_vs_source` | รวมเวลาพูดต้นฉบับ | รวมเวลาพากย์ / ประมาณจากบท |
| `translate_fidelity` | `source` (+ glossary) | `target` (ว่าง/สั้นยาว/ศัพท์) |
| `prosody_match` | ความดัง/pitch ต้นฉบับ | ไฟล์พากย์รายท่อน |
| `lip_overflow` | ช่องปาก + ท่อนถัดไป | ความยาว `tts` ล้น/สั้นเกิน |
| `term_consistency` | glossary / ชื่อ / ต้นฉบับซ้ำ | สะกดใน `target` ทั้งเรื่อง |
| `speaker_confusion` | `turns.json` + pitch | ป้ายผู้พูด / ทับเวลา / กระโดดเสียง |
| `dub_match` | บท `target` | `heard_score` จากเสียงพากย์ |
| `timing_fit` | ความยาวช่องปาก | ไฟล์ `tts/*.wav` |
| `recheck_gain` | — | `recheck.json` |

ทุกงานที่เสร็จจะเขียน `metrics.json` อัตโนมัติ

```powershell
python scripts/score_jobs.py
python scripts/score_jobs.py --write --nudge
python scripts/run_daily_metrics.py              # ประเมินงาน done วันนี้ (กรุงเทพ) เก็บลง DB
python scripts/run_daily_metrics.py --date 2026-11-09
python -m pytest tests/test_job_metrics.py -q
```

- **Daily metrics cron** (23:59 Asia/Bangkok): API สแกนงาน `done` ในวันนั้น → `job_metrics` → ตาราง `job_metric_scores` / `job_metric_daily` (ต้องรัน `supabase/migrations/20261109020000_job_metrics_daily.sql`) อ่านที่ `GET /admin/job-metrics/daily`
- **Auto-heal ASR** (`AUTO_HEAL_ASR=1`): ถ้า coverage ต่ำระหว่างวิเคราะห์ → ผ่อน VAD ชั่วคราว + fill_gaps/recheck หนึ่งรอบ เก็บผลที่ดีกว่า
- **Same-lang**: ต้นทาง = ปลายทาง → คัดลอก `source → target` ทันที ห้ามเข้า review/พากย์ด้วยบทว่าง
- **เกตก่อนพากย์**: บทว่างเหลือ หรือ `speech_coverage` &lt; `MIN_COVERAGE_SYNTHESIZE` (ค่าเริ่ม 0.70) → ปฏิเสธ พร้อมข้อความให้แปล/วิเคราะห์ใหม่
- **`RETRANSCRIBE_NOISY`**: เปิดเป็นค่าเริ่มต้น
- **Auto knobs** (`AUTO_KNOBS=1`): หลังมีสถิติหลายงาน ระบบขยับ `whisper_vad_threshold` / `fill_gap` / `dub_check_min` ในขอบเขตปลอดภัย เก็บที่ `data/metrics/knobs.json` (ไม่ต้องแก้ `.env` เอง)

ชุดทอง (`fixtures/gold/`, `scripts/score_gold.py`) ยังใช้เป็น regression เสริมได้

## เคล็ดลับ

- **ใส่จำนวนตัวละคร** ถ้ารู้ การแยกผู้พูดจะแม่นขึ้นมาก
- **เปิดตรวจบทก่อนพากย์** สำหรับงานจริง แก้บทกับตัวละครให้ถูกก่อน ประหยัดเวลากว่า
- **เสียงพากย์ยาวเกินฉาก** เพิ่ม "เร่งเสียงได้สูงสุด" ในหน้าตั้งค่า หรือลด `THAI_CHARS_PER_SEC` ใน `.env` ให้ระบบย่อบทเข้มขึ้น
- **เพลงดังกลบเสียงพากย์** ลด "ความดังเพลงประกอบ" ในหน้าตั้งค่า
- **ลิงก์โหลดไม่ได้** อัปเดต yt-dlp: `pip install -U yt-dlp`

## ข้อจำกัด

- `WORKER=local` งานรันทีละงานตามคิว เพราะการ์ดจอใบเดียวรันหลายโมเดลพร้อมกันไม่ไหว (`WORKER=modal` รันพร้อมกันได้)
- ช่วงที่ตัวละครพูดซ้อนกัน เสียงตัวอย่างอาจมีเสียงอีกคนปน ทำให้เสียงพากย์เพี้ยนได้
- ข้อมูลงานเก็บเป็นไฟล์ในโฟลเดอร์ `data/` ยังไม่มีระบบผู้ใช้หรือดาต้าเบส เหมาะกับใช้คนเดียวหรือทีมเล็ก
- ถ้าต้นฉบับไม่ใช่จีนหรืออังกฤษ เสียงพากย์อังกฤษอาจมีสำเนียงเพี้ยนบ้าง

## ฟีเจอร์ที่วางไว้ในอนาคต

ช่องสรุปคลิป · ลิปซิงก์ · ระบบผู้ใช้กับดาต้าเบส · ภาษาพากย์อื่นเพิ่ม

## เรื่องลิขสิทธิ์และสิทธิในเสียง

ระบบนี้โคลนเสียงของนักแสดงต้นฉบับ ถ้าจะเผยแพร่คลิปที่พากย์แล้ว ต้องได้รับอนุญาตจากเจ้าของคลิปและเจ้าของเสียงก่อน การดาวน์โหลดคลิปจากแพลตฟอร์มด้วยโปรแกรมภายนอกอาจขัดเงื่อนไขการใช้งานของแพลตฟอร์มนั้น และไม่ควรใช้เสียงของบุคคลจริงทำให้คนดูเข้าใจผิดว่าเขาพูดเอง
