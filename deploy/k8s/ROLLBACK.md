# Rollback / ย้อนกลับ

Production after the 2026-11-11 cutover. Writes happen only in k3s. Compose Caddy is the public edge. Starting the Compose API or web while the k3s API is running is a second writer and drops every write made since cutover.

หลังตัดรอบ 11 พ.ย. 2026 การเขียนเกิดที่ k3s เท่านั้น Caddy ของ Compose เป็นประตูสาธารณะ ถ้าเปิด API หรือเว็บของ Compose ขณะที่ API ของ k3s ยังรัน จะมีคนเขียนสองทาง และงานที่เกิดหลังตัดรอบจะหาย

The pre-cutover backup on the VPS is `~/pakdee-cutover-20261111/`. This file does not copy that directory and does not contain secrets.

## Current topology / สถานะจริง

| Piece | What is running |
| --- | --- |
| Ports 80/443 and TLS | Compose Caddy. Live config is `~/translate_2voice/deploy/Caddyfile.web`, edited on the server. The checkout there is `a2d0f5d` (no request body limit). `deploy/Caddyfile.k3s` documents the ClusterIP upstreams and also has no body limit. Git `main`'s `deploy/Caddyfile.web` is different: it adds a 600MB limit and still proxies to `api:8000` / `web:3000`. Never `git pull`, `git reset --hard`, or `git checkout -- deploy/Caddyfile.web` on the VPS. Copy the active file aside and compare before any update. |
| API upstream | `10.43.204.249:8000` (Service `api`, clusterIP pinned) |
| Web upstream | `10.43.26.212:3000` (Service `web`, clusterIP pinned) |
| App and database | k3s namespace `pakdee`, images from commit `b2efc9476cf4ddcad33e9a264eb99368d1705aec` at cutover. Later SHAs come from the k3s deploy workflow. |
| Compose `api` and `web` | Stopped, `restart: "no"`. Leave them stopped. |
| Compose `db` and `caddy` | Still running. The Compose database is the old copy. The app does not use it. |
| Traefik | ClusterIP only (`deploy/k8s/traefik/helmchartconfig.yaml`). Not on 80/443 and not a NodePort. |
| k3s deploy | `.github/workflows/deploy-k3s.yml` on push to `main`. Check name `test`. |

Reload the running Caddy without recreating it. `depends_on` in this repo changed, so `docker compose up` (including `--no-deps caddy`) recreates `pakdee-vps-caddy-1` and drops the live proxy. Reload the process that is already bound to 80/443:

```bash
docker exec pakdee-vps-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
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

Do this only when the site must be served by the Compose API again. Order is fixed. Pause automatic deploys first, then stop the k3s writer, then copy data, then back up the Compose database, then restore. Never the other way around. Two APIs must not run.

ทำเมื่อต้องให้ API ของ Compose รับงานอีกครั้ง ลำดับตายตัว: หยุด deploy อัตโนมัติก่อน แล้วหยุดตัวเขียนของ k3s แล้วคัดข้อมูล สำรองฐานของ Compose ก่อน restore ห้ามสลับลำดับ

Run this from the repo root on the VPS. The public site errors while `deploy/api` is at 0 replicas, because Caddy still dials the k3s Service. Leave it that way until section 3.

### 2.1 Pause automatic deploys / หยุด deploy อัตโนมัติ

A merge to `main` applies the manifests, and those Deployments set `replicas: 1`. That brings the k3s writer back. Set the variable before scaling down. `gh` must already be logged in. Check first:

```bash
gh auth status
gh variable set K3S_DEPLOY --repo bebarboss/translate_2voice --body false
gh variable get K3S_DEPLOY --repo bebarboss/translate_2voice
```

The get must print `false`. If `gh auth status` fails, set the same variable in the repo UI: Settings → Secrets and variables → Actions → Variables → `K3S_DEPLOY` = `false`. A pull request still runs tests. A push still builds images. The SSH apply is skipped only when this variable is `false` before that job starts.

A **Run workflow** (`workflow_dispatch`) still deploys while the variable is `false`. Do not start one. A deploy that is already running has passed the variable check and will apply `replicas: 1`. Wait for it to finish, or cancel it, before scaling. Then confirm the replica count again after the copy. Do not `kubectl apply` the app manifests while the API is scaled to 0.

Leave `K3S_DEPLOY` false until the k3s API is again the only writer. Section 5 is how to turn it back on.

### 2.2 Stop the k3s writer / หยุดตัวเขียนของ k3s

```bash
kubectl -n pakdee scale deploy/api --replicas=0
kubectl -n pakdee rollout status deploy/api --timeout=180s
kubectl -n pakdee get deploy/api -o jsonpath='{.spec.replicas}{"\n"}'
```

The printed count must be `0`. If it is `1`, a deploy applied the manifest. Cancel that run, repeat 2.1, and scale to 0 again. Do not copy data while the count can change.

### 2.3 Copy the k3s database and both volumes / คัดฐานและวอลุ่ม

`kubectl exec` has no `-T` flag. Dump straight to a local file. Do not `kubectl cp`.

```bash
mkdir -p ./backups/rollback
kubectl -n pakdee exec db-0 -- \
  pg_dump -U pakdee -d pakdee --format=custom --no-owner --no-acl \
  > ./backups/rollback/pakdee-k3s.dump
