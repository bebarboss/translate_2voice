#!/usr/bin/env bash
# Render the Traefik HelmChartConfig with an ACME email and apply it.
# Run on the VPS, from anywhere:
#   ACME_EMAIL=you@example.com bash deploy/k8s/scripts/apply-traefik.sh
#   bash deploy/k8s/scripts/apply-traefik.sh you@example.com
# If no address is given, ACME_EMAIL is read from deploy/.env when that file exists.
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

echo "==> apply Traefik HelmChartConfig (email $EMAIL)"
"$KUBECTL" apply -f "$tmp"

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
