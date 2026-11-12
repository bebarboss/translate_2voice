-- Read-only audit of historical refund mistakes in schema studio.
-- SELECT only. Wrapped in BEGIN READ ONLY ... ROLLBACK. No INSERT/UPDATE/DELETE/DDL.
--
-- How to run (psql). Do not open a transaction first; BEGIN fails if one is open.
-- The ROLLBACK ends the read-only transaction, so nothing is committed.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/audit/wrong_redub_refunds.sql
--
-- Output is one aggregate row. No email, user id, name, job id, or per-row detail.
-- Amounts are credits (ledger subunits / 100). 1.00 credit = 100 stored units.
--
-- Assumptions
-- 1. A charge ref is either a plain job id (first analysis) or
--    job_id || ':redub:' || N (one re-dub). Job ids contain no LIKE wildcards
--    (% or _), so ref || ':redub:%' matches only that job's re-dubs.
-- 2. A re-dub is charged only after the job has reached done, so a
--    job_id:redub:N charge means the original analysis had succeeded.
-- 3. A refund whose ref is the plain job id and whose created_at is at or
--    after any job_id:redub:N charge on the same account is counted as a
--    wrong refund of the original charge (the failure path passed job_id).
--    The ledger has no failure-event table, so a manual refund of the
--    original after a re-dub was charged is counted the same way.
-- 4. "Re-dub credits never refunded" is the latest re-dub charge at or
--    before that wrong refund which has no refund row with the same ref.
--    Earlier re-dubs are left out (a successful re-dub is not refunded).
--    Duplicate wrong refunds of the same job do not multiply this sum.
-- 5. A refund went to the wrong bucket when its credits column (top-up
--    returned) is greater than the top-up the matched charge took
--    (GREATEST(-charge.credits, 0)). A plan-only charge stores credits = 0
--    and minutes < 0. Refunding that plan portion into users.credits
--    (refund.credits > 0, refund.minutes = 0) matches this test.
--    wrong_bucket_credits is the excess top-up credited, not the plan
--    minutes that were skipped.
-- 6. Several charge rows with the same ref collapse to the earliest id.
--    Every refund row is counted.

BEGIN READ ONLY;

WITH charge_one AS (
  SELECT DISTINCT ON (user_id, ref)
         id, user_id, ref, credits, minutes, created_at
  FROM studio.ledger
  WHERE kind = 'charge' AND ref IS NOT NULL AND ref <> ''
  ORDER BY user_id, ref, id
),
refunds AS (
  SELECT id, user_id, ref, credits, minutes, created_at
  FROM studio.ledger
  WHERE kind = 'refund' AND ref IS NOT NULL AND ref <> ''
),
wrong_redub AS (
  SELECT r.id, r.user_id, r.ref, r.credits, r.minutes, r.created_at
  FROM refunds r
  JOIN charge_one orig
    ON orig.user_id = r.user_id AND orig.ref = r.ref
  WHERE r.ref NOT LIKE '%:redub:%'
    AND EXISTS (
      SELECT 1
      FROM charge_one rd
      WHERE rd.user_id = r.user_id
        AND rd.ref LIKE r.ref || ':redub:%'
        AND rd.created_at <= r.created_at
    )
),
missed_redub AS (
  SELECT DISTINCT ON (rd.user_id, rd.ref)
         GREATEST(-rd.credits, 0) + GREATEST(-rd.minutes, 0) AS units
  FROM wrong_redub w
  JOIN charge_one rd
    ON rd.user_id = w.user_id
   AND rd.ref LIKE w.ref || ':redub:%'
   AND rd.created_at <= w.created_at
  WHERE NOT EXISTS (
          SELECT 1
          FROM refunds rr
          WHERE rr.user_id = rd.user_id AND rr.ref = rd.ref
        )
    AND (rd.created_at, rd.id) = (
          SELECT rd2.created_at, rd2.id
          FROM charge_one rd2
          WHERE rd2.user_id = w.user_id
            AND rd2.ref LIKE w.ref || ':redub:%'
            AND rd2.created_at <= w.created_at
          ORDER BY rd2.created_at DESC, rd2.id DESC
          LIMIT 1
        )
  ORDER BY rd.user_id, rd.ref
),
wrong_bucket AS (
  SELECT (COALESCE(r.credits, 0) - GREATEST(-COALESCE(c.credits, 0), 0)) AS excess_units
  FROM refunds r
  JOIN charge_one c
    ON c.user_id = r.user_id AND c.ref = r.ref
  WHERE COALESCE(r.credits, 0) > GREATEST(-COALESCE(c.credits, 0), 0)
)
SELECT
  (SELECT COUNT(*) FROM wrong_redub) AS wrong_redub_refund_count,
  (SELECT COALESCE(SUM(GREATEST(credits, 0) + GREATEST(minutes, 0)), 0) / 100.0
     FROM wrong_redub) AS wrong_redub_credits_refunded,
  (SELECT COALESCE(SUM(units), 0) / 100.0 FROM missed_redub) AS redub_credits_never_refunded,
  (SELECT COUNT(*) FROM wrong_bucket) AS wrong_bucket_refund_count,
  (SELECT COALESCE(SUM(excess_units), 0) / 100.0 FROM wrong_bucket) AS wrong_bucket_credits;

ROLLBACK;
