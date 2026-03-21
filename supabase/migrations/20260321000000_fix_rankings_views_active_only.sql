-- Fix: Only assign national/state ranks to "Active" teams
-- Date: 2026-03-21
-- Problem: Teams with 1 game (status = "Not Enough Ranked Games") were receiving:
--   1. rank_in_cohort_final via COALESCE(rank_in_cohort_ml, rank_in_cohort)
--      because Layer 13 assigned rank_in_cohort_ml to ALL teams regardless of status.
--      (Fixed in Python: Layer 13 now only ranks Active teams.)
--   2. rank_in_state_final via ROW_NUMBER() in state_rankings_view, which ranked
--      ALL teams with status IN ('Active', 'Not Enough Ranked Games').
--
-- Fix: state_rankings_view now only computes rank_in_state_final for Active teams.
--      Non-Active teams still appear in the view (for display) but get NULL state rank.

-- =====================================================
-- Step 1: Drop existing views (state depends on rankings)
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate state_rankings_view — rank only Active teams
-- =====================================================

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
WITH active_ranked AS (
    -- Compute state ranks ONLY for Active teams
    SELECT
        rv.team_id_master,
        ROW_NUMBER() OVER (
            PARTITION BY rv.state, rv.age, rv.gender
            ORDER BY rv.power_score_final DESC
        ) AS rank_in_state_final
    FROM rankings_view rv
    WHERE rv.state IS NOT NULL
      AND rv.status = 'Active'
)
SELECT
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state AS state,
    rv.age AS age,
    rv.gender,

    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,

    rv.total_games_played,
    rv.total_wins,
    rv.total_losses,
    rv.total_draws,
    rv.win_percentage,

    rv.power_score_final,
    rv.sos_norm,
    rv.sos_norm_state,
    rv.offense_norm,
    rv.defense_norm,

    rv.perf_centered,

    rv.rank_in_cohort_final,

    -- State rank: NULL for non-Active teams (e.g., "Not Enough Ranked Games")
    ar.rank_in_state_final,

    rv.sos_rank_national,
    rv.sos_rank_state,

    rv.rank_change_7d,
    rv.rank_change_30d,

    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
LEFT JOIN active_ranked ar ON rv.team_id_master = ar.team_id_master
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW state_rankings_view IS 'State rankings view. rank_in_state_final computed ONLY for Active teams (8+ games). Non-Active teams appear but get NULL state rank. Inherits deprecated team exclusion from rankings_view.';

-- =====================================================
-- Step 3: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Verification
-- =====================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'state_rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: state_rankings_view not created';
    END IF;

    RAISE NOTICE 'Migration successful: state_rankings_view now ranks only Active teams';
END $$;
