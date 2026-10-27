# Dubbing Studio — หน้าเว็บ

หน้าเว็บ Next.js สำหรับ Dubbing API

| หน้า | ทำอะไร |
|---|---|
| `/` | ส่งคลิป อัปโหลดไฟล์หรือวางลิงก์ เลือกภาษาพากย์ ตรวจบท ฝังซับ |
| `/jobs` | งานทั้งหมด กรองตามสถานะ ค้นหา ยกเลิก ลองใหม่ ลบ |
| `/jobs/[id]` | เปลี่ยนตามสถานะงาน: กำลังประมวลผล → ตรวจบท → ผลลัพธ์และดาวน์โหลด |
| `/settings` | การเชื่อมต่อ ข้อมูลเครื่อง ค่าเริ่มต้น เสียงพากย์ ซับเริ่มต้น |

## รัน

```bash
npm install
cp .env.example .env.local     # Windows: copy .env.example .env.local
npm run dev                    # เปิด http://localhost:3000
```

ใน `.env.local`
- `BACKEND_URL` ที่อยู่ของ API เช่น `http://localhost:8000` หรือลิงก์ trycloudflare จาก Colab
- `API_KEY` ใส่ถ้า API ตั้ง `API_KEY` ไว้ คีย์อยู่ฝั่งเซิร์ฟเวอร์ Next.js เท่านั้น ไม่หลุดไปที่เบราว์เซอร์

เบราว์เซอร์เรียกทุกอย่างผ่าน `/api/*` ของ Next.js (`app/api/[...path]/route.ts`) ซึ่งส่งต่อไปที่ API จึงไม่ติด CORS และสตรีมไฟล์วิดีโอได้

ขึ้นใช้งานจริง: `npm run build` แล้ว `npm start`

## โครงสร้าง

```
app/
  layout.tsx, globals.css       ธีม ฟอนต์ IBM Plex Sans Thai (ฝังในโปรเจกต์ ไม่ต้องโหลดจาก Google)
  page.tsx                      หน้าส่งคลิป
  jobs/page.tsx                 งานทั้งหมด
  jobs/[id]/page.tsx            เลือกมุมมองตามสถานะ และถามสถานะทุก 2 วินาทีระหว่างทำงาน
  settings/page.tsx             ตั้งค่า
  api/[...path]/route.ts        proxy ไปที่ API
components/
  ProcessingView.tsx            ความคืบหน้า ขั้นตอน ยกเลิก/ลองใหม่ ฟังเสียงแยกแต่ละตัวละคร
  ReviewView.tsx                วิดีโอ + ซับ เลเยอร์ตัวละคร บทที่เลื่อนตามคลิป แก้บทและตัวละคร
  ResultView.tsx                สลับเสียงพากย์/ต้นฉบับ ฝังซับ ส่งออก เลเยอร์เสียง
  SubtitleStylePanel.tsx        เลือกฟอนต์ สี ขนาด ตำแหน่ง พร้อมภาพตัวอย่าง
lib/
  api.ts                        ชนิดข้อมูลและฟังก์ชันเรียก API
  format.ts                     ชื่อภาษา ชื่อขั้นตอน รูปแบบเวลา สีตัวละคร
```
