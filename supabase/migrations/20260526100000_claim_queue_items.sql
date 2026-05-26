-- RPC: claim_queue_items
--
-- Atomically claim up to p_limit pending scrape_requests for processing.
-- Uses FOR UPDATE SKIP LOCKED so multiple concurrent workflow runs can
-- drain the queue in parallel without double-processing.
--
-- Sets claimed rows to status='processing' and returns them.
--
-- Used by scripts/scrape_games.py --from-queue (clear-queue workflow).

CREATE OR REPLACE FUNCTION claim_queue_items(
    p_provider_id uuid DEFAULT NULL,
    p_limit integer DEFAULT 500
)
RETURNS TABLE(
    id uuid,
    team_id_master uuid,
    team_name text,
    provider_id uuid,
    provider_team_id text,
    game_date date,
    priority smallint,
    request_type text
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH to_claim AS (
        SELECT sr.id
        FROM scrape_requests sr
        WHERE sr.status = 'pending'
          AND (p_provider_id IS NULL OR sr.provider_id = p_provider_id)
        ORDER BY sr.priority ASC, sr.requested_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    ),
    claimed AS (
        UPDATE scrape_requests sr
        SET status = 'processing',
            processed_at = NOW()
        FROM to_claim tc
        WHERE sr.id = tc.id
        RETURNING sr.id, sr.team_id_master, sr.team_name,
                  sr.provider_id, sr.provider_team_id, sr.game_date,
                  sr.priority, sr.request_type
    )
    SELECT c.id, c.team_id_master, c.team_name, c.provider_id,
           c.provider_team_id, c.game_date, c.priority, c.request_type
    FROM claimed c;
END;
$$;

COMMENT ON FUNCTION claim_queue_items(uuid, integer) IS
  'Atomically claim pending scrape_requests with FOR UPDATE SKIP LOCKED. Safe for concurrent callers. Returns claimed rows set to processing.';

GRANT EXECUTE ON FUNCTION claim_queue_items(uuid, integer) TO authenticated, service_role;
