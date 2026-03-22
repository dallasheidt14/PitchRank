-- Precompute total_games/wins/losses/draws into rankings_full to eliminate
-- 7 correlated subqueries in rankings_view that cause statement timeouts
-- during Next.js static generation.
-- Date: 2026-03-22

-- =====================================================
-- Step 1: Add columns to rankings_full
-- =====================================================

ALTER TABLE rankings_full
  ADD COLUMN IF NOT EXISTS total_games_played INTEGER,
  ADD COLUMN IF NOT EXISTS total_wins         INTEGER,
  ADD COLUMN IF NOT EXISTS total_losses        INTEGER,
  ADD COLUMN IF NOT EXISTS total_draws         INTEGER;

-- =====================================================
-- Step 2: Covering indexes on games for team lookups
-- =====================================================

-- These support the aggregate query in backfill_total_game_stats
-- and any remaining ad-hoc lookups.
CREATE INDEX IF NOT EXISTS idx_games_home_team_stats
  ON games(home_team_master_id)
  INCLUDE (away_team_master_id, home_score, away_score, is_excluded)
  WHERE home_score IS NOT NULL AND away_score IS NOT NULL AND is_excluded = FALSE;

CREATE INDEX IF NOT EXISTS idx_games_away_team_stats
  ON games(away_team_master_id)
  INCLUDE (home_team_master_id, home_score, away_score, is_excluded)
  WHERE home_score IS NOT NULL AND away_score IS NOT NULL AND is_excluded = FALSE;

-- =====================================================
-- Step 3: RPC to bulk-compute total game stats
-- =====================================================

CREATE OR REPLACE FUNCTION backfill_total_game_stats()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count INTEGER;
BEGIN
  WITH game_agg AS (
    SELECT
      team_id,
      COUNT(*) AS total_games,
      SUM(CASE WHEN is_win  THEN 1 ELSE 0 END) AS total_w,
      SUM(CASE WHEN is_loss THEN 1 ELSE 0 END) AS total_l,
      SUM(CASE WHEN is_draw THEN 1 ELSE 0 END) AS total_d
    FROM (
      -- Home games
      SELECT
        g.home_team_master_id AS team_id,
        g.home_score > g.away_score AS is_win,
        g.home_score < g.away_score AS is_loss,
        g.home_score = g.away_score AS is_draw
      FROM games g
      WHERE g.home_score IS NOT NULL
        AND g.away_score IS NOT NULL
        AND g.is_excluded = FALSE

      UNION ALL

      -- Away games
      SELECT
        g.away_team_master_id AS team_id,
        g.away_score > g.home_score AS is_win,
        g.away_score < g.home_score AS is_loss,
        g.away_score = g.home_score AS is_draw
      FROM games g
      WHERE g.home_score IS NOT NULL
        AND g.away_score IS NOT NULL
        AND g.is_excluded = FALSE
    ) sub
    GROUP BY team_id
  )
  UPDATE rankings_full rf
  SET
    total_games_played = ga.total_games,
    total_wins         = ga.total_w,
    total_losses       = ga.total_l,
    total_draws        = ga.total_d
  FROM game_agg ga
  WHERE rf.team_id = ga.team_id;

  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count;
END;
$$;

COMMENT ON FUNCTION backfill_total_game_stats IS
  'Bulk-compute total_games_played/wins/losses/draws for every team in rankings_full. '
  'Does NOT overwrite win_percentage (that stays as the v53e capped-games value). '
  'rankings_view computes all-games win_percentage inline from the precomputed totals. '
  'Single scan of games table via UNION ALL, ~2-3 seconds for 700K games. '
  'Called after save_rankings_to_supabase in calculate_rankings.py.';

-- =====================================================
-- Step 4: Rewrite rankings_view — no correlated subqueries
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT
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

    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,

    COALESCE(rf.total_games_played, 0) AS total_games_played,
    COALESCE(rf.total_wins, 0) AS total_wins,
    COALESCE(rf.total_losses, 0) AS total_losses,
    COALESCE(rf.total_draws, 0) AS total_draws,
    CASE
      WHEN COALESCE(rf.total_games_played, 0) > 0
      THEN ((COALESCE(rf.total_wins, 0)::NUMERIC + COALESCE(rf.total_draws, 0)::NUMERIC * 0.5)
            / rf.total_games_played::NUMERIC) * 100
      ELSE NULL
    END AS win_percentage,

    rf.power_score_final,
    rf.sos_norm,
    rf.sos_norm_state,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    rf.perf_centered,

    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,

    rf.sos_rank_national,
    rf.sos_rank_state,

    rf.rank_change_7d,
    rf.rank_change_30d,

    rf.status,
    rf.last_game,
    rf.last_calculated

FROM teams t
LEFT JOIN rankings_full rf ON t.team_id_master = rf.team_id
LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
WHERE (rf.power_score_final IS NOT NULL OR cr.national_power_score IS NOT NULL)
  AND t.is_deprecated IS NOT TRUE;

COMMENT ON VIEW rankings_view IS 'National rankings view. Uses precomputed total_games/wins/losses/draws from rankings_full (no correlated subqueries). Excludes deprecated/merged teams.';

-- =====================================================
-- Step 5: Recreate state_rankings_view
-- =====================================================

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
WITH active_ranked AS (
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

    ar.rank_in_state_final,

    rv.sos_rank_national,
    rv.sos_rank_state,

    rv.rank_change_7d,
    rv.rank_change_30d,

    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
LEFT JOIN active_ranked ar ON rv.team_id_master = ar.team_id_master
LEFT JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW state_rankings_view IS 'State rankings view. rank_in_state_final computed ONLY for Active teams. Includes state rank changes from rankings_full. Inherits precomputed stats from rankings_view.';

-- =====================================================
-- Step 6: Grant permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Step 7: Initial backfill (populate existing data)
-- =====================================================

SELECT backfill_total_game_stats();

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
  populated INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views WHERE table_name = 'rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: rankings_view not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views WHERE table_name = 'state_rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: state_rankings_view not created';
    END IF;

    SELECT COUNT(*) INTO populated
    FROM rankings_full WHERE total_games_played IS NOT NULL;

    RAISE NOTICE 'Migration successful: % teams backfilled with total game stats', populated;
END $$;
