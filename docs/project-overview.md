# Pakdee: ภาพรวมโปรเจกต์

ระบบพากย์คลิปต่างประเทศเป็นภาษาไทยหรืออังกฤษ ใช้เสียงที่โคลนจากนักแสดงต้นฉบับ หรือเสียงจากคลังเสียงไทย
ส่งได้ทั้งไฟล์ ลิงก์ และไทม์ไลน์จากโปรแกรมตัดต่อ ผู้ใช้ตรวจแก้บทได้ก่อนพากย์ แล้วดาวน์โหลดวิดีโอ ซับ และเสียงแยกเลเยอร์

> เอกสารนี้สรุปสถานะ ณ 2026-11-04 วิธีติดตั้งและรายการ API แบบละเอียดอยู่ใน [README.md](../README.md)
> (README บางส่วนยังเขียนตามรุ่นก่อน เช่น ยังบอกว่าไม่มีระบบผู้ใช้)

---

## 1. ส่วนประกอบของระบบ

```
เบราว์เซอร์
  │
  ▼
หน้าเว็บ Next.js (web/) บน Vercel
  │  proxy /api/* แนบ API_KEY และ token ผู้ใช้ให้ (คีย์ไม่ออกไปที่เบราว์เซอร์)
  │  อัปโหลดไฟล์ใหญ่: ขอตั๋วจาก /api/upload-ticket แล้วส่งตรงไปที่ tunnel
  ▼
Cloudflare quick tunnel (container "tunnel")
  │
  ▼
API FastAPI (app/) ใน Docker บนเครื่องตัวเอง (container "api")
  │  งาน CPU: ดาวน์โหลด FFmpeg แปล ผสมเสียง ฝังซับ
  │  ไฟล์งานทั้งหมดอยู่ใน data/
  ├──► Modal (modal_app.py): ขั้นที่ใช้การ์ดจอ GPU L4 / A10G
  ├──► Typhoon 2.5 API (หรือผู้ให้บริการแบบ OpenAI-compatible เช่น Gemini): แปล ย่อบท วิเคราะห์เรื่อง
  └──► Supabase (REST ด้วย service_role key): คลังเสียง ค่าตั้ง ความจำคำแปล สถิติคุณภาพ
```

| ส่วน | เทคโนโลยี | ที่อยู่ในโค้ด |
|---|---|---|
| API | Python 3.11, FastAPI | [app/](../app) |
| ขั้นที่ใช้การ์ดจอ | Modal, PyTorch 2.14 (CUDA 12.6) | [modal_app.py](../modal_app.py), [app/pipeline/gpu.py](../app/pipeline/gpu.py) |
| หน้าเว็บ | Next.js 16, React 19, TypeScript | [web/](../web) |
| ฐานข้อมูล | Supabase (Postgres) + SQLite ที่ยังย้ายไม่เสร็จ | [supabase/migrations/](../supabase/migrations), [app/supabase_db.py](../app/supabase_db.py) |
| รันบนเครื่อง | Docker Compose: `api`, `tunnel`, `ngrok` (ทางเลือก) | [docker-compose.yml](../docker-compose.yml) |

---

## 2. ขั้นตอนพากย์ (pipeline)

ร้อยรวมใน [app/pipeline/runner.py](../app/pipeline/runner.py) ขั้นที่ใช้การ์ดจอเรียกผ่าน `gpu.py` ซึ่งรันบนเครื่องหรือบน Modal ตาม `WORKER`

