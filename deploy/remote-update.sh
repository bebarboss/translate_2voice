#!/usr/bin/env bash
# อัปเดตโค้ดบน VPS แล้ว rebuild/restart (เรียกจาก GitHub Actions หรือมือ)
#   bash deploy/remote-update.sh
#   bash deploy/remote-update.sh --api-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"

# Check before git pull. A pull can overwrite the on-server deploy/Caddyfile.web
# (the live edge, edited in place) and the next lines start Compose writers.
if [[ "${CONFIRM_COMPOSE_WRITERS:-}" != "k3s-data-moved-back" ]]; then
  echo "Refusing to update or start Compose." >&2
  echo "k3s owns production data. Copy that data back and scale deploy/api to 0 first." >&2
  echo "See deploy/k8s/ROLLBACK.md." >&2
  echo "Then: CONFIRM_COMPOSE_WRITERS=k3s-data-moved-back bash deploy/remote-update.sh" >&2
  exit 1
fi

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
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile rollback --profile web ps
echo "==> done $(date -Is)"
