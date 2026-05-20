-- RPC: find_stale_teams
--
-- Returns GotSport teams that have never been scraped or that haven't been
-- scraped in the last 90 days. Safety-net backstop for teams the daily
-- yesterday-game enqueue and weekly discovery enqueue both miss (deprecated→
-- undeprecated cycles, provider relinks, etc.).
--
-- Filters mirror scrape-games.yml exclusion logic:
-- - is_deprecated = false
-- - GotSport provider
-- - Excludes U8/U9 (age_group + birth_year)
-- - Excludes U20+ (birth_year)
-- - Excludes 'unknown_*' placeholder teams
--
-- Ordering: oldest scraped first (NULLs first — never-scraped teams).
--
-- Used by scripts/enqueue_safety_net.py (Phase 6).

CREATE OR REPLACE FUNCTION find_stale_teams(
    p_provider_id uuid,
    p_row_limit integer DEFAULT 500
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    SELECT t.team_id_master, t.team_name, t.provider_team_id
    FROM teams t, (SELECT EXTRACT(YEAR FROM NOW())::int AS yr) c
    WHERE t.is_deprecated = false
      AND t.provider_id = find_stale_teams.p_provider_id
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at < NOW() - INTERVAL '90 days')
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_stale_teams.p_row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_stale_teams(uuid, integer) TO authenticated, service_role;
