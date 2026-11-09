# ชุดคลิปทอง (gold fixtures)

ใช้วัดว่าถอดเสียง + ซ่อมบท ยังจับเสียงตะโกน / เด็ก / ช่องว่างยากได้หลังปรับ config

## โครงหนึ่งเคส

```
fixtures/gold/<id>/
  meta.json         # id, tags, language, mode, description, job_ref?
  expected.json     # segments[{start,end,text}], min_recall
  utterances.json   # บทพังก่อนซ่อม (โหมด repair)
  words.json        # คำจาก Whisper (โหมด repair)
  turns.json        # ช่วงผู้พูด (ไม่บังคับ)
  got.json          # ผลถอดเสียงคงที่ (โหมด snapshot)
  audio.wav         # คลิปสั้นสำหรับรัน Whisper ด้วย --live
```

### `mode`

| ค่า | ความหมาย |
| --- | --- |
| `repair` | รัน `repair_transcript` จาก words/utterances แล้วเทียบ expected |
| `snapshot` | เทียบ `got.json` หรือ `job_ref` transcript กับ expected (ไม่รันโมเดล) |
| `asr` | ต้องมี `audio.wav` — ใช้กับ `scripts/score_gold.py --live` |

### แท็กที่แนะนำ

`shout` · `child` · `noisy` · `thai` · `ja`

## เพิ่มเคสใหม่

1. หาช่วงที่ระบบพลาดจาก Review หรือ `data/corrections/*.jsonl`
2. ตัดเสียงสั้น (1–3 วิ) หรือใส่ words/utterances จำลอง
3. เขียน `expected.json` ให้มีข้อความ/เวลาที่ถูก
4. รัน `python scripts/score_gold.py` ให้ผ่านก่อน merge

## คะแนน

```powershell
python scripts/score_gold.py
python scripts/score_gold.py --tag shout
python scripts/score_gold.py --live   # เรียก Whisper ถ้ามี (ช้า)
```
