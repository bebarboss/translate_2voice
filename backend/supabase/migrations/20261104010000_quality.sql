-- วัดคุณภาพจากที่ผู้ใช้แก้ (app/quality.py): เทียบบทที่ AI ทำกับบทที่ใช้พากย์จริง ทุกครั้งที่พากย์เสร็จ
-- job_id, owner, project_id เป็น id ตัวอักษรของ API (ยังไม่ผูก foreign key เพราะงานยังเก็บเป็นไฟล์)

-- งานละแถว: จำนวนบรรทัดที่แก้แต่ละแบบ ไม่มีเนื้อหาบท (ลบงานแล้วยังเก็บไว้ทำสถิติ ปิดบัญชีถึงลบ)
create table if not exists job_quality (
  job_id           text primary key,
  owner            text not null default '',
  project_id       text not null default '',
  source_lang      text not null default '',
  target_lang      text not null,
  genre            text not null default '',
  duration         double precision not null default 0,
  lines_ai         integer not null default 0,   -- บรรทัดที่ AI ทำ
  lines_final      integer not null default 0,   -- บรรทัดตอนพากย์
  text_edited      integer not null default 0,   -- แก้คำแปล
  speaker_changed  integer not null default 0,   -- เปลี่ยนผู้พูด
  retimed          integer not null default 0,   -- เลื่อนเวลา
  added            integer not null default 0,   -- บรรทัดที่เพิ่ม (ตัด คัดลอก)
  removed          integer not null default 0,   -- บรรทัดที่ลบหรือรวม
  edit_distance    double precision not null default 0,  -- ระยะแก้คำแปลเฉลี่ยต่อบรรทัด (0–1)
  translations     integer not null default 1,   -- จำนวนครั้งที่แปลทั้งเรื่อง
  synth_runs       integer not null default 1,   -- จำนวนครั้งที่พากย์
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists job_quality_updated on job_quality (updated_at desc);
create index if not exists job_quality_owner on job_quality (owner);

-- บรรทัดที่ผู้ใช้แก้: ใช้เป็นชุดทดสอบตอนปรับ prompt หรือเปลี่ยนโมเดล (ลบงานหรือปิดบัญชีแล้วลบด้วย)
create table if not exists quality_lines (
  id             bigint generated always as identity primary key,
  job_id         text not null,
  line_id        integer not null,
  owner          text not null default '',
  target_lang    text not null,
  source         text not null,
  ai_target      text not null,
  final_target   text not null,
  ai_speaker     text not null default '',
  final_speaker  text not null default '',
  kinds          text not null,                -- text,speaker,time
  updated_at     timestamptz not null default now(),
  unique (job_id, line_id)
);
create index if not exists quality_lines_updated on quality_lines (updated_at desc);
create index if not exists quality_lines_owner on quality_lines (owner);

-- อ่านเขียนผ่าน API (service_role) เท่านั้น
alter table job_quality enable row level security;
alter table quality_lines enable row level security;
