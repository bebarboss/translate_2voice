# Dubbing Studio

ระบบพากย์คลิปละครต่างประเทศเป็นภาษาไทยหรืออังกฤษ ด้วยเสียงที่โคลนจากนักแสดงต้นฉบับ แบ่งเป็นสองส่วน

- **API** (โฟลเดอร์หลัก) — FastAPI รันโมเดลบนการ์ดจอเครื่องตัวเอง หรือส่งเฉพาะขั้นที่ใช้การ์ดจอไป Modal (`WORKER=modal`)
- **หน้าเว็บ** (`web/`) — Next.js สำหรับอัปโหลด ตรวจบท และดาวน์โหลด

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
app/
  main.py              จุดเข้า API (FastAPI)
  config.py            ค่าตั้งค่าจาก .env
  runtime_settings.py  ค่าที่ปรับจากหน้าเว็บ เก็บใน data/settings.json
  schemas.py           โครงสร้างข้อมูล
  jobs.py              เก็บสถานะงาน + คิว (local ทีละงาน, modal หลายงานพร้อมกัน) + ยกเลิก
  pipeline/
    download.py        รับลิงก์ด้วย yt-dlp
    audio.py           FFmpeg, Demucs, ตัดคลิป, ยืดหดเวลา
    diarize.py         pyannote + เลเยอร์เสียงแต่ละคน
    transcribe.py      faster-whisper + จับคู่คำกับผู้พูด
    translate.py       Typhoon แปล ทำคำอ่าน และย่อบท
    tts.py             F5-TTS ไทยและอังกฤษ
    mix.py             วางเสียงตามเวลา ผสม รวมวิดีโอ
    subs.py            ทำ .srt ฝังซับ และรายชื่อฟอนต์
    runner.py          ร้อยทุกขั้นเข้าด้วยกัน + พากย์ใหม่เฉพาะประโยคที่เปลี่ยน
    gpu.py             ขั้นที่ใช้การ์ดจอ เรียกบนเครื่องนี้หรือบน Modal ตาม WORKER
    mock.py            โหมดทดสอบที่ไม่ต้องใช้โมเดล
modal_app.py           ฟังก์ชันบน Modal GPU L4 (analyze_audio, synthesize_lines)
web/                   หน้าเว็บ Next.js (ดู web/README.md)
notebooks/colab_server.ipynb   รัน API บน Google Colab
scripts/client_example.py      ตัวอย่างเรียก API จาก Python
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
pip install -r requirements.txt
copy .env.example .env
# แก้ .env ให้ MOCK_PIPELINE=1
python run.py
```

**หน้าต่างที่ 2 — หน้าเว็บ**

```powershell
cd E:\thai-dubbing-api_1\thai-dubbing-api\web
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
pip install -r requirements-ml.txt
# แก้ .env: MOCK_PIPELINE=0 แล้วใส่ HF_TOKEN และ TYPHOON_API_KEY
python run.py
```

ครั้งแรกระบบจะดาวน์โหลดโมเดลรวมหลาย GB ครั้งเดียว

**การ์ดจอเล็ก (4–8 GB)** ตั้งใน `.env`: `WHISPER_MODEL=medium` หรือ `small`, `WHISPER_COMPUTE_TYPE=int8_float16` และตั้งคุณภาพเสียงเป็น "เร็ว (16 steps)" ในหน้าตั้งค่า ลองกับคลิปสั้น 2–3 นาทีก่อน

**ไม่มีการ์ดจอที่พอ** ใช้ `notebooks/colab_server.ipynb` บน Colab หรือเช่า GPU รายชั่วโมง แล้วตั้ง `BACKEND_URL` ใน `web/.env.local` ให้ชี้ไปที่ API นั้น

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
.venv\Scriptsctivate
pip install -r requirements.txt
pip install modal
modal setup                                   # ล็อกอิน Modal (เปิดเบราว์เซอร์)
modal secret create dubbing-keys HF_TOKEN=hf_xxx   # token เดียวกับที่กดยอมรับเงื่อนไข pyannote แล้ว
modal volume create dubbing-models            # เก็บแคชโมเดลอย่างเดียว
modal deploy modal_app.py                     # ครั้งแรกนานราว 10 นาที (สร้าง image ที่มี PyTorch)
```

แล้วแก้ `.env`: `WORKER=modal` (ใส่ `TYPHOON_API_KEY` ไว้เหมือนเดิม `HF_TOKEN` บนเครื่องไม่จำเป็นแล้ว) แล้ว `python run.py` เครื่องนี้ไม่ต้องติดตั้ง PyTorch หรือ `requirements-ml.txt`

- งานแรกหลัง deploy ช้ากว่าปกติ เพราะ Modal โหลดโมเดลหลาย GB ลง Volume ครั้งเดียว งานต่อ ๆ ไปเปิด container ใหม่ราว 30–60 วินาที
- container ปิดตัวเองเมื่อว่าง 1 นาที (`scaledown_window` ใน `modal_app.py`) ไม่เสียเครดิตตอนไม่มีงาน
- แก้ค่าโมเดลหรือเกณฑ์ใน `.env` มีผลทันที ไม่ต้อง deploy ใหม่ แต่ถ้าแก้โค้ดใน `app/pipeline/` ต้อง `modal deploy modal_app.py` ใหม่
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

**ฝั่ง Vercel (หน้าเว็บ)** Import repo นี้ ตั้ง *Root Directory* = `web` แล้วใส่ Environment Variables

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
