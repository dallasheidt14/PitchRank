-- One row per "find missing game" click the route queued. The click queues a scrape through
-- enqueue_scrape_request, which reuses a team's active (pending or running) request instead of
-- adding one and keeps that request's type and time, so the queue alone cannot say which teams
-- were clicked when.
--
-- No foreign keys: a click is a record of what was asked, and must not hold a team row or a
-- queue row in place.

CREATE TABLE IF NOT EXISTS missing_game_clicks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The id the team page posted, which can be a merged-away row's.
    team_id_master UUID NOT NULL,

    game_date DATE NOT NULL,

    clicked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- The queue request that covers the clicked date: the one the click created, or the one
    -- with the same registration and a date within 90 days that it reused. NULL when the queue refused
    -- the click because the team's active request is for another date or registration.
    scrape_request_id UUID
);

CREATE INDEX IF NOT EXISTS idx_missing_game_clicks_clicked_at ON missing_game_clicks (clicked_at);

COMMENT ON TABLE missing_game_clicks IS
  'One row per "find missing game" click the route queued, written by /api/scrape-missing-game, '
  'read by the missing-game investigation.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so without
-- these a browser could forge or erase clicks. The route records them with the service role after
-- its own premium check.

ALTER TABLE missing_game_clicks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "missing_game_clicks_deny_all" ON missing_game_clicks;
CREATE POLICY "missing_game_clicks_deny_all" ON missing_game_clicks
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "missing_game_clicks_deny_all" ON missing_game_clicks IS
  'Blocks all direct Data API access. Only the service role reads or writes clicks.';

DROP POLICY IF EXISTS "missing_game_clicks_service_role_all" ON missing_game_clicks;
CREATE POLICY "missing_game_clicks_service_role_all" ON missing_game_clicks
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "missing_game_clicks_service_role_all" ON missing_game_clicks IS
  'Service role has full access.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy leaves the
-- TRUNCATE in that default grant untouched. The UUID key has no sequence to revoke.
REVOKE ALL ON public.missing_game_clicks FROM anon, authenticated;
