-- Fix state_rankings view to use national rankings sorted by power_score
-- State rankings are just a filtered view of national rankings, not a separate calculation
-- We filter by state_code and sort by national_power_score DESC within each state/age/gender

-- Drop the old view
DROP VIEW IF EXISTS state_rankings;

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

-- Note: The state_rank column in current_rankings table is kept for backward compatibility
-- but is not used by this view. The calculate_state_rankings() function is deprecated.

