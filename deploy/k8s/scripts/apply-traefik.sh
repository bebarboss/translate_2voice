#!/usr/bin/env bash
# Render the Traefik HelmChartConfig with an ACME email and apply it.
# Run on the VPS, from anywhere:
#   ACME_EMAIL=you@example.com bash deploy/k8s/scripts/apply-traefik.sh
#   bash deploy/k8s/scripts/apply-traefik.sh you@example.com
# If no address is given, ACME_EMAIL is read from deploy/.env when that file exists.
#
# Applies the committed HelmChartConfig. That Service is ClusterIP, so this
# does not publish 80/443. A file that says LoadBalancer or NodePort is refused
# unless CONFIRM_PUBLIC_TRAEFIK=take-80-443-from-caddy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
K8S="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO="$(cd "$K8S/../.." && pwd)"
SRC="$K8S/traefik/helmchartconfig.yaml"
KUBECTL="${KUBECTL:-kubectl}"

EMAIL="${1:-${ACME_EMAIL:-}}"
if [[ -z "$EMAIL" && -f "$REPO/deploy/.env" ]]; then
  EMAIL="$(grep -E '^ACME_EMAIL=' "$REPO/deploy/.env" | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
fi

if [[ -z "$EMAIL" || "$EMAIL" != *@* || "$EMAIL" == *$'\n'* ]]; then
  echo "need an ACME email: bash deploy/k8s/scripts/apply-traefik.sh you@example.com" >&2
  exit 1
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
content="$(<"$SRC")"
printf '%s\n' "${content//__ACME_EMAIL__/$EMAIL}" >"$tmp"

if grep -Eq 'type: (LoadBalancer|NodePort)' "$tmp" && [[ "${CONFIRM_PUBLIC_TRAEFIK:-}" != "take-80-443-from-caddy" ]]; then
  echo "Refusing to apply Traefik as a LoadBalancer or NodePort." >&2
  echo "The public edge is Caddy. Keep service.spec.type: ClusterIP." >&2
  echo "See deploy/k8s/ROLLBACK.md." >&2
  exit 1
fi

echo "==> apply Traefik HelmChartConfig (email $EMAIL)"
"$KUBECTL" apply -f "$tmp"

# Traefik not installed: the HelmChartConfig is stored and Caddy keeps 80/443.
# Traefik already running: roll the chart. The committed type is ClusterIP.
# Do not treat a missing Deployment as a failure.
if ! "$KUBECTL" -n kube-system get deploy/traefik >/dev/null 2>&1; then
  echo "==> HelmChartConfig is stored. Traefik is not running."
  echo "    Caddy keeps 80/443. Do not run enable-ingress.sh."
  exit 0
fi
echo "==> Traefik is already running (ServiceLB still off, so 80/443 stay with Caddy)"

echo "==> wait for Traefik to roll the new config"
# The Helm controller applies values asynchronously. Rollout failure is the
# signal that the values were rejected. The resolver string may live in the
# Deployment args or only in the HelmChartConfig.
found=0
for _ in $(seq 1 24); do
  if "$KUBECTL" -n kube-system get deploy,helmchartconfig -o yaml 2>/dev/null | grep -q letsencrypt; then
    found=1
    break
  fi
  sleep 5
done
if [[ "$found" -ne 1 ]]; then
  echo "letsencrypt was not visible on the Traefik chart yet. kubectl -n kube-system describe helmchartconfig traefik" >&2
  exit 1
fi

"$KUBECTL" -n kube-system rollout status deploy/traefik --timeout=180s
echo "==> traefik ready"
