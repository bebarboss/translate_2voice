# Rollback / ย้อนกลับ

Production after the 2026-11-11 cutover. Writes happen only in k3s. Compose Caddy is the public edge. Starting the Compose API or web while the k3s API is running is a second writer and drops every write made since cutover.

หลังตัดรอบ 11 พ.ย. 2026 การเขียนเกิดที่ k3s เท่านั้น Caddy ของ Compose เป็นประตูสาธารณะ ถ้าเปิด API หรือเว็บของ Compose ขณะที่ API ของ k3s ยังรัน จะมีคนเขียนสองทาง และงานที่เกิดหลังตัดรอบจะหาย

The pre-cutover backup on the VPS is `~/pakdee-cutover-20261111/`. This file does not copy that directory and does not contain secrets.

## Current topology / สถานะจริง

| Piece | What is running |
| --- | --- |
| Ports 80/443 and TLS | Compose Caddy. Live config is `~/translate_2voice/deploy/Caddyfile.web`, edited on the server. The documented copy is `deploy/Caddyfile.k3s`. Do not let `git pull` replace the live file. |
| API upstream | `10.43.204.249:8000` (Service `api`, clusterIP pinned) |
| Web upstream | `10.43.26.212:3000` (Service `web`, clusterIP pinned) |
| App and database | k3s namespace `pakdee`, images from commit `b2efc9476cf4ddcad33e9a264eb99368d1705aec` at cutover. Later SHAs come from the k3s deploy workflow. |
| Compose `api` and `web` | Stopped, `restart: "no"`. Leave them stopped. |
| Compose `db` and `caddy` | Still running. The Compose database is the old copy. The app does not use it. |
| Traefik | ClusterIP only (`deploy/k8s/traefik/helmchartconfig.yaml`). Not on 80/443 and not a NodePort. |
| k3s deploy | `.github/workflows/deploy-k3s.yml` on push to `main`. Check name `test`. |

Reload Caddy without starting writers:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --no-deps caddy
```

Do not run `deploy/up.sh`, `deploy/remote-update.sh`, or the **Deploy VPS (compose rollback)** workflow unless the section below is finished. Do not run `enable-ingress.sh`.

## 1. Bad app image / อิมเมจแอปพัง

CI does this when a new image never becomes ready (`deploy/k8s/scripts/rollout.sh`). It does not touch Caddy, Traefik, or the database.

- API not ready: `kubectl rollout undo deployment/api`.
- Web not ready: undo `deployment/web` and `deployment/api`.
- Database not ready: the job fails and undoes nothing. `rollout undo` is never run on `statefulset/db`.

```bash
kubectl -n pakdee rollout undo deployment/web
kubectl -n pakdee rollout undo deployment/api
kubectl -n pakdee rollout status deployment/api --timeout=300s
kubectl -n pakdee rollout status deployment/web --timeout=180s
```

Pin a git SHA already in GHCR. Use the full 40-character SHA, not `latest`.

```bash
SHA=0123456789abcdef0123456789abcdef01234567
kubectl -n pakdee set image deployment/api api="ghcr.io/bebarboss/pakdee-api:${SHA}"
kubectl -n pakdee set image deployment/web web="ghcr.io/bebarboss/pakdee-web:${SHA}"
kubectl -n pakdee rollout status deployment/api --timeout=300s
kubectl -n pakdee rollout status deployment/web --timeout=180s
```

Do not `kubectl rollout undo statefulset/db`.

## 2. Move k3s data back before any Compose writer / ย้ายข้อมูลกลับก่อนเปิด Compose

Do this only when the site must be served by the Compose API again. Order is fixed: stop k3s writes, copy the new data onto the Compose disks, then start Compose. Never the other way around.

ทำเมื่อต้องให้ API ของ Compose รับงานอีกครั้ง ลำดับตายตัว: หยุดการเขียนของ k3s แล้วคัดข้อมูลใหม่ลงดิสก์ของ Compose จากนั้นค่อยเปิด Compose ห้ามสลับลำดับ

```bash
kubectl -n pakdee scale deploy/api --replicas=0
kubectl -n pakdee rollout status deploy/api --timeout=180s

kubectl -n pakdee exec -T db-0 -- \
  pg_dump -U pakdee -d pakdee --format=custom --no-owner --no-acl -f /tmp/pakdee-back.dump
kubectl -n pakdee cp db-0:/tmp/pakdee-back.dump ./backups/pakdee-back.dump

PV="$(kubectl -n pakdee get pvc api-data -o jsonpath='{.spec.volumeName}')"
sudo rsync -aH "$(kubectl get pv "$PV" -o jsonpath='{.spec.hostPath.path}')/" "$(pwd)/data/"

docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --no-deps db
docker compose -f deploy/docker-compose.yml --env-file deploy/.env cp ./backups/pakdee-back.dump db:/tmp/pakdee-back.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl --clean --if-exists /tmp/pakdee-back.dump
```

Compare row counts with k3s before you start the Compose API. Keep `deploy/api` at 0 replicas until that Compose process is the one you intend to keep. Two APIs must not run.

The Compose database volume is not the k3s data. Restoring the cutover dump `~/pakdee-cutover-20261111/` brings back the pre-cutover copy and throws away later writes. Use it only when the k3s copy itself is bad and you have decided to drop those writes.

## 3. Start Compose writers / เปิดตัวเขียนของ Compose

Only after section 2. `deploy/up.sh` and `deploy/remote-update.sh` exit before they pull or start containers unless this phrase is set. The GitHub workflow **Deploy VPS (compose rollback)** requires the same phrase in the `confirm` input. A pull checks out `main` and can replace the live `deploy/Caddyfile.web`. Compare that file with `deploy/Caddyfile.k3s` first. Point Caddy at `api:8000` and `web:3000` only after the Compose containers are the writers. Until then leave the ClusterIP upstreams in place.

```bash
CONFIRM_COMPOSE_WRITERS=k3s-data-moved-back bash deploy/up.sh --web
```

## 4. Traefik stays internal / Traefik ไม่เปิดสู่สาธารณะ

`kubectl apply` of `deploy/k8s/traefik/helmchartconfig.yaml` keeps `service.spec.type: ClusterIP`. `apply-traefik.sh` refuses the file if that type is LoadBalancer or NodePort. `enable-ingress.sh` restarts k3s and can bind 80/443. It exits immediately unless:

```bash
CONFIRM_PUBLIC_TRAEFIK=take-80-443-from-caddy bash deploy/k8s/scripts/enable-ingress.sh you@example.com
```

Do not set that variable. Caddy already has the certificates and the ports.

## 5. Pause k3s deploys / หยุด deploy ของ k3s

Pull-request tests keep running. Pushing to `main` still builds images. The SSH apply is skipped while `K3S_DEPLOY` is `false`. A manual **Run workflow** still deploys.

```bash
gh variable set K3S_DEPLOY --repo bebarboss/translate_2voice --body false
gh variable set K3S_DEPLOY --repo bebarboss/translate_2voice --body true
```

Deleting the StatefulSet does not delete the PVC (`whenDeleted: Retain`). `kubectl delete pvc` does.
