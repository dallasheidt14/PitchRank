-- Add indexes to speed up stats queries that are timing out
-- These indexes support the count queries for homepage stats

-- Index for games count query (filtering on score columns)
CREATE INDEX IF NOT EXISTS idx_games_home_score_not_null
ON games(home_score)
WHERE home_score IS NOT NULL;

-- Composite index for the full games filter
CREATE INDEX IF NOT EXISTS idx_games_valid_scores
ON games(home_team_master_id, away_team_master_id)
WHERE home_score IS NOT NULL
  AND away_score IS NOT NULL
  AND home_team_master_id IS NOT NULL
  AND away_team_master_id IS NOT NULL;

-- Index for rankings_full count
CREATE INDEX IF NOT EXISTS idx_rankings_full_power_score_not_null
ON rankings_full(power_score_final)
WHERE power_score_final IS NOT NULL;

-- Update the get_db_stats function to use COUNT with simpler logic
CREATE OR REPLACE FUNCTION get_db_stats()
RETURNS TABLE (total_games BIGINT, total_teams BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
  SELECT
    -- Simple count of games with scores (uses index)
    (SELECT COUNT(*) FROM games WHERE home_score IS NOT NULL) AS total_games,
    -- Simple count of ranked teams (uses index)
    (SELECT COUNT(*) FROM rankings_full WHERE power_score_final IS NOT NULL) AS total_teams;
$$;

GRANT EXECUTE ON FUNCTION get_db_stats() TO anon;
GRANT EXECUTE ON FUNCTION get_db_stats() TO authenticated;

COMMENT ON FUNCTION get_db_stats() IS 'Fast stats for homepage - uses indexed columns';
