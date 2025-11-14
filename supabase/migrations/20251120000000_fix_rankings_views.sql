-- Fix rankings_view and state_rankings_view to use canonical contract
-- This migration completely rewrites both views to:
-- 1. Use rankings_full as primary data source
-- 2. Expose only canonical fields (no legacy fields)
-- 3. Use precomputed rank_in_cohort_final from rankings_full (not recomputed)
-- 4. Compute rank_in_state_final live in state view
-- 5. Fallback to current_rankings ONLY for record stats (games_played, wins, losses, draws, win_percentage)

-- =====================================================
-- Step 1: Drop existing views
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Create rankings_view with canonical fields
-- =====================================================

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT 
    -- Team identity fields
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code AS state,
    rf.age_group AS age,
    rf.gender,

    -- Record stats (with fallback to current_rankings)
    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,
    COALESCE(rf.win_percentage, cr.win_percentage) AS win_percentage,

    -- Metrics (ONLY from rankings_full, NO fallback)
    rf.power_score_final,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Rank (use precomputed ML ranking from rankings_full, do NOT recompute)
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final

FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
LEFT JOIN current_rankings cr ON cr.team_id = t.team_id_master
WHERE rf.power_score_final IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view using rankings_full as primary source. Exposes only canonical fields: power_score_final, sos_norm, offense_norm, defense_norm, rank_in_cohort_final. Falls back to current_rankings only for record stats. Respects RLS policies.';

-- =====================================================
-- Step 3: Create state_rankings_view with canonical fields
-- =====================================================

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state AS state,
    rv.age AS age,
    rv.gender,

    -- Record stats
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,
    rv.win_percentage,

    -- Metrics
    rv.power_score_final,
    rv.sos_norm,
    rv.offense_norm,
    rv.defense_norm,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank (computed live in view)
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final

FROM rankings_view rv
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state, with dynamically calculated rank_in_state_final. Exposes only canonical fields. Respects RLS policies.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

