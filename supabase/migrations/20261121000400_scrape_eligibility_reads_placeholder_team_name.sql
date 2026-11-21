-- The six scrape-eligibility functions skip a team named "Unknown team" as well as one named
-- unknown_<provider_team_id>.
--
-- team_name is publicly readable and the legacy name exposes the provider's id, so a team with no
-- name is stored as "Unknown team". Apply this before the code writing that name ships: until it
-- is live, every new "Unknown team" row is eligible for scraping, though most hold event ids that
-- never resolve. Skipping the legacy form too keeps the rows not yet renamed out.
--
-- Each statement is its newest definition copied whole, with only the placeholder clause changed.
-- CREATE OR REPLACE assigns every attribute the statement leaves out its default, so volatility,
-- defaults, SECURITY DEFINER and SET search_path are repeated as they stand. Signatures are
-- unchanged, so no overload is created and the existing GRANTs are kept; find_topup_teams'
-- REVOKE and GRANT are restated as in 20260915120000.

-- get_teams_to_scrape_limited (unchanged from 20260824120000 except the placeholder clause)
create or replace function public.get_teams_to_scrape_limited(
  p_provider_id    uuid,
  p_limit          int     default null,   -- null = no limit
  p_shard_index    int     default 0,      -- 0-based
  p_shard_count    int     default 1,      -- 1 = no sharding (hash filter is a no-op)
  p_include_recent boolean default false,  -- bypass 7-day staleness filter
  p_null_only      boolean default false   -- only last_scraped_at IS NULL
)
returns setof public.teams
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  with current_year as (
    select extract(year from (now() - interval '7 months'))::int as yr
  )
  select t.*
  from public.teams t, current_year c
  where t.provider_id = p_provider_id

    -- Hash sharding with sign-safe Euclidean modulo. The extra (+ n) % n
    -- shifts any negative remainder into [0, n). Independent of
    -- last_scraped_at so shards stay disjoint even while other shards
    -- mutate that column mid-run.
    and (p_shard_count <= 1
         or (((hashtext(t.team_id_master::text) % p_shard_count) + p_shard_count) % p_shard_count) = p_shard_index)

    -- Staleness / null / include-recent gating.
    and (p_include_recent
         or t.last_scraped_at is null
         or t.last_scraped_at < now() - interval '7 days')
    and (not p_null_only or t.last_scraped_at is null)

    -- Age-group filter (PitchRank supports U10–U19 only).
    and (t.age_group is null
         or upper(trim(t.age_group)) not in ('U8','U-8','U9','U-9'))

    -- Birth-year exclusion — dynamic per current year.
    -- Mirrors the Python post-filter in scripts/scrape_games.py:
    --   young end: U9 (yr-8), U8 (yr-7), U7 (yr-6), against the season year
    --   old end:   aged out at 21+ (yr-20, yr-21), against the season year
    -- Five values — must match the Python list exactly.
    and (t.birth_year is null
         or t.birth_year not in (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))

    -- Placeholder unknown filter.
    and NOT (t.team_name = 'Unknown team' OR t.team_name = 'unknown_' || t.provider_team_id)

  order by t.last_scraped_at asc nulls first
  limit coalesce(p_limit, 2147483647);
$$;

-- get_scrape_eligibility_counts (unchanged from 20260824120000 except the placeholder clause)
create or replace function public.get_scrape_eligibility_counts(
  p_provider_id uuid default null
)
returns table (
  recent_count bigint,
  stale_count  bigint,
  never_count  bigint
)
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  with current_year as (
    select extract(year from (now() - interval '7 months'))::int as yr
  ),
  eligible as (
    select t.last_scraped_at
    from public.teams t, current_year c
    where (p_provider_id is null or t.provider_id = p_provider_id)

      -- Age-group filter (PitchRank supports U10–U19 only).
      and (t.age_group is null
           or upper(trim(t.age_group)) not in ('U8','U-8','U9','U-9'))

      -- Birth-year exclusion — dynamic per current year.
      --   young end: U9 (yr-8), U8 (yr-7), U7 (yr-6), against the season year
      --   old end:   aged out at 21+ (yr-20, yr-21), against the season year
      and (t.birth_year is null
           or t.birth_year not in (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))

      -- Placeholder unknown filter.
      and NOT (t.team_name = 'Unknown team' OR t.team_name = 'unknown_' || t.provider_team_id)
  )
  select
    count(*) filter (where last_scraped_at >= now() - interval '7 days')                                     as recent_count,
    count(*) filter (where last_scraped_at <  now() - interval '7 days' and last_scraped_at is not null)     as stale_count,
    count(*) filter (where last_scraped_at is null)                                                          as never_count
  from eligible;
$$;

-- find_recently_active_teams (unchanged from 20260824120000 except the placeholder clause)
create or replace function find_recently_active_teams(
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
        SELECT home_team_master_id AS master_id, home_provider_id::text AS provider_team_id
        FROM games
        WHERE game_date >= CURRENT_DATE - make_interval(days => find_recently_active_teams.p_active_window_days)
          AND game_date <= CURRENT_DATE
          AND is_excluded = false
          AND home_team_master_id IS NOT NULL
          AND home_provider_id IS NOT NULL
          AND provider_id = find_recently_active_teams.p_provider_id
        UNION
        SELECT away_team_master_id AS master_id, away_provider_id::text AS provider_team_id
        FROM games
        WHERE game_date >= CURRENT_DATE - make_interval(days => find_recently_active_teams.p_active_window_days)
          AND game_date <= CURRENT_DATE
          AND is_excluded = false
          AND away_team_master_id IS NOT NULL
          AND away_provider_id IS NOT NULL
          AND provider_id = find_recently_active_teams.p_provider_id
    ),
    resolved_masters AS (
        SELECT COALESCE(mm.canonical_team_id, am.master_id) AS master_id,
               am.provider_team_id
        FROM active_masters am
        LEFT JOIN team_merge_map mm ON mm.deprecated_team_id = am.master_id
    )
    SELECT DISTINCT t.team_id_master, t.team_name, rm.provider_team_id
    FROM resolved_masters rm
    JOIN teams t ON t.team_id_master = rm.master_id,
         (select extract(year from (now() - interval '7 months'))::int as yr) c
    WHERE t.is_deprecated = false
      AND (t.last_scraped_at IS NULL
           OR t.last_scraped_at < NOW() - make_interval(hours => find_recently_active_teams.p_cooldown_hours))
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'Unknown team' OR t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.team_id_master
    LIMIT find_recently_active_teams.p_row_limit;
$$;

-- find_stale_teams (unchanged from 20260827100300 except the placeholder clause)
create or replace function find_stale_teams(
    p_provider_id uuid,
    p_row_limit integer DEFAULT 500
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    SELECT t.team_id_master, t.team_name, t.provider_team_id
    FROM teams t, (select extract(year from (now() - interval '7 months'))::int as yr) c
    WHERE t.is_deprecated = false
      AND t.provider_id = find_stale_teams.p_provider_id
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at < NOW() - INTERVAL '90 days')
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'Unknown team' OR t.team_name = 'unknown_' || t.provider_team_id)
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
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_stale_teams.p_row_limit;
$$;

-- find_discovery_teams (unchanged from 20260915130000 except the placeholder clause)
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
    WHERE NOT (t.team_name = 'Unknown team' OR t.team_name = 'unknown_' || t.provider_team_id)
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

-- find_topup_teams (unchanged from 20260915120000 except the placeholder clause)
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
      AND NOT (t.team_name = 'Unknown team' OR t.team_name = 'unknown_' || t.provider_team_id)
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
