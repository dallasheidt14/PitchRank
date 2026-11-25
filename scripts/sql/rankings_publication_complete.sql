-- Whether this week's rankings publication is complete. One row; read-only.
--
-- Two readers send this file unchanged: scripts/check_scheduled_jobs.py, through the Supabase
-- Management API's read-only query endpoint, and the after-ranking follow-up, through the
-- read-only Supabase MCP execute_sql. Keep it one SELECT with no trailing statement, and keep
-- the output column names: both readers depend on them.
--
-- Output columns:
--   read_only               'on' when the transaction was read-only; readers refuse anything else
--   ranking_start           the latest Monday 12:30 UTC ranking start at or before now()
--   row_count               rankings_full rows
--   stale_rows              rows with no last_calculated, or one before ranking_start
--   newest_calculated       the newest last_calculated
--   previous_snapshot_date  the newest ranking_history snapshot dated before ranking_start's UTC date
--   previous_snapshot_rows  that snapshot's row count; NULL when there is no such snapshot
--   complete                rows exist, none is stale, and they number at least 95% of that snapshot
--
-- Tests pin the start inside their transaction with:
--   SET LOCAL pitchrank.ranking_start = '<timestamptz>';
--
-- The baseline is dated before the run's start, not before its publication. The calculator dates
-- its own snapshot when the run starts and writes it before publishing, so a run that crosses
-- midnight UTC would otherwise be compared with its own snapshot.
WITH this_week AS (
  -- This week's Monday 12:30 UTC, the ranking workflow's cron, as a UTC wall-clock time.
  SELECT date_trunc('week', now() AT TIME ZONE 'UTC') + interval '12 hours 30 minutes' AS monday_start
),
params AS (
  SELECT coalesce(
           nullif(current_setting('pitchrank.ranking_start', true), '')::timestamptz,
           (CASE WHEN w.monday_start <= now() AT TIME ZONE 'UTC' THEN w.monday_start
                 ELSE w.monday_start - interval '7 days'
            END) AT TIME ZONE 'UTC'
         ) AS ranking_start
  FROM this_week w
),
published AS (
  SELECT count(*) AS row_count,
         count(*) FILTER (WHERE r.last_calculated IS NULL OR r.last_calculated < p.ranking_start) AS stale_rows,
         max(r.last_calculated) AS newest_calculated
  FROM public.rankings_full r CROSS JOIN params p
),
previous AS (
  SELECT h.snapshot_date, count(*) AS snapshot_rows
  FROM public.ranking_history h
  WHERE h.snapshot_date = (
    SELECT max(snapshot_date) FROM public.ranking_history
    WHERE snapshot_date < (SELECT (ranking_start AT TIME ZONE 'UTC')::date FROM params)
  )
  GROUP BY h.snapshot_date
)
SELECT current_setting('transaction_read_only') AS read_only,
       p.ranking_start, pub.row_count, pub.stale_rows, pub.newest_calculated,
       prev.snapshot_date AS previous_snapshot_date, prev.snapshot_rows AS previous_snapshot_rows,
       (pub.row_count > 0 AND pub.stale_rows = 0 AND prev.snapshot_rows IS NOT NULL
        AND pub.row_count >= 0.95 * prev.snapshot_rows) AS complete
FROM params p CROSS JOIN published pub LEFT JOIN previous prev ON true
