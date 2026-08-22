-- Resolve merged teams in the two scrape-enqueue RPCs.
--
-- Both RPCs match games by the raw team_id_master on the game row and then require
-- teams.is_deprecated = false. Those two conditions cannot both hold for a merged team: the
-- game still points at the deprecated row (games are immutable and execute_team_merge only
-- counts them, it never repoints them), and the deprecated row is filtered out. The surviving
-- team does not match either, because no game names it. So the moment a team is merged, its
-- unplayed fixtures stop being enqueued for a score fill and nothing else picks them up --
-- there is no reaper and no other producer that looks at NULL scores.
--
-- After the 2026-08-21 merge batch this stranded 348 NULL-score games across 124 surviving
-- teams, 291 of them still upcoming. The same hole opens on every future merge.
--
-- Fix: resolve the game's team through team_merge_map before matching, using the same
-- IN (SELECT deprecated_team_id ... WHERE canonical_team_id = t.team_id_master) idiom already
-- used by the rankings views (20260210000000_fix_rankings_view_merge_resolution.sql).
-- team_merge_map is kept flat -- execute_team_merge cascades existing rows onto the new
-- canonical when a canonical is itself merged -- so a single hop is sufficient.

-- ── find_yesterday_null_score_teams ───────────────────────────────────────────
-- Signature unchanged; only the EXISTS clause gains the merge-resolved arms.
CREATE OR REPLACE FUNCTION find_yesterday_null_score_teams(
    p_yesterday date,
    p_provider_id uuid
)
RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)
LANGUAGE sql
STABLE
AS $$
    SELECT DISTINCT t.team_id_master, t.team_name, t.provider_team_id
    FROM teams t
    WHERE t.is_deprecated = false
      AND t.provider_id = find_yesterday_null_score_teams.p_provider_id
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at::date < CURRENT_DATE)
      AND EXISTS (
          SELECT 1 FROM games g
          WHERE (g.home_team_master_id = t.team_id_master
                 OR g.away_team_master_id = t.team_id_master
                 OR g.home_team_master_id IN (
                       SELECT mm.deprecated_team_id FROM team_merge_map mm
                       WHERE mm.canonical_team_id = t.team_id_master)
                 OR g.away_team_master_id IN (
                       SELECT mm.deprecated_team_id FROM team_merge_map mm
                       WHERE mm.canonical_team_id = t.team_id_master))
            AND g.game_date = find_yesterday_null_score_teams.p_yesterday
            AND g.home_score IS NULL
      )
    ORDER BY t.team_id_master;
$$;

GRANT EXECUTE ON FUNCTION find_yesterday_null_score_teams(date, uuid) TO authenticated, service_role;

-- ── find_recently_active_teams ────────────────────────────────────────────────
-- Here the game's team id is carried in a CTE and joined to teams, so the resolution goes on
-- the join rather than in a WHERE arm: map each active master id to its canonical before
-- joining, leaving unmerged ids untouched.
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
        SELECT home_team_master_id AS master_id
        FROM games
        WHERE game_date >= CURRENT_DATE - make_interval(days => find_recently_active_teams.p_active_window_days)
          AND game_date <= CURRENT_DATE
          AND is_excluded = false
          AND home_team_master_id IS NOT NULL
        UNION
        SELECT away_team_master_id AS master_id
        FROM games
        WHERE game_date >= CURRENT_DATE - make_interval(days => find_recently_active_teams.p_active_window_days)
          AND game_date <= CURRENT_DATE
          AND is_excluded = false
          AND away_team_master_id IS NOT NULL
    ),
    resolved_masters AS (
        SELECT DISTINCT COALESCE(mm.canonical_team_id, am.master_id) AS master_id
        FROM active_masters am
        LEFT JOIN team_merge_map mm ON mm.deprecated_team_id = am.master_id
    )
    SELECT t.team_id_master, t.team_name, t.provider_team_id
    FROM resolved_masters am
    JOIN teams t ON t.team_id_master = am.master_id,
         (SELECT EXTRACT(YEAR FROM NOW())::int AS yr) c
    WHERE t.is_deprecated = false
      AND t.provider_id = find_recently_active_teams.p_provider_id
      AND (t.last_scraped_at IS NULL
           OR t.last_scraped_at < NOW() - make_interval(hours => find_recently_active_teams.p_cooldown_hours))
      -- Age filters: PitchRank supports U10-U19 only.
      AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
      AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))
      -- Placeholder unknown filter.
      AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_recently_active_teams.p_row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_recently_active_teams(uuid, integer, integer, integer) TO authenticated, service_role;

COMMENT ON FUNCTION find_yesterday_null_score_teams IS
    'GotSport teams with a NULL-score game on p_yesterday, resolving games from merged teams '
    'through team_merge_map so a merge does not strand its fixtures.';
COMMENT ON FUNCTION find_recently_active_teams IS
    'GotSport teams active in the last p_active_window_days, resolving games from merged teams '
    'through team_merge_map so a merge does not strand its fixtures.';
