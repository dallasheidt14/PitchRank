-- Fix state_rankings_view: Add SOS tie-breaking to ROW_NUMBER for deterministic ranks
-- Date: 2026-03-07
-- Problem: ROW_NUMBER() in state_rankings_view sorted ONLY by power_score_final DESC.
--   When two teams have the same power_score_final, the DB assigned arbitrary rank order.
--   The rankings page (RankingsTable.tsx) re-computes ranks client-side with SOS tie-breaking,
--   causing the team header (which uses the view's rank_in_state_final or a COUNT query)
--   to show a different rank than the rankings page.
-- Fix: Add sos_norm_state DESC NULLS LAST as secondary sort in ROW_NUMBER, matching
--   the client-side tie-breaking logic. Also simplifies getTeam() to use this view rank directly.

-- =====================================================
-- Step 1: Drop existing view
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate state_rankings_view with SOS tie-breaking
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
    rv.win_percentage, -- Already recalculated from total games in base view

    -- Metrics
    rv.power_score_final,
    rv.sos_norm,  -- National normalization (kept for backward compatibility)
    rv.sos_norm_state,  -- State normalization (use this for state rankings display)
    rv.offense_norm,
    rv.defense_norm,

    -- Performance/form signal
    rv.perf_centered,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank: computed ONLY among Active/Not Enough Ranked Games teams
    -- Uses sos_norm_state as tie-breaker to match the rankings page client-side logic
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC, rv.sos_norm_state DESC NULLS LAST
    ) AS rank_in_state_final,

    -- SOS Ranks (passed through from base view)
    rv.sos_rank_national,  -- National SOS rank
    rv.sos_rank_state,     -- State SOS rank (pre-calculated in rankings engine)

    -- Rank change tracking (passed through from base view)
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- Activity status fields (passed through from base view)
    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');  -- Only rank active teams

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state, with rank_in_state_final computed among Active/Not Enough Ranked Games teams. Uses sos_norm_state as tie-breaker for deterministic ranking (matching client-side logic). Respects RLS policies.';

-- =====================================================
-- Step 3: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;
