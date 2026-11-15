-- Read-only ledger for ONE account in schema studio.
-- SELECT only. Wrapped in BEGIN READ ONLY ... ROLLBACK. No INSERT/UPDATE/DELETE/DDL.
-- Do not put an account id in this file. Pass it as a psql variable.
-- Do not open a transaction first.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v uid='ACCOUNT_ID' -f scripts/audit/ledger_for_account.sql
--
-- The owner runs this. It is not executed by deploy or by tests.
--
-- First result: that account's ledger rows, oldest first.
--   created_at  unix seconds
--   kind        charge, refund, trial, topup, ...
--   ref         job id, job_id:redub:N, plan id, or null
--   credits     signed top-up delta, stored subunits (100 = 1.00 credit)
--   minutes     signed plan-minute delta, same subunits
-- No email, name, user id, or other profile columns.
--
-- Second result: one comparison row.
--   sum_credits / sum_minutes   sum of the ledger deltas above
--   users_credits               current users.credits (top-up bucket)
--   minutes_left                active subscription only
--                               (expires_at > now); NULL if none is active
-- A charge is negative. A refund or grant is positive. They do not equal
-- the balance by themselves: users_credits changes only from the credits
-- column, minutes_left only from the minutes column while the plan lives.

BEGIN READ ONLY;

SELECT created_at, kind, ref, credits, minutes
FROM studio.ledger
WHERE user_id = :'uid'
ORDER BY created_at, id;

SELECT
  COALESCE(SUM(l.credits), 0) AS sum_credits,
  COALESCE(SUM(l.minutes), 0) AS sum_minutes,
  (SELECT u.credits FROM studio.users u WHERE u.id = :'uid') AS users_credits,
  (SELECT s.minutes_left
     FROM studio.subscriptions s
    WHERE s.user_id = :'uid'
      AND s.expires_at > EXTRACT(EPOCH FROM NOW())) AS minutes_left
FROM studio.ledger l
WHERE l.user_id = :'uid';

ROLLBACK;
