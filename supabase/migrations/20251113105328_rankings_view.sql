-- Create rankings_view for national rankings
-- This view calculates national_rank dynamically using window functions
-- to ensure ranks are always correct based on power_score

CREATE OR REPLACE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT 
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    t.age_group,
    t.gender,
    row_number() over (
        partition by t.age_group, t.gender
        order by r.national_power_score desc
    ) as national_rank,
    r.national_power_score,
    r.global_power_score,
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.win_percentage,
    r.strength_of_schedule,
    row_number() over (
        partition by t.age_group, t.gender
        order by r.strength_of_schedule desc nulls last
    ) as national_sos_rank
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
WHERE r.national_power_score IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view with dynamically calculated national_rank based on power_score. Respects RLS policies.';

-- Grant SELECT permissions
GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;

