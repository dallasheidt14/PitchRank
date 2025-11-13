-- Create state_rankings_view for state-specific rankings
-- This view calculates state_rank dynamically using window functions
-- State rankings derive from national rankings filtered by state_code

CREATE OR REPLACE VIEW state_rankings_view
WITH (security_invoker = true)
AS
SELECT
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    t.age_group,
    t.gender,
    r.national_rank,
    r.national_power_score as power_score,
    r.global_power_score,
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.win_percentage,
    r.strength_of_schedule,
    row_number() over (
        partition by t.age_group, t.gender, t.state_code
        order by r.national_power_score desc
    ) as state_rank
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
WHERE t.state_code IS NOT NULL
  AND r.national_power_score IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state_code, with dynamically calculated state_rank. Respects RLS policies.';

-- Grant SELECT permissions
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

