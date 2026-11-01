-- ฐานข้อมูลของ Dubbing Studio บน Supabase (Postgres)
-- แทนที่ไฟล์ใน data/: jobs/<id>/job.json, transcript.json, words.json, turns.json, gpu_analysis.json,
-- speaker_voices.json, voices/<id>/voice.json, embedding.npy, settings.json และ accounts.db (SQLite)
-- Supabase เก็บแค่ข้อมูล ไฟล์เสียง วิดีโอ และรูป ยังอยู่บนเครื่องที่รัน API (DATA_DIR) ตามโครงเดิม:
--   data/jobs/<job_id>/...  (input, vocals, bgm, stems/, tts/, output.mp4, ...)
--   data/voices/<voice_id>/... (original.*, ref.wav, image.*, moods/<mood>/...)
-- ตารางเก็บเฉพาะชื่อไฟล์ที่เดาจาก id ไม่ได้ (นามสกุลต่างกันไปตามที่อัปโหลด) หน้าเว็บโหลดไฟล์ผ่าน API เหมือนเดิม
--
-- ผู้ใช้ใช้ Supabase Auth (auth.users) แทนตาราง users/sessions เดิม รหัสผ่าน โทเคน และอีเมลยืนยันให้ Supabase จัดการ
-- API (FastAPI) ใช้ service_role key ซึ่งข้าม RLS ส่วน RLS มีไว้สำหรับหน้าเว็บที่อ่านข้อมูลตรงด้วย anon key + JWT ของผู้ใช้
-- เงินเก็บเป็นสตางค์ (bigint) เวลาในคลิปเก็บเป็นวินาที (double precision)

create extension if not exists vector;   -- ลายเสียง 256 มิติ (pyannote/wespeaker) ใช้หาเสียงในคลังที่ใกล้ตัวละคร

-- ---------------------------------------------------------------- ชนิดข้อมูล
create type job_status   as enum ('queued', 'running', 'awaiting_review', 'done', 'failed', 'cancelled');
create type job_phase    as enum ('analyze', 'synthesize', 'render', 'translate');
create type target_lang  as enum ('th', 'en');
create type gender       as enum ('', 'male', 'female');
create type voice_status as enum ('processing', 'ready', 'failed');
create type mood         as enum ('angry', 'sad', 'happy', 'whisper', 'scared');
create type ledger_kind  as enum ('topup', 'subscribe', 'charge', 'refund', 'adjust');
create type topup_status as enum ('pending', 'paid', 'failed', 'expired');

create or replace function touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end $$;

-- ---------------------------------------------------------------- ผู้ใช้และกระเป๋าเงิน
-- โปรไฟล์ต่อจาก auth.users (สร้างอัตโนมัติตอนสมัคร) ยอดเงินเก็บที่นี่ ประวัติทุกรายการอยู่ใน ledger
create table profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  display_name  text not null default '' check (char_length(display_name) <= 80),
  is_admin      boolean not null default false,
  balance       bigint not null default 0 check (balance >= 0),   -- สตางค์
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create trigger profiles_touch before update on profiles for each row execute function touch_updated_at();

create or replace function handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'name', split_part(new.email, '@', 1)));
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users for each row execute function handle_new_user();

create or replace function is_admin() returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select is_admin from profiles where id = auth.uid()), false)
$$;

-- แพ็กเกจรายเดือน (แก้ราคาได้จากตารางนี้ ไม่ต้องแก้โค้ด)
create table plans (
  id        text primary key,
  name      text not null,
  price     bigint not null check (price > 0),     -- สตางค์
  minutes   integer not null check (minutes > 0),
  days      integer not null default 30,
  active    boolean not null default true,
  sort      integer not null default 0
);
insert into plans (id, name, price, minutes, sort) values
  ('starter', 'เริ่มต้น', 29900, 30, 1),
  ('pro', 'มือโปร', 99000, 120, 2),
  ('studio', 'สตูดิโอ', 299000, 400, 3);

-- แพ็กเกจที่ซื้อ (เก็บประวัติทุกครั้ง แพ็กเกจที่ใช้อยู่ = แถวล่าสุดที่ยังไม่หมดอายุ)
create table subscriptions (
  id            bigint generated always as identity primary key,
  user_id       uuid not null references profiles (id) on delete cascade,
  plan_id       text not null references plans (id),
  minutes_left  integer not null check (minutes_left >= 0),
  started_at    timestamptz not null default now(),
  expires_at    timestamptz not null
);
create index subscriptions_user on subscriptions (user_id, expires_at desc);

