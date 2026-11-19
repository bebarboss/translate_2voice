-- แจ้งเตือนในแอป (inbox.py) Idempotent, additive only.
create table if not exists studio.notifications (
  id text primary key,
  user_id text not null,
  kind text not null,
  title text not null,
  body text not null default '',
  link text not null default '',
  job_id text not null default '',
  created_at double precision not null,
  read_at double precision
);
create index if not exists notifications_user_created on studio.notifications (user_id, created_at desc);
create index if not exists notifications_user_unread on studio.notifications (user_id) where read_at is null;
