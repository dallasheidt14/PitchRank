-- Restore rank_change_state_7d/30d to state_rankings_view
-- Date: 2026-03-10
-- Problem: The state_rankings_view was recreated in migrations 20260211 and 20260221
--   without the JOIN to rankings_full that provides rank_change_state_7d/30d.
--   These fields were originally added in 20260119000001 but lost during rollback.
--   The frontend (RankingsTable.tsx) expects rank_change_state_7d for state views,
--   falling back to national rank_change_7d when missing — causing outdated/wrong
--   rank change indicators for state-filtered rankings.
-- Fix: Recreate state_rankings_view with a JOIN back to rankings_full to expose
--   rank_change_state_7d and rank_change_state_30d.

-- =====================================================
-- Step 1: Drop existing view
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate state_rankings_view with state rank changes
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
    rv.win_percentage,

    -- Metrics
    rv.power_score_final,
    rv.sos_norm,
    rv.sos_norm_state,
    rv.offense_norm,
    rv.defense_norm,

    -- Performance/form signal
    rv.perf_centered,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank: computed ONLY among Active/Not Enough Ranked Games teams
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final,

    -- SOS Ranks (passed through from base view)
    rv.sos_rank_national,
    rv.sos_rank_state,

    -- National rank change tracking (passed through from base view)
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- State rank change tracking (from rankings_full)
    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    -- Activity status fields (passed through from base view)
    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state, with rank_in_state_final computed among Active/Not Enough Ranked Games teams. Includes both national rank changes (rank_change_7d/30d) and state rank changes (rank_change_state_7d/30d) via JOIN to rankings_full.';

-- =====================================================
-- Step 3: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;