### 2.1 วิเคราะห์ (`run_analyze`)
| ขั้น (`stage`) | ทำอะไร | โมดูล |
|---|---|---|
| `download` | โหลดคลิปจากลิงก์ด้วย yt-dlp (YouTube, TikTok, Facebook, Bilibili) | `download.py` |
| `extract_audio` | ดึงเสียงด้วย FFmpeg | `audio.py` |
| แยกเสียงพูดกับเพลง | BS-RoFormer (ค่าเริ่มต้น) หรือ Demucs ได้ `vocals` และ `bgm` | `audio.py` |
| แยกผู้พูด | pyannote community-1 ส่งออกเลเยอร์ `stems/speaker_XX.wav` | `diarize.py` |
| ถอดเสียง | faster-whisper large-v3 ตรวจภาษาเอง จับคู่คำกับผู้พูด | `transcribe.py` |
| ทำความสะอาดบท | ตัดประโยคที่ Whisper แต่งเอง กู้ประโยคที่พูดซ้อนกัน (SepFormer) | `hallucination.py`, `overlap.py` |
| วัดเสียงรายท่อน | ลายเสียง (wespeaker) ระดับเสียง ความสะอาด (SQUIM) ความตื่นเต้น | `voices.py`, `quality.py`, `emotion.py` |
| `story` | อ่านบททั้งเรื่อง: แนวเรื่อง ตัวละคร คำเฉพาะ และประโยคที่ผู้พูดน่าจะผิด | `translate.py` |
| `split_turns` | ตัดท่อนที่สองคนพูดต่อกันแต่ถูกรวมเป็นท่อนเดียว (AI เสนอจากบท ตรวจด้วยลายเสียง) | `turns.py` |
| `translate` | แปลด้วย Typhoon ใช้ความจำคำแปลของโปรเจกต์เป็นตัวอย่าง | `translate.py`, `memory.py` |
| `fit_lengths` | ย่อบทให้พูดทันเวลา ใส่เครื่องหมาย `/` ตรงจังหวะหยุดของต้นฉบับ | `translate.py`, `pauses.py` |
| `analyzed` | หยุดรอผู้ใช้ตรวจบท (ถ้าเปิดตรวจบท) | |

### 2.2 พากย์ (`run_synthesize`)
| ขั้น | ทำอะไร |
|---|---|
| `tts` | F5-TTS (ไทย: `f5-tts-th`, อังกฤษ: `f5-tts`) พากย์ทีละช่วงตามจังหวะหยุด ใช้เสียงต้นฉบับประโยคเดียวกันหรือเสียงจากคลังเป็นตัวอย่าง พากย์ใหม่เฉพาะประโยคที่แก้ |
| ตรวจเสียงที่พากย์ | ถอดเสียงที่พากย์ได้ด้วย Whisper เทียบกับบท ต่ำกว่า `DUB_CHECK_MIN` ลองใหม่ ยังไม่ผ่านขึ้นป้าย "ควรฟัง" (โค้ดเสร็จแล้ว ยังไม่ deploy Modal) |
| ปรับเสียง | ระดับและการขึ้นลงตามต้นฉบับ (Praat PSOLA) ความดัง เสียงก้องห้อง เสียงหายใจ | 
| `mix` | วางเสียงตามเวลา ยืดหดได้ไม่เกิน `MAX_SPEEDUP` ผสมกับเพลงเดิม |
| `mux_video` / `burn_subs` | รวมวิดีโอ ทำ SRT/ASS ฝังซับถ้าเลือก |
| บันทึกผล | บันทึกสถิติคุณภาพ (`quality.record`) ความจำคำแปล (งานในโปรเจกต์) และวินาทีที่ใช้เสียงนักพากย์ |

`run_render` ฝังซับใหม่อย่างเดียวหลังเปลี่ยนรูปแบบซับ ไม่พากย์ใหม่

### 2.3 นำเข้าไทม์ไลน์ ([app/timeline/](../app/timeline))
รับ Final Cut Pro XML, FCPXML, EDL, OTIO (หรือ zip ที่รวมไฟล์สื่อ) จาก Premiere / Resolve
ถอดเสียงทีละแทร็ก แปล พากย์ แล้วส่งออก zip ที่มีไทม์ไลน์ + แทร็กพากย์ไทยแยกคน + WAV ยาวเท่าไทม์ไลน์ + SRT
timecode รองรับ NTSC แบบเศษส่วนจริงและ drop-frame

---

## 3. ฟีเจอร์ที่ผู้ใช้เห็น

### งานพากย์
- ส่งไฟล์หรือลิงก์ เลือกภาษาต้นทาง ปลายทาง (ไทย/อังกฤษ) จำนวนตัวละคร ตรวจบทก่อนพากย์ ฝังซับ
- **หน้าตรวจบท** (`ReviewView`): วิดีโอ เลเยอร์ตัวละครบนเส้นเวลา (`SpeakerLanes`) ลาก ตัด คัดลอก รวม แยกประโยค เปลี่ยนตัวละคร ตั้งชื่อ
  - แผงวิเคราะห์เรื่อง (`RetranslatePanel`): ประโยคที่ผู้พูดน่าจะผิด พร้อมปุ่ม "เปลี่ยนเป็น…"
  - แปลใหม่ทั้งเรื่องหรือบางประโยค
