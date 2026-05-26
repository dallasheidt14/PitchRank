-- RPC: find_yesterday_null_score_teams (v2)
--
-- Rewrite drives from games (via idx_games_date) on game_date + NULL home_score,
-- then joins teams. The v1 form drove from teams with an EXISTS subquery, which
-- timed out under tournament-weekend volume (Memorial Day 2026: 7,214 NULL-score
-- games on a single day vs ~600 on a normal day).
--
-- Returns distinct GotSport teams that had a game on p_yesterday with NULL
-- home_score. Either side of the matchup counts. Excludes deprecated teams and
-- teams already scraped today.

CREATE OR REPLACE FUNCTION find_yesterday_null_score_teams(
    p_yesterday date,
    p_provider_id uuid
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    WITH affected_masters AS (
        SELECT home_team_master_id AS master_id
        FROM games
        WHERE game_date = find_yesterday_null_score_teams.p_yesterday
          AND home_score IS NULL
          AND home_team_master_id IS NOT NULL
        UNION
        SELECT away_team_master_id AS master_id
        FROM games
        WHERE game_date = find_yesterday_null_score_teams.p_yesterday
          AND home_score IS NULL
          AND away_team_master_id IS NOT NULL
    )
    SELECT DISTINCT t.team_id_master, t.team_name, t.provider_team_id
    FROM affected_masters am
    JOIN teams t ON t.team_id_master = am.master_id
    WHERE t.is_deprecated = false
      AND t.provider_id = find_yesterday_null_score_teams.p_provider_id
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at::date < CURRENT_DATE)
    ORDER BY t.team_id_master;
$$;

GRANT EXECUTE ON FUNCTION find_yesterday_null_score_teams(date, uuid) TO authenticated, service_role;
