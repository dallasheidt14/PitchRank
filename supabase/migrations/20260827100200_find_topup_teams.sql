-- Serve drain_queue.py's teams-table top-up from an RPC so it shares the one
-- canonical scrape-eligibility predicate with find_stale_teams and
-- find_discovery_teams rather than hand-building an equivalent PostgREST query.
--
-- p_cutoff is an absolute timestamp, not a relative window, because the caller
-- computes it once before its paging loop. A now()-relative gate evaluated per
-- call would let a team cross the boundary mid-run and insert at the head of
-- the descending order, pushing rows the loop had not read yet past its offset.
--
-- Deprecated teams are not filtered here: the PostgREST query this replaces did
-- not filter them either, and widening the rule is a separate change.

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
    -- team_id_master breaks ties for stable OFFSET paging, not just determinism:
    -- last_scraped_at is stamped per run, so tie groups span thousands of rows.
    ORDER BY t.last_scraped_at DESC, t.team_id_master
    LIMIT find_topup_teams.p_row_limit
    OFFSET find_topup_teams.p_offset;
$$;

REVOKE EXECUTE ON FUNCTION public.find_topup_teams(uuid, timestamptz, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.find_topup_teams(uuid, timestamptz, integer, integer) TO service_role;

COMMENT ON FUNCTION public.find_topup_teams(uuid, timestamptz, integer, integer) IS
  'Eligible GotSport teams last scraped before p_cutoff, most-recently-scraped first, '
  'for drain_queue.py to top up a short queue batch. Carries the canonical scrape-'
  'eligibility predicate shared with find_stale_teams and find_discovery_teams.';
