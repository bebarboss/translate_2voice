-- คิวอีเมลและการตั้งค่าแจ้งเตือนรายข้อ
-- init นี้รันเมื่อ volume ว่าง ฐานที่มีข้อมูลแล้วให้รัน
-- backend/supabase/migrations/20261119120000_email_outbox.sql

alter table studio.users add column if not exists notify_prefs text not null default '{}';
alter table studio.users add column if not exists credits_low_armed integer not null default 1;

create table if not exists studio.notification_outbox (
  id text primary key,
  user_id text not null default '',
  to_email text not null,
  kind text not null,
  subject text not null,
  text_body text not null,
  html_body text not null,
  headers text not null default '{}',
  status text not null default 'pending'
    check (status in ('pending', 'sending', 'sent', 'dead')),
  attempts integer not null default 0,
  next_attempt_at double precision not null,
  last_error text not null default '',
  created_at double precision not null,
  sent_at double precision,
  dedupe_key text not null
);
create unique index if not exists notification_outbox_dedupe on studio.notification_outbox (dedupe_key);
create index if not exists notification_outbox_due on studio.notification_outbox (status, next_attempt_at);
