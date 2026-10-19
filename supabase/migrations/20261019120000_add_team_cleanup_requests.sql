-- The weekly team-cleanup loop's undo requests. The owner presses Undo on the review page, the website
-- files a pending request here, and the loop's next hourly tick runs that lane's revert and records how
-- it went. A run, stage and lane have at most one pending request at a time.

CREATE TABLE IF NOT EXISTS team_cleanup_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),

    stage TEXT NOT NULL CHECK (stage IN ('clubs', 'states', 'ages')),

    -- The owner's choices ('owner') or the changes the evidence settled ('auto').
    lane TEXT NOT NULL CHECK (lane IN ('auto', 'owner')),

    -- Undo the lane's applied changes; the only request the loop takes so far.
    action TEXT NOT NULL DEFAULT 'revert' CHECK (action IN ('revert')),

    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- The signed-in admin who pressed Undo.
    requested_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL,

    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),

    handled_at TIMESTAMPTZ,

    -- What the loop's run of the request said, for the page to show.
    result TEXT CHECK (char_length(result) <= 2000),

    -- A CHECK passes on NULL, so status's NOT NULL is what makes this whole.
    CONSTRAINT team_cleanup_requests_handled_is_whole
        CHECK ((status = 'pending') = (handled_at IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_requests_one_pending
    ON team_cleanup_requests (run_id, stage, lane, action)
    WHERE status = 'pending';

COMMENT ON TABLE team_cleanup_requests IS
  'The weekly team-cleanup loop''s undo requests from the review page: the website files them pending, '
  'and the loop''s hourly tick runs each lane''s revert and records the result.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so without
-- these a browser could file or erase undo requests. The website files them through a server route
-- that checks for an admin and then uses the service role.

ALTER TABLE team_cleanup_requests ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_requests_deny_all" ON team_cleanup_requests;
CREATE POLICY "team_cleanup_requests_deny_all" ON team_cleanup_requests
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_requests_deny_all" ON team_cleanup_requests IS
  'Blocks all direct Data API access. Only the service role reads or writes undo requests.';

DROP POLICY IF EXISTS "team_cleanup_requests_service_role_all" ON team_cleanup_requests;
CREATE POLICY "team_cleanup_requests_service_role_all" ON team_cleanup_requests
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_requests_service_role_all" ON team_cleanup_requests IS
  'Service role has full access: the website''s admin route files requests, and the cleanup loop runs '
  'and records them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy leaves the
-- TRUNCATE in that default grant untouched. The UUID key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_requests FROM anon, authenticated;