- **เลือกเสียง** (`VoiceCast`, `VoicePicker`): เสียงต้นฉบับหรือเสียงจากคลังต่อตัวละคร
- **ผลงาน** (`ResultView`): ดาวน์โหลด MP4, SRT, zip, เลเยอร์เสียงแยก แจ้งจำนวนประโยคที่ "ควรฟัง"
- ยกเลิกงาน ลองใหม่จากขั้นที่ล้ม แก้บทหลังพากย์แล้วพากย์ใหม่เฉพาะที่เปลี่ยน

### โปรเจกต์ ([app/projects.py](../app/projects.py))
- รวมหลายตอนของเรื่องเดียวกัน จำแนวเรื่อง คำเฉพาะ ตัวละคร (ชื่อ บทบาท สรรพนาม เสียง ลายเสียง)
- ตอนใหม่จับคู่ผู้พูดกับตัวละครด้วยลายเสียงเอง (เฉพาะที่มั่นใจ)
- ความจำคำแปล: คู่ต้นฉบับ → บทที่ผู้ใช้แก้ ส่งเป็นตัวอย่างตอนแปลตอนต่อไป

### คลังเสียง ([app/voice_library.py](../app/voice_library.py), [app/pipeline/library.py](../app/pipeline/library.py))
- อัปโหลดเสียงไทย ระบบแยกเพลง ถอดข้อความ คัดท่อน 3–10 วินาทีที่สะอาดที่สุดของคนพูดหลัก
- เสียงเดียวมีได้หลายอารมณ์ (`moods/<mood>/`)
- แยกเสียงจากคลิปหลายคนพูดเข้าคลัง (`LibraryJobView`)

### นักพากย์ ([app/actors.py](../app/actors.py))
- สมัคร → ผู้ดูแลอนุมัติ → ยอมรับหนังสือยินยอม PDPA และสิทธิ์ใช้เสียง → อัดเสียงหลายอารมณ์ → ผู้ดูแลตรวจฟัง
- บันทึกวินาทีที่เสียงถูกใช้ทุกงาน คิดค่าตอบแทนรายเดือน (`ACTOR_RATE_SATANG_PER_MIN`) หักภาษี ณ ที่จ่าย ส่งออก CSV

### บัญชี เครดิต และกฎหมาย
- ล็อกอินด้วย Google เท่านั้น (`AUTH_ENABLED`) เห็นเฉพาะงานของตัวเอง ผู้ดูแลตาม `ADMIN_EMAILS`
- เครดิตและแพ็กเกจ (`BILLING_ENABLED`) 1 เครดิต = คลิป 1 นาที ผู้ดูแลไม่ถูกตัดเครดิต ยังไม่ได้ต่อระบบรับชำระเงิน (`PAYMENT_PROVIDER`)
- ความยินยอม: ข้อกำหนด นโยบายความเป็นส่วนตัว รับข่าวสาร บันทึกเป็นหลักฐานทุกครั้ง (เวอร์ชัน แฮช เวลา IP) เปลี่ยนเวอร์ชันแล้วต้องยอมรับใหม่
- ดาวน์โหลดข้อมูลของตัวเอง และปิดบัญชี (ลบข้อมูลรวมถึงสถิติคุณภาพ)
- อีเมลแจ้งเตือนผ่าน SMTP (ยังไม่ได้ตั้งค่า)

### ผู้ดูแลระบบ (`/admin`)
- ผู้ใช้ เครดิต นักพากย์ ตรวจเสียง ค่าตอบแทน
- **คุณภาพ**: สัดส่วนบรรทัดที่ผู้ใช้แก้ (คำแปล ผู้พูด เวลา เพิ่ม ลบ) รายสัปดาห์และรายคู่ภาษา บรรทัดที่แก้ดาวน์โหลดเป็น CSV ใช้เป็นชุดทดสอบ
- สำรองข้อมูล (ไฟล์ JSON และ accounts.db ทุก `BACKUP_HOURS` ชั่วโมง)

### หน้าเว็บทั้งหมด ([web/app/](../web/app))
`/` หน้าแรก · `/jobs` และ `/jobs/[id]` · `/projects` และ `/projects/[id]` · `/voices` · `/timeline` · `/settings` · `/account`
· `/actor`, `/actor-consent`, `/actors` · `/admin` · `/login`, `/welcome`, `/onboarding` · `/promotions` · `/terms`, `/privacy`
รองรับภาษาไทยและอังกฤษ ([web/lib/i18n.ts](../web/lib/i18n.ts), [web/lib/i18n-en.ts](../web/lib/i18n-en.ts))

---

## 4. ข้อมูลเก็บที่ไหน

