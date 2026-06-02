-- Backfill final scores onto previously null-score (scheduled) game rows.
--
-- Scheduled GotSport games are inserted ahead of kickoff with NULL scores and
-- is_immutable=TRUE. The prevent_game_updates trigger blocks a raw score UPDATE
-- on those rows, so a direct .update() silently fails. This RPC mirrors
-- apply_game_correction's toggle sequence (off -> write -> on): each statement
-- changes a disjoint field set, so each passes the trigger's Exception 1
-- (is_immutable toggle with scores/teams/date unchanged).

CREATE OR REPLACE FUNCTION batch_backfill_null_scores(
    updates JSONB
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_targets TEXT[];
    v_count INTEGER := 0;
BEGIN
    -- No-clobber guard: only rows that exist AND still have NULL scores are
    -- eligible. A second call after scores land selects nothing and returns 0.
    SELECT array_agg(g.game_uid) INTO v_targets
    FROM games g
    JOIN jsonb_to_recordset(updates) AS u(game_uid TEXT) ON g.game_uid = u.game_uid
    WHERE g.home_score IS NULL AND g.away_score IS NULL;

    IF v_targets IS NULL THEN
        RETURN 0;
    END IF;

    -- Statement 1: toggle immutability off (passes trigger Exception 1).
    UPDATE games
    SET is_immutable = FALSE
    WHERE game_uid = ANY(v_targets);

    -- Statement 2: write scores while mutable, capturing rows actually changed.
    -- result is CHAR(1) with CHECK (result IN ('W','L','D','U')). LEFT(u.result, 1)
    -- guards only the length error ("value too long for character(1)"); a single
    -- char outside the CHECK set (e.g. 'X') would still abort the whole chunk.
    -- Current callers (GotSport) emit only W/L/D/None, all valid.
    UPDATE games g
    SET home_score = u.home_score,
        away_score = u.away_score,
        result = LEFT(u.result, 1)::CHAR(1),
        scraped_at = COALESCE(u.scraped_at, now())
    FROM jsonb_to_recordset(updates)
        AS u(game_uid TEXT, home_score INTEGER, away_score INTEGER, result TEXT, scraped_at TIMESTAMPTZ)
    WHERE g.game_uid = u.game_uid AND g.game_uid = ANY(v_targets);

    GET DIAGNOSTICS v_count = ROW_COUNT;

    -- Statement 3: re-lock (passes Exception 1, scores now unchanged).
    UPDATE games
    SET is_immutable = TRUE
    WHERE game_uid = ANY(v_targets);

    RETURN v_count;
END;
$$;

-- Restrict execution to service_role (the server-side ETL pipeline). This RPC
-- is SECURITY DEFINER (bypasses RLS) and writes core result fields, so it must
-- NOT be callable by anon/authenticated. Postgres grants EXECUTE to PUBLIC by
-- default and anon/authenticated inherit PUBLIC, so REVOKE that before granting.
REVOKE EXECUTE ON FUNCTION batch_backfill_null_scores(JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION batch_backfill_null_scores(JSONB) TO service_role;

COMMENT ON FUNCTION batch_backfill_null_scores(JSONB) IS
'Backfill final scores onto previously null-score (scheduled) game rows.
Takes a JSONB array of {game_uid, home_score, away_score, result, scraped_at} objects.
Toggles is_immutable off -> writes scores (only where existing scores are NULL,
the no-clobber guard) -> toggles immutability back on, working with the
prevent_game_updates trigger via its is_immutable-toggle exception.
Returns the number of rows whose scores were written.';
