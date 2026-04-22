-- Fix signed-modulo bug in get_teams_to_scrape_limited hash sharding.
--
-- The original function (added in 20260422000002) used:
--     (hashtext(team_id_master::text) % p_shard_count) = p_shard_index
--
-- Postgres `%` preserves the sign of the dividend, so negative hashes
-- produce negative remainders (-1, -2, -3, -4 at p_shard_count=5). These
-- never match positive shard_index values 1..4 — ~48% of teams were silently
-- unassigned. Shard 0 accidentally received both +0 and -0 residues, so it
-- absorbed ~20% of teams while shards 1-4 got ~10% each.
--
-- Fix: Euclidean modulo `((h % n) + n) % n`. Guaranteed non-negative result
-- in [0, n). Safe against INT32_MIN where `abs()` would overflow.
--
-- This migration is additive in intent — it replaces the function body via
-- CREATE OR REPLACE. The signature, indexes, and grants are unchanged.

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
