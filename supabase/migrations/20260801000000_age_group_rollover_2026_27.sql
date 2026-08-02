-- Migration: Age-group rollover for the 2026-27 season
-- Date: 2026-08-01
-- Purpose: US youth soccer switches from calendar-birth-year cohorts to an
--          Aug 1 - Jul 31 window, so every team moves up exactly one age group.
--          Nothing is deleted, no history moves, and no ratings change here.
--
-- Driven off the current age_group label, not birth_year: birth_year is ~91%
-- NULL, so a birth-year approach would reach under 9% of rows.
--
-- The map is an explicit WHEN list and never arithmetic, because a naive +1 on
-- u19 produces u20 -- which the ranking calculator quarantines and then DELETEs
-- from rankings_full.  That is irreversible.
--
-- No BEGIN/COMMIT in this file: the operator supplies the transaction so the
-- count checks in Step 5 can run before COMMIT.  Run as postgres/service-role.
-- An UPDATE without a matching SELECT policy returns 0 rows with no error, so a
-- clean exit proves nothing -- the counts are the proof.

-- =====================================================
-- Step 1: Preconditions
-- =====================================================
-- A re-run would double-roll every team.  Either backup table existing is the
-- marker, so a half-finished rollback that dropped only one still aborts here
-- rather than failing partway through Step 2.  Dropping both, which completes a
-- rollback, re-arms this file.
--
-- The roll matches labels literally, so anything outside the stored cohort set
-- would be passed over and left a cohort behind.  The pattern below pins the set
-- itself (u0 and u3-u21), not merely the shape: a shape-only check would accept
-- 'u07' and 'u99', which normalizers elsewhere can produce and which no CASE arm
-- handles.

DO $$
DECLARE
  bad text;
BEGIN
  IF to_regclass('public.teams_age_rollover_backup_2026') IS NOT NULL
     OR to_regclass('public.rankings_full_age_rollover_backup_2026') IS NOT NULL THEN
    RAISE EXCEPTION 'Rollover already applied. Aborting.';
  END IF;

  SELECT string_agg(DISTINCT quote_literal(age_group), ', ') INTO bad
  FROM public.teams WHERE age_group !~ '^u(0|[3-9]|1[0-9]|2[01])$';
  IF bad IS NOT NULL THEN
    RAISE EXCEPTION 'teams holds unsupported age_group labels the roll would skip: %', bad;
  END IF;

  SELECT string_agg(DISTINCT quote_literal(age_group), ', ') INTO bad
  FROM public.rankings_full WHERE age_group !~ '^u(0|[3-9]|1[0-9]|2[01])$';
  IF bad IS NOT NULL THEN
    RAISE EXCEPTION 'rankings_full holds unsupported age_group labels the roll would skip: %', bad;
  END IF;
END $$;

-- =====================================================
-- Step 2: Snapshot prior labels
-- =====================================================
-- Nothing else records prior values of age_group -- no audit trail, no history
-- table.  These two tables are the entire rollback plan.

-- Schema-qualified throughout: the Step 1 guard looks for these in public, so an
-- unqualified CREATE under a search_path like 'ops, public' would land them
-- elsewhere and leave the guard blind to a roll that already happened.
--
-- Lock first.  Scrapers insert teams continuously and the operator's transaction
-- does not serialize these statements by itself, so without this a row committed
-- between the snapshot and the UPDATE is absent from the backup, gets rolled,
-- and cannot be restored.

LOCK TABLE public.teams, public.rankings_full IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE public.teams_age_rollover_backup_2026 AS
  SELECT team_id_master, age_group, now() AS snapshot_at FROM public.teams;

CREATE TABLE public.rankings_full_age_rollover_backup_2026 AS
  SELECT team_id, age_group, now() AS snapshot_at FROM public.rankings_full;

-- CREATE TABLE AS does not inherit RLS, and public is exposed over PostgREST,
-- so without this both snapshots would be reachable with the anon key -- and a
-- deleted snapshot is an unrecoverable rollover.  No policy is added because
-- only the service role needs to read them.
ALTER TABLE public.teams_age_rollover_backup_2026 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rankings_full_age_rollover_backup_2026 ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.teams_age_rollover_backup_2026 FROM anon, authenticated;
REVOKE ALL ON public.rankings_full_age_rollover_backup_2026 FROM anon, authenticated;

