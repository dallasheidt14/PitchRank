-- The weekly team-cleanup loop's review cards, one row per proposed change a page build shows, so the
-- owner can decide them on the website and the loop's applier can read the choices back without a
-- live session. A build writes its cards in two lanes: the changes the evidence already settles
-- ('auto', always Apply, applied by the loop) and the ones the owner decides ('owner').
--
-- The owner marks a run's page done on team_cleanup_runs; the applier then reads the decided owner
-- cards. Team ids live inside each card's payload as the build read them; readers resolve them
-- through team_merge_map.

CREATE TABLE IF NOT EXISTS team_cleanup_cards (
    -- <page_run>_<hash of the change>, as the page build names its cards.
    card_id TEXT PRIMARY KEY,

    run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),

    stage TEXT NOT NULL CHECK (stage IN ('clubs', 'states', 'ages')),

    lane TEXT NOT NULL CHECK (lane IN ('auto', 'owner')),

    -- The page build that wrote the card; a rebuild writes a new one.
    page_run TEXT NOT NULL,

    -- The card's place on its page; each lane may number its own, so it orders cards but is not a key.
    position INTEGER NOT NULL CHECK (position >= 1),

    -- What the page shows: the change, the team, its group and the evidence beside it.
    card JSONB NOT NULL,

    decision TEXT CHECK (decision IN ('apply', 'dont_apply', 'unsure')),

    note TEXT CHECK (char_length(note) <= 2000),

    decided_at TIMESTAMPTZ,

    -- The signed-in admin who last decided the card; empty for an auto card.
    decided_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT team_cleanup_cards_id_names_its_build
        CHECK (left(card_id, char_length(page_run) + 1) = page_run || '_'),

    -- The loop applies every auto card; only an owner card waits on a person. A bare comparison
    -- would let an auto card with no decision through, since a CHECK passes on NULL.
    CONSTRAINT team_cleanup_cards_auto_is_apply
        CHECK (lane = 'owner' OR decision IS NOT DISTINCT FROM 'apply')
);

CREATE INDEX IF NOT EXISTS idx_team_cleanup_cards_page
    ON team_cleanup_cards (page_run, position);

CREATE INDEX IF NOT EXISTS idx_team_cleanup_cards_run
    ON team_cleanup_cards (run_id, stage, page_run);

COMMENT ON TABLE team_cleanup_cards IS
  'The weekly team-cleanup loop''s review cards, in an auto lane the loop applies and an owner lane '
  'the owner decides on the website. Team ids inside card are stored as written; readers resolve '
  'them through team_merge_map.';

-- The owner's "done" on a run's page, or the Sunday deadline standing in for it. Either lets the
-- applier apply the decided owner cards; the undecided ones return on the next run.
ALTER TABLE team_cleanup_runs
    ADD COLUMN IF NOT EXISTS owner_done_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS owner_done_by TEXT CHECK (owner_done_by IN ('owner', 'deadline'));

ALTER TABLE team_cleanup_runs
    DROP CONSTRAINT IF EXISTS team_cleanup_runs_owner_done_is_whole;

ALTER TABLE team_cleanup_runs
    ADD CONSTRAINT team_cleanup_runs_owner_done_is_whole
        CHECK ((owner_done_at IS NULL) = (owner_done_by IS NULL));

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so
-- without these a browser could decide, add or erase the owner's cards. The website writes them
-- through a server route that checks for an admin and then uses the service role.

ALTER TABLE team_cleanup_cards ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_cards_deny_all" ON team_cleanup_cards;
CREATE POLICY "team_cleanup_cards_deny_all" ON team_cleanup_cards
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_cards_deny_all" ON team_cleanup_cards IS
  'Blocks all direct Data API access. Only the service role reads or writes cards.';

DROP POLICY IF EXISTS "team_cleanup_cards_service_role_all" ON team_cleanup_cards;
CREATE POLICY "team_cleanup_cards_service_role_all" ON team_cleanup_cards
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_cards_service_role_all" ON team_cleanup_cards IS
  'Service role has full access: the cleanup loop writes and reads cards, and the website''s admin '
  'routes save the owner''s choices.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched. The text key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_cards FROM anon, authenticated;
