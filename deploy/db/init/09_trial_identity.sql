-- ผูกบัญชีกับ Google sub และจำการรับแพ็กทดลองแบบไม่เก็บข้อมูลส่วนตัว
-- google_sub อยู่บน users เฉพาะตอนบัญชียังเปิด ปิดบัญชีแล้วลบค่านี้
-- trial_claims เก็บเฉพาะ HMAC ของอีเมลที่ปรับรูปแล้ว และของ sub (ไม่มีอีเมลหรือ sub ดิบ)
-- init นี้รันเมื่อ volume ว่าง ฐานที่มีข้อมูลแล้วให้รัน supabase/migrations/20261112000000_trial_identity.sql

alter table studio.users add column if not exists google_sub text;

create unique index if not exists users_google_sub
  on studio.users (google_sub)
  where google_sub is not null;

create table if not exists studio.trial_claims (
  id_hash text primary key,
  kind text not null,
  created_at double precision not null
);
