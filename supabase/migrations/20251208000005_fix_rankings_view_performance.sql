-- Migration: Fix rankings_view performance issue
-- Purpose: Remove expensive correlated subqueries that call resolve_team_id()
--          causing query timeouts
--
-- Problem: The previous migration (20251208000004) added correlated subqueries
--          that scan the entire games table for each team, calling resolve_team_id()
--          on every row. This creates O(teams × games × 2) complexity which times out.
--
-- Solution: Use pre-computed values from current_rankings table instead of
--           calculating them live in the view with correlated subqueries.

-- =====================================================
-- Step 1: Drop existing views
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view WITHOUT expensive correlated subqueries
-- =====================================================

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields (always canonical, never deprecated)
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code AS state,
    CASE
      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
      WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
      ELSE NULL
    END AS age,
    CASE
      WHEN rf.gender = 'Male' THEN 'M'
      WHEN rf.gender = 'Female' THEN 'F'
      WHEN rf.gender = 'Boys' THEN 'M'
      WHEN rf.gender = 'Girls' THEN 'F'
      WHEN rf.gender = 'M' THEN 'M'
      WHEN rf.gender = 'F' THEN 'F'
      ELSE rf.gender
    END AS gender,

    -- Record stats (from rankings_full - CAPPED AT 30 GAMES for rankings algorithm)
    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,

    -- Total games count - use pre-computed values from current_rankings
    -- NOTE: These values do NOT include merged team games until the rankings
    -- calculator is updated to resolve merged teams. This is a tradeoff for
    -- performance. The merge resolution can be added to the rankings calculator
    -- instead of computing it live in the view.
    COALESCE(cr.games_played, rf.games_played) AS total_games_played,
    COALESCE(cr.wins, rf.wins) AS total_wins,
    COALESCE(cr.losses, rf.losses) AS total_losses,
    COALESCE(cr.draws, rf.draws) AS total_draws,

    -- Win percentage calculated from pre-computed totals (0-100 scale)
    CASE
      WHEN COALESCE(cr.games_played, rf.games_played) > 0
      THEN ((COALESCE(cr.wins, rf.wins)::NUMERIC + (COALESCE(cr.draws, rf.draws)::NUMERIC * 0.5))
            / COALESCE(cr.games_played, rf.games_played)::NUMERIC) * 100
      ELSE NULL
    END AS win_percentage,

    -- Metrics (ONLY from rankings_full)
    rf.power_score_final,
    rf.sos_norm,
    rf.sos_norm_state,  -- State normalization (for state rankings display)
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Rank (use precomputed ML ranking from rankings_full)
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,

    -- SOS Ranks (pre-calculated in rankings engine)
    rf.sos_rank_national,
    rf.sos_rank_state,

    -- Rank change tracking
    rf.rank_change_7d,
    rf.rank_change_30d,

    -- Activity status fields
    rf.status,
    rf.last_game,

    -- Metadata
    rf.last_calculated

FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
LEFT JOIN current_rankings cr ON cr.team_id = t.team_id_master
WHERE rf.power_score_final IS NOT NULL
  AND t.is_deprecated = FALSE;  -- Exclude deprecated teams from results

COMMENT ON VIEW rankings_view IS 'National rankings view with deprecated team filtering. Uses pre-computed game counts from current_rankings for performance. Merged team game resolution should be done in the rankings calculator, not live in the view.';

-- =====================================================
-- Step 3: Recreate state_rankings_view
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
    rv.sos_norm_state,  -- State normalization (for state rankings display)
    rv.offense_norm,
    rv.defense_norm,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank (computed live in view - this is fast with proper indexes)
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final,

    -- SOS Ranks
    rv.sos_rank_national,
    rv.sos_rank_state,

    -- Rank change tracking
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- Activity status fields
    rv.status,
    rv.last_game,

    -- Metadata
    rv.last_calculated

FROM rankings_view rv
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view. Deprecated teams excluded via rankings_view filter.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Step 5: Recreate merged_teams_view (preserved from previous migration)
-- =====================================================

-- Must DROP first because CREATE OR REPLACE cannot change column order
DROP VIEW IF EXISTS merged_teams_view CASCADE;

CREATE VIEW merged_teams_view AS
SELECT
    mm.id as merge_id,
    mm.deprecated_team_id,
    dt.team_name as deprecated_team_name,
    dt.club_name as deprecated_club_name,
    mm.canonical_team_id,
    ct.team_name as canonical_team_name,
    ct.club_name as canonical_club_name,
    mm.merged_at,
    mm.merged_by,
    mm.merge_reason,
    mm.confidence_score,
    (SELECT COUNT(*) FROM games g
     WHERE g.home_team_master_id = mm.deprecated_team_id
        OR g.away_team_master_id = mm.deprecated_team_id) as games_with_deprecated_id
FROM team_merge_map mm
JOIN teams dt ON mm.deprecated_team_id = dt.team_id_master
JOIN teams ct ON mm.canonical_team_id = ct.team_id_master
ORDER BY mm.merged_at DESC;

COMMENT ON VIEW merged_teams_view IS 'View of all team merges with team names and game counts for admin dashboard.';

GRANT SELECT ON merged_teams_view TO authenticated;

-- =====================================================
-- Verification
-- =====================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: rankings_view not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'state_rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: state_rankings_view not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'merged_teams_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: merged_teams_view not created';
    END IF;

    RAISE NOTICE 'Migration successful: Fixed rankings_view performance by removing correlated subqueries';
END $$;
