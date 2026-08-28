-- Stop re-enqueueing teams that have stopped playing, or that never produced a game.
--
-- find_stale_teams selects on "never scraped or 90d+ stale" and find_discovery_teams
-- on "no future games". A dormant team satisfies both permanently, so both re-enqueue
-- it every Sunday forever: 80% of all scrape-log rows found zero games, and 12,732
-- teams with no game rows at all had absorbed 313,226 scrapes between them.
--
-- Both gain the canonical eligibility predicate, verbatim and byte-identical to the
-- copy in find_topup_teams. The -- canonical-eligibility-v1 anchor is how
-- tests/unit/test_scrape_activity_predicate.py locates the three copies to compare;
-- bump the version suffix if the rule changes.
--
-- EVERY table reference inside that block must stay schema-qualified, which is why
-- it says public.ranking_history while the surrounding clauses name `teams` bare.
-- These two functions are security-invoker with no search_path, but the third copy
-- lives in find_topup_teams, which runs under SET search_path = ''. An unqualified
-- name added to the shared block would resolve here and throw there — and the drift
-- test would stay green, because the copies would still be identical.
--
-- find_recently_active_teams and find_yesterday_null_score_teams are deliberately
-- left alone. They are already immune to dormant teams — both key off a recent game
-- row — and they are the only automated producers that can re-enqueue a team that
-- has come back, so filtering them is what would make this a one-way door.
-- get_teams_to_scrape_limited is manual-dispatch only (scrape-games.yml) and out of
-- scope.
--
-- Signatures are unchanged, so no overload is created and CREATE OR REPLACE
-- preserves the existing GRANTs.

-- find_discovery_teams (unchanged except the canonical eligibility predicate)
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
      AND ( -- canonical-eligibility-v1
            -- a fixture in the future, or within the last 30 days (late scores, outages)
            (t.last_fixture_at IS NOT NULL AND t.last_fixture_at >= CURRENT_DATE - 30)
            -- ranked in any snapshot in the last 30 days
         OR EXISTS (SELECT 1 FROM public.ranking_history h
                     WHERE h.team_id = t.team_id_master
                       AND h.snapshot_date >= CURRENT_DATE - 30)
            -- played recently enough
         OR (t.last_played_at IS NOT NULL
             AND t.last_played_at > CURRENT_DATE - INTERVAL '12 months')
            -- never produced a game, but not yet proven futile
         OR (COALESCE(t.game_row_count, 0) = 0 AND COALESCE(t.scrape_attempts, 0) < 10)
            -- six-month re-probe: nothing filtered stays filtered forever
         OR (t.last_scraped_at IS NULL
             OR t.last_scraped_at < NOW() - INTERVAL '6 months')
      )
    ORDER BY
      -- Teams with a game in the last 90 days first (schedule probably arriving soon),
      -- then oldest-scraped (NULLs first).
      COALESCE(tf.has_recent, 0) DESC,
      t.last_scraped_at ASC NULLS FIRST
    LIMIT find_discovery_teams.p_row_limit;
$$;

-- find_stale_teams (unchanged except the canonical eligibility predicate)
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
      AND ( -- canonical-eligibility-v1
            -- a fixture in the future, or within the last 30 days (late scores, outages)
            (t.last_fixture_at IS NOT NULL AND t.last_fixture_at >= CURRENT_DATE - 30)
            -- ranked in any snapshot in the last 30 days
         OR EXISTS (SELECT 1 FROM public.ranking_history h
                     WHERE h.team_id = t.team_id_master
                       AND h.snapshot_date >= CURRENT_DATE - 30)
            -- played recently enough
         OR (t.last_played_at IS NOT NULL
             AND t.last_played_at > CURRENT_DATE - INTERVAL '12 months')
            -- never produced a game, but not yet proven futile
         OR (COALESCE(t.game_row_count, 0) = 0 AND COALESCE(t.scrape_attempts, 0) < 10)
            -- six-month re-probe: nothing filtered stays filtered forever
         OR (t.last_scraped_at IS NULL
             OR t.last_scraped_at < NOW() - INTERVAL '6 months')
      )
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_stale_teams.p_row_limit;
$$;
