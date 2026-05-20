-- RPC: find_discovery_teams
--
-- Returns GotSport teams that have NO future games visible in our database.
-- These are the teams the daily yesterday-game enqueue can't trigger off —
-- either their season just ended (schedule coming soon), they're new, or they're
-- genuinely inactive. Discovery enqueue rescrapes them to catch newly-published
-- schedules.
--
-- Ordering: teams with a game in the last 90 days come first (likely between
-- seasons, schedule update imminent), then everything else by oldest
-- last_scraped_at (NULLs first — never-scraped teams).
--
-- Used by scripts/enqueue_discovery_teams.py (Phase 5).

CREATE OR REPLACE FUNCTION find_discovery_teams(
    p_provider_id uuid,
    p_row_limit integer DEFAULT 1000
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    -- Pre-aggregate per-team game flags so we scan games once, not once per team.
    -- The naive (NOT EXISTS in WHERE + EXISTS in ORDER BY) form timed out at the
    -- 137K-team scale. This CTE form runs in seconds.
    WITH team_flags AS (
        SELECT
            team_id_master,
            MAX(CASE WHEN game_date > CURRENT_DATE THEN 1 ELSE 0 END) AS has_future,
            MAX(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '90 days' THEN 1 ELSE 0 END) AS has_recent
        FROM (
            SELECT home_team_master_id AS team_id_master, game_date FROM games WHERE home_team_master_id IS NOT NULL
            UNION ALL
            SELECT away_team_master_id AS team_id_master, game_date FROM games WHERE away_team_master_id IS NOT NULL
        ) g
        GROUP BY team_id_master
    )
    SELECT t.team_id_master, t.team_name, t.provider_team_id
    FROM teams t
    LEFT JOIN team_flags tf ON tf.team_id_master = t.team_id_master,
         (SELECT EXTRACT(YEAR FROM NOW())::int AS yr) c
    WHERE t.is_deprecated = false
      AND t.provider_id = find_discovery_teams.p_provider_id
      AND COALESCE(tf.has_future, 0) = 0  -- no future games on record
      -- Match scrape-games age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))
      -- Placeholder unknown team filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY
      -- Teams with a game in the last 90 days first (schedule probably arriving soon),
      -- then oldest-scraped (NULLs first).
      COALESCE(tf.has_recent, 0) DESC,
      t.last_scraped_at ASC NULLS FIRST
    LIMIT find_discovery_teams.p_row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_discovery_teams(uuid, integer) TO authenticated, service_role;
