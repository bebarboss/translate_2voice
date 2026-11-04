-- ความจำคำแปลของโปรเจกต์ (app/memory.py): คู่ "ต้นฉบับ → บทพากย์ที่ใช้จริง" ของแต่ละตอน
-- ใช้เป็นตัวอย่างให้ผู้แปลตอนแปลตอนถัดไปของเรื่องเดียวกัน (สรรพนาม คำเรียก สำนวนประจำตัวละคร)
-- edited = true: ผู้ใช้แก้จากที่ AI แปล (ใช้เป็นตัวอย่าง) / false: ใช้ตามที่ AI แปล (ใช้เฉพาะต้นฉบับตรงกันทุกคำ)
-- project_id, job_id, owner เป็น id ตัวอักษรของ API (ยังไม่ผูก foreign key เพราะโปรเจกต์และงานยังเก็บเป็นไฟล์)

create table if not exists translation_memory (
  id            bigint generated always as identity primary key,
  project_id    text not null,
  job_id        text not null,
  line_id       integer not null,
  owner         text not null default '',
  character_id  text not null default '',
  speaker_name  text not null default '',
  source        text not null,
  source_norm   text not null,
  target        text not null,
  target_lang   text not null,
  edited        boolean not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (job_id, line_id)
);
create index if not exists translation_memory_project on translation_memory (project_id, target_lang, updated_at desc);
create index if not exists translation_memory_owner on translation_memory (owner);

-- อ่านเขียนผ่าน API (service_role) เท่านั้น หน้าเว็บด้วย anon key อ่านไม่ได้
alter table translation_memory enable row level security;
