-- find_discovery_teams, redefined from 20260827100300 with the same signature, filters,
-- eligibility predicate and ordering. Two things change:
--
-- * "No future games" and "a game in the last 90 days" read teams.last_fixture_at, which
--   resolves team_merge_map, instead of aggregating every games row per call. The column is
--   only as fresh as its last refresh, so a fixture imported since then leaves that team
--   eligible: a wasted scrape, and a row-limit slot another team would have had.
-- * The eligibility predicate filters a sorted subquery (see the comment there). The
--   placeholder filter sits outside with it only to give the shared block the `AND (`
--   opener the drift test anchors on.
--
-- CREATE OR REPLACE with an unchanged signature creates no overload and keeps the GRANTs.

create or replace function find_discovery_teams(
    p_provider_id uuid,
    p_row_limit integer DEFAULT 1000
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    SELECT t.team_id_master, t.team_name, t.provider_team_id
    FROM (
        SELECT tm.*, COALESCE(tm.last_fixture_at >= CURRENT_DATE - 90, false) AS has_recent
        FROM teams tm,
             (select extract(year from (now() - interval '7 months'))::int as yr) c
        WHERE tm.is_deprecated = false
          AND tm.provider_id = find_discovery_teams.p_provider_id
          AND (tm.last_fixture_at IS NULL OR tm.last_fixture_at <= CURRENT_DATE)  -- no future games on record
          -- Match scrape-games age filters: PitchRank supports U10-U19 only.
          AND (tm.age_group IS NULL OR UPPER(TRIM(tm.age_group)) NOT IN ('U8','U-8','U9','U-9'))
          AND (tm.birth_year IS NULL OR tm.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))
        ORDER BY
          -- Teams with a game in the last 90 days first (schedule probably arriving soon),
          -- then oldest-scraped (NULLs first).
          has_recent DESC,
          tm.last_scraped_at ASC NULLS FIRST
    ) t
    -- Filtering outside the sorted subquery stops the predicate's ranking_history probe once
    -- the LIMIT is filled, instead of running it on every candidate team.
    -- Placeholder unknown team filter.
    WHERE NOT (t.team_name = 'unknown_' || t.provider_team_id)
      AND ( -- canonical-eligibility-v1
            -- a fixture in the future, or within the last 30 days (late scores, outages)
            (t.last_fixture_at IS NOT NULL AND t.last_fixture_at >= CURRENT_DATE - 30)
            -- ranked in any snapshot in the last 30 days
         OR EXISTS (SELECT 1 FROM public.ranking_history h
                     WHERE h.team_id = t.team_id_master
                       AND h.snapshot_date >= CURRENT_DATE - 30)
            -- played recently enough
         OR (t.last_played_at IS NOT NULL
             AND t.last_played_at > CURRENT_DATE - INTERVAL '12 months')
            -- never produced a game, but not yet proven futile
         OR (COALESCE(t.game_row_count, 0) = 0 AND COALESCE(t.scrape_attempts, 0) < 10)
            -- six-month re-probe: nothing filtered stays filtered forever
         OR (t.last_scraped_at IS NULL
             OR t.last_scraped_at < NOW() - INTERVAL '6 months')
      )
    -- Must match the subquery's order, which then satisfies it with no second sort; any
    -- other order makes that sort drain the filter, probing every candidate team.
    ORDER BY t.has_recent DESC, t.last_scraped_at ASC NULLS FIRST
    LIMIT find_discovery_teams.p_row_limit;
$$;
