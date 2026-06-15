-- Cache the home page hero figures so the page render never runs the slow exact
-- counts. The home page is statically rendered through the Data API under the
-- anon role (3s statement_timeout); an exact COUNT(*) over ~1.3M games takes
-- ~25s, so it timed out and froze the page on its hardcoded 16,000 / 2,800
-- fallbacks. A daily job recomputes the exact counts off the request path and
-- get_db_stats() serves the single cached row.

CREATE TABLE IF NOT EXISTS homepage_stats (
  id BOOLEAN PRIMARY KEY DEFAULT TRUE,
  total_games BIGINT NOT NULL DEFAULT 0,
  total_teams BIGINT NOT NULL DEFAULT 0,
  refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT homepage_stats_singleton CHECK (id)
);

-- Figures are public (rendered on the home page) but only ever written by the
-- scheduled refresh and read through get_db_stats(); no direct Data API access.
ALTER TABLE homepage_stats ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access" ON homepage_stats
  FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE homepage_stats IS
  'Single-row cache of the home page hero figures (games analyzed, active teams ranked). Recomputed daily by refresh_homepage_stats() so the render path never runs the slow exact counts.';

-- Recompute the exact figures and upsert the singleton row. SECURITY DEFINER so
-- the daily job bypasses RLS; raised statement_timeout because the exact games
-- count runs ~25s, past any role default.
CREATE OR REPLACE FUNCTION refresh_homepage_stats()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '300s'
AS $$
BEGIN
  INSERT INTO public.homepage_stats (id, total_games, total_teams, refreshed_at)
  VALUES (
    TRUE,
    (SELECT COUNT(*)
       FROM public.games
      WHERE home_team_master_id IS NOT NULL
        AND away_team_master_id IS NOT NULL
        AND home_score IS NOT NULL
        AND away_score IS NOT NULL
        AND is_excluded = FALSE),
    (SELECT COUNT(*)
       FROM public.rankings_full
      WHERE status = 'Active'),
    NOW()
  )
  ON CONFLICT (id) DO UPDATE
    SET total_games = EXCLUDED.total_games,
        total_teams = EXCLUDED.total_teams,
        refreshed_at = EXCLUDED.refreshed_at;
END;
$$;

-- Serve the cached row. Keeps the prior get_db_stats() shape (total_games,
-- total_teams) so callers are unchanged.
CREATE OR REPLACE FUNCTION get_db_stats()
RETURNS TABLE (total_games BIGINT, total_teams BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT total_games, total_teams
  FROM public.homepage_stats
  WHERE id = TRUE;
$$;

GRANT EXECUTE ON FUNCTION get_db_stats() TO anon;
GRANT EXECUTE ON FUNCTION get_db_stats() TO authenticated;

COMMENT ON FUNCTION get_db_stats() IS
  'Returns the cached home page figures (games analyzed, active teams ranked) from homepage_stats; refreshed daily by refresh_homepage_stats().';

-- Seed immediately so the row exists with real data before the first cron run.
SELECT refresh_homepage_stats();
