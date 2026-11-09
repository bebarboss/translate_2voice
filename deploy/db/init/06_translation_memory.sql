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
