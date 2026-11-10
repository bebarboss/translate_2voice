#!/usr/bin/env bash
# Render deploy/k8s. The Postgres init SQL lives in deploy/db/init, which is
# outside this kustomize root, so the load restrictor must be opened.
#   bash deploy/k8s/scripts/render.sh > /tmp/pakdee.yaml
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
K8S="$(cd "$SCRIPT_DIR/.." && pwd)"
KUBECTL="${KUBECTL:-kubectl}"
exec "$KUBECTL" kustomize "$K8S" --load-restrictor LoadRestrictionsNone
