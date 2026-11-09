#!/usr/bin/env bash
# อัปเดตโค้ดบน VPS แล้ว rebuild/restart (เรียกจาก GitHub Actions หรือมือ)
#   bash deploy/remote-update.sh
#   bash deploy/remote-update.sh --api-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"

echo "==> $(date -Is) git fetch/pull"
git fetch --prune origin
git checkout main
git pull --ff-only origin main

if [[ ! -f .env || ! -f deploy/.env ]]; then
  echo "ต้องมี .env และ deploy/.env บนเซิร์ฟเวอร์" >&2
  exit 1
fi

if [[ "$MODE" == "--api-only" ]]; then
  echo "==> rebuild api only"
  docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build api
else
  echo "==> up.sh --web"
  chmod +x deploy/up.sh
  bash deploy/up.sh --web
fi

echo "==> status"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile web ps
echo "==> done $(date -Is)"
