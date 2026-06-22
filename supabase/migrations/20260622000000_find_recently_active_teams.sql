-- RPC: find_recently_active_teams
--
-- Returns GotSport teams that played a game in the last p_active_window_days
-- days and have NOT been scraped in the last p_cooldown_hours hours. Closes the
-- gap where an actively-playing team's newly-created games (tournament bracket
-- rounds, late-added fixtures) are re-queued by no other producer: the
-- yesterday-game enqueue only sees games already in the DB, discovery only sees
-- teams with no future games, and the safety net only fires at 90-day staleness.
--
-- Drives from games (games-first, like find_yesterday_null_score_teams) rather
-- than a teams-driven EXISTS, which times out at full team-table scale. The
-- cooldown gate skips teams scraped very recently so we don't waste scrape budget.
--
-- Only past games count (game_date <= CURRENT_DATE): GotSport imports future
-- scheduled fixtures, so without the upper bound any team with an upcoming game
-- would qualify as "recently active" and crowd out teams that actually just played.
--
-- Filters mirror find_stale_teams: is_deprecated, GotSport provider, U8/U9 +
-- U20+ age exclusions, 'unknown_*' placeholder exclusion. is_excluded games are
-- ignored so excluded/futsal results don't count as activity (a deliberate
-- addition the other finders don't have).
--
-- Ordering: oldest scraped first (NULLs first) so the row limit favors the teams
-- most overdue for a re-scrape.
--
-- Used by scripts/enqueue_active_teams.py (priority 2).

CREATE OR REPLACE FUNCTION find_recently_active_teams(
    p_provider_id uuid,
    p_active_window_days integer DEFAULT 3,
    p_cooldown_hours integer DEFAULT 20,
    p_row_limit integer DEFAULT 2000
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    WITH active_masters AS (
        SELECT home_team_master_id AS master_id
        FROM games
        WHERE game_date >= CURRENT_DATE - make_interval(days => find_recently_active_teams.p_active_window_days)
          AND game_date <= CURRENT_DATE
          AND is_excluded = false
          AND home_team_master_id IS NOT NULL
        UNION
        SELECT away_team_master_id AS master_id
        FROM games
        WHERE game_date >= CURRENT_DATE - make_interval(days => find_recently_active_teams.p_active_window_days)
          AND game_date <= CURRENT_DATE
          AND is_excluded = false
          AND away_team_master_id IS NOT NULL
    )
    SELECT t.team_id_master, t.team_name, t.provider_team_id
    FROM active_masters am
    JOIN teams t ON t.team_id_master = am.master_id,
         (SELECT EXTRACT(YEAR FROM NOW())::int AS yr) c
    WHERE t.is_deprecated = false
      AND t.provider_id = find_recently_active_teams.p_provider_id
      AND (t.last_scraped_at IS NULL
           OR t.last_scraped_at < NOW() - make_interval(hours => find_recently_active_teams.p_cooldown_hours))
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_recently_active_teams.p_row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_recently_active_teams(uuid, integer, integer, integer) TO authenticated, service_role;

-- Forward-only refresh of the priority-ladder doc to register the new tier-2 producer.
COMMENT ON COLUMN scrape_requests.priority IS
  'Lower number = higher priority. 1=user-clicked, 2=daily yesterday-game + active-team, 3=discovery, 4=safety-net, 5=default';
