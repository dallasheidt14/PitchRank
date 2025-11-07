-- Update state_rankings view and RLS policies
-- This migration updates the view definition and ensures RLS policies are properly configured
-- State rankings are now a filtered view of national rankings, not a separate calculation

-- Drop existing view (CASCADE to handle any dependencies)
DROP VIEW IF EXISTS state_rankings CASCADE;

-- Recreate state_rankings view with essential columns only
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

-- Grant SELECT permissions to authenticated role (RLS policies on underlying tables will apply)
GRANT SELECT ON state_rankings TO authenticated;
GRANT SELECT ON state_rankings TO anon;

-- Note: RLS policies on the underlying tables (current_rankings, teams) will automatically
-- apply to this view since it uses security_invoker = true

