-- Recompute rankings_full.total_games_played / total_wins / total_losses /
-- total_draws, one caller-driven keyset page at a time.
--
-- WHY A NEW FUNCTION RATHER THAN A REPLACEMENT
--
-- backfill_total_game_stats() has been cancelled on every production run for
-- months, and its Python fallback has never written a row, so these four columns
-- are stale site-wide: measured 2026-09-07, 13,159 of 139,837 ranked teams (9.4%)
-- disagreed with a live recount and 32,972 played games were missing from the
-- stored totals.
--
-- Its `SET LOCAL statement_timeout = '300s'` is inert. PostgreSQL arms that timer
-- once per top-level client command and statements inside a function never re-arm
-- it, so the budget in force is the session's: pg_db_role_setting gives
-- `authenticator` 8s and has no service_role entry, and SET ROLE does not re-apply
-- per-role settings. 20260827100100 records the same finding, having hit it in
-- refresh_team_scrape_activity, and names this function as the other instance.
--
-- This ships under a NEW name instead of replacing the old signature. CREATE OR
-- REPLACE with a changed argument list creates an overload rather than replacing,
-- so every existing zero-arg call would fail with "function is not unique" until
-- the old one is dropped -- and the drop also wipes its GRANTs. The old function
-- is left in place, now unreferenced by any caller.
--
-- MERGE RESOLUTION
--
-- execute_team_merge cascades `teams` and `team_alias_map` but repoints neither
-- `games` nor `team_scrape_log`, so aggregating raw master ids undercounts every
-- team that has absorbed a merge. The old function did not resolve merges, which
-- is why 3,058 of the 8,078 rows whose total_games_played sat BELOW their capped
-- games_played are teams that had absorbed one (measured 2026-09-07). That pair is
-- near-impossible on fresh totals rather than strictly impossible: the engine's
-- games_played counts a self-match from both sides, while this function excludes
-- it, so the ~985 self-match games can still produce it legitimately.
--
-- PAGE COST
--
-- Measured 2026-09-07 with EXPLAIN ANALYZE on the shape below at p_batch_size =
-- 2000: 141 ms, against the 8s a service-role PostgREST call gets. The two
-- correlated NOT EXISTS clauses plan as Hash Anti Joins rather than per-row
-- subqueries, and both game lookups are index-only scans on
-- idx_games_home_team_stats / idx_games_away_team_stats. Re-measure before
-- raising p_batch_size: a page that exceeds the budget cannot be rescued by the
-- caller's retry, since every attempt would hit the same wall.
--
-- A merge can also pull BOTH endpoints of an old game onto one canonical team.
-- Such a row is not a fixture that team played, and counting it from both sides
-- would record one win and one loss against it, so it is excluded rather than
-- deduped.

