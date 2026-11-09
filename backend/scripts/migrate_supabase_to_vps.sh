#!/usr/bin/env bash
# Dump จาก Supabase คลาวด์ แล้ว restore เข้า Postgres บน VPS (container ชื่อ db ใน compose)
#
# ใช้จากเครื่องที่มี pg_dump/pg_restore และเข้าถึงทั้ง SOURCE และ VPS ได้:
#   export SOURCE='postgresql://postgres....@aws-0-....pooler.supabase.com:5432/postgres'
#   bash scripts/migrate_supabase_to_vps.sh
#
# บน VPS ให้ compose รันอยู่แล้ว และตั้ง ROOT เป็นรากโปรเจกต์
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ROOT/deploy/.env")
WORKDIR="${WORKDIR:-/tmp/pakdee-db-migrate}"
mkdir -p "$WORKDIR"

if [[ -z "${SOURCE:-}" ]]; then
  echo "ตั้ง SOURCE เป็น connection string ของ Supabase (session/direct) ก่อน" >&2
  exit 2
fi

echo "==> dump studio"
pg_dump "$SOURCE" --format=custom --no-owner --no-acl --schema=studio -f "$WORKDIR/studio.dump"

echo "==> dump public app tables"
pg_dump "$SOURCE" --format=custom --no-owner --no-acl \
  -t app_settings -t voices -t voice_moods \
  -t translation_memory -t job_quality -t quality_lines \
  -t job_metric_scores -t job_metric_daily \
  -f "$WORKDIR/public_app.dump"

echo "==> copy into db container"
"${COMPOSE[@]}" cp "$WORKDIR/studio.dump" db:/tmp/studio.dump
"${COMPOSE[@]}" cp "$WORKDIR/public_app.dump" db:/tmp/public_app.dump

echo "==> restore (ใช้ --clean ถ้าต้องการทับตารางจาก init)"
RESTORE_FLAGS=(--no-owner --no-acl)
if [[ "${CLEAN:-0}" == "1" ]]; then
  RESTORE_FLAGS+=(--clean --if-exists)
fi
"${COMPOSE[@]}" exec -T db pg_restore -U "${POSTGRES_USER:-pakdee}" -d "${POSTGRES_DB:-pakdee}" \
  "${RESTORE_FLAGS[@]}" /tmp/studio.dump || true
"${COMPOSE[@]}" exec -T db pg_restore -U "${POSTGRES_USER:-pakdee}" -d "${POSTGRES_DB:-pakdee}" \
  "${RESTORE_FLAGS[@]}" /tmp/public_app.dump || true

echo "==> counts"
"${COMPOSE[@]}" exec -T db psql -U "${POSTGRES_USER:-pakdee}" -d "${POSTGRES_DB:-pakdee}" -c \
  "select 'users' as t, count(*) from studio.users union all select 'jobs', count(*) from studio.jobs union all select 'voices', count(*) from voices;"

echo "เสร็จแล้ว — ตรวจ login / รายการงานบน API"
