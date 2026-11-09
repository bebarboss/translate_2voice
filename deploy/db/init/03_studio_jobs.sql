-- งานและโปรเจกต์ใน schema studio (แทน data/jobs/*/job.json, transcript.json และ data/projects/*.json)
-- id เป็นตัวอักษร 12 ตัวเหมือนเดิม owner เป็น text id ของ studio.users (ไม่ผูก FK กับ public.profiles)
-- เก็บเอกสารทั้งก้อนใน jsonb ให้โครงตรงกับ Pydantic Job / Project / Utterance
-- ไฟล์มีเดียยังอยู่ที่ data/jobs/<id>/ (input, tts, output ฯลฯ)

create schema if not exists studio;

create table if not exists studio.jobs (
  id text primary key,
  owner text,
  status text not null,
  created_at double precision not null,
  updated_at double precision not null,
  doc jsonb not null
);
create index if not exists studio_jobs_owner on studio.jobs (owner);
create index if not exists studio_jobs_updated on studio.jobs (updated_at desc);

create table if not exists studio.transcripts (
  job_id text primary key references studio.jobs (id) on delete cascade,
  utterances jsonb not null default '[]'::jsonb,
  updated_at double precision not null
);

create table if not exists studio.projects (
  id text primary key,
  owner text,
  updated_at double precision not null,
  doc jsonb not null
);
create index if not exists studio_projects_owner on studio.projects (owner);
create index if not exists studio_projects_updated on studio.projects (updated_at desc);
