-- Return all approved aliases for a provider in a single RPC call.
--
-- Replaces the paginated .range() loop in
-- src/etl/enhanced_pipeline.py::EnhancedETLPipeline._ensure_initialized, which
-- currently issues ~84 paginated GETs at 1000 rows each per pipeline init for
-- the GotSport provider.
--
-- service_role-only RPC; no GRANT needed. Additive — does not modify existing
-- alias tables or functions.

create or replace function public.get_approved_aliases(p_provider_id uuid)
returns table (
  provider_team_id text,
  team_id_master   uuid,
  match_method     text,
  review_status    text
)
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  -- review_status is surfaced as a constant column so callers that cache it
  -- see the same row shape whether they hit the RPC or the legacy paginated
  -- .range() fallback (which projects review_status from the table).
  select
    m.provider_team_id,
    m.team_id_master,
    m.match_method,
    'approved'::text as review_status
  from public.team_alias_map m
  where m.provider_id = p_provider_id
    and m.review_status = 'approved';
$$;

comment on function public.get_approved_aliases(uuid) is
'Return all approved (provider_team_id, team_id_master, match_method) rows for
the given provider in one call. Replaces paginated alias preload.';

-- Covering partial index — serves the RPC in a single index-only scan.
create index if not exists team_alias_map_provider_approved_idx
  on public.team_alias_map (provider_id)
  include (provider_team_id, team_id_master, match_method)
  where review_status = 'approved';
