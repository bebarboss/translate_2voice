-- One ledger row with kind = 'trial' per user (Postgres schema studio).
-- Re-runnable. Does not DELETE or UPDATE customer rows.
--
-- Init SQL (deploy/db/init/02_studio_accounts.sql) creates this index only on an
-- empty data directory. Run this file by hand on a database that already has data.
-- The API also attempts the same guarded CREATE INDEX on its first Postgres
-- connection (pgstore.connect). If the database role cannot create indexes, this
-- file is the step that adds it.
--
-- When any user already has more than one kind='trial' row, the index is skipped
-- and the script still succeeds. Inspect, then create the index yourself:
--   SELECT user_id, COUNT(*)
--   FROM studio.ledger
--   WHERE kind = 'trial'
--   GROUP BY user_id
--   HAVING COUNT(*) > 1;
--   CREATE UNIQUE INDEX ledger_trial_once ON studio.ledger (user_id) WHERE kind = 'trial';

DO $$
DECLARE
  dup_users integer;
BEGIN
  SELECT COUNT(*) INTO dup_users FROM (
    SELECT user_id
    FROM studio.ledger
    WHERE kind = 'trial'
    GROUP BY user_id
    HAVING COUNT(*) > 1
  ) d;

  IF dup_users > 0 THEN
    RAISE WARNING 'ledger_trial_once was NOT created: % user(s) already have more than one kind=trial ledger row. No rows were deleted or updated.', dup_users;
  ELSE
    CREATE UNIQUE INDEX IF NOT EXISTS ledger_trial_once
      ON studio.ledger (user_id)
      WHERE kind = 'trial';
  END IF;
END $$;
