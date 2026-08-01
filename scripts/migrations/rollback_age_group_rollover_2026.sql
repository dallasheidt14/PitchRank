-- Migration: Roll back the 2026-27 age-group rollover
-- Date: 2026-08-01
-- Purpose: Restore teams.age_group and rankings_full.age_group from the backup
--          tables written by supabase/migrations/20260801000000_age_group_rollover_2026_27.sql
--
-- No BEGIN/COMMIT in this file: the operator supplies the transaction, same as
-- the migration, so the counts below can be checked before COMMIT.
--
-- Restores only rows present when the snapshot was taken; Step 3 counts the rest.
--
-- EXPIRES at the first post-roll ranking run. That run re-anchors scores and
-- recomputes the merged u19 normalizations, and restoring labels undoes neither.
-- Check for in-flight ranking runs before relying on this file.

-- =====================================================
-- Step 1: Restore prior labels
-- =====================================================
-- Rows whose label never changed are skipped, so a partial roll restores just
-- as cleanly as a complete one.

UPDATE public.teams t SET age_group = b.age_group
FROM public.teams_age_rollover_backup_2026 b
WHERE t.team_id_master = b.team_id_master AND t.age_group <> b.age_group;

UPDATE public.rankings_full r SET age_group = b.age_group
FROM public.rankings_full_age_rollover_backup_2026 b
WHERE r.team_id = b.team_id AND r.age_group <> b.age_group;

-- =====================================================
-- Step 2: Refresh planner statistics
-- =====================================================
-- Same reason as the forward migration: four indexes lead with age_group, and a
-- stale plan on idx_rankings_full_age_gender empties the ranking pages.

ANALYZE public.teams;
ANALYZE public.rankings_full;

-- =====================================================
-- Step 3: Verify -- run these BEFORE COMMIT
-- =====================================================
/*
-- RUN THIS FIRST. Every check below is a "zero mismatches" test, and zero is
-- also what they return when the backup is invisible to this role -- which the
-- forward migration's ENABLE ROW LEVEL SECURITY makes reachable. These are
-- absolute magnitudes, so they separate "nothing was wrong" from "nothing was
-- seen". Both backup counts must be NON-ZERO, and rows_restored must be
-- non-zero whenever a roll was actually applied.
SELECT
  (SELECT COUNT(*) FROM public.teams_age_rollover_backup_2026)          AS teams_backed_up,
  (SELECT COUNT(*) FROM public.rankings_full_age_rollover_backup_2026)  AS rankings_backed_up,
  (SELECT COUNT(*) FROM public.teams t
     JOIN public.teams_age_rollover_backup_2026 b USING (team_id_master)
   WHERE t.age_group = b.age_group)                                     AS rows_restored;

-- Every row matches its snapshot again. Expect 0 from both.
SELECT COUNT(*)
FROM public.teams t
JOIN public.teams_age_rollover_backup_2026 b USING (team_id_master)
WHERE t.age_group IS DISTINCT FROM b.age_group;

SELECT COUNT(*)
FROM public.rankings_full r
JOIN public.rankings_full_age_rollover_backup_2026 b USING (team_id)
WHERE r.age_group IS DISTINCT FROM b.age_group;

-- Rows created after the snapshot, which no restore can reach. Not necessarily
-- zero -- scrapers insert teams continuously. Judge whether the count is small
-- enough to accept; these rows keep their post-roll labels either way.
SELECT
  (SELECT COUNT(*) FROM public.teams t
     LEFT JOIN public.teams_age_rollover_backup_2026 b USING (team_id_master)
   WHERE b.team_id_master IS NULL)                         AS teams_created_after_snapshot,
  (SELECT COUNT(*) FROM public.rankings_full r
     LEFT JOIN public.rankings_full_age_rollover_backup_2026 b USING (team_id)
   WHERE b.team_id IS NULL)                                AS rankings_created_after_snapshot;

-- Census, to compare against the pre-roll numbers.
SELECT age_group, COUNT(*) FROM public.teams GROUP BY 1 ORDER BY 1;
SELECT age_group, COUNT(*) FROM public.rankings_full GROUP BY 1 ORDER BY 1;
*/

-- =====================================================
-- Step 4: Drop the backups
-- =====================================================
-- Dropping them re-arms the forward migration's guard, so this is part of
-- completing a rollback rather than cleanup. Run only once the counts check out
-- and the restore is committed.
--
-- DROP TABLE public.teams_age_rollover_backup_2026;
-- DROP TABLE public.rankings_full_age_rollover_backup_2026;
--
-- Then clear the migration history, which dropping the backups does not touch:
--   supabase migration repair --status reverted 20260801000000
-- Without it the ledger still records the rollover as applied, so the next
-- `supabase db push` skips the file while the database sits pre-roll.
