-- Fix statement timeout in backfill_total_game_stats RPC
-- The bulk UPDATE on ~103K rankings_full rows exceeds Supabase's
-- default PostgREST statement timeout. Since this function is
-- SECURITY DEFINER, SET LOCAL applies only within the transaction.
-- Date: 2026-03-24

CREATE OR REPLACE FUNCTION backfill_total_game_stats()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count INTEGER;
BEGIN
  -- Allow up to 120s for the bulk UPDATE (default PostgREST timeout is 8-30s)
  SET LOCAL statement_timeout = '120s';

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
  'Single scan of games table via UNION ALL. '
  'Uses SET LOCAL statement_timeout = 120s to avoid PostgREST timeout on bulk UPDATE. '
  'Called after save_rankings_to_supabase in calculate_rankings.py.';