-- เติมเงิน (รอชำระ → ชำระแล้ว) provider_ref = เลขอ้างอิงของช่องทางชำระเงิน
create table topups (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references profiles (id) on delete cascade,
  amount        bigint not null check (amount between 10000 and 5000000),   -- 100–50,000 บาท
  provider      text not null,
  provider_ref  text,
  status        topup_status not null default 'pending',
  created_at    timestamptz not null default now(),
  paid_at       timestamptz
);
create index topups_user on topups (user_id, created_at desc);
create unique index topups_provider_ref on topups (provider, provider_ref) where provider_ref is not null;

-- ทุกการเคลื่อนไหวของเงินและนาที (บวก = เข้า ลบ = ออก) ตัดนาทีของงานได้ครั้งเดียวต่องาน
create table ledger (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references profiles (id) on delete cascade,
  kind        ledger_kind not null,
  amount      bigint not null default 0,     -- สตางค์
  minutes     integer not null default 0,
  job_id      text,                          -- charge/refund ของงานไหน (ไม่ผูก FK เพราะลบงานแล้วประวัติต้องอยู่)
  topup_id    uuid references topups (id),
  note        text not null default '',
  created_by  uuid references profiles (id), -- ผู้ดูแลที่ปรับยอด (kind = adjust)
  created_at  timestamptz not null default now()
);
create index ledger_user on ledger (user_id, id desc);
create unique index ledger_charge_once on ledger (job_id) where kind = 'charge';
create unique index ledger_refund_once on ledger (job_id) where kind = 'refund';

-- ---------------------------------------------------------------- ค่าตั้งระบบ (หน้าตั้งค่า แถวเดียว)
create table app_settings (
  id          smallint primary key default 1 check (id = 1),
  data        jsonb not null default '{}'::jsonb,   -- RuntimeSettings ทั้งก้อน แอปตรวจรูปแบบเอง
  updated_at  timestamptz not null default now(),
  updated_by  uuid references profiles (id)
);
insert into app_settings (id) values (1);
create trigger app_settings_touch before update on app_settings for each row execute function touch_updated_at();

