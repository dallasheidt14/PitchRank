-- The browser roles read teams and games column by column, without the columns that carry a provider's
-- own team id: teams.provider_team_id, and on games home_provider_id, away_provider_id, source_url
-- (the provider page it was read from) and game_uid (older rows build it from the two provider ids).
-- Server routes and scripts read them with the service role, which holds every column.
--
-- A column added to either table later is NOT readable by anon or authenticated until a later migration
-- grants it, so a page that names a new column fails until then, and a `*` select on either table fails.
--
-- Apply only after the site's explicit column lists have deployed.

REVOKE SELECT ON public.teams FROM anon, authenticated;
GRANT SELECT (
    id,
    team_id_master,
    provider_id,
    team_name,
    club_name,
    state,
    state_code,
    age_group,
    birth_year,
    gender,
    created_at,
    updated_at,
    last_scraped_at,
    is_deprecated,
    team_name_original,
    league,
    distinction,
    last_played_at,
    last_fixture_at,
    game_row_count,
    scrape_attempts,
    state_source,
    state_confidence,
    state_assigned_at
) ON public.teams TO anon, authenticated;

REVOKE SELECT ON public.games FROM anon, authenticated;
GRANT SELECT (
    id,
    home_team_master_id,
    away_team_master_id,
    home_score,
    away_score,
    result,
    game_date,
    competition,
    division_name,
    event_name,
    venue,
    provider_id,
    scraped_at,
    created_at,
    is_immutable,
    original_import_id,
    ml_overperformance,
    age_group,
    mls_division,
    is_excluded
) ON public.games TO anon, authenticated;
