-- Migration: Add age_group and mls_division to games table for Modular11
-- Date: 2026-01-18
-- Purpose: Allow games with same provider IDs/date/scores but different age groups/divisions
--          to coexist (e.g., 14_U14_HD vs 14_U15_HD playing on same date with same scores)
--          This fixes the composite key constraint issue for Modular11

-- Step 1: Add age_group and mls_division columns to games table
ALTER TABLE public.games
ADD COLUMN IF NOT EXISTS age_group TEXT NULL,
ADD COLUMN IF NOT EXISTS mls_division TEXT NULL;

-- Add comments
COMMENT ON COLUMN public.games.age_group IS 'Age group for the game (e.g., U14, U15). Required for Modular11 to distinguish games with same provider IDs but different age groups.';
COMMENT ON COLUMN public.games.mls_division IS 'MLS division for Modular11 games (HD or AD). Required for Modular11 to distinguish games with same provider IDs and age group but different divisions.';

-- Step 2: Drop the old unique constraint
DROP INDEX IF EXISTS idx_games_unique;

-- Step 3: Create a new unique constraint that includes age_group and mls_division
-- For Modular11: include age_group and mls_division
-- For other providers: age_group and mls_division will be NULL, so they're still unique by the original fields
CREATE UNIQUE INDEX idx_games_unique ON games(
    provider_id, 
    home_provider_id, 
    away_provider_id, 
    game_date,
    COALESCE(home_score, -1),
    COALESCE(away_score, -1),
    COALESCE(age_group, ''),  -- Empty string for NULL (other providers)
    COALESCE(mls_division, '')  -- Empty string for NULL (other providers)
);

-- Step 4: Create index for Modular11 queries by age_group/division
CREATE INDEX IF NOT EXISTS idx_games_modular11_age_division 
ON games(provider_id, age_group, mls_division) 
WHERE age_group IS NOT NULL AND mls_division IS NOT NULL;

COMMENT ON INDEX idx_games_unique IS 'Unique constraint for games. For Modular11, includes age_group and mls_division to allow games with same provider IDs/date/scores but different age groups/divisions (e.g., 14_U14_HD vs 14_U15_HD).';
