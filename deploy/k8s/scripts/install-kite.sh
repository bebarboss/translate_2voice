#!/usr/bin/env bash
# Install or upgrade Kite in namespace kite-system.
# Hostname comes from KITE_HOST or deploy/k8s/config.env (default kite.cobie.online).
# Generates Secret kite-secrets the first time only. Never prints the key.
#
#   bash deploy/k8s/scripts/install-kite.sh
#   KITE_HOST=kite.example.com bash deploy/k8s/scripts/install-kite.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
K8S="$(cd "$SCRIPT_DIR/.." && pwd)"
KUBECTL="${KUBECTL:-kubectl}"
CHART="${KITE_CHART:-oci://ghcr.io/kite-org/charts/kite}"
CHART_VERSION="${KITE_CHART_VERSION:-0.17.0}"
NS=kite-system

KITE_HOST="${KITE_HOST:-}"
if [[ -z "$KITE_HOST" && -f "$K8S/config.env" ]]; then
  KITE_HOST="$(grep -E '^KITE_HOST=' "$K8S/config.env" | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
fi
KITE_HOST="${KITE_HOST:-kite.cobie.online}"

if [[ ! "$KITE_HOST" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "KITE_HOST must be a hostname, not a URL: $KITE_HOST" >&2
  exit 1
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "==> helm is not installed"
  if command -v sudo >/dev/null 2>&1; then
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | sudo bash
  else
    echo "install Helm 3.8+ and re-run" >&2
    exit 1
  fi
fi

echo "==> namespace $NS"
"$KUBECTL" create namespace "$NS" --dry-run=client -o yaml | "$KUBECTL" apply -f -

if "$KUBECTL" -n "$NS" get secret kite-secrets >/dev/null 2>&1; then
  echo "==> secret kite-secrets already exists (left unchanged)"
else
  echo "==> create secret kite-secrets with a generated JWT and encryption key"
  "$KUBECTL" -n "$NS" create secret generic kite-secrets \
    --from-literal=JWT_SECRET="$(openssl rand -base64 48)" \
    --from-literal=KITE_ENCRYPT_KEY="$(openssl rand -base64 32)"
fi

echo "==> helm upgrade --install kite $CHART --version $CHART_VERSION"
helm upgrade --install kite "$CHART" \
  --version "$CHART_VERSION" \
  --namespace "$NS" \
  --values "$K8S/kite/values.yaml" \
  --set-string "host=https://${KITE_HOST}" \
  --wait --timeout 8m

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed "s/__KITE_HOST__/${KITE_HOST}/g" "$K8S/kite/ingress.yaml" >"$tmp"
"$KUBECTL" apply -f "$tmp"

"$KUBECTL" -n "$NS" rollout status deploy/kite --timeout=180s

cat <<EOF

Kite is up. Create the administrator before the hostname is public.
There is no default username or password. The first account becomes admin.

Safer path (DNS not required):
  kubectl -n kite-system port-forward --address 127.0.0.1 svc/kite 18080:8080
  # from your laptop: ssh -L 8080:127.0.0.1:18080 khaimook@VPS
  # open http://127.0.0.1:8080 and set a long random password

Public URL, after the certificate is issued:
  https://${KITE_HOST}

Choose the in-cluster connection when Kite asks which cluster to add.
Do not rotate kite-secrets unless you accept losing encrypted data.
EOF
