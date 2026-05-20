-- RPC: enqueue_scrape_request
--
-- Idempotent enqueue with priority promotion. If a pending request already
-- exists for the team, the priority is promoted via LEAST (toward 1 = highest
-- priority) and the row's other fields are refreshed; requested_at is
-- preserved so the request keeps its FIFO position within its priority tier.
-- If no pending request exists, a new row is inserted.
--
-- Returns the id of the affected row (existing or newly created).
--
-- Used by:
--   - frontend/app/api/scrape-missing-game (priority 1, user-clicked)
--   - scripts/enqueue_yesterday_games.py (priority 2, Phase 4)
--   - scripts/enqueue_discovery_teams.py (priority 3, Phase 5)
--   - scripts/enqueue_safety_net.py     (priority 4, Phase 6)

CREATE OR REPLACE FUNCTION enqueue_scrape_request(
    p_team_id_master uuid,
    p_team_name text,
    p_provider_id uuid,
    p_provider_team_id text,
    p_game_date date,
    p_request_type text,
    p_priority smallint
)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
    v_id uuid;
BEGIN
    -- Promote priority on any existing pending row for this team.
    -- LEAST keeps the higher-priority (lower-numbered) value.
    UPDATE scrape_requests
    SET priority = LEAST(priority, p_priority),
        game_date = COALESCE(p_game_date, game_date),
        team_name = COALESCE(p_team_name, team_name),
        provider_id = COALESCE(p_provider_id, provider_id),
        provider_team_id = COALESCE(p_provider_team_id, provider_team_id)
    WHERE team_id_master = p_team_id_master
      AND status = 'pending'
    RETURNING id INTO v_id;

    IF v_id IS NULL THEN
        INSERT INTO scrape_requests (
            team_id_master,
            team_name,
            provider_id,
            provider_team_id,
            game_date,
            status,
            request_type,
            priority,
            requested_at
        ) VALUES (
            p_team_id_master,
            p_team_name,
            p_provider_id,
            p_provider_team_id,
            p_game_date,
            'pending',
            p_request_type,
            p_priority,
            NOW()
        )
        RETURNING id INTO v_id;
    END IF;

    RETURN v_id;
END;
$$;

COMMENT ON FUNCTION enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint) IS
  'Idempotent enqueue with priority promotion (LEAST). One pending row per team — existing pending requests get their priority bumped toward 1 instead of duplicating. requested_at preserved on update so FIFO position is maintained within the new priority tier.';

GRANT EXECUTE ON FUNCTION enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint)
  TO authenticated, service_role;
