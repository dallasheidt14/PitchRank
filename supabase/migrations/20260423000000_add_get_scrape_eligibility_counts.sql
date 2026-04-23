-- Dashboard-aligned team-scraping status counts that mirror the exact
-- eligibility filters in get_teams_to_scrape_limited.
--
-- The Streamlit dashboard previously counted teams directly against
-- public.teams with just a last_scraped_at predicate. That gave "needs
-- scraping" totals that included U8/U9, U20+/U7, and placeholder
-- unknown_<provider_team_id> rows — which the scrape workflow will never
-- pick up. Operators saw 6,000+ "stale" teams even when the workflow had
-- already drained everything it was allowed to scrape.
--
-- This RPC returns recent/stale/never counts over the SAME eligibility
-- predicate the workflow uses, so dashboard numbers and workflow behavior
-- stay in lockstep. Passing p_provider_id = NULL counts across all providers.
--
-- service_role-only; no GRANT needed.

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
    select extract(year from now())::int as yr
  ),
  eligible as (
    select t.last_scraped_at
    from public.teams t, current_year c
    where (p_provider_id is null or t.provider_id = p_provider_id)

      -- Age-group filter (PitchRank supports U10–U19 only).
      and (t.age_group is null
           or upper(trim(t.age_group)) not in ('U8','U-8','U9','U-9'))

      -- Birth-year exclusion — dynamic per current year.
      --   young end: U7 (yr-7), U8 (yr-8), U9 (yr-9)
      --   old end:   U20 (yr-20), U21 (yr-21)
      and (t.birth_year is null
           or t.birth_year not in (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))

      -- Placeholder unknown filter.
      and not (t.team_name = 'unknown_' || t.provider_team_id)
  )
  select
    count(*) filter (where last_scraped_at >= now() - interval '7 days')                                     as recent_count,
    count(*) filter (where last_scraped_at <  now() - interval '7 days' and last_scraped_at is not null)     as stale_count,
    count(*) filter (where last_scraped_at is null)                                                          as never_count
  from eligible;
$$;

comment on function public.get_scrape_eligibility_counts(uuid) is
'Recent/stale/never-scraped counts over scrape-eligible teams only. Mirrors
the eligibility filters of get_teams_to_scrape_limited so dashboard KPIs
reflect what the scrape workflow will actually pick up.';
