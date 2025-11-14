-- Create team_predictive_view to expose predictive fields from rankings_full
-- This view keeps predictive data separate from canonical rankings contract
-- Predictive fields are NOT in rankings_view or state_rankings_view

-- =====================================================
-- Step 1: Drop existing view if it exists
-- =====================================================

DROP VIEW IF EXISTS team_predictive_view CASCADE;

-- =====================================================
-- Step 2: Create team_predictive_view
-- =====================================================

CREATE VIEW team_predictive_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity (use canonical field name)
    rf.team_id AS team_id_master,
    
    -- Predictive fields (always exist)
    rf.exp_margin,
    rf.exp_win_rate,
    
    -- Predictive fields (optional - compute if not stored)
    COALESCE(
        rf.exp_goals_for,
        -- Compute if not stored: league_avg_goals_per_game ≈ 3.1 (US youth)
        CASE 
            WHEN rf.off_norm IS NOT NULL AND rf.def_norm IS NOT NULL THEN
                -- expected_total_goals = 3.1 * ((offense_norm + defense_norm) / 2)
                -- exp_goals_for = expected_total_goals / (1 + exp(-exp_margin))
                3.1 * ((rf.off_norm + rf.def_norm) / 2.0) / (1.0 + EXP(-COALESCE(rf.exp_margin, 0)))
            ELSE NULL
        END
    ) AS exp_goals_for,
    
    COALESCE(
        rf.exp_goals_against,
        -- Compute if not stored
        CASE 
            WHEN rf.off_norm IS NOT NULL AND rf.def_norm IS NOT NULL AND rf.exp_margin IS NOT NULL THEN
                -- expected_total_goals = 3.1 * ((offense_norm + defense_norm) / 2)
                -- exp_goals_against = expected_total_goals - exp_goals_for
                3.1 * ((rf.off_norm + rf.def_norm) / 2.0) - (
                    3.1 * ((rf.off_norm + rf.def_norm) / 2.0) / (1.0 + EXP(-rf.exp_margin))
                )
            ELSE NULL
        END
    ) AS exp_goals_against,
    
    -- Helpful extras for advanced predictive widgets
    rf.power_score_final,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm

FROM rankings_full rf
WHERE rf.exp_margin IS NOT NULL OR rf.exp_win_rate IS NOT NULL;

COMMENT ON VIEW team_predictive_view IS 'Predictive match result view exposing Layer 13 ML predictive fields. Kept separate from canonical rankings views. Includes exp_margin, exp_win_rate, and computed exp_goals_for/exp_goals_against if not stored.';

-- =====================================================
-- Step 3: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON team_predictive_view TO authenticated;
GRANT SELECT ON team_predictive_view TO anon;