test -s ./backups/rollback/pakdee-k3s.dump
```

Keep both PVCs. Do not `kubectl delete pvc api-data api-backups`. Copy `api-data` onto the Compose media tree and `api-backups` beside it. Do not pass `--delete` to rsync.

```bash
PV="$(kubectl -n pakdee get pvc api-data -o jsonpath='{.spec.volumeName}')"
sudo rsync -aH "$(kubectl get pv "$PV" -o jsonpath='{.spec.hostPath.path}')/" "$(pwd)/data/"

PVB="$(kubectl -n pakdee get pvc api-backups -o jsonpath='{.spec.volumeName}')"
mkdir -p "$(pwd)/backups/from-k3s"
sudo rsync -aH "$(kubectl get pv "$PVB" -o jsonpath='{.spec.hostPath.path}')/" "$(pwd)/backups/from-k3s/"
```

Confirm `deploy/api` is still 0 replicas after the copy. Scale it to 0 again if a deploy moved it.

### 2.4 Back up the Compose database, then restore / สำรองฐาน Compose แล้วค่อย restore

The Compose `db` container is already running and is the pre-cutover copy. Do not recreate it. Dump it before `pg_restore --clean`, which drops objects in that database.

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_dump -U pakdee -d pakdee --format=custom --no-owner --no-acl \
  > ./backups/rollback/pakdee-compose-before-restore.dump
test -s ./backups/rollback/pakdee-compose-before-restore.dump

docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl --clean --if-exists \
  < ./backups/rollback/pakdee-k3s.dump
```

Compare row counts with the k3s database before you start the Compose API. Keep `deploy/api` at 0 replicas until that Compose process is the one you intend to keep.

The Compose database volume is not the k3s data. Restoring the cutover dump `~/pakdee-cutover-20261111/` brings back the pre-cutover copy and throws away later writes. Use it only when the k3s copy itself is bad and you have decided to drop those writes. The file written in 2.4 is the backup of that Compose database from just before the restore.

## 3. Start Compose writers / เปิดตัวเขียนของ Compose

Only after section 2, and only while `deploy/api` is still 0 replicas and `K3S_DEPLOY` is still `false`. `deploy/up.sh` and `deploy/remote-update.sh` exit before they pull or start containers unless this phrase is set. The GitHub workflow **Deploy VPS (compose rollback)** requires the same phrase in the `confirm` input.

`up.sh --web` passes both `--profile rollback` and `--profile web`. `--profile web` alone fails, because `web` depends on `api` and `api` is not in that profile (`service "web" depends on undefined service "api"`). A hand-run Compose command that starts the web container needs both profiles. It still starts a writer, so it is not a way around the data copy.

```bash
CONFIRM_COMPOSE_WRITERS=k3s-data-moved-back bash deploy/up.sh --web
```

Those scripts copy `deploy/Caddyfile.web` to `$HOME/pakdee-Caddyfile.web.<timestamp>` before `git pull` and copy it back if the pull changes the file. The VPS checkout is `a2d0f5d`. Do not `git reset --hard` or `git checkout -- deploy/Caddyfile.web`. Compare the preserved file with git before you change upstreams.

Point Caddy at `api:8000` and `web:3000` only after the Compose containers are the writers and the k3s API is still at 0 replicas. Until then leave the ClusterIP upstreams in place. After you edit the live file, reload the running process. Do not `docker compose up` Caddy:

```bash
docker exec pakdee-vps-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

## 4. Traefik stays internal / Traefik ไม่เปิดสู่สาธารณะ

`kubectl apply` of `deploy/k8s/traefik/helmchartconfig.yaml` keeps `service.spec.type: ClusterIP`. `apply-traefik.sh` refuses the file if that type is LoadBalancer or NodePort. `enable-ingress.sh` restarts k3s and can bind 80/443. It exits immediately unless:

```bash
CONFIRM_PUBLIC_TRAEFIK=take-80-443-from-caddy bash deploy/k8s/scripts/enable-ingress.sh you@example.com
```

Do not set that variable. Caddy already has the certificates and the ports.

## 5. Resume k3s deploys / เปิด deploy ของ k3s อีกครั้ง

Section 2.1 already paused deploys. Leave `K3S_DEPLOY` false for the whole time the Compose API is a writer, or while `deploy/api` is held at 0. Turn it back on only when the k3s API is the only writer again.

`gh auth status` must succeed, or set the variable in Settings → Secrets and variables → Actions → Variables.

```bash
gh auth status
gh variable set K3S_DEPLOY --repo bebarboss/translate_2voice --body true
gh variable get K3S_DEPLOY --repo bebarboss/translate_2voice
```

A manual **Run workflow** deploys even while the variable is `false`.

Deleting the StatefulSet does not delete `api-data` or `api-backups` (`whenDeleted: Retain` on the database volume; the API claims are separate PVCs). `kubectl delete pvc api-data api-backups` does delete the media and the backup files. Do not delete them as part of a rollback.