นโยบาย: **ข้อมูลทั้งหมดต้องอยู่ใน Supabase** ไฟล์เสียงและวิดีโอยังอยู่ใน `data/` บนเครื่อง

| ข้อมูล | ตอนนี้อยู่ที่ | สถานะ |
|---|---|---|
| คลังเสียง (`voices`, `voice_moods`) | Supabase + ไฟล์สำรอง | ใช้งานแล้ว |
| ค่าตั้งจากหน้าเว็บ (`app_settings`) | Supabase + `data/settings.json` สำรอง | ใช้งานแล้ว |
| ความจำคำแปล (`translation_memory`) | Supabase | ใช้งานแล้ว (ยังมีทางสำรอง SQLite ที่ต้องลบ) |
| สถิติคุณภาพ (`job_quality`, `quality_lines`) | Supabase | **ยังไม่ได้รัน migration `20261104010000_quality.sql`** |
| ผู้ใช้ session เครดิต ความยินยอม นักพากย์ | `data/accounts.db` (SQLite) | รอย้าย |
| งาน บท โปรเจกต์ | ไฟล์ JSON ใน `data/jobs/`, `data/projects/` | รอย้าย |
| ไฟล์เสียง วิดีโอ เลเยอร์ | `data/` | อยู่บนเครื่องต่อ (ย้ายไป Supabase Storage ต้องตัดสินใจก่อน) |

ตาราง `profiles`, `ledger`, `jobs` ฯลฯ ใน `20261101000000_init.sql` ออกแบบตาม Supabase Auth (id เป็น uuid)
แต่แอปใช้ Google login ที่ id เป็นตัวอักษร จึงยังไม่ได้ใช้ ต้องสร้างตารางแบบ id ตัวอักษรตอนย้าย

**การย้ายติดอยู่ที่รหัสผ่านฐานข้อมูล:** ต่อ Postgres ทั้งแบบ pooler และแบบตรงไม่ผ่าน ต้องรีเซ็ตรหัสผ่านใน Supabase แล้วตั้ง `SUPABASE_DB_URL` แบบ pooler ใหม่
ลำดับที่วางไว้: บัญชี เครดิต ความยินยอม นักพากย์ ก่อน แล้วค่อยงานและโปรเจกต์ ตรวจจำนวนแถวทุกตาราง

---

## 5. Modal (ขั้นที่ใช้การ์ดจอ)

| ฟังก์ชัน | ทำอะไร | โมเดล |
|---|---|---|
| `analyze_audio` | แยกเพลง แยกผู้พูด ถอดเสียง วัดค่าต่อท่อน และเตรียมเสียงเข้าคลัง (`voice_ref=True`) | BS-RoFormer/Demucs, pyannote, faster-whisper, wespeaker, SQUIM |
| `resplit_turns` | ตัดท่อนตามจุดเปลี่ยนคนที่ AI เสนอ จัดกลุ่มผู้พูดใหม่ | wespeaker |
| `synthesize_lines` | พากย์ทีละชุด (`MODAL_TTS_BATCH` ประโยค) ตรวจเสียงที่พากย์ | F5-TTS, faster-whisper |

- GPU: L4 ถ้าคิวเต็มใช้ A10G, timeout 60 นาที, ปิด container เมื่อว่าง 60 วินาที
- Volume `dubbing-models`: เก็บแคชโมเดล (`HF_HOME`, `TORCH_HOME`, `PYTHAINLP_DATA_DIR`) โหลดจากเน็ตครั้งเดียว
- Secret `dubbing-keys`: `HF_TOKEN`
- Dict `dubbing-progress`: ส่งความคืบหน้ากลับมาให้ API
- ค่าใน `.env` ที่อยู่ใน `REMOTE_FIELDS` (gpu.py) ส่งไปทุกครั้ง แก้แล้วมีผลทันที แต่แก้โค้ดใน `app/pipeline/` ต้อง `modal deploy modal_app.py` ใหม่

### ลดเวลาเปิดเครื่อง (cold start) ที่พิจารณาไว้
เวลาเปิดเครื่องหมดไปกับ: เปิดเครื่องและโหลด image → `import torch` → อ่านโมเดลจาก Volume แล้วโหลดขึ้นการ์ดจอ (ช้าสุด)

