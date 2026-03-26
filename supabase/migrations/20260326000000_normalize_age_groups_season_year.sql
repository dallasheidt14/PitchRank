-- Migration: Normalize age_groups using soccer season year (Aug 1 cutoff)
-- Date: 2026-03-26
-- Purpose: Fix age_group inconsistencies caused by hardcoded CURRENT_YEAR = 2025.
--          Soccer seasons run Aug 1 – Jul 31, so as of March 2026 the season year
--          is still 2025.  Any teams whose age_group was computed with 2026 are
--          one year too high and need correction.
--
-- Season year logic: before Aug 1 → previous calendar year; on/after Aug 1 → current year
-- Right now (March 2026) the season year is 2025.
-- Formula: age_group = 'u' || (2025 - birth_year + 1)

-- =====================================================
-- Step 1: Preview affected teams (run SELECT first)
-- =====================================================
/*
SELECT
    team_id_master,
    team_name,
    age_group AS current_age_group,
    birth_year,
    'u' || (2025 - birth_year + 1)::TEXT AS expected_age_group
FROM teams
WHERE
    birth_year IS NOT NULL
    AND birth_year BETWEEN 2005 AND 2019
    AND age_group != 'u' || (2025 - birth_year + 1)::TEXT
ORDER BY birth_year, team_name
LIMIT 50;
*/

-- =====================================================
-- Step 2: Apply the fix
-- =====================================================

UPDATE teams
SET
    age_group = 'u' || (2025 - birth_year + 1)::TEXT,
    updated_at = NOW()
WHERE
    birth_year IS NOT NULL
    AND birth_year BETWEEN 2005 AND 2019
    AND age_group != 'u' || (2025 - birth_year + 1)::TEXT;

-- =====================================================
-- Step 3: Verify
-- =====================================================
/*
SELECT COUNT(*) AS remaining_mismatches
FROM teams
WHERE
    birth_year IS NOT NULL
    AND birth_year BETWEEN 2005 AND 2019
    AND age_group != 'u' || (2025 - birth_year + 1)::TEXT;
*/
