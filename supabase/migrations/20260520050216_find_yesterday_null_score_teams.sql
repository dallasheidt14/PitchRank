-- RPC: find_yesterday_null_score_teams
--
-- Returns distinct GotSport teams that had a game yesterday with NULL home_score.
-- Either side of the matchup counts (home or away). Excludes deprecated teams
-- and teams already scraped today (last_scraped_at >= today gate).
--
-- Used by scripts/enqueue_yesterday_games.py (Phase 4).

CREATE OR REPLACE FUNCTION find_yesterday_null_score_teams(
    p_yesterday date,
    p_provider_id uuid
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    SELECT DISTINCT t.team_id_master, t.team_name, t.provider_team_id
    FROM teams t
    WHERE t.is_deprecated = false
      AND t.provider_id = find_yesterday_null_score_teams.p_provider_id
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at::date < CURRENT_DATE)
      AND EXISTS (
          SELECT 1 FROM games g
          WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
            AND g.game_date = find_yesterday_null_score_teams.p_yesterday
            AND g.home_score IS NULL
      )
    ORDER BY t.team_id_master;
$$;

GRANT EXECUTE ON FUNCTION find_yesterday_null_score_teams(date, uuid) TO authenticated, service_role;
