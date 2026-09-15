-- find_topup_teams, identical to 20260827100200 (signature, body, grants) apart from
-- ORDER BY ... DESC NULLS LAST. Results are unchanged: last_scraped_at < p_cutoff
-- already excludes NULLs, so only the query plan changes.

CREATE OR REPLACE FUNCTION public.find_topup_teams(
    p_provider_id uuid,
    p_cutoff timestamptz,
    p_row_limit integer DEFAULT 1000,
    p_offset integer DEFAULT 0
)
RETURNS TABLE(
    team_id_master uuid,
    team_name text,
    provider_id uuid,
    provider_team_id text,
    age_group text,
    birth_year integer,
    last_scraped_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT t.team_id_master, t.team_name, t.provider_id, t.provider_team_id,
           t.age_group, t.birth_year, t.last_scraped_at
    FROM public.teams t,
         (select extract(year from (now() - interval '7 months'))::int as yr) c
    WHERE t.provider_id = find_topup_teams.p_provider_id
      AND t.last_scraped_at < find_topup_teams.p_cutoff
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
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
    -- NULLS LAST is the order teams_provider_scrape_priority_idx yields walked
    -- backwards; plain DESC (NULLS FIRST) cannot take its order from the index, so
    -- every eligible team is sorted.
    -- team_id_master breaks ties for stable OFFSET paging, not just determinism:
    -- last_scraped_at is stamped per run, so tie groups span thousands of rows.
    ORDER BY t.last_scraped_at DESC NULLS LAST, t.team_id_master
    LIMIT find_topup_teams.p_row_limit
    OFFSET find_topup_teams.p_offset;
$$;

REVOKE EXECUTE ON FUNCTION public.find_topup_teams(uuid, timestamptz, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.find_topup_teams(uuid, timestamptz, integer, integer) TO service_role;
