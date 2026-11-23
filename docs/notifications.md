# อีเมลแจ้งเตือน

อีเมลเข้าคิวที่ตาราง `notification_outbox` แล้วเธรดพื้นหลังของ API ส่งออก ไม่ส่งตรงในคำขอ
ไม่ได้ตั้ง `SMTP_HOST` และ `MAIL_FROM` = ไม่เข้าคิว บันทึก log อย่างเดียว (ปิดที่อยู่อีเมล)

สวิตช์ทั้งกลุ่มอยู่ที่ `users.notify_email` (`PUT /auth/notify`)
ค่าที่เก็บรายข้ออยู่ที่ `users.notify_prefs` และไม่ถูกเขียนทับเมื่อเปิดหรือปิดสวิตช์ทั้งกลุ่ม
อีเมลจะออกเมื่อเป็นอีเมลนักพากย์/เงิน (ส่งเสมอ) หรือเมื่อสวิตช์ทั้งกลุ่มเปิดและข้อนั้นเปิดอยู่

## ตัวแปรสภาพแวดล้อม

| ตัวแปร | ที่อยู่ | ค่าว่างทำอะไร |
| --- | --- | --- |
| `SMTP_HOST` | `deploy/k8s/config.env` | ไม่เข้าคิว |
| `SMTP_PORT` | config.env ค่าเริ่ม 587 | พอร์ต 465 ใช้ TLS ตั้งแต่เชื่อม พอร์ตอื่นต้อง STARTTLS ก่อน AUTH |
| `SMTP_USER` | config.env | ว่าง = ไม่ล็อกอิน |
| `SMTP_PASSWORD` | Secret เท่านั้น (`secret.example.yaml` เป็น `""`) | ห้าม commit ค่าจริง |
| `MAIL_FROM` | config.env | ต้องคู่กับ `SMTP_HOST` ถึงจะส่ง ชื่อที่แสดงคือ พากย์ดี |
| `WEB_URL` | config.env | ว่าง = ไม่ใส่ปุ่มและลิงก์ท้ายเมล (ไม่มีลิงก์สัมพัทธ์) |
| `API_URL` | config.env เป็นค่าว่าง | ว่าง = ไม่ใส่หัว `List-Unsubscribe` |
| `UNSUBSCRIBE_SECRET` | Secret เท่านั้น เป็น `""` | ว่าง = ไม่ใส่ลิงก์ยกเลิกรับ |

โปรดักชันบน Resend (โดเมน `notify.cobie.online`, ภูมิภาค `us-east-1`) ใช้ค่านี้จนกว่าจะตรวจส่งผ่านแล้ว:

```
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
```

พอร์ต 465 จนกว่าจะยืนยันได้ รหัส `SMTP_PASSWORD` อยู่ใน Kubernetes Secret เท่านั้น ไม่ใส่ใน config หรือในไฟล์ที่ commit

## DNS ของ notify.cobie.online (Resend)

เรคคอร์ดนี้ทีมใส่ใน Cloudflare แล้ว ภูมิภาค Resend คือ `us-east-1`
ตารางนี้มีแค่ชื่อเรคคอร์ด ไม่มีค่าและไม่มีคีย์

| ชนิด | ชื่อ | ใช้ทำอะไร |
| --- | --- | --- |
| TXT | `resend._domainkey.notify` | DKIM |
| CNAME | `rsend.notify` | tracking / return-path ของ Resend (ใช้คู่กับ CNAME ด้านล่าง แทน MX และ SPF) |
| CNAME | `send.notify` | tracking / return-path ของ Resend (ใช้คู่กับ CNAME ด้านบน แทน MX และ SPF) |
| TXT | `_dmarc.notify` | DMARC นโยบาย `p=none` |

## การส่งซ้ำ

หยิบแถว `pending` ที่ถึงเวลาในธุรกรรมเดียว Postgres ใช้ `FOR UPDATE SKIP LOCKED` จึงไม่ส่งซ้ำข้าม pod
พอร์ตที่ไม่ใช่ 465 ทำ EHLO แล้วต้องได้ STARTTLS ก่อน EHLO อีกครั้งและ AUTH เซิร์ฟเวอร์ไม่ประกาศ STARTTLS = สถานะ `dead` ไม่ล็อกอินแบบเคลียร์เท็กซ์
SMTP 5xx และหัวข้อที่ฉีดอักขระควบคุม = `dead` ทันที
ส่งไม่สำเร็จครั้งที่ 1 ถึง 4 รอ 1 นาที, 5 นาที, 30 นาที, 2 ชั่วโมง ครั้งที่ 5 เป็น `dead`
ช่วง 6 ชั่วโมงอยู่ในตารางแต่ไม่ถูกตั้งคิว
แถวที่ค้างสถานะ `sending` นานเกิน 15 นาทีถูกดึงกลับ ถ้าครบ 5 ครั้งแล้วเป็น `dead`
log ปิดบังที่อยู่อีเมลเป็น `a***@domain` และไม่บันทึกรหัส SMTP

## ไมเกรชัน

