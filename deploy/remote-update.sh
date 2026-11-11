#!/usr/bin/env bash
# อัปเดตโค้ดบน VPS แล้ว rebuild/restart (เรียกจาก GitHub Actions หรือมือ)
#   bash deploy/remote-update.sh
#   bash deploy/remote-update.sh --api-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"

# Check before git pull. The VPS checkout is a2d0f5d and deploy/Caddyfile.web
# was edited in place. A pull, reset, or checkout of that file replaces the
# live edge. The next lines also start Compose writers.
if [[ "${CONFIRM_COMPOSE_WRITERS:-}" != "k3s-data-moved-back" ]]; then
  echo "Refusing to update or start Compose." >&2
  echo "k3s owns production data. Copy that data back and scale deploy/api to 0 first." >&2
  echo "See deploy/k8s/ROLLBACK.md." >&2
  echo "Then: CONFIRM_COMPOSE_WRITERS=k3s-data-moved-back bash deploy/remote-update.sh" >&2
  exit 1
fi

echo "==> $(date -Is) git fetch/pull"
caddy_src="deploy/Caddyfile.web"
caddy_backup=""
if [[ -f "$caddy_src" ]]; then
  caddy_backup="$HOME/pakdee-Caddyfile.web.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -a "$caddy_src" "$caddy_backup"
  echo "Preserved active Caddyfile at $caddy_backup"
fi
git fetch --prune origin
if ! git checkout main; then
  echo "checkout main stopped. Do not git reset or git checkout -- $caddy_src" >&2
  exit 1
fi
if ! git pull --ff-only origin main; then
  echo "pull stopped. The active Caddyfile was left in place." >&2
  echo "Do not git reset --hard or git checkout -- $caddy_src" >&2
  [[ -n "$caddy_backup" ]] && echo "Copy: $caddy_backup" >&2
  exit 1
fi
if [[ -n "$caddy_backup" ]] && ! cmp -s "$caddy_src" "$caddy_backup"; then
  cp -a "$caddy_backup" "$caddy_src"
  echo "Restored active $caddy_src from $caddy_backup"
fi

if [[ ! -f .env || ! -f deploy/.env ]]; then
  echo "ต้องมี .env และ deploy/.env บนเซิร์ฟเวอร์" >&2
  exit 1
fi

if [[ "$MODE" == "--api-only" ]]; then
  echo "==> rebuild api only"
  docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile rollback up -d --build api
else
  echo "==> up.sh --web"
  chmod +x deploy/up.sh
  bash deploy/up.sh --web
fi

echo "==> status"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile rollback --profile web ps
echo "==> done $(date -Is)"
