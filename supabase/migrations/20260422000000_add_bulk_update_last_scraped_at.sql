-- Bulk update teams.last_scraped_at from a JSONB payload.
--
-- Replaces per-row UPDATE loops in scripts/scrape_games.py::_bulk_log_team_scrapes
-- and src/etl/enhanced_pipeline.py::_update_team_scrape_dates. A single RPC call
-- with ~2,000 rows replaces ~2,000 sequential REST round-trips.
--
-- Payload shape: [{"team_id_master": "<uuid>", "last_scraped_at": "<iso8601>"}, ...]
--
-- Behavioral contract:
--   * Empty or null `updates` returns 0 immediately.
--   * Duplicate team_id_master keys in payload: last value wins (UPDATE...FROM picks
--     one arbitrarily). Acceptable — callers produce unique keys by construction.
--   * team_id_master values with no matching row in `teams`: silently skipped.
--     Returned rowcount reflects ACTUAL updates, not input length. Callers must
--     treat `rowcount < len(payload)` as a warning, not an error.
--   * Malformed timestamp strings: cast error raised loudly. Do not mask.
--
-- service_role-only RPC; no GRANT needed. Additive — does not modify existing
-- objects.

create or replace function public.bulk_update_last_scraped_at(updates jsonb)
returns int
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  affected int;
begin
  if updates is null or jsonb_array_length(updates) = 0 then
    return 0;
  end if;

  update public.teams t
     set last_scraped_at = u.last_scraped_at
    from jsonb_to_recordset(updates) as u(
      team_id_master uuid,
      last_scraped_at timestamptz
    )
   where t.team_id_master = u.team_id_master;

  get diagnostics affected = row_count;
  return affected;
end;
$$;

comment on function public.bulk_update_last_scraped_at(jsonb) is
'Bulk update teams.last_scraped_at from a JSONB array of {team_id_master, last_scraped_at}.
Returns the number of rows actually updated (may be less than input length if a
team_id_master has no matching row).';
