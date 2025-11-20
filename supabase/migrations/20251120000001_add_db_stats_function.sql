-- Create function to get database stats for homepage
-- This is more efficient than multiple separate count queries

CREATE OR REPLACE FUNCTION get_db_stats()
RETURNS TABLE (total_games BIGINT, total_teams BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
  SELECT
    (SELECT COUNT(*)
     FROM games
     WHERE home_team_master_id IS NOT NULL
       AND away_team_master_id IS NOT NULL
       AND home_score IS NOT NULL
       AND away_score IS NOT NULL) AS total_games,
    (SELECT COUNT(*)
     FROM rankings_full
     WHERE power_score_final IS NOT NULL) AS total_teams;
$$;

-- Grant execute permission to anon and authenticated users
GRANT EXECUTE ON FUNCTION get_db_stats() TO anon;
GRANT EXECUTE ON FUNCTION get_db_stats() TO authenticated;

COMMENT ON FUNCTION get_db_stats() IS 'Returns total games (with valid scores/teams) and total ranked teams for homepage stats display';
