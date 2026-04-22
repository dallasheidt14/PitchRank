-- Ordered, filtered, shard-aware team fetch for scrape-games.
--
-- Replaces the 130K-team paginated fetch + Python-side sort in
-- scripts/scrape_games.py:297-396. Pushes filtering (age_group, birth_year,
-- placeholder unknown) and priority ordering (NULLS FIRST, then oldest) into
-- Postgres, and adds deterministic hash sharding for parallel workflow shards.
--
-- THIS MIGRATION IS PURELY ADDITIVE. The existing
-- `get_teams_to_scrape(p_provider_id)` function used by src/scrapers/base.py
-- is NOT modified or dropped.
--
-- Note: hashtext() is deterministic within a Postgres major version. If the PG
-- major version changes, shards reshuffle — acceptable, one-time rescrape of
-- some teams.
--
-- service_role-only RPC; no GRANT needed.

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
    select extract(year from now())::int as yr
  )
  select t.*
  from public.teams t, current_year c
  where t.provider_id = p_provider_id

    -- Hash sharding: mutation-safe, independent of last_scraped_at.
    and (p_shard_count <= 1 or (hashtext(t.team_id_master::text) % p_shard_count) = p_shard_index)

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
    --   young end: U7 (yr-7), U8 (yr-8), U9 (yr-9)
    --   old end:   U20 (yr-20), U21 (yr-21)
    -- Five values — must match the Python list exactly.
    and (t.birth_year is null
         or t.birth_year not in (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))

    -- Placeholder unknown filter.
    and not (t.team_name = 'unknown_' || t.provider_team_id)

  order by t.last_scraped_at asc nulls first
  limit coalesce(p_limit, 2147483647);
$$;

comment on function public.get_teams_to_scrape_limited(uuid, int, int, int, boolean, boolean) is
'Ordered, filtered, shard-aware team fetch for scrape-games. Priority: NULL
last_scraped_at first, then oldest. Hash shards by team_id_master for
mutation-safe parallel workflow shards.';

-- Composite index: provider_id + priority order (NULLS FIRST).
-- Serves the primary WHERE + ORDER BY path for the RPC.
create index if not exists teams_provider_scrape_priority_idx
  on public.teams (provider_id, last_scraped_at asc nulls first);
