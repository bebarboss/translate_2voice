#!/usr/bin/env bash
# Apply a rendered manifest on the VPS and wait for rollouts.
# On a failed app rollout, undo the Deployments (previous ReplicaSet).
# The database StatefulSet is not undone: that would risk the volume.
#
#   bash deploy/k8s/scripts/rollout.sh /tmp/pakdee.yaml
set -euo pipefail

MANIFEST="${1:?usage: rollout.sh MANIFEST.yaml}"
NS="${NS:-pakdee}"
KUBECTL="${KUBECTL:-kubectl}"

if [[ ! -f "$MANIFEST" ]]; then
  echo "manifest not found: $MANIFEST" >&2
  exit 1
fi

need_secret() {
  local name="$1"
  if ! "$KUBECTL" -n "$NS" get secret "$name" >/dev/null 2>&1; then
    echo "missing secret $NS/$name — create it before the first deploy (deploy/k8s/README.md)" >&2
    exit 1
  fi
}

need_secret pakdee-secrets
need_secret ghcr-pull

echo "==> apply $MANIFEST"
"$KUBECTL" apply -f "$MANIFEST"

dump() {
  local kind="$1"
  echo "==> describe $kind" >&2
  "$KUBECTL" -n "$NS" describe "$kind" >&2 || true
  echo "==> logs $kind" >&2
  "$KUBECTL" -n "$NS" logs "$kind" --all-containers --tail=80 >&2 || true
}

undo_deploy() {
  local name="$1"
  echo "==> rollout undo deployment/$name" >&2
  if "$KUBECTL" -n "$NS" rollout undo "deployment/$name"; then
    "$KUBECTL" -n "$NS" rollout status "deployment/$name" --timeout=180s || true
  else
    echo "no previous revision for deployment/$name" >&2
  fi
}

echo "==> wait for statefulset/db"
if ! "$KUBECTL" -n "$NS" rollout status statefulset/db --timeout=180s; then
  dump statefulset/db
  exit 1
fi

echo "==> wait for deployment/api"
if ! "$KUBECTL" -n "$NS" rollout status deployment/api --timeout=300s; then
  dump deployment/api
  undo_deploy api
  exit 1
fi

echo "==> wait for deployment/web"
if ! "$KUBECTL" -n "$NS" rollout status deployment/web --timeout=180s; then
  dump deployment/web
  undo_deploy web
  undo_deploy api
  exit 1
fi

echo "==> rollout ok"
"$KUBECTL" -n "$NS" get deploy,sts,pods
