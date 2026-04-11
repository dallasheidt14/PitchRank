create table if not exists public.game_explainability (
  team_id uuid not null references public.teams(team_id_master) on delete cascade,
  game_uuid uuid not null references public.games(id) on delete cascade,
  game_id text not null,
  opp_id uuid not null references public.teams(team_id_master) on delete cascade,
  game_date date null,
  gf integer null,
  ga integer null,
  team_mu double precision null,
  team_sigma double precision null,
  opp_mu double precision null,
  opp_sigma double precision null,
  expected_outcome double precision null,
  actual_outcome double precision null,
  outcome_surprise double precision null,
  g_factor double precision null,
  recency_weight double precision null,
  rating_contribution double precision null,
  off_residual double precision null,
  def_residual double precision null,
  last_calculated timestamptz not null default now(),
  created_at timestamptz not null default now(),
  primary key (team_id, game_uuid)
);

create index if not exists idx_game_explainability_team_date
  on public.game_explainability (team_id, game_date desc, game_uuid);

create index if not exists idx_game_explainability_game_uuid
  on public.game_explainability (game_uuid);

alter table public.game_explainability enable row level security;

create policy "premium_users_can_read_game_explainability"
  on public.game_explainability for select
  to authenticated
  using (
    exists (
      select 1
      from public.user_profiles up
      where up.id = auth.uid()
        and up.plan in ('premium', 'admin')
    )
  );

grant select on public.game_explainability to authenticated;
grant select on public.game_explainability to service_role;
grant insert, update on public.game_explainability to service_role;

create or replace function public.batch_upsert_game_explainability(rows jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  affected_count integer;
begin
  with payload as (
    select
      (item->>'team_id')::uuid as team_id,
      (item->>'game_uuid')::uuid as game_uuid,
      item->>'game_id' as game_id,
      (item->>'opp_id')::uuid as opp_id,
      (item->>'game_date')::date as game_date,
      (item->>'gf')::integer as gf,
      (item->>'ga')::integer as ga,
      (item->>'team_mu')::double precision as team_mu,
      (item->>'team_sigma')::double precision as team_sigma,
      (item->>'opp_mu')::double precision as opp_mu,
      (item->>'opp_sigma')::double precision as opp_sigma,
      (item->>'expected_outcome')::double precision as expected_outcome,
      (item->>'actual_outcome')::double precision as actual_outcome,
      (item->>'outcome_surprise')::double precision as outcome_surprise,
      (item->>'g_factor')::double precision as g_factor,
      (item->>'recency_weight')::double precision as recency_weight,
      (item->>'rating_contribution')::double precision as rating_contribution,
      (item->>'off_residual')::double precision as off_residual,
      (item->>'def_residual')::double precision as def_residual
    from jsonb_array_elements(rows) as item
  )
  insert into public.game_explainability (
    team_id,
    game_uuid,
    game_id,
    opp_id,
    game_date,
    gf,
    ga,
    team_mu,
    team_sigma,
    opp_mu,
    opp_sigma,
    expected_outcome,
    actual_outcome,
    outcome_surprise,
    g_factor,
    recency_weight,
    rating_contribution,
    off_residual,
    def_residual,
    last_calculated
  )
  select
    payload.team_id,
    payload.game_uuid,
    payload.game_id,
    payload.opp_id,
    payload.game_date,
    payload.gf,
    payload.ga,
    payload.team_mu,
    payload.team_sigma,
    payload.opp_mu,
    payload.opp_sigma,
    payload.expected_outcome,
    payload.actual_outcome,
    payload.outcome_surprise,
    payload.g_factor,
    payload.recency_weight,
    payload.rating_contribution,
    payload.off_residual,
    payload.def_residual,
    now()
  from payload
  on conflict (team_id, game_uuid) do update
  set
    game_id = excluded.game_id,
    opp_id = excluded.opp_id,
    game_date = excluded.game_date,
    gf = excluded.gf,
    ga = excluded.ga,
    team_mu = excluded.team_mu,
    team_sigma = excluded.team_sigma,
    opp_mu = excluded.opp_mu,
    opp_sigma = excluded.opp_sigma,
    expected_outcome = excluded.expected_outcome,
    actual_outcome = excluded.actual_outcome,
    outcome_surprise = excluded.outcome_surprise,
    g_factor = excluded.g_factor,
    recency_weight = excluded.recency_weight,
    rating_contribution = excluded.rating_contribution,
    off_residual = excluded.off_residual,
    def_residual = excluded.def_residual,
    last_calculated = now();

  get diagnostics affected_count = row_count;

  return affected_count;
end;
$$;

grant execute on function public.batch_upsert_game_explainability(jsonb) to service_role;

comment on table public.game_explainability is
  'Per-team, per-game Glicko explainability breakdown derived post-hoc from final converged ratings.';

comment on function public.batch_upsert_game_explainability(jsonb) is
  'Batch upserts per-team game explainability rows from a JSONB payload.';
