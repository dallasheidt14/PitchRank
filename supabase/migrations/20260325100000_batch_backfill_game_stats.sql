-- Replace backfill_total_game_stats with a batched version.
--
-- Problem: the original single-UPDATE approach tries to join ~716K game rows
-- against ~110K rankings_full rows in one transaction, routinely exceeding
-- the 120s statement timeout on Supabase.
--
-- Fix: materialise the aggregation into a temp table (fast — sequential scan
-- + GROUP BY), then UPDATE rankings_full in batches of 10 000 teams using a
-- cursor so no single statement runs longer than a few seconds.
--
-- Date: 2026-03-25

CREATE OR REPLACE FUNCTION backfill_total_game_stats()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  batch_size  CONSTANT INT := 10000;
  total_updated INT := 0;
  batch_updated INT;
  cur CURSOR FOR
    SELECT team_id, total_games, total_w, total_l, total_d
    FROM _tmp_game_agg
    ORDER BY team_id;
  rec RECORD;
  batch_ids UUID[];
  batch_games INT[];
  batch_w     INT[];
  batch_l     INT[];
  batch_d     INT[];
  i INT;
BEGIN
  -- Safety net: allow up to 300s for the entire function
  SET LOCAL statement_timeout = '300s';

  -- ---------------------------------------------------------------
  -- Step 1: Materialise the game aggregation into a temp table.
  -- This is the fast part — a single sequential scan of `games`.
  -- ---------------------------------------------------------------
  CREATE TEMP TABLE _tmp_game_agg ON COMMIT DROP AS
  SELECT
    team_id,
    COUNT(*)::INT                                        AS total_games,
    SUM(CASE WHEN is_win  THEN 1 ELSE 0 END)::INT       AS total_w,
    SUM(CASE WHEN is_loss THEN 1 ELSE 0 END)::INT       AS total_l,
    SUM(CASE WHEN is_draw THEN 1 ELSE 0 END)::INT       AS total_d
  FROM (
    -- Home games
    SELECT
      g.home_team_master_id AS team_id,
      g.home_score > g.away_score AS is_win,
      g.home_score < g.away_score AS is_loss,
      g.home_score = g.away_score AS is_draw
    FROM games g
    WHERE g.home_score IS NOT NULL
      AND g.away_score IS NOT NULL
      AND g.is_excluded = FALSE

    UNION ALL

    -- Away games
    SELECT
      g.away_team_master_id AS team_id,
      g.away_score > g.home_score AS is_win,
      g.away_score < g.home_score AS is_loss,
      g.away_score = g.home_score AS is_draw
    FROM games g
    WHERE g.home_score IS NOT NULL
      AND g.away_score IS NOT NULL
      AND g.is_excluded = FALSE
  ) sub
  GROUP BY team_id;

  -- Index the temp table so the batched joins are fast
  CREATE INDEX ON _tmp_game_agg (team_id);

  -- ---------------------------------------------------------------
  -- Step 2: UPDATE rankings_full in batches via a cursor.
  -- We accumulate batch_size rows from the cursor, then issue one
  -- UPDATE per batch. This keeps each UPDATE small and well within
  -- the statement timeout.
  -- ---------------------------------------------------------------
  OPEN cur;
  LOOP
    -- Collect a batch
    batch_ids   := ARRAY[]::UUID[];
    batch_games := ARRAY[]::INT[];
    batch_w     := ARRAY[]::INT[];
    batch_l     := ARRAY[]::INT[];
    batch_d     := ARRAY[]::INT[];
    i := 0;

    LOOP
      FETCH cur INTO rec;
      EXIT WHEN NOT FOUND;
      i := i + 1;
      batch_ids   := array_append(batch_ids,   rec.team_id);
      batch_games := array_append(batch_games, rec.total_games);
      batch_w     := array_append(batch_w,     rec.total_w);
      batch_l     := array_append(batch_l,     rec.total_l);
      batch_d     := array_append(batch_d,     rec.total_d);
      EXIT WHEN i >= batch_size;
    END LOOP;

    -- No more rows
    EXIT WHEN i = 0;

    -- Perform the batched UPDATE by unnesting the arrays into a
    -- virtual table and joining against rankings_full.
    UPDATE rankings_full rf
    SET
      total_games_played = b.total_games,
      total_wins         = b.total_w,
      total_losses       = b.total_l,
      total_draws        = b.total_d
    FROM unnest(batch_ids, batch_games, batch_w, batch_l, batch_d)
         AS b(team_id, total_games, total_w, total_l, total_d)
    WHERE rf.team_id = b.team_id;

    GET DIAGNOSTICS batch_updated = ROW_COUNT;
    total_updated := total_updated + batch_updated;
  END LOOP;

  CLOSE cur;

  RETURN total_updated;
END;
$$;

COMMENT ON FUNCTION backfill_total_game_stats IS
  'Bulk-compute total_games_played/wins/losses/draws for every team in rankings_full. '
  'Does NOT overwrite win_percentage (that stays as the v53e capped-games value). '
  'rankings_view computes all-games win_percentage inline from the precomputed totals. '
  'Single scan of games table via UNION ALL, materialised into a temp table. '
  'Updates rankings_full in batches of 10,000 to avoid statement timeout. '
  'Uses SET LOCAL statement_timeout = 300s as a safety net. '
  'Called after save_rankings_to_supabase in calculate_rankings.py.';
