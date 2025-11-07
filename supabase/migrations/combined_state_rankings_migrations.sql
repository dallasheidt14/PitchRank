-- ============================================================================
-- State Rankings View Fix - Combined Migration
-- ============================================================================
-- This migration fixes the state_rankings view to be a filtered view of 
-- national rankings (not a separate calculation) and deprecates the old
-- calculation function and column.
--
-- Apply this SQL via Supabase Dashboard SQL Editor
-- ============================================================================

-- Step 1: Drop existing view (CASCADE to handle any dependencies)
DROP VIEW IF EXISTS state_rankings CASCADE;

-- Step 2: Recreate state_rankings view with essential columns only
-- This is a filtered view of national rankings, not a separate calculation
CREATE OR REPLACE VIEW state_rankings
WITH (security_invoker = true)
AS
SELECT 
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    t.age_group,
    t.gender,
    r.national_rank,  -- National rank (by age/gender)
    r.national_power_score  -- PowerScore (used for sorting within state)
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
WHERE t.state_code IS NOT NULL  -- Only show teams with state codes
ORDER BY 
    t.gender, 
    t.age_group, 
    t.state_code, 
    r.national_power_score DESC;  -- Sort by power_score DESC within each state/age/gender

COMMENT ON VIEW state_rankings IS 'State rankings view: National rankings filtered by state, sorted by national_power_score DESC. This is a filtered view, not a separate calculation. For extended stats, join with team_stats or analytics tables.';

-- Step 3: Grant SELECT permissions
GRANT SELECT ON state_rankings TO authenticated;
GRANT SELECT ON state_rankings TO anon;

-- Step 4: Deprecate calculate_state_rankings() function
COMMENT ON FUNCTION calculate_state_rankings() IS 
'DEPRECATED: State rankings are now derived directly by filtering national_rankings by state_code. Use the state_rankings SQL view instead. This function is retained for backward compatibility only.';

-- Step 5: Deprecate state_rank column
COMMENT ON COLUMN current_rankings.state_rank IS 
'Deprecated — state_rank is now derived dynamically via state_rankings view. This column is retained for backward compatibility only.';

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- The state_rankings view is now a filtered view of national rankings.
-- State rankings are sorted by national_power_score DESC within each
-- state/age/gender combination.
-- ============================================================================
