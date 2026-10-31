-- The weekly team-cleanup loop's spot-check of its automatic merges. When a run closes, the loop picks up to
-- ten of the merges the reviewers cleared and the automatic lane applied, files them here and lists them in
-- the summary email; the owner marks each right or wrong on the review page. The verdicts measure the
-- reviewers over time, and decide when the automatic lane's cap may rise. A run's sample is picked once.

CREATE TABLE IF NOT EXISTS team_cleanup_spot_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),

    -- 1 to 10, the order the email lists them in.
    position SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 10),

    -- The merge's automatic card, which holds both teams as the page showed them and the reviewers' reason.
    card_id TEXT NOT NULL REFERENCES team_cleanup_cards (card_id),

    picked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    verdict TEXT CHECK (verdict IN ('right', 'wrong')),

    note TEXT CHECK (char_length(note) <= 2000),

    judged_at TIMESTAMPTZ,

    -- The signed-in admin who judged it.
    judged_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL,

    CONSTRAINT team_cleanup_spot_checks_judged_is_whole
        CHECK ((verdict IS NULL) = (judged_at IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_spot_checks_position
    ON team_cleanup_spot_checks (run_id, position);

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_spot_checks_card
    ON team_cleanup_spot_checks (run_id, card_id);

COMMENT ON TABLE team_cleanup_spot_checks IS
  'Up to ten of a weekly team-cleanup run''s automatic merges, picked when the run closes, each marked '
  'right or wrong by the owner on the review page.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so without
-- these a browser could rewrite or erase the verdicts. The website reads and records them through a
-- server route that checks for an admin and then uses the service role.

ALTER TABLE team_cleanup_spot_checks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_spot_checks_deny_all" ON team_cleanup_spot_checks;
CREATE POLICY "team_cleanup_spot_checks_deny_all" ON team_cleanup_spot_checks
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_spot_checks_deny_all" ON team_cleanup_spot_checks IS
  'Blocks all direct Data API access. Only the service role reads or writes spot-checks.';

DROP POLICY IF EXISTS "team_cleanup_spot_checks_service_role_all" ON team_cleanup_spot_checks;
CREATE POLICY "team_cleanup_spot_checks_service_role_all" ON team_cleanup_spot_checks
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_spot_checks_service_role_all" ON team_cleanup_spot_checks IS
  'Service role has full access: the cleanup loop picks the sample, and the website''s admin route records '
  'the verdicts.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy leaves the
-- TRUNCATE in that default grant untouched. The UUID key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_spot_checks FROM anon, authenticated;
