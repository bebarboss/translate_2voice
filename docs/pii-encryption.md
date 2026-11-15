# Actor payout encryption at rest

เลขประจำตัวผู้เสียภาษี (`tax_id`) และเลขบัญชี (`account_no`) ของนักพากย์ถูกเข้ารหัสในแอปก่อนลงฐานข้อมูล สคีมาคือ Postgres `studio` (มี SQLite สำรองสำหรับโหมดไฟล์)

This change is staged. It adds columns and dual-writes. It does not drop the plaintext columns, and it does not run SQL against production.

## What is stored

| Table | Plaintext (kept for now) | New columns |
| --- | --- | --- |
| `studio.actor_payment` | `tax_id`, `account_no` | `tax_id_enc`, `tax_id_hmac`, `account_no_enc` |
| `studio.actor_payouts` | `tax_id` (copied on payout) | `tax_id_enc`, `tax_id_hmac` |

`account_no` is not copied onto payouts, so there is no `account_no_enc` there.

Ciphertext format: `v<version>:` + base64(12-byte nonce ‖ AES-256-GCM ciphertext). Each value gets a new nonce. The GCM additional data is `table:column:row_id`, so a blob cannot be moved to another row or column. `row_id` is `actor_payment.user_id` or `actor_payouts.id`.

`tax_id_hmac` is HMAC-SHA256 of the tax id after spaces and hyphens are removed. The remainder must be ASCII digits `0-9`. Thai digits and fullwidth digits are rejected, not converted. Payment rows use the index for lookup and uniqueness. Payout rows use a non-unique index because one person is paid more than once. Encryption and the HMAC run only after that check.

Reads prefer ciphertext. If the encrypted column is empty, the plaintext column is used. If ciphertext is present and decryption fails, the read fails. Authorized paths still return the full value: `GET /admin/actors/{id}/payment`, the withholding CSV, and `/auth/export`. Masking on the actor's own page still keeps the last 4 characters. The CSV formula guard (`csv_text`) is unchanged.

## Keys

Three environment variables, all from Secret `pakdee-pii`. Never commit the values, and do not paste them into a shell command, a ticket, or this file.

| Variable | Meaning |
| --- | --- |
| `PII_ENC_KEYS` | Comma-separated `version:base64`. Each key is 32 bytes. Example shape: `1:<base64>,2:<base64>` |
| `PII_ENC_ACTIVE_VERSION` | Version used for new writes, such as `1` or `v1`. Older versions stay in `PII_ENC_KEYS` so old rows still decrypt. |
| `PII_HMAC_KEY` | Separate 32-byte key for the tax-id blind index. |

Generate each key with `openssl rand -base64 32`.

If any of the three is missing, the API refuses to start. That is the production behavior. `PII_ENC_DEV_EPHEMERAL=1` generates a process-local key for tests and a local API only. It is ignored when `KUBERNETES_SERVICE_HOST` is set, and the backfill command refuses it. Do not set that flag in the cluster. Do not put it in `config.env`.

The API deployment references the Secret with `secretKeyRef`. The pod does not start until `pakdee-pii` exists. `deploy/k8s/pii-secret.example.yaml` is an empty example and is not applied by Kustomize.

## 1. Generate keys without leaving them in shell history

Run this on a trusted admin machine, not in a recorded terminal and not with `set -x`.

```bash
set +o history
unset HISTFILE
umask 077
d=$(mktemp -d)
chmod 700 "$d"
openssl rand -base64 32 | tr -d '\n' > "$d/enc_v1"
openssl rand -base64 32 | tr -d '\n' > "$d/hmac"
python3 - "$d" <<'PY'
import pathlib, sys, base64
d = pathlib.Path(sys.argv[1])
enc = (d / "enc_v1").read_text().strip()
hmac_key = (d / "hmac").read_text().strip()
if len(base64.b64decode(enc)) != 32 or len(base64.b64decode(hmac_key)) != 32:
    raise SystemExit("expected 32-byte keys")
(d / "pii.env").write_text(
    "PII_ENC_ACTIVE_VERSION=1\n"
    f"PII_ENC_KEYS=1:{enc}\n"
    f"PII_HMAC_KEY={hmac_key}\n"
)
(d / "pii.env").chmod(0o600)
print("key lengths ok")
PY
```