-- ---------------------------------------------------------------- คลังเสียง
create table voices (
  id            text primary key,                 -- 12 ตัวอักษรฐาน 16 เหมือนเดิม (ลิงก์และ voice_map เดิมใช้ต่อได้)
  owner_id      uuid references profiles (id) on delete set null,   -- null = คลังกลางของระบบ
  is_public     boolean not null default true,    -- ผู้ใช้ทุกคนเลือกใช้ได้
  name          text not null check (char_length(name) between 1 and 80),
  gender        gender not null default '',
  tone          text not null default '' check (char_length(tone) <= 80),
  description   text not null default '' check (char_length(description) <= 1000),
  categories    text[] not null default '{}' check (cardinality(categories) <= 10),
  image         text not null default '',          -- ชื่อไฟล์รูปใน data/voices/<id>/ (image.jpg ฯลฯ) ว่าง = ไม่มีรูป
  status        voice_status not null default 'processing',
  stage         text not null default 'queued',
  error         text,
  source_name   text not null default '',          -- ชื่อไฟล์ที่ผู้ใช้อัปโหลด (ไฟล์จริงคือ data/voices/<id>/original.<ext>)
  ref_text      text not null default '',          -- ข้อความที่พูดในเสียงตัวอย่าง (F5-TTS ต้องตรงทุกคำ)
  ref_duration  real,
  pitch_hz      real,
  quality       real,                              -- ความสะอาด (ประมาณ PESQ 1–4.5)
  analysis      jsonb,                             -- ผลประเมินทั้งไฟล์ (VoiceAnalysis)
  embedding     vector(256),                       -- ลายเสียงของเสียงหลัก
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index voices_categories on voices using gin (categories);
create index voices_ready on voices (status) where status = 'ready';
create trigger voices_touch before update on voices for each row execute function touch_updated_at();

-- เสียงตัวอย่างอารมณ์อื่นของเสียงเดียวกัน
create table voice_moods (
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
create trigger voice_moods_touch before update on voice_moods for each row execute function touch_updated_at();

-- ---------------------------------------------------------------- งานพากย์
create table jobs (
  id                text primary key,              -- 12 ตัวอักษรฐาน 16 เหมือนเดิม
  owner_id          uuid references profiles (id) on delete cascade,   -- null = สร้างตอนระบบบัญชีปิด
  status            job_status not null default 'queued',
  stage             text not null default 'queued',
  progress          real not null default 0 check (progress between 0 and 1),
  phase             job_phase not null default 'analyze',
  filename          text not null,
  source_url        text,
  input_name        text,                          -- ไฟล์คลิปใน data/jobs/<id>/ (input.mp4 ฯลฯ) null = ยังดาวน์โหลดจากลิงก์ไม่เสร็จ
  source_lang       text,                          -- null = ตรวจภาษาอัตโนมัติ
  detected_lang     text,
  target_lang       target_lang not null default 'th',
  num_speakers      smallint check (num_speakers between 1 and 20),
  review            boolean not null default false,
  genre             text not null default '' check (char_length(genre) <= 80),
  glossary          text not null default '' check (char_length(glossary) <= 2000),
  burn_subs         boolean not null default false,
  sub_style         jsonb,                          -- SubtitleStyle (null = ค่าเริ่มต้นของระบบ)
  duration          real,                           -- ความยาวคลิป (วินาที)
  synth_stats       jsonb,                          -- {redubbed, reused}
  error             text,
  -- คิว: worker หลายเครื่องแย่งงานด้วย claim_next_job() ไม่ซ้ำกันเพราะ FOR UPDATE SKIP LOCKED
  queued_at         timestamptz,
  started_at        timestamptz,
  finished_at       timestamptz,
  worker_id         text,                           -- เครื่องที่รันอยู่
  lease_until       timestamptz,                    -- worker ต่ออายุเป็นระยะ หมดอายุ = เครื่องตาย ปล่อยงานคืนคิว
  cancel_requested  boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index jobs_owner on jobs (owner_id, created_at desc);
create index jobs_queue on jobs (queued_at) where status = 'queued';
create index jobs_running on jobs (lease_until) where status = 'running';
create trigger jobs_touch before update on jobs for each row execute function touch_updated_at();

-- ตัวละครของงาน (แทน speakers, voice_map, speaker_names ใน job.json)
create table job_speakers (
  job_id        text not null references jobs (id) on delete cascade,
  speaker       text not null,                    -- speaker_01, speaker_02, ...
  display_name  text not null default '' check (char_length(display_name) <= 40),
  voice_id      text references voices (id) on delete set null,   -- null = เลียนเสียงนักแสดงต้นฉบับ
  gender_guess  gender,                            -- ที่ระบบเดาจากระดับเสียง
  pitch_hz      real,
  embedding     vector(256),                       -- ลายเสียงตัวละคร (แทน speaker_voices.json)
  sort          smallint not null default 0,
  primary key (job_id, speaker)
);

-- บทพากย์ทีละประโยค (แทน transcript.json) และค่าที่วัดตอนวิเคราะห์ (แทน gpu_analysis.json lines)
create table utterances (
  job_id        text not null references jobs (id) on delete cascade,
  line_id       integer not null,                  -- id เดิมในบท (ใช้ตั้งชื่อไฟล์เสียงพากย์)
  speaker       text not null,
  start_sec     double precision not null check (start_sec >= 0),
  end_sec       double precision not null,
  source_text   text not null default '',
  target_text   text not null default '',
  take          smallint not null default 0 check (take between 0 and 99),
  mood          mood,                              -- null = เสียงปกติ
  tts_key       text,                              -- คีย์แคชเสียงพากย์ล่าสุด (บทหรือเสียงเปลี่ยน = พากย์ใหม่)
  quality       real,                              -- ความสะอาดของเสียงต้นฉบับท่อนนี้
  pitch_st      real,                              -- ระดับเสียง (เซมิโทนเทียบ 1 Hz)
  embedding     vector(256),                       -- ลายเสียงท่อนนี้
  primary key (job_id, line_id),
  foreign key (job_id, speaker) references job_speakers (job_id, speaker) on update cascade,
  check (end_sec > start_sec)
);
create index utterances_time on utterances (job_id, start_sec);

-- ผลวิเคราะห์ก้อนใหญ่ที่อ่านทั้งก้อนครั้งเดียว (แทน words.json, turns.json, gpu_analysis.json speech)
create table job_analysis (
  job_id      text primary key references jobs (id) on delete cascade,
  words       jsonb not null default '[]'::jsonb,   -- [{start, end, text, segment}] เวลาแต่ละคำ
  turns       jsonb not null default '[]'::jsonb,   -- [{start, end, speaker}] ช่วงพูดของแต่ละคน
  speech      jsonb not null default '[]'::jsonb,   -- ช่วงที่มีเสียงพูดแต่ถอดไม่ได้
  updated_at  timestamptz not null default now()
);
create trigger job_analysis_touch before update on job_analysis for each row execute function touch_updated_at();

-- ---------------------------------------------------------------- ฟังก์ชันที่ต้องทำในธุรกรรมเดียว
-- หยิบงานถัดไปของสายงาน (heavy/light) ให้ worker แบบวนตามผู้ใช้ และไม่เกิน p_user_cap งานหนักต่อคน
-- คืนแถวงานที่ถูกจองแล้ว (status = running) หรือไม่มีแถวถ้าไม่มีงานที่หยิบได้
create or replace function claim_next_job(p_worker text, p_light boolean, p_user_cap integer, p_lease interval default '2 minutes')
returns setof jobs language plpgsql security definer set search_path = public as $$
declare picked text;
begin
  -- งานที่ worker ตายกลางทาง (lease หมด) กลับเข้าคิว
  update jobs set status = 'queued', worker_id = null, lease_until = null, stage = 'queued'
  where status = 'running' and lease_until < now();

  with busy as (
    select owner_id, count(*) n from jobs
    where status = 'running' and phase in ('analyze', 'synthesize') group by owner_id
  ), ranked as (
    select j.id, coalesce(b.n, 0) owner_busy,
           row_number() over (partition by j.owner_id order by j.queued_at) owner_rank, j.queued_at
    from jobs j left join busy b on b.owner_id is not distinct from j.owner_id
    where j.status = 'queued' and not j.cancel_requested
      and ((j.phase in ('render', 'translate')) = p_light)
      and (p_light or p_user_cap <= 0 or j.owner_id is null or coalesce(b.n, 0) < p_user_cap)
  )
  select r.id into picked from ranked r
  order by r.owner_busy, r.owner_rank, r.queued_at
  limit 1;
  if picked is null then return; end if;

  return query
  update jobs set status = 'running', worker_id = p_worker, lease_until = now() + p_lease,
                  started_at = now(), stage = 'starting'
  where id = (select id from jobs where id = picked and status = 'queued' for update skip locked)
  returning *;
end $$;

-- ตัดนาทีของงาน: ใช้นาทีในแพ็กเกจก่อน ที่เหลือหักเงิน (สตางค์ต่อนาที) ตัดครั้งเดียวต่องาน ไม่พอ = error
-- ledger.minutes = นาทีที่หักจากแพ็กเกจ (ติดลบ) ledger.amount = เงินที่หัก (ติดลบ) คืนได้ตรงตามที่หักไป
create or replace function charge_job(p_user uuid, p_job text, p_seconds double precision, p_per_minute bigint)
returns void language plpgsql security definer set search_path = public as $$
declare need int := greatest(1, ceil(p_seconds / 60.0)::int); sub subscriptions; from_plan int := 0; cost bigint;
begin
  if exists (select 1 from ledger where job_id = p_job and kind = 'charge') then return; end if;
  select * into sub from subscriptions where user_id = p_user and expires_at > now() and minutes_left > 0
    order by expires_at desc limit 1 for update;
  if found then from_plan := least(need, sub.minutes_left); end if;
  cost := (need - from_plan) * p_per_minute;
  update profiles set balance = balance - cost where id = p_user and balance >= cost;
  if not found then raise exception 'นาทีพากย์หรือเงินไม่พอ ต้องใช้ % นาที', need using errcode = 'P0402'; end if;
  if from_plan > 0 then update subscriptions set minutes_left = minutes_left - from_plan where id = sub.id; end if;
  insert into ledger (user_id, kind, amount, minutes, job_id, note)
  values (p_user, 'charge', -cost, -from_plan, p_job, format('พากย์คลิป %s นาที', need));
end $$;

-- คืนเงินและนาทีแพ็กเกจของงานที่วิเคราะห์ไม่สำเร็จ ตามที่ตัดไปจริง (คืนครั้งเดียว นาทีคืนเข้าแพ็กเกจที่ยังใช้อยู่)
create or replace function refund_job(p_job text) returns void language plpgsql security definer set search_path = public as $$
declare c ledger;
begin
  select * into c from ledger where job_id = p_job and kind = 'charge';
  if not found or exists (select 1 from ledger where job_id = p_job and kind = 'refund') then return; end if;
  update profiles set balance = balance - c.amount where id = c.user_id;
  if c.minutes < 0 then
    update subscriptions set minutes_left = minutes_left - c.minutes
    where id = (select id from subscriptions where user_id = c.user_id and expires_at > now()
                order by expires_at desc limit 1);
  end if;
  insert into ledger (user_id, kind, amount, minutes, job_id, note)
  values (c.user_id, 'refund', -c.amount, -c.minutes, p_job, 'คืนนาที งานวิเคราะห์ไม่สำเร็จ');
end $$;

-- ---------------------------------------------------------------- สิทธิ์ (RLS) สำหรับหน้าเว็บที่อ่านตรง
alter table profiles      enable row level security;
alter table plans         enable row level security;
alter table subscriptions enable row level security;
alter table topups        enable row level security;
alter table ledger        enable row level security;
alter table app_settings  enable row level security;
alter table voices        enable row level security;
alter table voice_moods   enable row level security;
alter table jobs          enable row level security;
alter table job_speakers  enable row level security;
alter table utterances    enable row level security;
alter table job_analysis  enable row level security;

-- ข้อมูลของตัวเองอ่านได้ ผู้ดูแลอ่านได้ทั้งหมด การเขียนที่เกี่ยวกับเงินทำผ่าน API (service_role) เท่านั้น
create policy "own profile"   on profiles      for select using (id = auth.uid() or is_admin());
create policy "rename self"   on profiles      for update using (id = auth.uid()) with check (id = auth.uid());
create policy "plans public"  on plans         for select using (active or is_admin());
create policy "own subs"      on subscriptions for select using (user_id = auth.uid() or is_admin());
create policy "own topups"    on topups        for select using (user_id = auth.uid() or is_admin());
create policy "own ledger"    on ledger        for select using (user_id = auth.uid() or is_admin());
create policy "settings read" on app_settings  for select using (auth.role() = 'authenticated');
create policy "settings admin" on app_settings for update using (is_admin()) with check (is_admin());

-- คลังเสียง: ทุกคนที่เข้าสู่ระบบใช้เสียงสาธารณะได้ แก้ได้เฉพาะเจ้าของหรือผู้ดูแล
create policy "voices read"   on voices      for select using (is_public or owner_id = auth.uid() or is_admin());
create policy "voices write"  on voices      for all using (owner_id = auth.uid() or is_admin())
                                             with check (owner_id = auth.uid() or is_admin());
create policy "moods read"    on voice_moods for select using (exists (select 1 from voices v where v.id = voice_id
                                             and (v.is_public or v.owner_id = auth.uid() or is_admin())));
create policy "moods write"   on voice_moods for all using (exists (select 1 from voices v where v.id = voice_id
                                             and (v.owner_id = auth.uid() or is_admin())));

-- งาน: เห็นและแก้ได้เฉพาะงานของตัวเอง (สถานะงานเปลี่ยนโดย worker ผ่าน service_role)
create policy "jobs own"      on jobs for select using (owner_id = auth.uid() or is_admin());
create policy "jobs edit"     on jobs for update using (owner_id = auth.uid())
                              with check (owner_id = auth.uid());
create policy "speakers own"  on job_speakers for all using (exists (select 1 from jobs j where j.id = job_id
                              and (j.owner_id = auth.uid() or is_admin())));
create policy "lines own"     on utterances   for all using (exists (select 1 from jobs j where j.id = job_id
                              and (j.owner_id = auth.uid() or is_admin())));
create policy "analysis own"  on job_analysis for select using (exists (select 1 from jobs j where j.id = job_id
                              and (j.owner_id = auth.uid() or is_admin())));

-- Supabase ให้สิทธิ์ anon/authenticated แก้ทุกคอลัมน์โดยค่าเริ่มต้น RLS กันแค่ "แถวไหน" ไม่กัน "คอลัมน์ไหน"
-- จึงตัดสิทธิ์เขียนออกให้หมด แล้วเปิดเฉพาะคอลัมน์ที่ผู้ใช้แก้เองได้ ยอดเงิน สถานะงาน และเจ้าของ แก้ได้ผ่าน API เท่านั้น
revoke insert, update, delete on profiles, plans, subscriptions, topups, ledger, app_settings,
  jobs, job_analysis from anon, authenticated;
revoke all on voices, voice_moods, job_speakers, utterances from anon;
grant update (display_name) on profiles to authenticated;
grant update (genre, glossary, burn_subs, sub_style, review) on jobs to authenticated;
grant update (data) on app_settings to authenticated;   -- RLS ยังจำกัดให้เฉพาะผู้ดูแล

-- ความคืบหน้างานแบบเรียลไทม์ (แทนการถามทุก 2 วินาที)
alter publication supabase_realtime add table jobs;
