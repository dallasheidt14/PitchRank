-- Scrape eligibility rolls with the soccer season, not the calendar.
--
-- The excluded-cohort years were derived from extract(year from now()), which
-- rolls on Jan 1 while cohorts roll on Aug 1. From Aug 1 to Dec 31 the old
-- offsets excluded the U10 cohort (labelled "U9"), and from Jan 1 to Jul 31
-- they excluded u19's oldest birth year (the age-20 collapse files it into
-- u19). now() - interval '7 months' yields the season year: Aug-Dec maps to
-- the calendar year, Jan-Jul to the previous one.
--
-- Offsets against the season year: yr-21/yr-20 (aged out, U21+) and
-- yr-8/yr-7/yr-6 (U9 and younger). yr-19 stays eligible: it is u19.
-- Signatures are unchanged (no overloads created) and CREATE OR REPLACE
-- preserves the existing GRANTs. Mirrors scripts/drain_queue.py
-- _excluded_birth_years and src/utils/team_utils.py scrape_excluded_birth_years.

-- get_teams_to_scrape_limited (unchanged except the season-year CTE and cohort offsets)
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
    and not (t.team_name = 'unknown_' || t.provider_team_id)

  order by t.last_scraped_at asc nulls first
  limit coalesce(p_limit, 2147483647);
$$;

-- get_scrape_eligibility_counts (unchanged except the season-year CTE and cohort offsets)
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
      and not (t.team_name = 'unknown_' || t.provider_team_id)
  )
  select
    count(*) filter (where last_scraped_at >= now() - interval '7 days')                                     as recent_count,
    count(*) filter (where last_scraped_at <  now() - interval '7 days' and last_scraped_at is not null)     as stale_count,
    count(*) filter (where last_scraped_at is null)                                                          as never_count
  from eligible;
$$;

-- find_discovery_teams (unchanged except the season-year CTE and cohort offsets)
create or replace function find_discovery_teams(
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
         (select extract(year from (now() - interval '7 months'))::int as yr) c
    WHERE t.is_deprecated = false
      AND t.provider_id = find_discovery_teams.p_provider_id
      AND COALESCE(tf.has_future, 0) = 0  -- no future games on record
      -- Match scrape-games age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 8, c.yr - 7, c.yr - 6))
      -- Placeholder unknown team filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY
      -- Teams with a game in the last 90 days first (schedule probably arriving soon),
      -- then oldest-scraped (NULLs first).
      COALESCE(tf.has_recent, 0) DESC,
      t.last_scraped_at ASC NULLS FIRST
    LIMIT find_discovery_teams.p_row_limit;
$$;

-- find_stale_teams (unchanged except the season-year CTE and cohort offsets)
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
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_stale_teams.p_row_limit;
$$;

-- find_recently_active_teams (unchanged except the season-year CTE and cohort offsets)
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
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.team_id_master
    LIMIT find_recently_active_teams.p_row_limit;
$$;
