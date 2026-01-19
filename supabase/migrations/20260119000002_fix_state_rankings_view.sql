-- Fix state_rankings_view to include all required columns
-- Date: 2026-01-19
-- Purpose: Previous migration missed status and last_game columns

-- =====================================================
-- Step 1: Drop and recreate state_rankings_view with ALL columns
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;

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

    -- Record stats (capped at 30 for rankings algorithm)
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,

    -- Total games and record (all games, not capped)
    rv.total_games_played,
    rv.total_wins,
    rv.total_losses,
    rv.total_draws,
    rv.win_percentage, -- Already recalculated from total games in base view

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
    ) AS rank_in_state_final,

    -- National rank change tracking (passed through from base view)
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- State rank change tracking (from rankings_full)
    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    -- Activity status fields (passed through from base view)
    rv.status,
    rv.last_game,

    -- Metadata
    rv.last_calculated

FROM rankings_view rv
JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state, with dynamically calculated rank_in_state_final. Includes both national rank changes (rank_change_7d/30d) and state rank changes (rank_change_state_7d/30d), plus activity status fields for filtering inactive teams.';

-- =====================================================
-- Step 2: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;