-- =====================================================
-- Step 3: Roll each table up one cohort
-- =====================================================
-- One statement per table.  Sequential per-cohort updates would double-roll
-- (u9->u10, then that same row u10->u11);
--
-- No is_deprecated filter -- deprecated rows roll too, which keeps the backup
-- and the restore symmetric.


UPDATE public.teams SET age_group = CASE age_group
    WHEN 'u7'  THEN 'u8'  WHEN 'u8'  THEN 'u9'  WHEN 'u9'  THEN 'u10'
    WHEN 'u10' THEN 'u11' WHEN 'u11' THEN 'u12' WHEN 'u12' THEN 'u13'
    WHEN 'u13' THEN 'u14' WHEN 'u14' THEN 'u15' WHEN 'u15' THEN 'u16'
    WHEN 'u16' THEN 'u17' WHEN 'u17' THEN 'u19' WHEN 'u18' THEN 'u19'
    ELSE age_group
  END
WHERE age_group IN ('u7','u8','u9','u10','u11','u12','u13','u14','u15','u16','u17','u18');

UPDATE public.rankings_full SET age_group = CASE age_group
    WHEN 'u7'  THEN 'u8'  WHEN 'u8'  THEN 'u9'  WHEN 'u9'  THEN 'u10'
    WHEN 'u10' THEN 'u11' WHEN 'u11' THEN 'u12' WHEN 'u12' THEN 'u13'
    WHEN 'u13' THEN 'u14' WHEN 'u14' THEN 'u15' WHEN 'u15' THEN 'u16'
    WHEN 'u16' THEN 'u17' WHEN 'u17' THEN 'u19' WHEN 'u18' THEN 'u19'
    ELSE age_group
  END
WHERE age_group IN ('u7','u8','u9','u10','u11','u12','u13','u14','u15','u16','u17','u18');

-- =====================================================
-- Step 4: Refresh planner statistics
-- =====================================================
-- Not optional.  Four indexes lead with age_group.  A bad plan on
-- idx_rankings_full_age_gender has previously caused 57014 statement timeouts
-- and rendered ranking pages empty during frontend builds.


ANALYZE public.teams;
ANALYZE public.rankings_full;

