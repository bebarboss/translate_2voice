#!/usr/bin/env bash
# Publish Traefik on 80/443 by enabling ServiceLB.
# Run on the VPS only after Compose Caddy has released those ports.
#
#   bash deploy/k8s/scripts/enable-ingress.sh you@example.com
#
# Two installs are valid before this runs. Both leave 80/443 with Caddy:
#   servicelb disabled, Traefik already running (this VPS)
#   traefik and servicelb both disabled (fresh install)
# The script removes those names from /etc/rancher/k3s/config.yaml and
# config.yaml.d, restarts k3s, then applies the HelmChartConfig.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

# Drop "- servicelb" and "- traefik" from k3s config files. Delete a file
# that has no keys left. Prints "changed" if it rewrote or removed the file.
strip_disable() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  sudo python3 - "$f" <<'PY'
import os, sys
path = sys.argv[1]
original = open(path).read()
lines = original.splitlines()
kept = [ln for ln in lines if ln.strip() not in ("- servicelb", "- traefik")]
out = []
i = 0
while i < len(kept):
    if kept[i].strip() == "disable:":
        j = i + 1
        while j < len(kept) and kept[j].strip() == "":
            j += 1
        if j >= len(kept) or not kept[j].lstrip().startswith("- "):
            i += 1
            continue
    out.append(kept[i])
    i += 1
keys = [ln for ln in out if ln.strip() and not ln.strip().startswith("#")]
if not keys:
    os.remove(path)
    print("removed", path)
    raise SystemExit(0)
text = "\n".join(out).rstrip() + "\n"
if text != original:
    open(path, "w").write(text)
    print("rewrote", path)
else:
    print("unchanged", path)
    raise SystemExit(2)
PY
}

shopt -s nullglob
changed=0
for f in /etc/rancher/k3s/config.yaml /etc/rancher/k3s/config.yaml.d/*.yaml; do
  [[ -f "$f" ]] || continue
  if grep -qE '^[[:space:]]*-[[:space:]]*(servicelb|traefik)[[:space:]]*$' "$f"; then
    set +e
    strip_disable "$f"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      changed=1
    elif [[ "$rc" -ne 2 ]]; then
      exit "$rc"
    fi
  fi
done
shopt -u nullglob

if [[ "$changed" -ne 1 ]]; then
  echo "no k3s config disables servicelb or traefik" >&2
  echo "looked in /etc/rancher/k3s/config.yaml and config.yaml.d/*.yaml" >&2
  if systemctl cat k3s 2>/dev/null | grep -Eq -- '--disable(=| )[^ ]*servicelb'; then
    echo "k3s.service still passes --disable=servicelb. Remove that flag, then:" >&2
    echo "  sudo systemctl daemon-reload && sudo systemctl restart k3s" >&2
  fi
  exit 1
fi

echo "==> restart k3s (ServiceLB starts and binds 80/443; Traefik starts too if it was disabled)"
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
