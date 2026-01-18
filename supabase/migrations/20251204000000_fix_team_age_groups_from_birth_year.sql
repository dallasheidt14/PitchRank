-- Migration: Fix team age_groups based on birth year in team names
-- Date: 2025-12-04
-- Purpose: Correct teams where age_group doesn't match the birth year in their name
--          (e.g., "ILLINOIS MAGIC FC 2014" should be U12, not U13)
--
-- Formula: age_group = 2025 - birth_year + 1
-- Example: 2025 - 2014 + 1 = 12 → U12

-- =====================================================
-- Step 1: Preview affected teams (run this first)
-- =====================================================

-- This query shows teams that need fixing
-- Run this SELECT first to see what will be updated:

/*
SELECT
    team_id_master,
    team_name,
    age_group AS current_age_group,
    CASE
        WHEN team_name ~ '\b20(1[0-8])\b' THEN
            'u' || (2025 - (2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER) + 1)::TEXT
        ELSE NULL
    END AS expected_age_group,
    CASE
        WHEN team_name ~ '\b20(1[0-8])\b' THEN
            2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER
        ELSE NULL
    END AS extracted_birth_year,
    gender,
    state_code
FROM teams
WHERE
    -- Has a birth year in the name (2010-2018)
    team_name ~ '\b20(1[0-8])\b'
    -- And current age_group doesn't match expected
    AND age_group != 'u' || (2025 - (2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER) + 1)::TEXT
ORDER BY team_name;
*/

-- =====================================================
-- Step 2: Apply the fix
-- =====================================================

-- Update teams where age_group doesn't match birth year in name
UPDATE teams
SET
    age_group = 'u' || (2025 - (2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER) + 1)::TEXT,
    birth_year = 2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER,
    updated_at = NOW()
WHERE
    -- Has a birth year in the name (2010-2018 range for youth soccer)
    team_name ~ '\b20(1[0-8])\b'
    -- And current age_group doesn't match expected
    AND age_group != 'u' || (2025 - (2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER) + 1)::TEXT;

-- =====================================================
-- Step 3: Verify the fix
-- =====================================================

-- Run this after the update to verify no mismatches remain:
/*
SELECT COUNT(*) AS remaining_mismatches
FROM teams
WHERE
    team_name ~ '\b20(1[0-8])\b'
    AND age_group != 'u' || (2025 - (2000 + (regexp_match(team_name, '\b20(1[0-8])\b'))[1]::INTEGER) + 1)::TEXT;
*/

-- =====================================================
-- Notes
-- =====================================================
-- This migration:
-- 1. Extracts 4-digit birth years (2010-2018) from team names
-- 2. Calculates the correct age_group using: 2025 - birth_year + 1
-- 3. Updates both age_group and birth_year columns
-- 4. Only affects teams where there's a mismatch
--
-- After running this migration, you MUST recalculate rankings:
--   python scripts/calculate_rankings.py


