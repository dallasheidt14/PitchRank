-- Fix rankings_view and state_rankings_view
-- This migration drops and recreates the views to fix schema mismatches
-- Postgres cannot use CREATE OR REPLACE VIEW when column names/types/order change

-- =====================================================
-- Step 1: Drop existing views with CASCADE
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Create new rankings_view
-- =====================================================
-- This view provides national rankings with all required fields for the frontend
-- Calculates ranks dynamically using window functions to ensure accuracy

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT 
    -- Team identity fields
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    t.age_group,
    t.gender,
    
    -- Power scores with fallback logic
    -- power_score_final prioritizes global (cross-age normalized) over national (age-group specific)
    r.national_power_score,
    r.global_power_score,
    COALESCE(r.global_power_score, r.national_power_score) as power_score_final,
    
    -- Game statistics
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.win_percentage,
    
    -- Strength of Schedule
    r.strength_of_schedule,
    
    -- Dynamically calculated ranks
    -- National rank: within age_group + gender cohort, ordered by power_score_final DESC
    row_number() OVER (
        PARTITION BY t.age_group, t.gender
        ORDER BY COALESCE(r.global_power_score, r.national_power_score) DESC
    ) as national_rank,
    
    -- National SOS rank: within age_group + gender cohort, ordered by SOS DESC
    row_number() OVER (
        PARTITION BY t.age_group, t.gender
        ORDER BY r.strength_of_schedule DESC NULLS LAST
    ) as national_sos_rank

FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
WHERE r.national_power_score IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view with dynamically calculated ranks. Includes power_score_final with fallback logic (global > national). Respects RLS policies.';

-- =====================================================
-- Step 3: Create new state_rankings_view
-- =====================================================
-- This view provides state-specific rankings filtered from national rankings
-- Calculates state ranks dynamically using window functions

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
    row_number() OVER (
        PARTITION BY rv.age_group, rv.gender, rv.state_code
        ORDER BY rv.strength_of_schedule DESC NULLS LAST
    ) as state_sos_rank

FROM rankings_view rv
WHERE rv.state_code IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state_code, with dynamically calculated state_rank and state_sos_rank. Respects RLS policies.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

