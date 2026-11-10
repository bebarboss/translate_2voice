# Rollback / ย้อนกลับ

Concrete commands for the VPS. Run them as `khaimook` from a checkout of this repo. Nothing here uninstalls k3s or deletes a PVC.

คำสั่งใช้บน VPS ผู้ใช้ `khaimook` จากโฟลเดอร์ของ repo ไม่มีการถอน k3s และไม่มีการลบ PVC

Related: [README.md](README.md) (install and cutover). The database dump taken before cutover is `./backups/pakdee-cutover.dump`.

## 1. Bad app deploy / deploy แอปพัง

CI does this by itself when a new image never becomes ready (`deploy/k8s/scripts/rollout.sh`):

- API not ready: `kubectl -n pakdee rollout undo deployment/api`, then the job fails.
- Web not ready: undo `deployment/web` **and** `deployment/api` (the API was already moved to the same SHA), then the job fails.
- Database not ready: the job fails and does **not** undo anything. `rollout undo` is never run against `statefulset/db`.

CI ย้อน Deployment เองถ้าพอดใหม่ไม่พร้อม ถ้า API ไม่พร้อมจะ undo เฉพาะ API ถ้าเว็บไม่พร้อมจะ undo ทั้งเว็บและ API ถ้าฐานข้อมูลไม่พร้อม job จะล้มโดยไม่ undo อะไร และจะไม่ undo `statefulset/db` เด็ดขาด

`revisionHistoryLimit` is 3, so undo can reach the previous three ReplicaSets.

See what is running and what you can return to:

```bash
kubectl -n pakdee get deploy api web -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.template.spec.containers[0].image}{"\n"}{end}'
kubectl -n pakdee rollout history deployment/api
kubectl -n pakdee rollout history deployment/web
```

Undo the last deploy (both, so web and API stay on the same SHA):

```bash
kubectl -n pakdee rollout undo deployment/web
kubectl -n pakdee rollout undo deployment/api
kubectl -n pakdee rollout status deployment/api --timeout=300s
kubectl -n pakdee rollout status deployment/web --timeout=180s
```

Undo to a specific revision (the number comes from `rollout history`):

```bash
kubectl -n pakdee rollout undo deployment/api --to-revision=2
kubectl -n pakdee rollout undo deployment/web --to-revision=2
kubectl -n pakdee rollout status deployment/api --timeout=300s
kubectl -n pakdee rollout status deployment/web --timeout=180s
```

Pin a git SHA that was already pushed to GHCR. Use the full 40-character SHA from the deploy you want, not `latest`.

ปักภาพด้วย SHA ที่เคย push ขึ้น GHCR แล้ว ใช้ SHA เต็ม 40 ตัวจาก deploy ที่ต้องการ ไม่ใช้แท็ก `latest`

```bash
SHA=0123456789abcdef0123456789abcdef01234567
kubectl -n pakdee set image deployment/api api="ghcr.io/bebarboss/pakdee-api:${SHA}"
kubectl -n pakdee set image deployment/web web="ghcr.io/bebarboss/pakdee-web:${SHA}"
kubectl -n pakdee rollout status deployment/api --timeout=300s
kubectl -n pakdee rollout status deployment/web --timeout=180s
```

Do not `kubectl rollout undo statefulset/db`. That does not restore Postgres data, and a new Pod can come up against the same volume in a bad state.

## 2. Failed cutover / สลับทราฟฟิกไม่สำเร็จ

Goal: Caddy listens on 80/443 again, and k3s Traefik does not.

เป้าหมายคือให้ Caddy ฟัง 80/443 อีกครั้ง และให้ Traefik ของ k3s หยุดฟังพอร์ตนั้น

If `enable-ingress.sh` has **not** been run, k3s was never on those ports. Start Compose again:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile web up -d db api web caddy
curl -fsS https://pakdee-api.cobie.online/health
```

If `enable-ingress.sh` **has** been run, put the hold file back and restart k3s. That disables Traefik and ServiceLB and frees 80/443. App pods and the database disk stay. Then start Compose.

```bash
sudo cp deploy/k8s/traefik/k3s-hold-ports.yaml /etc/rancher/k3s/config.yaml.d/00-pakdee-hold-ports.yaml
sudo systemctl restart k3s

# wait until the API answers, then until 443 is free
kubectl get nodes
sudo ss -lptn 'sport = :80'
sudo ss -lptn 'sport = :443'