| ทางเลือก | ผล | ข้อเสีย | คำแนะนำ |
|---|---|---|---|
| เก็บโมเดลใน image แทน Volume | เร็วขึ้นเล็กน้อย | image ใหญ่หลายสิบ GB สร้าง image ใหม่ทุกครั้งที่อัปเดต | ไม่ทำ |
| ยืด `scaledown_window` เป็น 3–5 นาที | งานที่ตามมาติดกันไม่ต้องรอเปิดเครื่อง | จ่ายช่วงว่างเพิ่ม | ทำก่อน แก้บรรทัดเดียว |
| Memory snapshot (`modal.Cls` + `@modal.enter(snap=True)`) | ข้าม import และอ่านโมเดล เหลือแค่ย้ายขึ้นการ์ดจอ | ต้องแก้โครงสร้างโหลดโมเดลใน `gpu.py`, snapshot ล้างทุก deploy, แบบเก็บสถานะการ์ดจอยังทดลอง | ทำถ้าวัดแล้วเปิดเครื่องเกิน 30 วินาที |
| `min_containers=1` | ไม่ต้องรอเลย | จ่ายค่าการ์ดจอตลอดเวลา | เมื่อมีลูกค้ามากพอ |

ขั้นต่อไป: วัดเวลาจาก log ของ Modal แยกตามฟังก์ชันก่อนตัดสินใจ

---

## 6. ค่าตั้งค่าที่สำคัญ ([app/config.py](../app/config.py))