The script prints `key lengths ok`. It does not print the keys. Leave `$d` in place until the age backup and the Secret both exist, then shred it (step 4).

## 2. Back up the keys with age

The owner holds the age private key. Only the public key (`age1...`) is used to encrypt. If the owner does not have a key yet, they create it on their own computer and keep the private file offline. Do not run `age-keygen` on the server and then delete the private key.

On the owner's machine:

```bash
age-keygen -o "$HOME/keys/pakdee-pii-age.txt"
```

That command prints the public key once. Copy that public key to the admin machine (it is not secret). Then, on the admin machine, with `OWNER_AGE_PUB` set to that public key:

```bash
age -r "$OWNER_AGE_PUB" -o "$HOME/pakdee-pii-keys.age" "$d/pii.env"
```

Store `pakdee-pii-keys.age` somewhere durable (an offline disk or a password-manager attachment). The private key stays with the owner. Losing both the cluster Secret and this backup makes the ciphertext unreadable. The plaintext columns still exist until a later change, but new writes after that loss cannot be decrypted.

## 3. Create the Kubernetes Secret

Still on the admin machine, from the directory that is not recording history:

```bash
kubectl -n pakdee create secret generic pakdee-pii \
  --from-env-file="$d/pii.env" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n pakdee get secret pakdee-pii \
  -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}'
```

The second command prints the key names only. You should see `PII_ENC_ACTIVE_VERSION`, `PII_ENC_KEYS`, and `PII_HMAC_KEY`.

## 4. Shred the plaintext

```bash
shred -u "$d/pii.env" "$d/enc_v1" "$d/hmac" || rm -P "$d/pii.env" "$d/enc_v1" "$d/hmac"
rmdir "$d"
```

## 5. Add the columns

Fresh databases already have the columns from `deploy/db/init/02_studio_accounts.sql`. An existing database does not re-run init. Apply the additive file yourself, after a backup, before the image that dual-writes is rolled out. This repository does not apply it in CI and does not apply it on API startup.

From a checkout, with the SQL file on your machine:

```bash
kubectl -n pakdee exec -i statefulset/db -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < backend/supabase/migrations/20261112010000_actor_pii_columns.sql
```

The file only adds nullable columns and indexes. It is safe to run again. It does not print row values and it does not drop `tax_id` or `account_no`.

If `CREATE UNIQUE INDEX` fails, two payment rows already share a blind index. Do not select `tax_id`. Count the index values instead:

```sql
SELECT tax_id_hmac, count(*)
FROM studio.actor_payment
WHERE tax_id_hmac IS NOT NULL AND tax_id_hmac <> ''
GROUP BY tax_id_hmac
HAVING count(*) > 1;
```

SQLite (the file backend) adds the same columns the next time the API opens `accounts.db`. Postgres does not.

## 6. Roll out and backfill

Roll out the API only after `pakdee-pii` exists and the SQL has been applied. The new pod loads the keys at startup and exits if they are missing.

Backfill copies plaintext into the new columns. It skips rows that already have ciphertext, so a second run changes nothing. `--dry-run` does not write. Output is counts only.

```bash
kubectl -n pakdee exec deployment/api -- python -m app.pii_backfill --dry-run --count-only
kubectl -n pakdee exec deployment/api -- python -m app.pii_backfill --batch 200 --count-only
```

From a local checkout with the same three variables in the environment (still not on the command line):

```bash
python backend/scripts/backfill_actor_pii.py --dry-run --count-only
```

A conflict count means two payment rows normalize to the same tax id. The first row (by `user_id`) is encrypted. The other is left unchanged and counted as `conflicts`. The command does not print either value.

After backfill, check versions without reading the column contents:

```sql
SELECT split_part(tax_id_enc, ':', 1) AS version, count(*)
FROM studio.actor_payment
WHERE tax_id_enc IS NOT NULL AND tax_id_enc <> ''
GROUP BY 1;
```

## 7. Restore

On the owner's machine, decrypt to a mode-0600 file. The private key is the file from `age-keygen`. It is not in this repository.

```bash
umask 077
d=$(mktemp -d)
age -d -i "$HOME/keys/pakdee-pii-age.txt" -o "$d/pii.env" pakdee-pii-keys.age
```

Copy that env file to the admin machine by a channel you trust, apply it with the same `kubectl create secret ... --from-env-file` command as step 3, restart the API, then shred the env file on both machines. Do not copy the age private key to the server.

```bash
kubectl -n pakdee rollout restart deployment/api
kubectl -n pakdee rollout status deployment/api
```

## 8. Rotate the encryption key

Keep every old version in `PII_ENC_KEYS` until a later rewrap has rewritten every ciphertext. This change does not rewrap existing rows. New writes use the active version. Old rows still decrypt.

On the admin machine, with history off:

```bash
set +o history
unset HISTFILE
umask 077
d=$(mktemp -d)
chmod 700 "$d"
kubectl -n pakdee get secret pakdee-pii -o json > "$d/secret.json"
python3 - "$d" <<'PY'
import json, sys, base64, pathlib
d = pathlib.Path(sys.argv[1])
data = json.loads((d / "secret.json").read_text())["data"]
lines = []
for key in ("PII_ENC_ACTIVE_VERSION", "PII_ENC_KEYS", "PII_HMAC_KEY"):
    lines.append(key + "=" + base64.b64decode(data[key]).decode())
path = d / "pii.env"
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
(d / "secret.json").unlink()
PY
openssl rand -base64 32 | tr -d '\n' > "$d/enc_new"
python3 - "$d" <<'PY'
import pathlib, sys, base64
d = pathlib.Path(sys.argv[1])
env = {}
for line in (d / "pii.env").read_text().splitlines():
    k, v = line.split("=", 1)
    env[k] = v
keys = {}
for part in env["PII_ENC_KEYS"].split(","):
    ver, raw = part.split(":", 1)
    keys[int(ver.lstrip("v") or ver)] = raw
new = (d / "enc_new").read_text().strip()
if len(base64.b64decode(new)) != 32:
    raise SystemExit("new key must be 32 bytes")
nxt = max(keys) + 1
keys[nxt] = new
env["PII_ENC_KEYS"] = ",".join(f"{ver}:{keys[ver]}" for ver in sorted(keys))
env["PII_ENC_ACTIVE_VERSION"] = str(nxt)
text = "".join(f"{k}={env[k]}\n" for k in ("PII_ENC_ACTIVE_VERSION", "PII_ENC_KEYS", "PII_HMAC_KEY"))
(d / "pii.env").write_text(text)
print(f"active version is now {nxt}; previous versions kept")
PY
```

Age-encrypt `$d/pii.env` again (step 2) so the backup matches the new set. Apply the Secret (step 3). Then shred the plaintext and restart the API:

```bash
shred -u "$d/pii.env" "$d/enc_new" || rm -P "$d/pii.env" "$d/enc_new"
rmdir "$d"
kubectl -n pakdee rollout restart deployment/api
```

Do not delete an old version from `PII_ENC_KEYS` until `split_part` shows that version is unused. Rewrapping old ciphertext is a later change.

The HMAC key is separate. Rotating it changes every `tax_id_hmac` and is not part of this procedure.

## Later: drop plaintext columns

Do not run this yet. Run it only in a future change, after every payment and payout row has ciphertext, reads have been using those columns, and a backup of the keys exists.

```sql
alter table studio.actor_payment drop column tax_id;
alter table studio.actor_payment drop column account_no;
alter table studio.actor_payouts drop column tax_id;
```

The application would then have to stop writing those columns. That code is not in this change.