kubectl -n pakdee scale deploy/api --replicas=0
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile web up -d db api web caddy
curl -fsS https://pakdee-api.cobie.online/health
sudo ss -lptn 'sport = :443'
```

`ss` should show `caddy` or `docker-proxy`, not `svclb`.

The same hold file is what the install uses. While it exists, a later `systemctl restart k3s` will not bring Traefik back. Run `enable-ingress.sh` again only when you mean to take the ports.

If you would rather stop the whole cluster (Kite included) and leave the disks:

```bash
sudo systemctl stop k3s
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile web up -d db api web caddy
curl -fsS https://pakdee-api.cobie.online/health
```

`systemctl stop` does not uninstall k3s. `sudo systemctl start k3s` brings the pods and PVCs back. Do not `docker compose down -v`.

The Compose workflow **Deploy VPS (compose rollback)** is manual. Run it only while k3s is not listening on 80/443 (`systemctl stop k3s`, or the hold file is in place and Traefik is gone).

## 3. Database / ฐานข้อมูล

CI never rolls the database back. `rollout undo` on the StatefulSet is not a restore. The copy that matters is the `pg_dump` taken in [README.md](README.md) section 5, before traffic moved: `./backups/pakdee-cutover.dump`.

CI ไม่ย้อนฐานข้อมูลให้อัตโนมัติ `rollout undo` ไม่ใช่การกู้ข้อมูล ไฟล์ที่ใช้กู้คือ `./backups/pakdee-cutover.dump` ที่ dump ไว้ก่อนสลับทราฟฟิก

Restore that dump into k3s Postgres. Scale the API to 0 first so nothing is connected. `--clean --if-exists` drops objects that are already there. Ignore benign "does not exist" messages. Do not ignore errors about the `vector` extension.

```bash
kubectl -n pakdee scale deploy/api --replicas=0
kubectl -n pakdee cp ./backups/pakdee-cutover.dump db-0:/tmp/pakdee-cutover.dump
kubectl -n pakdee exec -i db-0 -- \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl --clean --if-exists /tmp/pakdee-cutover.dump
kubectl -n pakdee exec db-0 -- \
  psql -U pakdee -d pakdee -c \
  "select 'studio.users' as t, count(*) from studio.users
   union all select 'studio.jobs', count(*) from studio.jobs
   union all select 'voices', count(*) from voices;"
kubectl -n pakdee scale deploy/api --replicas=1
kubectl -n pakdee rollout status deploy/api --timeout=300s
```

Compare those counts with the listing you saved during the dump. Jobs that were `running` are marked failed when the API process starts. That is existing API behaviour.

The Compose database is a different disk (the Docker volume). It still has the pre-cutover data if you did not `docker compose down -v` and you did not restore a newer dump into it. Starting Compose, as in section 2, serves that copy. It does not read the k3s PVC.

If people already used the site on k3s and you are going back to Compose, copy the k3s database out first:

```bash
kubectl -n pakdee scale deploy/api --replicas=0
kubectl -n pakdee exec -T db-0 -- \
  pg_dump -U pakdee -d pakdee --format=custom --no-owner --no-acl -f /tmp/pakdee-back.dump
kubectl -n pakdee cp db-0:/tmp/pakdee-back.dump ./backups/pakdee-back.dump

docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d db
docker compose -f deploy/docker-compose.yml --env-file deploy/.env cp ./backups/pakdee-back.dump db:/tmp/pakdee-back.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl --clean --if-exists /tmp/pakdee-back.dump
```

Do that only after Traefik is off the ports (section 2), then `docker compose ... --profile web up -d api web caddy`.

Deleting the StatefulSet does not delete the PVC (`whenDeleted: Retain`). `kubectl delete pvc` does, and local-path then removes the directory.

## 4. Pause automatic deploys / หยุด deploy อัตโนมัติชั่วคราว

Pull-request tests keep running. Pushing to `main` still builds and pushes images, but the SSH deploy is skipped while the Actions variable `K3S_DEPLOY` is `false`. A manual **Run workflow** still deploys.

เทสบน pull request ยังรัน การ push เข้า `main` ยัง build ภาพ แต่จะไม่ SSH ไป deploy ตราบใดที่ตัวแปร `K3S_DEPLOY` เป็น `false` การกด Run workflow เองยัง deploy ได้

```bash
gh variable set K3S_DEPLOY --repo bebarboss/translate_2voice --body false
gh variable list --repo bebarboss/translate_2voice
```

Resume (an empty or any other value also deploys; `false` is the only pause):

```bash
gh variable set K3S_DEPLOY --repo bebarboss/translate_2voice --body true
```

Or in the GitHub UI: Settings → Secrets and variables → Actions → Variables.

To stop the workflow entirely, including pull-request tests:

```bash
gh workflow disable deploy-k3s.yml --repo bebarboss/translate_2voice
gh workflow enable deploy-k3s.yml --repo bebarboss/translate_2voice
```

The cluster stays on whatever SHA is already running. New `:latest` tags can still appear in GHCR while deploys are paused. Pin with `kubectl set image` (section 1) if you need a specific SHA. Do not point the Deployment at `:latest` to "roll back".
