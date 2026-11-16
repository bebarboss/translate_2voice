-- Voice reports queue (actors.py). Idempotent, additive only.
-- Was missing on databases created before this table existed in init (init does not re-run).

create table if not exists studio.voice_reports (
  id text primary key,
  voice_id text not null,
  reporter_id text not null default '',
  reason text not null,
  detail text not null default '',
  status text not null default 'open',
  created_at double precision not null,
  resolved_at double precision,
  resolved_by text not null default '',
  admin_note text not null default ''
);
create index if not exists voice_reports_voice on studio.voice_reports (voice_id, status);
create index if not exists voice_reports_status on studio.voice_reports (status, created_at);