| กลุ่ม | ตัวแปร |
|---|---|
| ระบบ | `DATA_DIR`, `API_KEY`, `MAX_UPLOAD_MB`, `MOCK_PIPELINE`, `DEVICE`, `LOW_VRAM` |
| ที่รันการ์ดจอ | `WORKER` (local/modal), `MODAL_APP`, `MODAL_MAX_JOBS`, `MODAL_TTS_BATCH`, `LIGHT_WORKERS`, `USER_MAX_JOBS`, `USER_MAX_QUEUED` |
| ฐานข้อมูล | `DB_BACKEND` (files/supabase), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` |
| บัญชี | `AUTH_ENABLED`, `BILLING_ENABLED`, `GOOGLE_CLIENT_ID`, `ADMIN_EMAILS`, `PAYMENT_PROVIDER` |
| นักพากย์ | `ACTOR_RATE_SATANG_PER_MIN`, `ACTOR_WHT_PERCENT`, `ACTOR_WHT_MIN_SATANG`, `ACTOR_INCOME_TYPE` |
| PDPA | `PDPA_CONTROLLER_NAME`, `PDPA_CONTROLLER_CONTACT` |
| สำรองและอีเมล | `BACKUP_DIR`/`BACKUP_PATH`, `BACKUP_HOURS`, `BACKUP_KEEP`, `SMTP_*`, `MAIL_FROM`, `WEB_URL`, `NOTIFY_MIN_SECONDS` |
| โมเดล | `SEPARATOR`, `SEPARATOR_MODEL`, `DENOISE_MODEL`, `DIARIZATION_MODEL`, `WHISPER_MODEL`, `WHISPER_COMPUTE_TYPE`, `HF_TOKEN` |
| แปล | `TYPHOON_API_KEY`, `TYPHOON_BASE_URL`, `TYPHOON_MODEL`, `TYPHOON_TEMPERATURE`, `TRANSLATE_BATCH_SIZE`, `TRANSLATE_EN_LOCAL`, `STORY_ANALYSIS` |
| ความยาวบท | `THAI_CHARS_PER_SEC`, `THAI_SYLLABLES_PER_SEC`, `EN_WORDS_PER_SEC`, `MAX_LINE_SEC`, `MAX_SPEEDUP`, `MAX_SLOWDOWN`, `FIT_*` |
| ผู้พูด | `VOICE_MATCH`, `VOICE_MIN_SIM`, `DIAR_REFINE`, `DIAR_EXCLUSIVE`, `DIAR_MERGE_SIM`, `TURN_SPLIT`, `OVERLAP_RECOVER` |
| เสียงพากย์ | `REF_MIN_SEC`, `REF_MAX_SEC`, `REF_MIN_QUALITY`, `PAUSE_MATCH`, `MIN_PAUSE_SEC`, `BREATH_KEEP`, `EMOTION_MATCH`, `LOUDNESS_MATCH`, `PROSODY_MATCH`, `ROOM_REVERB`, `DUB_CHECK`, `DUB_CHECK_MIN`, `DUB_CHECK_RETRIES` |
| ผสมเสียง | `VOICE_GAIN`, `BGM_GAIN` (ปรับจากหน้าตั้งค่าได้) |

ค่าลับ (คีย์ API, service_role key, รหัสผ่านฐานข้อมูล) อยู่ใน `.env` และ `web/.env*.local` เท่านั้น ห้าม commit

---

## 7. การพัฒนาและ deploy

| เรื่อง | วิธี |
|---|---|
| สาขา | ทำงานบน `modal-gpu-worker` แล้ว fast-forward เข้า `main` push ทั้งสองสาขา |
| หน้าเว็บ | push `main` แล้ว Vercel deploy เอง (Root Directory = `web`, ตั้ง `BACKEND_URL`, `API_KEY`) |
| API | `docker compose up -d --build --no-deps api` รีสตาร์ตเฉพาะ `api` |
| tunnel | **ห้ามรีสตาร์ต** container `tunnel` ลิงก์ trycloudflare จะเปลี่ยน ต้องแก้ `BACKEND_URL` บน Vercel |
| Modal | `modal deploy modal_app.py` เมื่อแก้โค้ดใน `app/pipeline/` |
| ทดสอบ API | `pytest tests` (pauses, quality, timeline) |
| ตรวจหน้าเว็บ | `npx tsc --noEmit` ใน `web/` และตรวจว่าข้อความไทยมีคำแปลอังกฤษใน `i18n-en.ts` ครบ |
| โหมดทดสอบ | `MOCK_PIPELINE=1` รันครบทุกขั้นโดยไม่โหลดโมเดล |

เครื่องพัฒนา: ไดรฟ์ C เต็ม Docker และแคชโมเดลอยู่ไดรฟ์ E ไฟล์ชั่วคราวของ Node ใช้ `E:\tmp-next`

---

## 8. งานค้างและแผนต่อไป

**ต้องทำก่อนใช้ฟีเจอร์ที่ push ไปแล้ว**
- [ ] รัน `supabase/migrations/20261104010000_quality.sql` ใน Supabase SQL Editor
- [ ] deploy Modal ให้การตรวจเสียงที่พากย์ทำงาน แล้วทดสอบกับสำเนางานจริงเพื่อปรับ `DUB_CHECK_MIN`

**ย้ายข้อมูลเข้า Supabase**
- [ ] รีเซ็ตรหัสผ่านฐานข้อมูล ตั้ง `SUPABASE_DB_URL` แบบ pooler
- [ ] ย้าย accounts.db (ผู้ใช้ เครดิต ความยินยอม นักพากย์) แล้วงานและโปรเจกต์ ลบทางสำรอง SQLite

**ปรับความแม่น**
- [ ] ตรวจบทอัตโนมัติหลังแปล
- [ ] ใช้โมเดลที่เก่งกว่าตอนวิเคราะห์เรื่องและตรวจบท
- [ ] รวมประโยคที่ถูกตัดกลางคัน
- [ ] แยกผู้พูดละเอียดขึ้น (มีร่าง `app/pipeline/align.py` จัดเวลาคำด้วย wav2vec2 ยังไม่ได้ตัดสินใจว่าจะใช้)
- [ ] ลดเวลาเปิดเครื่องของ Modal (หัวข้อ 5)

**ก่อนเปิดให้ลูกค้าจริง**
- [ ] ตั้ง `PDPA_CONTROLLER_NAME` / `PDPA_CONTROLLER_CONTACT`
- [ ] ให้ทนายตรวจข้อกำหนด นโยบาย หนังสือยินยอมนักพากย์ และให้นักบัญชีตรวจเรื่องหักภาษีค่าตอบแทน
- [ ] ตั้ง `BACKUP_PATH` เป็นโฟลเดอร์ที่ซิงก์ขึ้นคลาวด์
- [ ] ตั้ง SMTP สำหรับอีเมลแจ้งเตือน
- [ ] ต่อระบบรับชำระเงิน
- [ ] อัปเดต README ให้ตรงกับระบบปัจจุบัน

---

## 9. ลิขสิทธิ์และสิทธิในเสียง
ระบบโคลนเสียงของนักแสดงต้นฉบับ การเผยแพร่คลิปที่พากย์ต้องได้รับอนุญาตจากเจ้าของคลิปและเจ้าของเสียง
การโหลดคลิปจากแพลตฟอร์มด้วยโปรแกรมภายนอกอาจขัดเงื่อนไขของแพลตฟอร์ม
เสียงนักพากย์ในคลังใช้ได้ตามหนังสือยินยอมที่นักพากย์ยอมรับเท่านั้น
