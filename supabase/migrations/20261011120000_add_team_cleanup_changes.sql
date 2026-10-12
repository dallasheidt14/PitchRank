-- One row per change a weekly team-cleanup run applied to a team, so "what did the loop change,
-- when, under which run" is answerable from any machine. The clubs and ages appliers' own record is
-- a CSV log; this is its database copy, and for states it sits beside team_state_audit.
--
-- A row is written after the change is verified from the database, and an undo stamps reverted_at
-- rather than deleting it.

CREATE TABLE IF NOT EXISTS team_cleanup_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),

    stage TEXT NOT NULL CHECK (stage IN ('reconcile', 'clubs', 'states', 'ages', 'merges')),

    team_id_master UUID NOT NULL,

    -- The teams column changed, e.g. club_name, state_code, age_group.
    field TEXT NOT NULL,

    old_value TEXT,

    -- Required, so the one-row-per-change index below compares it: NULLs never collide.
    new_value TEXT NOT NULL,

    -- The script that wrote the change, e.g. scripts/fix_band_cohorts.py.
    applier TEXT NOT NULL,

    -- Who it wrote as: the applier's --actor, or the actor its own ledger records.
    actor TEXT NOT NULL,

    -- The applier's log the change was read from, when it keeps one.
    log_file TEXT,

    applied_at TIMESTAMPTZ NOT NULL,

    reverted_at TIMESTAMPTZ,

    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- A retried ledger write must not record a change twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_changes_one_per_change
    ON team_cleanup_changes (run_id, stage, team_id_master, field, new_value);

CREATE INDEX IF NOT EXISTS idx_team_cleanup_changes_team
    ON team_cleanup_changes (team_id_master);

COMMENT ON TABLE team_cleanup_changes IS
  'Each change a weekly team-cleanup run applied to a team, recorded after it was verified. An '
  'undo stamps reverted_at. Team ids are stored as written; readers resolve them through '
  'team_merge_map.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so
-- without these a browser could rewrite or erase the record of what the loop changed.

ALTER TABLE team_cleanup_changes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_changes_deny_all" ON team_cleanup_changes;
CREATE POLICY "team_cleanup_changes_deny_all" ON team_cleanup_changes
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_changes_deny_all" ON team_cleanup_changes IS
  'Blocks all direct Data API access. Only the service role reads or writes changes.';

DROP POLICY IF EXISTS "team_cleanup_changes_service_role_all" ON team_cleanup_changes;
CREATE POLICY "team_cleanup_changes_service_role_all" ON team_cleanup_changes
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_changes_service_role_all" ON team_cleanup_changes IS
  'Service role has full access: the cleanup loop''s applier records changes and its undo stamps them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched. The uuid key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_changes FROM anon, authenticated;
