-- รายงานปัญหา / ข้อเสนอแนะจากผู้ใช้
create table if not exists studio.feedback (
  id text primary key,
  user_id text,
  email text not null default '',
  name text not null default '',
  category text not null,
  subject text not null,
  body text not null,
  job_id text not null default '',
  status text not null default 'open',
  admin_note text not null default '',
  created_at double precision not null,
  resolved_at double precision
);

create index if not exists feedback_status_created on studio.feedback (status, created_at desc);
create index if not exists feedback_user on studio.feedback (user_id, created_at desc);
