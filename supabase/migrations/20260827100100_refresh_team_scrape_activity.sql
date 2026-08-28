-- Recompute the teams.last_played_at / last_fixture_at / game_row_count /
-- scrape_attempts signals that scrape eligibility reads.
--
-- Batching is CALLER-DRIVEN, one keyset page per call, because a function
-- cannot extend its own statement_timeout. PostgreSQL arms that timer once, at
-- the start of each top-level client command; statements run inside a function
-- never re-arm it, so `SET LOCAL statement_timeout` in this body would change
-- the GUC and nothing else. Verified 2026-08-27: a DO block setting it to '1s'
-- still completed a pg_sleep(3), while the same value set before the statement
-- cancelled with 57014.
--
-- What is actually in force for a PostgREST call is the session's value.
-- pg_db_role_setting carries statement_timeout=8s for `authenticator` and has
-- no service_role entry, and SET ROLE does not re-apply per-role settings — so
-- a service-role RPC gets 8 seconds. A whole-table recompute needs minutes and
-- would be cancelled every run. scripts/refresh_team_scrape_activity.py walks
-- the table instead, passing the previous page's last id back as p_after, so
-- every individual call stays far inside that budget.
--
-- (This is also why 20260325100000's identically-shaped SET LOCAL never worked:
-- .turbo/backfill-review-2026-07-27.md records backfill_total_game_stats's RPC
-- branch raising on every production run.)
--
-- Both aggregates resolve team_merge_map. execute_team_merge cascades `teams`
-- and `team_alias_map` but repoints neither `games` nor `team_scrape_log`, so a
-- page must gather each canonical team's deprecated ids before aggregating, or
-- it undercounts every team that has absorbed a merge.
--
-- is_excluded is deliberately NOT filtered: an excluded game still evidences a
-- team that exists and plays, which is the only question these columns answer.

CREATE OR REPLACE FUNCTION public.refresh_team_scrape_activity(
  p_after uuid DEFAULT NULL,
  p_batch_size integer DEFAULT 2000,
  p_dry_run boolean DEFAULT false
)
RETURNS TABLE (rows_changed integer, last_team_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_changed integer := 0;
  v_last uuid;
BEGIN
  CREATE TEMP TABLE _tmp_team_scrape_activity ON COMMIT DROP AS
  WITH batch AS (
    SELECT t.team_id_master
    FROM public.teams t
    WHERE p_after IS NULL OR t.team_id_master > p_after
    ORDER BY t.team_id_master
    LIMIT p_batch_size
  ),
  -- Each canonical team in the page, plus every deprecated id that merged into
  -- it, so the aggregates below see the merged-away history too.
  sources AS (
    SELECT b.team_id_master AS canonical_id, b.team_id_master AS source_id
    FROM batch b
    UNION
    SELECT m.canonical_team_id, m.deprecated_team_id
    FROM public.team_merge_map m
    JOIN batch b ON b.team_id_master = m.canonical_team_id
  ),
  -- UNION, not UNION ALL, and the game id is carried so it can dedupe on: when a
  -- merge pulls both endpoints of an old game onto one canonical team, that game
  -- matches on both joins and UNION ALL would count it twice in game_row_count.
  game_rows AS (
    SELECT s.canonical_id, g.id AS game_id, g.game_date, g.home_score, g.away_score
    FROM sources s
    JOIN public.games g ON g.home_team_master_id = s.source_id
    UNION
    SELECT s.canonical_id, g.id, g.game_date, g.home_score, g.away_score
    FROM sources s
    JOIN public.games g ON g.away_team_master_id = s.source_id
  ),
  game_agg AS (
    SELECT gr.canonical_id,
           MAX(gr.game_date) FILTER (
             WHERE gr.home_score IS NOT NULL AND gr.away_score IS NOT NULL
           ) AS last_played_at,
           MAX(gr.game_date) AS last_fixture_at,
           COUNT(*) AS game_row_count
    FROM game_rows gr
    GROUP BY gr.canonical_id
  ),
  log_agg AS (
    SELECT s.canonical_id, COUNT(*) AS non_error_attempts
    FROM sources s
    JOIN public.team_scrape_log l ON l.team_id = s.source_id
    WHERE l.status <> 'error'
    GROUP BY s.canonical_id
  )
  SELECT b.team_id_master,
         g.last_played_at,
         g.last_fixture_at,
         COALESCE(g.game_row_count, 0)::integer     AS game_row_count,
         COALESCE(l.non_error_attempts, 0)::integer AS scrape_attempts
  FROM batch b
  LEFT JOIN game_agg g ON g.canonical_id = b.team_id_master
  LEFT JOIN log_agg  l ON l.canonical_id = b.team_id_master;

  -- The page's last id, not the last id CHANGED: the caller advances on this,
  -- so a page where nothing moved must still carry the walk forward.
  --
  -- ORDER BY ... LIMIT 1 rather than MAX(): PostgreSQL has no max(uuid) aggregate,
  -- and the error is a plan-time 42883 that fails the whole call. Nothing in CI
  -- executes this SQL, so only a live run would have surfaced it.
  SELECT b.team_id_master INTO v_last
  FROM pg_temp._tmp_team_scrape_activity b
  ORDER BY b.team_id_master DESC
  LIMIT 1;

  IF p_dry_run THEN
    SELECT COUNT(*) INTO v_changed
    FROM pg_temp._tmp_team_scrape_activity b
    JOIN public.teams t ON t.team_id_master = b.team_id_master
    WHERE (t.last_played_at, t.last_fixture_at, t.game_row_count, t.scrape_attempts)
          IS DISTINCT FROM
          (b.last_played_at, b.last_fixture_at, b.game_row_count, b.scrape_attempts);
  ELSE
    UPDATE public.teams t
    SET last_played_at  = b.last_played_at,
        last_fixture_at = b.last_fixture_at,
        game_row_count  = b.game_row_count,
        scrape_attempts = b.scrape_attempts
    FROM pg_temp._tmp_team_scrape_activity b
    WHERE t.team_id_master = b.team_id_master
      AND (t.last_played_at, t.last_fixture_at, t.game_row_count, t.scrape_attempts)
          IS DISTINCT FROM
          (b.last_played_at, b.last_fixture_at, b.game_row_count, b.scrape_attempts);

    GET DIAGNOSTICS v_changed = ROW_COUNT;
  END IF;

  RETURN QUERY SELECT v_changed, v_last;
END;
$$;

-- Writer RPC: revoke the default PUBLIC execute so no public client can drive it.
REVOKE EXECUTE ON FUNCTION public.refresh_team_scrape_activity(uuid, integer, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refresh_team_scrape_activity(uuid, integer, boolean) TO service_role;

COMMENT ON FUNCTION public.refresh_team_scrape_activity(uuid, integer, boolean) IS
  'Recompute teams.last_played_at / last_fixture_at / game_row_count / scrape_attempts '
  'for one keyset page of teams after p_after, from games and team_scrape_log, both '
  'resolved through team_merge_map. Returns the number of rows whose values changed and '
  'the page''s last team_id_master; p_dry_run returns the count without writing. Called '
  'in a loop by scripts/refresh_team_scrape_activity.py — one whole-table call would be '
  'cancelled by the 8s statement_timeout a service-role PostgREST request inherits.';
