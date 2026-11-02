-- The weekly team-cleanup loop's requests to undo one card's change. The owner presses Undo on one change on
-- the review page, the website files a pending request here, and the loop's next hourly tick runs
-- scripts/team_cleanup/undo_card.py on it inside the apply window and records how it went. A card has at most
-- one pending request at a time. team_cleanup_requests holds the undos of a whole lane.
--
-- Hand-applied: run it in the SQL editor, then record it with
--   supabase migration repair --status applied 20261031140000

CREATE TABLE IF NOT EXISTS team_cleanup_card_undos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),

    -- The card whose change to undo; its stage and lane come from the card.
    card_id TEXT NOT NULL REFERENCES team_cleanup_cards (card_id),

    -- Also record the change as not to propose again: Don't apply, or Keep separate for a pair.
    decline BOOLEAN NOT NULL DEFAULT true,

    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- The signed-in admin who pressed Undo.
    requested_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL,

    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),

    handled_at TIMESTAMPTZ,

    -- What the loop's run of the request said, for the page to show.
    result TEXT CHECK (char_length(result) <= 2000),

    -- A CHECK passes on NULL, so status's NOT NULL is what makes this whole.
    CONSTRAINT team_cleanup_card_undos_handled_is_whole
        CHECK ((status = 'pending') = (handled_at IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_card_undos_one_pending
    ON team_cleanup_card_undos (card_id)
    WHERE status = 'pending';

COMMENT ON TABLE team_cleanup_card_undos IS
  'The weekly team-cleanup loop''s requests to undo one card''s change: the website files them pending, and '
  'the loop''s hourly tick runs each and records the result.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so without
-- these a browser could file or erase undo requests. The website files them through a server route
-- that checks for an admin and then uses the service role.

ALTER TABLE team_cleanup_card_undos ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_card_undos_deny_all" ON team_cleanup_card_undos;
CREATE POLICY "team_cleanup_card_undos_deny_all" ON team_cleanup_card_undos
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_card_undos_deny_all" ON team_cleanup_card_undos IS
  'Blocks all direct Data API access. Only the service role reads or writes card undo requests.';

DROP POLICY IF EXISTS "team_cleanup_card_undos_service_role_all" ON team_cleanup_card_undos;
CREATE POLICY "team_cleanup_card_undos_service_role_all" ON team_cleanup_card_undos
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_card_undos_service_role_all" ON team_cleanup_card_undos IS
  'Service role has full access: the website''s admin route files requests, and the cleanup loop runs '
  'and records them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy leaves the
-- TRUNCATE in that default grant untouched. The UUID key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_card_undos FROM anon, authenticated;
