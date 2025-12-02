-- Fix SOS null handling in rankings views
-- This migration updates the views to handle NULL strength_of_schedule values properly
-- and removes the filter that was excluding teams without SOS

-- Update rankings_view to handle NULL SOS
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

COMMENT ON VIEW rankings_view IS 'National rankings view with dynamically calculated national_rank based on power_score. Handles NULL strength_of_schedule values. Respects RLS policies.';

-- Update state_rankings_view to handle NULL SOS
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
    ) as state_rank,
    row_number() over (
        partition by t.age_group, t.gender
        order by r.strength_of_schedule desc nulls last
    ) as national_sos_rank,
    row_number() over (
        partition by t.age_group, t.gender, t.state_code
        order by r.strength_of_schedule desc nulls last
    ) as state_sos_rank
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
WHERE t.state_code IS NOT NULL
  AND r.national_power_score IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state_code, with dynamically calculated state_rank. Handles NULL strength_of_schedule values. Respects RLS policies.';

-- Grant SELECT permissions
GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;


