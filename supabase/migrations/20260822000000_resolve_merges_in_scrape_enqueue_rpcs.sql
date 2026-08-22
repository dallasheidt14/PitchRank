-- Resolve merged teams in the two scrape-enqueue RPCs.
--
-- Both RPCs match a game's raw team_id_master against teams and then require
-- teams.is_deprecated = false. Those two conditions cannot both hold for a merged team: the
-- game still points at the deprecated row (games are immutable and execute_team_merge only
-- counts them, it never repoints them), and the deprecated row is filtered out. The surviving
-- team does not match either, because no game names it. So the moment a team is merged, its
-- unplayed fixtures stop being enqueued for a score fill and nothing else picks them up --
-- there is no reaper and no other producer that looks at NULL scores.
--
-- Measured after the 2026-08-21 merge batch: 348 NULL-score games stranded across 124
-- surviving teams, 291 of them still upcoming. The same hole opens on every future merge.
--
-- Three changes, both functions:
--
--   1. Resolve each affected master through team_merge_map before joining to teams. The map
--      is kept flat -- execute_team_merge cascades existing rows onto the new canonical when
--      a canonical is itself merged -- so a single hop suffices.
--
--   2. Return the provider team id carried on the GAME rather than teams.provider_team_id.
--      execute_team_merge repoints team_alias_map but copies no columns onto the survivor, so
--      after a merge the canonical row's provider_team_id can name a different registration
--      than the one holding the missing score. Of the 295 survivors in that batch, 243 hold
--      more than one GotSport registration.
--
--   3. Filter on the game's provider rather than the team row's provider label, so a team
--      merged into a canonical belonging to another provider is still enqueued for its
--      GotSport fixtures. On a normal day this selects the same teams as the old predicate
--      (106 of 106 on 2026-08-20); it differs only for merged cross-provider rows, which is
--      the defect being fixed.
--
-- The games-first shape of both functions is deliberate and preserved here. 20260526000000
-- replaced a teams-first EXISTS form in find_yesterday_null_score_teams after it timed out on
-- Memorial Day 2026 (7,214 NULL-score games in a day against ~600 normally); driving from
-- games via idx_games_date keeps that plan.
--
-- A team holding several registrations with fixtures on the same day yields one row per
-- registration. enqueue_scrape_request keeps at most one pending row per team, so one of them
-- is scraped; that is a queue-level constraint rather than something these functions decide.

-- ── find_yesterday_null_score_teams ───────────────────────────────────────────
CREATE OR REPLACE FUNCTION find_yesterday_null_score_teams(
    p_yesterday date,
    p_provider_id uuid
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    WITH affected_masters AS (
        SELECT home_team_master_id AS master_id, home_provider_id::text AS provider_team_id
        FROM games
        WHERE game_date = find_yesterday_null_score_teams.p_yesterday
          AND home_score IS NULL
          AND home_team_master_id IS NOT NULL
          AND home_provider_id IS NOT NULL
          AND provider_id = find_yesterday_null_score_teams.p_provider_id
        UNION
        SELECT away_team_master_id AS master_id, away_provider_id::text AS provider_team_id
        FROM games
        WHERE game_date = find_yesterday_null_score_teams.p_yesterday
          AND home_score IS NULL
          AND away_team_master_id IS NOT NULL
          AND away_provider_id IS NOT NULL
          AND provider_id = find_yesterday_null_score_teams.p_provider_id
    ),
    resolved_masters AS (
        SELECT COALESCE(mm.canonical_team_id, am.master_id) AS master_id,
               am.provider_team_id
        FROM affected_masters am
        LEFT JOIN team_merge_map mm ON mm.deprecated_team_id = am.master_id
    )
    SELECT DISTINCT t.team_id_master, t.team_name, rm.provider_team_id
    FROM resolved_masters rm
    JOIN teams t ON t.team_id_master = rm.master_id
    WHERE t.is_deprecated = false
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at::date < CURRENT_DATE)
    ORDER BY t.team_id_master;
$$;

GRANT EXECUTE ON FUNCTION find_yesterday_null_score_teams(date, uuid) TO authenticated, service_role;

-- ── find_recently_active_teams ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION find_recently_active_teams(
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
         (SELECT EXTRACT(YEAR FROM NOW())::int AS yr) c
    WHERE t.is_deprecated = false
      AND (t.last_scraped_at IS NULL
           OR t.last_scraped_at < NOW() - make_interval(hours => find_recently_active_teams.p_cooldown_hours))
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.team_id_master
    LIMIT find_recently_active_teams.p_row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_recently_active_teams(uuid, integer, integer, integer) TO authenticated, service_role;

COMMENT ON FUNCTION find_yesterday_null_score_teams IS
    'GotSport teams with a NULL-score game on p_yesterday, driven from games, resolving merged '
    'teams through team_merge_map and returning the registration the fixture belongs to.';
COMMENT ON FUNCTION find_recently_active_teams IS
    'GotSport teams active in the last p_active_window_days, driven from games, resolving merged '
    'teams through team_merge_map and returning the registration the fixture belongs to.';
