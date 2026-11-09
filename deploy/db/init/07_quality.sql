create table if not exists job_quality (
  job_id           text primary key,
  owner            text not null default '',
  project_id       text not null default '',
  source_lang      text not null default '',
  target_lang      text not null,
  genre            text not null default '',
  duration         double precision not null default 0,
  lines_ai         integer not null default 0,
  lines_final      integer not null default 0,
  text_edited      integer not null default 0,
  speaker_changed  integer not null default 0,
  retimed          integer not null default 0,
  added            integer not null default 0,
  removed          integer not null default 0,
  edit_distance    double precision not null default 0,
  translations     integer not null default 1,
  synth_runs       integer not null default 1,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists job_quality_updated on job_quality (updated_at desc);
create index if not exists job_quality_owner on job_quality (owner);

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
  kinds          text not null,
  updated_at     timestamptz not null default now(),
  unique (job_id, line_id)
);
create index if not exists quality_lines_updated on quality_lines (updated_at desc);
create index if not exists quality_lines_owner on quality_lines (owner);