รันบนฐานที่มีข้อมูลแล้ว:

- `backend/supabase/migrations/20261119120000_email_outbox.sql`

ฐานที่สร้างใหม่ได้ตารางจาก:

- `deploy/db/init/10_email_outbox.sql` (docker-compose หยิบไฟล์ใน `deploy/db/init/` ตามชื่อ, k3s ระบุใน `deploy/k8s/kustomization.yaml`)

คอลัมน์ที่เพิ่มบน `studio.users`: `notify_prefs` (JSON) และ `credits_low_armed`

รันไทม์ยังมี `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` ในโปรเซสสำหรับ SQLite และฐานที่ยังไม่ได้รันไฟล์ด้านบน

## API สำหรับหน้าเว็บ

สวิตช์ทั้งกลุ่ม (ล็อกอิน + `X-API-Key` เหมือนเส้นทางบัญชีอื่น) ไม่เขียนทับค่าที่เก็บรายข้อ

```
PUT /auth/notify
{"on": true}
```

ตอบข้อมูลผู้ใช้เดิม รวม `notify_email`

ค่าที่เก็บรายข้อ ค่าที่ยังไม่เคยตั้งเป็น `true` ไม่ถูกบังด้วยสวิตช์ทั้งกลุ่ม

```
GET /auth/notify-prefs
{
  "email": {
    "job_review": true,
    "job_done": true,
    "job_failed": true,
    "credits_low": true
  },
  "always_on": ["actor_applied", "actor_voice_submitted", "actor_reviewed", "voice_reviewed", "actor_paid"]
}

PUT /auth/notify-prefs
{"job_review": false}
```

ส่งมาเฉพาะข้อที่เปลี่ยน คีย์ที่ไม่รู้จักหรือค่าที่ไม่ใช่บูลีนได้ 422
`PUT` ตอบรูปแบบเดียวกับ `GET` และไม่เปลี่ยน `notify_email`

อีเมลที่ส่งจริงของข้อที่ตั้งค่าได้ = `notify_email` และ `email[category]`
`{"on": false}` ปิดอีเมลงานและเครดิตใกล้หมด แต่ค่าที่เก็บรายข้อยังอยู่
`{"on": true}` เปิดกลับตามค่าที่เก็บ ไม่บังคับให้ทุกข้อเป็นจริง
`always_on` ส่งเสมอ ไม่มีลิงก์ยกเลิกรับและไม่มีหัว `List-Unsubscribe`
กล่องข้อความในแอปของเครดิตใกล้หมดถูกเขียนแม้ปิดอีเมล

ยกเลิกการรับอีเมลหนึ่งข้อ ไม่ต้องล็อกอินและไม่ต้องใช้ `X-API-Key`
ตอบได้แค่ 200, 400 (โทเคนว่าง เสีย หรือถูกแก้ไข), 410 (หมดอายุ) และ 422 เฉพาะเมื่อเลี่ยงไม่ได้
ไม่มีทางตอบ 401 หรือ 403 แม้คำขอจะแนบคุกกี้ `dub_session` หรือ `X-User-Token` ที่ใช้ไม่ได้
เพราะ proxy ของหน้าเว็บลบคุกกี้ session เมื่อเห็น 401
access log ของ uvicorn แทนค่า `token` บนเส้นทางนี้ด้วย `token=REDACTED`
โทเคนเป็น HMAC-SHA256 อายุ 60 วัน ของ user id + หมวด + เวลาหมดอายุ ไม่มีอีเมลในโทเคนหรือใน URL

```
GET /notifications/unsubscribe?token=...
200 {"category": "job_done"}
```

อ่านอย่างเดียว ไม่เปลี่ยนการตั้งค่า เรียกซ้ำกี่ครั้งค่าเดิม

```
POST /notifications/unsubscribe?token=...
Content-Type: application/x-www-form-urlencoded

List-Unsubscribe=One-Click
```

หรือ

```
POST /notifications/unsubscribe
{"token": "..."}
```

```
200 {"ok": true, "category": "job_done"}
```

เรียกซ้ำได้ ข้อนั้นถูกตั้งเป็นปิด ข้ออื่นและสวิตช์ทั้งกลุ่มไม่เปลี่ยน
โทเคนเสีย ถูกแก้ไข หรือหมวดที่ไม่ใช่ข้อที่ตั้งค่าได้ = 400 `ลิงก์ยกเลิกไม่ถูกต้อง`
ลงชื่อถูกแต่หมดอายุ = 410 `ลิงก์ยกเลิกหมดอายุ`
ตัวตอบกลับมีแค่ฟิลด์ด้านบน ไม่มีอีเมลและไม่มี user id

ลิงก์ในท้ายเมลชี้ไปที่หน้าเว็บ `{WEB_URL}/unsubscribe?token=...` และ `{WEB_URL}/account?tab=prefs`
หัว `List-Unsubscribe` ชี้มาที่ `{API_URL}/notifications/unsubscribe?token=...` เมื่อตั้ง `API_URL` และมีโทเคน
