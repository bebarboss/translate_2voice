-- รันครั้งแรกเมื่อ volume pg_data ว่าง (docker-entrypoint-initdb.d)
create extension if not exists vector;

create or replace function touch_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;
