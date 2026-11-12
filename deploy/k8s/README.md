# Pakdee on k3s / พากย์ดีบน k3s

Production runs on k3s on the same single VPS (2 vCPU, about 3.8 GB RAM). The cutover on 2026-11-11 is done. Compose Caddy still owns 80/443 and forwards to the pinned ClusterIPs. Compose `api` and `web` stay stopped. Do not follow the old steps that publish Traefik or start those containers. Rollback order is [ROLLBACK.md](ROLLBACK.md).

production รันบน k3s แล้ว การตัดรอบวันที่ 11 พ.ย. 2026 เสร็จแล้ว Caddy ของ Compose ยังถือพอร์ต 80/443 และส่งต่อไป ClusterIP ที่ปักไว้ `api` กับ `web` ของ Compose ต้องหยุดอยู่ อย่าทำขั้นตอนเก่าที่เปิด Traefik สู่สาธารณะหรือสตาร์ทสองคอนเทนเนอร์นั้น ลำดับย้อนกลับอยู่ใน [ROLLBACK.md](ROLLBACK.md)

## Design / แนวทาง

| Piece | Choice |
| --- | --- |
| App manifests | Kustomize in `deploy/k8s/` (namespace `pakdee`) |
| Edge | Compose Caddy on 80/443. Documented config is `deploy/Caddyfile.k3s` (no body size limit). The live file is `~/translate_2voice/deploy/Caddyfile.web`, edited in place on checkout `a2d0f5d`. Do not `git pull`, `git reset`, or `git checkout --` that file. Compare it and keep it. API `10.43.204.249:8000`, web `10.43.26.212:3000`. Those ClusterIPs are pinned on the Services. Traefik stays ClusterIP and is not a public listener. |
| TLS | Caddy ACME on the live file: HSTS, nosniff, referrer-policy, 30 minute API timeouts, no request body limit. Git's `deploy/Caddyfile.web` on current `main` adds a 600MB limit and still proxies to Compose names. That is not the file the VPS is running. |
| Postgres | StatefulSet, `pgvector/pgvector:pg16`, 10Gi `local-path` PVC, init SQL from `deploy/db/init/`. ClusterIP `db:5432` only. |
| API / web | Deployments, **Recreate** (one replica). The API queue is in-process and the media volume is ReadWriteOnce. Images `ghcr.io/bebarboss/pakdee-api` and `ghcr.io/bebarboss/pakdee-web`, tagged with the git SHA and `latest`. |
| Config | `config.env` → ConfigMap `pakdee-config`. Secrets from `secret.example.yaml`, applied by you, never committed. |
| CI | `.github/workflows/deploy-k3s.yml`. The pull-request job id and check name are `test` (pytest and `npm run typecheck`). Branch protection on `main` requires that exact context. Push to `main` builds, pushes, SSHes to the VPS, `kubectl apply`, waits, and `kubectl rollout undo` if the new pods do not become ready. |
| Dashboard | [Kite](https://kitehq.dev) via Helm `oci://ghcr.io/kite-org/charts/kite` in namespace `kite-system`. |
| Domains | `pakdee-api.cobie.online`, `pakdee-app.cobie.online`, `kite.cobie.online` (`KITE_HOST` in `config.env`). |

`enable-ingress.sh` restarts k3s and can bind 80/443. It exits unless `CONFIRM_PUBLIC_TRAEFIK=take-80-443-from-caddy`. Do not set that. `apply-traefik.sh` applies a ClusterIP Service and refuses `type: LoadBalancer` or `type: NodePort` without the same phrase. A push to `main` still tests, builds, and rolls the k3s Deployments. It does not start Compose and it does not change Traefik's Service type.

Render check, from a checkout (no cluster required):

```bash
bash deploy/k8s/scripts/render.sh > /tmp/pakdee.yaml
kubectl kustomize deploy/k8s --load-restrictor LoadRestrictionsNone > /tmp/pakdee.yaml
kustomize build deploy/k8s --load-restrictor LoadRestrictionsNone > /tmp/pakdee.yaml
```

The load restrictor is required because the Postgres ConfigMap reads `deploy/db/init/*.sql`, which sits outside `deploy/k8s`. `render.sh` is that command. Plain `kubectl kustomize deploy/k8s` without the flag refuses those files. `kubeconform -strict` against Kubernetes 1.33 validates that output. Skip kind `CustomResourceDefinition`: the schema bundle has no document for that kind. Middleware and ServersTransport are still checked.

Memory limits on this box: Traefik 192Mi, Postgres 640Mi, API 1280Mi, web 384Mi, Kite 256Mi. Requests are much smaller so the pods schedule next to k3s itself. A deploy restarts API and web one at a time (a few seconds). Do not raise those limits all at once or the node can be OOM-killed.

## What you must do before the first automatic deploy / ก่อน deploy อัตโนมัติครั้งแรก

Do these on the VPS **before** merging to `main` (or re-run the workflow after). The first CI run fails closed if the secrets or kubeconfig are missing. It does not SSH anywhere until you have created the GitHub secrets.

ทำบน VPS ก่อน merge เข้า `main` ไม่งั้น job จะล้มเพราะยังไม่มี secret หรือ kubectl

1. Install k3s with **ServiceLB disabled**. Traefik may stay enabled (this VPS) or be disabled too. Give user `khaimook` a kubeconfig.
2. Apply the Traefik ACME config (`apply-traefik.sh`). If Traefik is already running it rolls the chart. If Traefik is disabled it only stores the HelmChartConfig. Either way it does not bind 80/443.
3. Create namespace secrets `pakdee-secrets` and `ghcr-pull`, then apply `deploy/k8s` (works on this k3s immediately).
4. Point Cloudflare DNS (orange cloud) and turn off edge HTTPS redirect for the ACME path, or use an Origin certificate.
5. Add the GitHub Actions secrets listed below.
6. Merge. CI builds images and starts pods. Caddy still owns 80/443. Nothing in k3s listens there.
7. Cutover is already done. Leave Compose `api` and `web` stopped. Do not run `enable-ingress.sh`.

Kite is separate. Install it with `install-kite.sh` or Actions → **CI and deploy k3s** → **Run workflow** with **install_kite** checked. That dispatch does not rebuild the app.

## GitHub Actions secrets / ความลับของ GitHub

Settings → Secrets and variables → Actions. These are the only Actions secrets this workflow reads. Copy the values you already use for `VPS_HOST`, `VPS_USER`, and `VPS_SSH_KEY` if that key is the `khaimook` deploy key. Prefer a dedicated ed25519 key that can log in as `khaimook` and nothing else. The k3s API stays on the VPS; the workflow never receives a kubeconfig.

| Secret | Required | Example / meaning |
| --- | --- | --- |
| `K3S_SSH_HOST` | yes | VPS address |
| `K3S_SSH_USER` | yes | `khaimook` |
| `K3S_SSH_KEY` | yes | Private key PEM, including the `BEGIN` / `END` lines and real newlines |
| `K3S_SSH_KNOWN_HOSTS` | yes | Output of `ssh-keyscan -p 22 -H <host>` (stops a MITM on the first connection) |
| `K3S_SSH_PORT` | no | `22` if unset |

`GITHUB_TOKEN` is provided by Actions and is what **pushes** images. It is not a secret you create. The cluster **pulls** with a separate token stored only on the VPS (next section).

There is no lint script in the repo. CI runs `pytest` in `backend/` and `npm run typecheck` in `frontend/`.

The old workflow `Deploy VPS (compose rollback)` does not run on push. A manual run refuses unless the `confirm` input is `k3s-data-moved-back`. That phrase is only for [ROLLBACK.md](ROLLBACK.md), after k3s data has been copied back and the k3s API is scaled to 0. Do not `systemctl stop k3s` to bring Compose writers back.

## 1. Install k3s / ติดตั้ง k3s

Compose Caddy keeps 80/443. ServiceLB stays off, and Traefik's Service stays ClusterIP, so k3s does not bind those ports. Do not pass `--disable` on the install command line. Leave the drop-in in place. `enable-ingress.sh` would remove it and can publish Traefik; the script now refuses.

Caddy ยังถือพอร์ต 80/443 Traefik เป็น ClusterIP และ ServiceLB ปิดอยู่ อย่าใส่ `--disable` ในคำสั่งติดตั้ง และอย่ารัน `enable-ingress.sh`

**This VPS: Traefik on, ServiceLB off, Service type ClusterIP.** A LoadBalancer or NodePort on `svc/traefik` is a public listener. Do not put one back.

```bash
sudo mkdir -p /etc/rancher/k3s/config.yaml.d
sudo cp deploy/k8s/traefik/k3s-hold-servicelb.yaml /etc/rancher/k3s/config.yaml.d/00-pakdee-hold-ports.yaml
curl -sfL https://get.k3s.io | sh -
sudo install -d -o khaimook -g khaimook -m 700 /home/khaimook/.kube
sudo install -o khaimook -g khaimook -m 600 /etc/rancher/k3s/k3s.yaml /home/khaimook/.kube/config
kubectl get nodes
kubectl -n kube-system get deploy
# traefik is present
sudo ss -lptn 'sport = :443'
# caddy / docker-proxy, not svclb
```

**Fresh install: Traefik and ServiceLB both off.** Same ports, and `deploy/traefik` does not exist until cutover. Copy `deploy/k8s/traefik/k3s-hold-ports.yaml` to that same path instead of `k3s-hold-servicelb.yaml`. Do not copy that file onto a node where Traefik is already running. The next restart would stop it.

ถ้า Traefik รันอยู่แล้ว ห้ามใช้ไฟล์ที่ปิด `traefik` ด้วย จะทำให้ restart ครั้งหน้าดับ Traefik

Confirm port 6443 is not reachable from the internet. Allow 22, 80, and 443 (tcp and udp). Do not enable ufw until OpenSSH is allowed, or you will lock yourself out.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw deny 6443/tcp
sudo ufw status
```

Install Helm only if you will install Kite (the script does this when `helm` is missing):

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | sudo bash
```

## 2. Traefik and Cloudflare / TLS

Hostnames, all orange-cloud A records to the VPS IP:

- `pakdee-api.cobie.online`
- `pakdee-app.cobie.online`
- `kite.cobie.online` (or whatever you set as `KITE_HOST`)

SSL/TLS mode: **Full (strict)** once the origin has a certificate. HTTP-01 itself only needs Cloudflare to forward **port 80** to the origin.

Traefik redirects HTTP→HTTPS on the origin **after** it answers `/.well-known/acme-challenge/`. That redirect is compatible with Let's Encrypt. Cloudflare's **Always Use HTTPS** is not: the challenge never reaches the VPS. Before the first issuance (and for renewals):

- Leave **Always Use HTTPS** off, or
- Add a Configuration Rule: if URI Path starts with `/.well-known/acme-challenge/` then skip Always Use HTTPS.
- Bypass cache for that path.

Orange-cloud clients use Cloudflare's HTTP/3. Origin UDP 443 is only for a grey-cloud record. WebSockets (Kite logs and terminal) pass Traefik; Cloudflare's proxy may still idle-timeout long shells on the free plan.

Public certificates are Caddy's, not Traefik's. `apply-traefik.sh` only refreshes the internal HelmChartConfig (ClusterIP). It reads `ACME_EMAIL` from `deploy/.env` if you omit it. It refuses the file when the Service type is LoadBalancer or NodePort.

```bash
bash deploy/k8s/scripts/apply-traefik.sh you@example.com
```

The Ingress in this bundle is not the public edge. Traefik is ClusterIP, so applying it does not open 80/443. Caddy dials the ClusterIP Services directly. The bundle includes the Traefik CRDs, so Middleware and the Ingress apply even when the controller is not installed yet.

```bash
bash deploy/k8s/scripts/render.sh > /tmp/pakdee.yaml
kubectl apply -f /tmp/pakdee.yaml || true
kubectl apply -f /tmp/pakdee.yaml
kubectl -n pakdee get deploy,sts,ingress
```

The first apply can miss Middleware until the CRDs are Established. The second apply is the one that must succeed. `rollout.sh` does the same.

### If HTTP-01 cannot get through Cloudflare

**Origin CA (simplest when the names are already proxied).** In Cloudflare → SSL/TLS → Origin Server, create a certificate that covers the three hostnames (15 years). Full (strict) trusts it. No Let's Encrypt.

```bash
kubectl -n pakdee create secret tls pakdee-origin-tls \
  --cert=origin.pem --key=origin.key
```

Then on the Ingress, remove the `certresolver` annotation and set `secretName: pakdee-origin-tls` under `spec.tls`. Do the same for `deploy/k8s/kite/ingress.yaml`. Delete the local key files. Renew before the Origin certificate expires.

**DNS-01.** Install cert-manager and an Issuer that uses a Cloudflare API token (Zone / DNS / Edit on `cobie.online` only). Point the Ingress at the Certificate's secret and remove `certresolver`. cert-manager is extra memory on this node; use it only if you cannot open port 80 for the challenge. This repo does not ship that Issuer because the token must not be committed.

## 3. App secrets and the GHCR pull secret / ความลับของแอป

```bash
kubectl apply -f deploy/k8s/namespace.yaml
cp deploy/k8s/secret.example.yaml /tmp/pakdee-secret.yaml
nano /tmp/pakdee-secret.yaml
kubectl apply -f /tmp/pakdee-secret.yaml
shred -u /tmp/pakdee-secret.yaml
```

`DATABASE_URL` must use host `db`, database and user `pakdee` (unless you changed all three together), and the same password as `POSTGRES_PASSWORD`. Copy the real values from the existing root `.env` and `deploy/.env`. Do not commit the filled file.

`pakdee-secrets` must also contain `ADMIN_EMAILS`, `PAYMENT_PROVIDER=stripe`, `R2_ENABLED=1`, `R2_BUCKET`, `R2_ACCOUNT_ID`, and `R2_ENDPOINT`. Those keys are listed as placeholders in `secret.example.yaml`. Do not put a real admin address in `config.env` or the ConfigMap. The Deployment loads the ConfigMap first and the Secret second, so a key present in both is taken from the Secret. Keeping these out of the ConfigMap means an empty ConfigMap value cannot clear them.

Actor tax ids and bank account numbers use a separate Secret, `pakdee-pii`. The API deployment reads `PII_ENC_KEYS`, `PII_ENC_ACTIVE_VERSION`, and `PII_HMAC_KEY` from it with `secretKeyRef`. Create that Secret before rolling out the encryption image, or the pod will not start. Steps for generating keys, `age` backup, restore, and rotation are in [docs/pii-encryption.md](../../docs/pii-encryption.md). Do not commit the key values.

The workflow pushes with `GITHUB_TOKEN`. The node pulls with a personal access token that has **read:packages** (classic) or a fine-grained token limited to these packages. Images stay private.

```bash
kubectl -n pakdee create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=bebarboss \
  --docker-password='<github-pat-read-packages>'
```

After the first push, confirm the packages exist under `ghcr.io/bebarboss/pakdee-api` and `pakdee-web` and that the Actions token could link them (the image label `org.opencontainers.image.source` points at this repo). If the push is denied, in the package settings allow this repository's Actions access.

`config.env` is safe to commit. It already has the production hostnames. `KITE_HOST` is the one knob for the dashboard. Ingress hosts for the app are filled from `API_DOMAIN` and `WEB_DOMAIN` at render time. A change is picked up on the next deploy because the image tag changes and the pods restart. A manual edit between deploys needs `kubectl -n pakdee rollout restart deploy/api deploy/web`.

## 4. Kite / แดชบอร์ด

Chart version is pinned to `0.17.0` in `install-kite.sh`. SQLite is on a 1Gi `local-path` PVC (`/data/kite.db`, WAL mode). There is no default login and no encryption key in git. The script creates Secret `kite-secrets` with `openssl rand` the first time and will not rotate it.

RBAC is not cluster-admin. Kite can read the cluster, change workloads, exec into pods, and read/write Secrets (so the Helm UI works, and a Kite admin can see `pakdee-secrets`). It cannot create ClusterRoleBindings or bind cluster roles, and it cannot shell onto the node. `anonymousUserEnabled` is false.

```bash
# optional: KITE_HOST=stats.cobie.online
bash deploy/k8s/scripts/install-kite.sh
```

Create the admin **before** the name resolves publicly. There is no default password; the first visitor becomes the administrator. Use a long random password and store it in a password manager.

```bash
# on the VPS
kubectl -n kite-system port-forward --address 127.0.0.1 svc/kite 18080:8080
# on your laptop
ssh -L 8080:127.0.0.1:18080 khaimook@<vps>
# browser: http://127.0.0.1:8080
```

Then open `https://kite.cobie.online` and add the cluster as **in-cluster**. Do not delete `kite-secrets` or the PVC. A new encryption key cannot read the old database.

Re-run the script or the **install_kite** workflow to upgrade. Both call `helm upgrade --install` and apply the Ingress again.

Kite limits are 20m/64Mi request and 300m/256Mi limit. If it OOM-kills, raise the limit in `deploy/k8s/kite/values.yaml` before you raise anything else.

## 5. Move Postgres / ย้ายฐานข้อมูล

This import already ran. Do not run it again. The commands below stop Caddy and `pg_restore --clean` into the k3s database, which replaces live data with the pre-cutover dump. The way back to Compose is [ROLLBACK.md](ROLLBACK.md): copy the new k3s data out first, and never run both writers.

การย้ายนี้ทำไปแล้ว อย่ารันซ้ำ คำสั่งด้านล่างจะหยุด Caddy และ restore ทับฐานของ k3s ด้วยดัมพ์ก่อนตัดรอบ ทางกลับไป Compose อยู่ใน [ROLLBACK.md](ROLLBACK.md)

```bash
kubectl -n pakdee scale deploy/api --replicas=0

# stop writers; keep the Compose database process up
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile rollback --profile web stop api web caddy

docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  psql -U pakdee -d pakdee -c \
  "select 'studio.users' as t, count(*) from studio.users
   union all select 'studio.jobs', count(*) from studio.jobs
   union all select 'voices', count(*) from voices;"

docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_dump -U pakdee -d pakdee --format=custom --no-owner --no-acl \
  -f /tmp/pakdee-cutover.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env \
  cp db:/tmp/pakdee-cutover.dump ./backups/pakdee-cutover.dump
```

Restore into k3s. `--clean --if-exists` drops objects the init scripts already created, then recreates them from the dump. Ignore benign "does not exist" messages. Do not ignore errors about the `vector` extension; the image provides it.

```bash
kubectl -n pakdee cp ./backups/pakdee-cutover.dump db-0:/tmp/pakdee-cutover.dump
kubectl -n pakdee exec -i db-0 -- \
  pg_restore -U pakdee -d pakdee --no-owner --no-acl --clean --if-exists /tmp/pakdee-cutover.dump

kubectl -n pakdee exec db-0 -- \
  psql -U pakdee -d pakdee -c \
  "select 'studio.users' as t, count(*) from studio.users
   union all select 'studio.jobs', count(*) from studio.jobs
   union all select 'voices', count(*) from voices;"
```

The two count listings must match before you send traffic. Jobs that were `running` are marked failed when the API process starts again; retry them from the UI. That is the same behaviour as a Compose restart.

## 6. Move job files / ย้ายไฟล์งาน

This copy already ran. Do not run it again. The rsync below copies the Compose `data/` tree onto the k3s volume and overwrites newer files that exist in both. Reverse direction, after the k3s API is scaled to 0, is in [ROLLBACK.md](ROLLBACK.md).

การคัดลอกนี้ทำไปแล้ว อย่ารันซ้ำ rsync ด้านล่างเขียนทับไฟล์บนวอลุ่ม k3s ทิศทางกลับอยู่ใน [ROLLBACK.md](ROLLBACK.md)

```bash
PV="$(kubectl -n pakdee get pvc api-data -o jsonpath='{.spec.volumeName}')"
HOST_PATH="$(kubectl get pv "$PV" -o jsonpath='{.spec.hostPath.path}')"
sudo rsync -aH "$(pwd)/data/" "$HOST_PATH/"

PVB="$(kubectl -n pakdee get pvc api-backups -o jsonpath='{.spec.volumeName}')"
sudo rsync -aH "$(pwd)/backups/" "$(kubectl get pv "$PVB" -o jsonpath='{.spec.hostPath.path}')/"
```

The API image runs as root, matching today's container, so root-owned files from Compose are readable.

## 7. Cutover is done / การตัดรอบเสร็จแล้ว

Do not repeat the old cutover. It stopped Caddy and published Traefik on 80/443. That is not the running topology, and doing it now takes the site off the working edge.

Caddy stays up. Compose `api` and `web` stay stopped (`restart: "no"`). Traefik stays ClusterIP. New app deploys are the k3s workflow on `main`. Check health with:

```bash
curl -fsS https://pakdee-api.cobie.online/health
curl -fsSI https://pakdee-app.cobie.online/ | head
kubectl -n pakdee get pods,svc
kubectl -n kube-system get svc traefik
```

`traefik` must be `ClusterIP`. `api` must be `10.43.204.249` and `web` must be `10.43.26.212`. Port 443 must be Caddy, not `svclb`.

Do not `docker compose down -v`. That deletes `pg_data`. Do not `docker compose up` the API or web. `deploy/up.sh` refuses unless `CONFIRM_COMPOSE_WRITERS=k3s-data-moved-back`, and that phrase is only for the rollback in [ROLLBACK.md](ROLLBACK.md) after k3s data has been copied back.

## 8. Roll back / ย้อนกลับ

Commands for a bad image, a failed cutover, a database restore, and pausing CI deploys are in [ROLLBACK.md](ROLLBACK.md).

คำสั่งย้อนกลับ deploy ที่พัง, สลับทราฟฟิกไม่สำเร็จ, กู้ฐานข้อมูล, และหยุด deploy อัตโนมัติ อยู่ใน [ROLLBACK.md](ROLLBACK.md).

## 9. What happens on every merge / หลัง merge

Push to `main` runs tests, builds both images for `linux/amd64` (`ML=0`, no API key baked into the web image), pushes `:SHA` and `:latest`, renders `deploy/k8s` (`bash deploy/k8s/scripts/render.sh`, which allows Kustomize to read `deploy/db/init`), and replaces the image tags with that SHA. It SSHes in and runs `rollout.sh`. API waits up to 5 minutes (imports are slow), web up to 3 minutes. If the API Deployment fails, CI runs `kubectl rollout undo deployment/api`. If the web Deployment fails, CI undoes web and the API. The database is never rolled back. Set Actions variable `K3S_DEPLOY` to `false` to skip that SSH deploy; details are in [ROLLBACK.md](ROLLBACK.md).

**Run workflow → api_only** rebuilds only the API and `kubectl set image` on `deployment/api`. **install_kite** only runs the Kite script. A normal push does not touch Kite.

In-cluster objects CI does not create: `pakdee-secrets`, `ghcr-pull`, the Traefik HelmChartConfig, and Kite. Those are yours to apply once.

## Troubleshooting / แก้ปัญหา

| Symptom | Check |
| --- | --- |
| CI cannot SSH | `K3S_SSH_KNOWN_HOSTS` must match this host. Re-run `ssh-keyscan`. |
| `ImagePullBackOff` | `ghcr-pull` and package visibility. `kubectl -n pakdee describe pod` |
| API not ready | `kubectl -n pakdee logs deploy/api`. `DATABASE_URL` host is `db`. Password matches `POSTGRES_PASSWORD`. |
| Certificate stuck | Cloudflare Always Use HTTPS, port 80, DNS still pointing at the old Caddy during the challenge. `kubectl -n kube-system logs deploy/traefik` |
| Traefik not listening on 443 | Expected. Caddy owns 443. `kubectl -n kube-system get svc traefik` must say ClusterIP. Do not run `enable-ingress.sh`. |
| Kite asks for a password you never set | Someone else opened the URL first, or you are on a fresh PVC. |
| Client IP is a Cloudflare address | Optional: set `ports.websecure.forwardedHeaders.trustedIPs` to the current Cloudflare ranges (`https://www.cloudflare.com/ips-v4`). Do not set `insecure: true` while 443 is open to the world. |
