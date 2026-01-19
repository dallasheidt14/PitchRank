-- Add state rank change columns to rankings_full and update views
-- Date: 2026-01-19
-- Purpose: Expose state rank changes (rank_change_state_7d, rank_change_state_30d) in rankings

-- =====================================================
-- Step 1: Add state rank change columns to rankings_full
-- =====================================================

ALTER TABLE rankings_full
ADD COLUMN IF NOT EXISTS rank_change_state_7d INTEGER;

ALTER TABLE rankings_full
ADD COLUMN IF NOT EXISTS rank_change_state_30d INTEGER;

COMMENT ON COLUMN rankings_full.rank_change_state_7d IS 'State rank change over 7 days (positive = improved within state)';
COMMENT ON COLUMN rankings_full.rank_change_state_30d IS 'State rank change over 30 days (positive = improved within state)';

-- =====================================================
-- Step 2: Recreate state_rankings_view with state rank changes
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

    -- NEW: State rank change tracking (from rankings_full via rankings_view)
    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    -- Metadata
    rv.last_calculated

FROM rankings_view rv
JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state, with dynamically calculated rank_in_state_final. Includes both national rank changes (rank_change_7d/30d) and state rank changes (rank_change_state_7d/30d).';

-- =====================================================
-- Step 3: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Notes
-- =====================================================
-- rank_change_7d / rank_change_30d: National rank changes (how team moved in overall rankings)
-- rank_change_state_7d / rank_change_state_30d: State rank changes (how team moved within their state)
--
-- Example interpretation:
-- Team A: rank_change_7d = +11, rank_change_state_7d = +10
-- Means: Team A moved up 11 spots nationally and 10 spots within their state over the past 7 days
--
-- State rank changes will be NULL for existing data until new snapshots are saved with state rank data.
