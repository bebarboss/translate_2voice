#!/usr/bin/env bash
# Turn on k3s Traefik and ServiceLB so they listen on 80/443.
# Run on the VPS only after Compose Caddy has released those ports.
#
#   bash deploy/k8s/scripts/enable-ingress.sh you@example.com
#
# The email is forwarded to apply-traefik.sh. What this script changes:
#   rm /etc/rancher/k3s/config.yaml.d/00-pakdee-hold-ports.yaml
#   systemctl restart k3s
#   apply the Traefik HelmChartConfig and wait for deploy/traefik
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOLD="${HOLD:-/etc/rancher/k3s/config.yaml.d/00-pakdee-hold-ports.yaml}"
KUBECTL="${KUBECTL:-kubectl}"

if ! command -v ss >/dev/null 2>&1; then
  echo "ss is required (package iproute2) so this script can refuse to start while 80/443 are taken" >&2
  exit 1
fi

port_busy() {
  local port="$1" proto="$2" out
  if ! out="$(ss -H -l"${proto}"n "sport = :${port}")"; then
    echo "ss failed while checking port ${port}" >&2
    exit 1
  fi
  [[ -n "$out" ]]
}

if port_busy 80 t || port_busy 443 t || port_busy 443 u; then
  echo "port 80 or 443 is still in use. Stop Compose Caddy first:" >&2
  echo "  docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile web stop caddy" >&2
  echo "  sudo ss -lptn 'sport = :80' ; sudo ss -lptn 'sport = :443'" >&2
  exit 1
fi

if [[ ! -f "$HOLD" ]]; then
  echo "hold file not found: $HOLD" >&2
  echo "If k3s was installed with --disable=traefik on the systemd command line," >&2
  echo "delete that flag from the unit (or from /etc/rancher/k3s/config.yaml) before restarting." >&2
  exit 1
fi

echo "==> remove $HOLD"
sudo rm -f "$HOLD"

echo "==> restart k3s (Traefik and ServiceLB start and bind 80/443)"
sudo systemctl restart k3s

echo "==> wait for the API"
ready=0
for _ in $(seq 1 60); do
  if "$KUBECTL" get nodes >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" -ne 1 ]]; then
  echo "kubectl could not reach the API after restart" >&2
  exit 1
fi
"$KUBECTL" wait --for=condition=Ready node --all --timeout=180s

echo "==> wait for the Traefik Deployment to appear"
found=0
for _ in $(seq 1 60); do
  if "$KUBECTL" -n kube-system get deploy/traefik >/dev/null 2>&1; then
    found=1
    break
  fi
  sleep 2
done
if [[ "$found" -ne 1 ]]; then
  echo "deploy/traefik did not appear. kubectl -n kube-system get helmchart,deploy" >&2
  exit 1
fi

bash "$SCRIPT_DIR/apply-traefik.sh" "$@"

echo "==> ingress should now own 80/443"
"$KUBECTL" -n kube-system get svc traefik
sudo ss -lptn 'sport = :80' || true
sudo ss -lptn 'sport = :443' || true
