-- Migration: Add team deprecation support
-- Purpose: Enable soft-deletion of teams for merge feature
-- This is Phase 1.1 of the team merge implementation
--
-- IMPORTANT: This allows marking teams as deprecated without deleting them,
-- which preserves all historical data (games, rankings, audit trails).

-- Add soft deprecation column
-- Default FALSE means no existing behavior changes
ALTER TABLE teams
ADD COLUMN IF NOT EXISTS is_deprecated BOOLEAN DEFAULT FALSE;

-- Add index for efficiently filtering active teams
-- This partial index only includes non-deprecated teams, making lookups fast
CREATE INDEX IF NOT EXISTS idx_teams_active
ON teams(team_id_master)
WHERE is_deprecated = FALSE;

-- Add index for finding deprecated teams (for admin queries)
CREATE INDEX IF NOT EXISTS idx_teams_deprecated
ON teams(team_id_master)
WHERE is_deprecated = TRUE;

-- Add composite index for common query pattern (age_group + gender + active)
CREATE INDEX IF NOT EXISTS idx_teams_cohort_active
ON teams(age_group, gender)
WHERE is_deprecated = FALSE;

-- Documentation
COMMENT ON COLUMN teams.is_deprecated IS
  'Soft deletion flag for team merges. When TRUE, team is excluded from rankings '
  'and active queries but all historical data (games, rankings) is preserved. '
  'Set via execute_team_merge() function, never delete teams directly.';

-- Verify the column was added
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'teams' AND column_name = 'is_deprecated'
    ) THEN
        RAISE EXCEPTION 'Migration failed: is_deprecated column not created';
    END IF;

    RAISE NOTICE 'Migration successful: is_deprecated column added to teams table';
END $$;
