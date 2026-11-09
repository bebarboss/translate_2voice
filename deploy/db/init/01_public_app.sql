-- ตาราง public ที่แอปใช้ผ่าน app/supabase_db.py (ไม่พึ่ง auth.users / profiles)

do $$ begin
  create type gender as enum ('', 'male', 'female');
exception when duplicate_object then null;
end $$;

do $$ begin
  create type voice_status as enum ('processing', 'ready', 'failed');
exception when duplicate_object then null;
end $$;

do $$ begin
  create type mood as enum ('angry', 'sad', 'happy', 'whisper', 'scared');
exception when duplicate_object then null;
end $$;

create table if not exists app_settings (
  id          smallint primary key default 1 check (id = 1),
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);
insert into app_settings (id) values (1) on conflict (id) do nothing;
drop trigger if exists app_settings_touch on app_settings;
create trigger app_settings_touch before update on app_settings
  for each row execute function touch_updated_at();

create table if not exists voices (
  id            text primary key,
  owner_id      text,
  is_public     boolean not null default true,
  name          text not null check (char_length(name) between 1 and 80),
  gender        gender not null default '',
  tone          text not null default '' check (char_length(tone) <= 80),
  description   text not null default '' check (char_length(description) <= 1000),
  categories    text[] not null default '{}' check (cardinality(categories) <= 10),
  image         text not null default '',
  status        voice_status not null default 'processing',
  stage         text not null default 'queued',
  error         text,
  source_name   text not null default '',
  ref_text      text not null default '',
  ref_duration  real,
  pitch_hz      real,
  quality       real,
  analysis      jsonb,
  embedding     vector(256),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists voices_categories on voices using gin (categories);
create index if not exists voices_ready on voices (status) where status = 'ready';
drop trigger if exists voices_touch on voices;
create trigger voices_touch before update on voices
  for each row execute function touch_updated_at();

create table if not exists voice_moods (
  voice_id      text not null references voices (id) on delete cascade,
  mood          mood not null,
  status        voice_status not null default 'processing',
  stage         text not null default 'queued',
  error         text,
  source_name   text not null default '',
  ref_text      text not null default '',
  ref_duration  real,
  quality       real,
  analysis      jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (voice_id, mood)
);
drop trigger if exists voice_moods_touch on voice_moods;
create trigger voice_moods_touch before update on voice_moods
  for each row execute function touch_updated_at();
