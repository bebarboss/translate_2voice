-- READ ONLY. Do not run until the impact review is approved.
-- Reports paid plans replaced by the automatic trial grant from cc68c41
-- (deployed 2026-11-12 ~01:28 UTC). SELECTs only. No writes, no temp tables.
--
-- What the ledger can reconstruct
--   * A kind='trial' row is the grant. Its minutes value is the NEW subscription
--     balance in sub-units (1 credit = 100), including rollover, not a delta.
--   * The previous subscription row was replaced, so plan_id / expires_at /
--     minutes_left of the paid plan are gone from studio.subscriptions.
--   * The previous plan is the latest ledger row before that trial with
--     kind in (subscribe, adjust) and ref not null and ref <> 'trial'.
--     That row's minutes is the balance written when the paid plan started.
--   * charge/refund rows between those two ids are minute deltas.
--     est_remaining = prev_granted + those deltas.
--   * Carry stored on the trial row is max(trial.minutes - 200, 0) when the
--     trial plan is the default 2 credits. est_credits_lost = remaining - carry.
--
-- Limits
--   * Manual POST /billing/trial after the deploy writes the same kind='trial'
--     row as auto-login. Paid users were not offered the button, but a direct
--     API call would look identical.
--   * "Still in term" assumes the paid plan lasts 30 days from that ledger row
--     (starter and pro defaults). A custom BILLING_PLANS duration will mis-label
--     active vs expired. Expired rows were also replaced; their minutes were
--     not spendable. The detail query below keeps only likely-still-in-term.
--   * If remaining was above the 2-credit rollover cap, carry is capped and the
--     loss above the cap is visible only when the charge/refund reconstruction
--     matches the destroyed minutes_left. Manual SQL edits, or minute movements
--     with some other kind, are not in this sum.
--   * Closed accounts keep the ledger but their email is now
--     closed-<id>@deleted.invalid. user_id is the stable key.
--   * Base units are 200 (2 credits). If the trial plan's minutes were not 2,
--     carried_credits and est_credits_lost are wrong.
--   * If one user has more than one kind=trial row after the deploy, the
--     earliest row is the overwrite. Later rows are ignored.

-- Per user. Drop the WHERE clause to include prior paid plans that were likely
-- already expired when the trial replaced the row.
WITH params AS (
  SELECT EXTRACT(EPOCH FROM TIMESTAMPTZ '2026-11-12 01:28:00+00') AS deployed_at,
         200 AS trial_base_units
),
trial_grant AS (
  SELECT l.user_id, l.id, l.created_at, l.minutes, l.note
  FROM studio.ledger l
  CROSS JOIN params p
  WHERE l.kind = 'trial'
    AND l.created_at >= p.deployed_at
),
prev_plan AS (
  SELECT DISTINCT ON (t.user_id)
         t.user_id,
         t.id AS trial_id,
         t.created_at AS trial_at,
         t.minutes AS trial_minutes,
         t.note AS trial_note,
         prev.id AS prev_id,
         prev.kind AS prev_kind,
         prev.ref AS prev_plan,
         prev.created_at AS prev_at,
         prev.minutes AS prev_granted
  FROM trial_grant t
  JOIN studio.ledger prev
    ON prev.user_id = t.user_id
   AND prev.id < t.id
   AND prev.kind IN ('subscribe', 'adjust')
   AND prev.ref IS NOT NULL
   AND prev.ref <> 'trial'
  ORDER BY t.user_id, t.id ASC, prev.id DESC
),
movement AS (
  SELECT pp.user_id,
         COALESCE(SUM(l.minutes) FILTER (WHERE l.kind IN ('charge', 'refund')), 0) AS minute_delta
  FROM prev_plan pp
  LEFT JOIN studio.ledger l
    ON l.user_id = pp.user_id
   AND l.id > pp.prev_id
   AND l.id < pp.trial_id
  GROUP BY pp.user_id
)
SELECT
  pp.user_id,
  u.email,
  pp.prev_plan,
  pp.prev_kind,
  to_timestamp(pp.prev_at) AT TIME ZONE 'UTC' AS prev_plan_at_utc,
  to_timestamp(pp.trial_at) AT TIME ZONE 'UTC' AS trial_at_utc,
  (pp.trial_at < pp.prev_at + 30 * 86400) AS likely_still_in_term,
  ROUND(GREATEST(pp.prev_granted + mv.minute_delta, 0) / 100.0, 2) AS est_remaining_credits,
  ROUND(GREATEST(pp.trial_minutes - p.trial_base_units, 0) / 100.0, 2) AS carried_credits,
  ROUND(
    GREATEST(
      GREATEST(pp.prev_granted + mv.minute_delta, 0)
      - GREATEST(pp.trial_minutes - p.trial_base_units, 0),
      0
    ) / 100.0, 2) AS est_credits_lost
FROM prev_plan pp
JOIN movement mv ON mv.user_id = pp.user_id
JOIN studio.users u ON u.id = pp.user_id
CROSS JOIN params p
WHERE pp.trial_at < pp.prev_at + 30 * 86400
ORDER BY est_credits_lost DESC, pp.user_id;

-- Totals for the same population (likely still inside the 30-day term).
WITH params AS (
  SELECT EXTRACT(EPOCH FROM TIMESTAMPTZ '2026-11-12 01:28:00+00') AS deployed_at,
         200 AS trial_base_units
),
trial_grant AS (
  SELECT l.user_id, l.id, l.created_at, l.minutes
  FROM studio.ledger l
  CROSS JOIN params p
  WHERE l.kind = 'trial'
    AND l.created_at >= p.deployed_at
),
prev_plan AS (
  SELECT DISTINCT ON (t.user_id)
         t.user_id,
         t.id AS trial_id,
         t.created_at AS trial_at,
         t.minutes AS trial_minutes,
         prev.id AS prev_id,
         prev.created_at AS prev_at,
         prev.minutes AS prev_granted
  FROM trial_grant t
  JOIN studio.ledger prev
    ON prev.user_id = t.user_id
   AND prev.id < t.id
   AND prev.kind IN ('subscribe', 'adjust')
   AND prev.ref IS NOT NULL
   AND prev.ref <> 'trial'
  ORDER BY t.user_id, t.id ASC, prev.id DESC
),
movement AS (
  SELECT pp.user_id,
         COALESCE(SUM(l.minutes) FILTER (WHERE l.kind IN ('charge', 'refund')), 0) AS minute_delta
  FROM prev_plan pp
  LEFT JOIN studio.ledger l
    ON l.user_id = pp.user_id
   AND l.id > pp.prev_id
   AND l.id < pp.trial_id
  GROUP BY pp.user_id
),
loss AS (
  SELECT
    GREATEST(
      GREATEST(pp.prev_granted + mv.minute_delta, 0)
      - GREATEST(pp.trial_minutes - p.trial_base_units, 0),
      0
    ) AS lost_units
  FROM prev_plan pp
  JOIN movement mv ON mv.user_id = pp.user_id
  CROSS JOIN params p
  WHERE pp.trial_at < pp.prev_at + 30 * 86400
)
SELECT COUNT(*) AS customers,
       ROUND(COALESCE(SUM(lost_units), 0) / 100.0, 2) AS est_credits_lost_total
FROM loss;
