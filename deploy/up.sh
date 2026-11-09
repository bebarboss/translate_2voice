#!/usr/bin/env bash
# รันจากโฟลเดอร์รากโปรเจกต์:
#   bash deploy/up.sh          # API + Postgres + Caddy
#   bash deploy/up.sh --web    # + Frontend (Next.js)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ไม่มี .env ที่รากโปรเจกต์ — คัดลอกจาก .env.example แล้วใส่คีย์" >&2
  exit 1
fi
if [[ ! -f deploy/.env ]]; then
  echo "ไม่มี deploy/.env — คัดลอกจาก deploy/.env.vps.example" >&2
  exit 1
fi

PROFILE=()
WITH_WEB=0
if [[ "${1:-}" == "--web" ]] || [[ "${1:-}" == "--frontend" ]]; then
  WITH_WEB=1
  PROFILE=(--profile web)

  if ! grep -qE '^CADDYFILE=' deploy/.env; then
    echo "CADDYFILE=./Caddyfile.web" >> deploy/.env
  else
    # บังคับใช้ Caddyfile ที่เสิร์ฟทั้ง API + หน้าเว็บ
    if grep -qE '^CADDYFILE=' deploy/.env; then
      sed -i.bak -E 's|^CADDYFILE=.*|CADDYFILE=./Caddyfile.web|' deploy/.env
      rm -f deploy/.env.bak
    fi
  fi

  if ! grep -qE '^WEB_DOMAIN=.+' deploy/.env || grep -qE '^WEB_DOMAIN=\s*$' deploy/.env; then
    echo "ตั้ง WEB_DOMAIN ใน deploy/.env ก่อนใช้ --web (เช่น www.yourdomain.com)" >&2
    exit 1
  fi
  if ! grep -qE '^PUBLIC_BACKEND_URL=https?://' deploy/.env; then
    echo "ตั้ง PUBLIC_BACKEND_URL ใน deploy/.env (เช่น https://api.yourdomain.com)" >&2
    exit 1
  fi

  # ถ้ายังไม่มี WEB_API_KEY ให้คัดจาก API_KEY ใน .env ราก
  if ! grep -qE '^WEB_API_KEY=.+' deploy/.env; then
    api_key="$(grep -E '^API_KEY=' .env | head -1 | cut -d= -f2- || true)"
    if [[ -z "${api_key}" ]]; then
      echo "ตั้ง API_KEY ใน .env หรือ WEB_API_KEY ใน deploy/.env" >&2
      exit 1
    fi
    echo "WEB_API_KEY=${api_key}" >> deploy/.env
    echo "ใส่ WEB_API_KEY จาก API_KEY ใน .env แล้ว"
  fi
fi

mkdir -p data backups
docker compose -f deploy/docker-compose.yml --env-file deploy/.env "${PROFILE[@]}" up -d --build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env "${PROFILE[@]}" ps

api_domain="$(grep -E '^API_DOMAIN=' deploy/.env | head -1 | cut -d= -f2-)"
echo
echo "ตรวจ API: curl -sS https://${api_domain}/health"
if [[ "$WITH_WEB" -eq 1 ]]; then
  web_domain="$(grep -E '^WEB_DOMAIN=' deploy/.env | head -1 | cut -d= -f2-)"
  echo "Frontend:  https://${web_domain}"
  echo "อัปเดตเว็บครั้งถัดไป: bash deploy/up.sh --web"
fi