CREATE OR REPLACE FUNCTION public.backfill_total_game_stats_page(
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
  CREATE TEMP TABLE _tmp_total_game_stats ON COMMIT DROP AS
  WITH batch AS (
    SELECT r.team_id
    FROM public.rankings_full r
    WHERE p_after IS NULL OR r.team_id > p_after
    ORDER BY r.team_id
    LIMIT p_batch_size
  ),
  -- Each team in the page plus every deprecated id merged into it, so the
  -- aggregate below sees the merged-away history too.
  sources AS (
    SELECT b.team_id AS canonical_id, b.team_id AS source_id
    FROM batch b
    UNION
    SELECT m.canonical_team_id, m.deprecated_team_id
    FROM public.team_merge_map m
    JOIN batch b ON b.team_id = m.canonical_team_id
  ),
  -- One row per (team, game) carrying that team's own goals for and against.
  -- UNION ALL is safe because a game whose other endpoint also resolves to this
  -- canonical team is excluded, and that is the only way one game could match a
  -- single team on both joins.
  perspectives AS (
    SELECT s.canonical_id, g.home_score AS gf, g.away_score AS ga
    FROM sources s
    JOIN public.games g ON g.home_team_master_id = s.source_id
    WHERE g.home_score IS NOT NULL
      AND g.away_score IS NOT NULL
      AND g.is_excluded = FALSE
      AND NOT EXISTS (
        SELECT 1 FROM sources o
        WHERE o.canonical_id = s.canonical_id
          AND o.source_id = g.away_team_master_id
      )
    UNION ALL
    SELECT s.canonical_id, g.away_score, g.home_score
    FROM sources s
    JOIN public.games g ON g.away_team_master_id = s.source_id
    WHERE g.home_score IS NOT NULL
      AND g.away_score IS NOT NULL
      AND g.is_excluded = FALSE
      AND NOT EXISTS (
        SELECT 1 FROM sources o
        WHERE o.canonical_id = s.canonical_id
          AND o.source_id = g.home_team_master_id
      )
  ),
  agg AS (
    SELECT p.canonical_id,
           COUNT(*)::integer                                AS total_games,
           COUNT(*) FILTER (WHERE p.gf > p.ga)::integer     AS total_wins,
           COUNT(*) FILTER (WHERE p.gf < p.ga)::integer     AS total_losses,
           COUNT(*) FILTER (WHERE p.gf = p.ga)::integer     AS total_draws
    FROM perspectives p
    GROUP BY p.canonical_id
  )
  -- LEFT JOIN, and COALESCE to zero: a ranked team whose games were all excluded
  -- or merged away has a real total of 0, and must be written down to it rather
  -- than keeping whatever it last held.
  SELECT b.team_id,
         COALESCE(a.total_games, 0)  AS total_games,
         COALESCE(a.total_wins, 0)   AS total_wins,
         COALESCE(a.total_losses, 0) AS total_losses,
         COALESCE(a.total_draws, 0)  AS total_draws
  FROM batch b
  LEFT JOIN agg a ON a.canonical_id = b.team_id;

  -- The page's last id, not the last id CHANGED: the caller advances on this, so
  -- a page where nothing moved must still carry the walk forward.
  --
  -- ORDER BY ... LIMIT 1 rather than MAX(): PostgreSQL has no max(uuid) aggregate
  -- and the error is a plan-time 42883 that fails the whole call. Nothing in CI
  -- executes this SQL, so only a live run would surface it.
  SELECT t.team_id INTO v_last
  FROM pg_temp._tmp_total_game_stats t
  ORDER BY t.team_id DESC
  LIMIT 1;

  IF p_dry_run THEN
    SELECT COUNT(*) INTO v_changed
    FROM pg_temp._tmp_total_game_stats t
    JOIN public.rankings_full r ON r.team_id = t.team_id
    WHERE (r.total_games_played, r.total_wins, r.total_losses, r.total_draws)
          IS DISTINCT FROM
          (t.total_games, t.total_wins, t.total_losses, t.total_draws);
  ELSE
    UPDATE public.rankings_full r
    SET total_games_played = t.total_games,
        total_wins         = t.total_wins,
        total_losses       = t.total_losses,
        total_draws        = t.total_draws
    FROM pg_temp._tmp_total_game_stats t
    WHERE r.team_id = t.team_id
      AND (r.total_games_played, r.total_wins, r.total_losses, r.total_draws)
          IS DISTINCT FROM
          (t.total_games, t.total_wins, t.total_losses, t.total_draws);

    GET DIAGNOSTICS v_changed = ROW_COUNT;
  END IF;

  RETURN QUERY SELECT v_changed, v_last;
END;
$$;

-- Writer RPC: revoke the default PUBLIC execute so no public client can drive it.
REVOKE EXECUTE ON FUNCTION public.backfill_total_game_stats_page(uuid, integer, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.backfill_total_game_stats_page(uuid, integer, boolean) TO service_role;

COMMENT ON FUNCTION public.backfill_total_game_stats_page(uuid, integer, boolean) IS
  'Recompute rankings_full.total_games_played / total_wins / total_losses / total_draws '
  'for one keyset page of ranked teams after p_after, from games resolved through '
  'team_merge_map, excluding games whose two endpoints resolve to the same team. Returns '
  'the number of rows whose values changed and the page''s last team_id; p_dry_run returns '
  'the count without writing. Called in a loop by scripts/calculate_rankings.py — one '
  'whole-table call is cancelled by the 8s statement_timeout a service-role PostgREST '
  'request inherits, which is why backfill_total_game_stats() never completed.';
