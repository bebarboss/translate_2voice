-- Additive columns for application-level encryption of actor tax_id and account_no.
-- Idempotent. Does not read or print column values.
-- Does not drop plaintext tax_id or account_no. That later step is documented in
-- docs/pii-encryption.md and is not part of this change.
--
-- Fresh databases get the columns from deploy/db/init/02_studio_accounts.sql.
-- Postgres init does not re-run after the first boot. Apply this file by hand
-- on a database that already has data, before the dual-write release.
-- The exact command is in docs/pii-encryption.md. This file only adds nullable
-- columns and indexes.

alter table studio.actor_payment add column if not exists tax_id_enc text;
alter table studio.actor_payment add column if not exists tax_id_hmac text;
alter table studio.actor_payment add column if not exists account_no_enc text;

create unique index if not exists actor_payment_tax_hmac_uniq
  on studio.actor_payment (tax_id_hmac)
  where tax_id_hmac is not null and tax_id_hmac <> '';

alter table studio.actor_payouts add column if not exists tax_id_enc text;
alter table studio.actor_payouts add column if not exists tax_id_hmac text;

create index if not exists actor_payouts_tax_hmac
  on studio.actor_payouts (tax_id_hmac);
