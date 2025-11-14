-- Update rankings_view and state_rankings_view to read from rankings_full
-- with fallback to current_rankings for backward compatibility
-- This migration enables the views to use comprehensive ranking data when available

-- =====================================================
-- Step 1: Drop existing views
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Create updated rankings_view
-- =====================================================
-- This view reads from rankings_full if available, otherwise falls back to current_rankings
-- Uses COALESCE to prioritize rankings_full data

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT 
    -- Team identity fields (from teams table)
    COALESCE(rf.team_id, cr.team_id) as team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    COALESCE(rf.age_group, t.age_group) as age_group,
    COALESCE(rf.gender, t.gender) as gender,
    
    -- Power scores with fallback logic
    -- Prioritize rankings_full, fallback to current_rankings
    COALESCE(rf.national_power_score, cr.national_power_score) as national_power_score,
    COALESCE(rf.global_power_score, cr.global_power_score) as global_power_score,
    -- power_score_final: ML > global > adj > national
    COALESCE(
        rf.powerscore_ml,
        rf.global_power_score,
        rf.powerscore_adj,
        rf.national_power_score,
        cr.global_power_score,
        cr.national_power_score
    ) as power_score_final,
    
    -- Game statistics
    COALESCE(rf.games_played, cr.games_played, 0) as games_played,
    COALESCE(rf.wins, cr.wins, 0) as wins,
    COALESCE(rf.losses, cr.losses, 0) as losses,
    COALESCE(rf.draws, cr.draws, 0) as draws,
    COALESCE(rf.win_percentage, cr.win_percentage) as win_percentage,
    
    -- Strength of Schedule
    COALESCE(rf.strength_of_schedule, rf.sos, cr.strength_of_schedule) as strength_of_schedule,
    
    -- Dynamically calculated ranks
    -- National rank: within age_group + gender cohort, ordered by power_score_final DESC
    row_number() OVER (
        PARTITION BY COALESCE(rf.age_group, t.age_group), COALESCE(rf.gender, t.gender)
        ORDER BY COALESCE(
            rf.powerscore_ml,
            rf.global_power_score,
            rf.powerscore_adj,
            rf.national_power_score,
            cr.global_power_score,
            cr.national_power_score
        ) DESC
    ) as national_rank,
    
    -- National SOS rank: within age_group + gender cohort, ordered by SOS DESC
    -- Use RANK() instead of ROW_NUMBER() to handle ties properly
    RANK() OVER (
        PARTITION BY COALESCE(rf.age_group, t.age_group), COALESCE(rf.gender, t.gender)
        ORDER BY COALESCE(rf.strength_of_schedule, rf.sos, cr.strength_of_schedule) DESC NULLS LAST
    ) as national_sos_rank

FROM current_rankings cr
JOIN teams t ON cr.team_id = t.team_id_master
LEFT JOIN rankings_full rf ON cr.team_id = rf.team_id
WHERE COALESCE(rf.national_power_score, cr.national_power_score) IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view reading from rankings_full (with fallback to current_rankings). Includes power_score_final with ML > global > adj > national fallback. Respects RLS policies.';

-- =====================================================
-- Step 3: Create updated state_rankings_view
-- =====================================================
-- This view reads from rankings_view (which already uses rankings_full)

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state_code,
    rv.age_group,
    rv.gender,
    
    -- Power scores
    rv.national_power_score,
    rv.global_power_score,
    rv.power_score_final,
    -- Backward compatibility: power_score alias (used by frontend for ordering)
    rv.power_score_final as power_score,
    
    -- Game statistics
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,
    rv.win_percentage,
    
    -- Strength of Schedule
    rv.strength_of_schedule,
    
    -- National ranks (from base rankings_view)
    rv.national_rank,
    rv.national_sos_rank,
    
    -- State-specific ranks
    -- State rank: within age_group + gender + state_code cohort, ordered by power_score_final DESC
    row_number() OVER (
        PARTITION BY rv.age_group, rv.gender, rv.state_code
        ORDER BY rv.power_score_final DESC
    ) as state_rank,
    
    -- State SOS rank: within age_group + gender + state_code cohort, ordered by SOS DESC
    -- Use RANK() instead of ROW_NUMBER() to handle ties properly
    RANK() OVER (
        PARTITION BY rv.age_group, rv.gender, rv.state_code
        ORDER BY rv.strength_of_schedule DESC NULLS LAST
    ) as state_sos_rank

FROM rankings_view rv
WHERE rv.state_code IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state_code, with dynamically calculated state_rank and state_sos_rank. Reads from rankings_full via rankings_view. Respects RLS policies.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