-- =====================================================
-- Step 5: Verify -- run these BEFORE COMMIT
-- =====================================================
/*
-- Census. Keep these numbers; they are what the post-COMMIT checks compare to.
SELECT age_group, COUNT(*) FROM public.teams GROUP BY 1 ORDER BY 1;
SELECT age_group, COUNT(*) FROM public.rankings_full GROUP BY 1 ORDER BY 1;

-- RUN THIS FIRST. Every check below is a "zero mismatches" test, and zero is
-- also what they return when the backup is empty or the role cannot see the
-- rows -- the silent no-op described in the header. These are absolute
-- magnitudes, so they distinguish "nothing was wrong" from "nothing was seen".
-- Both counts must be NON-ZERO.
SELECT
  (SELECT COUNT(*) FROM public.teams_age_rollover_backup_2026)          AS teams_backed_up,
  (SELECT COUNT(*) FROM public.rankings_full_age_rollover_backup_2026)  AS rankings_backed_up;

-- Rows the roll actually moved, counted positively, beside the number that
-- should have moved. The two must be EQUAL and non-zero. Both are computed here
-- so neither has to be derived by hand mid-transaction.
SELECT
  (SELECT COUNT(*) FROM public.teams t
     JOIN public.teams_age_rollover_backup_2026 b USING (team_id_master)
   WHERE t.age_group IS DISTINCT FROM b.age_group)                      AS rows_moved,
  (SELECT COUNT(*) FROM public.teams_age_rollover_backup_2026
   WHERE age_group IN ('u7','u8','u9','u10','u11','u12','u13','u14','u15','u16','u17','u18'))
                                                                        AS rows_expected;

-- ANALYZE reports success even when it silently skipped a table it could not
-- analyze, so confirm it landed. stats_fetch_consistency defaults to 'cache',
-- which pins an object's first stats read for the rest of the transaction, so
-- clear the snapshot first or an earlier read in this session masks the result.
-- Both rows must come back true.
SELECT pg_stat_clear_snapshot();
SELECT relname, last_analyze, last_analyze >= transaction_timestamp() AS analyzed_this_txn
FROM pg_stat_user_tables
WHERE schemaname = 'public' AND relname IN ('teams', 'rankings_full');

-- Every row landed exactly where the map says. Expect 0 rows from both.
-- This is the check that catches a double-roll: a twice-rolled row shows up
-- here as from_age u9 -> to_age u11.
SELECT b.age_group AS from_age, t.age_group AS to_age, COUNT(*)
FROM public.teams t
JOIN public.teams_age_rollover_backup_2026 b USING (team_id_master)
WHERE t.age_group IS DISTINCT FROM CASE b.age_group
    WHEN 'u7'  THEN 'u8'  WHEN 'u8'  THEN 'u9'  WHEN 'u9'  THEN 'u10'
    WHEN 'u10' THEN 'u11' WHEN 'u11' THEN 'u12' WHEN 'u12' THEN 'u13'
    WHEN 'u13' THEN 'u14' WHEN 'u14' THEN 'u15' WHEN 'u15' THEN 'u16'
    WHEN 'u16' THEN 'u17' WHEN 'u17' THEN 'u19' WHEN 'u18' THEN 'u19'
    ELSE b.age_group
  END
GROUP BY 1, 2;

SELECT b.age_group AS from_age, r.age_group AS to_age, COUNT(*)
FROM public.rankings_full r
JOIN public.rankings_full_age_rollover_backup_2026 b USING (team_id)
WHERE r.age_group IS DISTINCT FROM CASE b.age_group
    WHEN 'u7'  THEN 'u8'  WHEN 'u8'  THEN 'u9'  WHEN 'u9'  THEN 'u10'
    WHEN 'u10' THEN 'u11' WHEN 'u11' THEN 'u12' WHEN 'u12' THEN 'u13'
    WHEN 'u13' THEN 'u14' WHEN 'u14' THEN 'u15' WHEN 'u15' THEN 'u16'
    WHEN 'u16' THEN 'u17' WHEN 'u17' THEN 'u19' WHEN 'u18' THEN 'u19'
    ELSE b.age_group
  END
GROUP BY 1, 2;

-- Source cohorts are empty, the row count is unchanged, and neither table holds
-- a malformed label. Expect 0, 0, 0, 0.
SELECT
  (SELECT COUNT(*) FROM public.teams WHERE age_group IN ('u7','u18'))          AS drained_cohorts,
  (SELECT COUNT(*) FROM public.teams) - (SELECT COUNT(*) FROM public.teams_age_rollover_backup_2026)
                                                                        AS row_count_drift,
  (SELECT COUNT(*) FROM public.teams WHERE age_group !~ '^u[0-9]{1,2}$')       AS malformed_labels,
  (SELECT COUNT(*) FROM public.rankings_full WHERE age_group !~ '^u[0-9]{1,2}$')
                                                                        AS malformed_labels_rankings;

-- rankings_full follows a different shape, and that is expected: it holds no
-- rows below u10 and no u18 (18 folds to 19 at write time), so u10 empties out
-- to u11 with nothing arriving from u9. The U10 board stays empty until the
-- next ranking run repopulates it from the newly-u10 teams.
SELECT COUNT(*) FROM public.rankings_full WHERE age_group = 'u10';
*/

-- =====================================================
-- Step 6: After COMMIT
-- =====================================================
-- Run each in its own transaction -- the RAISE EXCEPTION and the restore writes
-- would otherwise poison the production transaction.
--   1. Re-run this file. It must abort on the Step 1 guard. Roll back.
--   2. Run scripts/migrations/rollback_age_group_rollover_2026.sql. Counts must
--      return to pre-roll. Roll back, leaving the roll in place.
--   3. Record the version as applied:
--        supabase migration repair --status applied 20260801000000
--      A hand-applied file leaves no row in supabase_migrations.schema_migrations,
--      so the next `supabase db push` would try to re-apply it, hit the Step 1
--      guard, and abort -- blocking every unrelated migration in that push.
-- Then dispatch the ranking workflow to repopulate U10, renumber the merged u19
-- cohort, and re-anchor scores. Purge and redeploy before checking boards: page
-- caching means a stale page satisfies every check even if the run failed.
