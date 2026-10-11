-- One row per weekly team-cleanup run, mirroring the run.json the loop keeps in its run store, so
-- another session or machine can see that a run is open and which applier holds it.
--
-- At most one run is open at a time (the partial unique index below). An applier takes the run's
-- lease with an update guarded on the lease being free or expired, and clears it when it is done.

CREATE TABLE IF NOT EXISTS team_cleanup_runs (
    -- <YYYY-MM-DD>-<scope>; it also names the run's folder in the store.
    run_id TEXT PRIMARY KEY,

    scope JSONB NOT NULL,

    status TEXT NOT NULL
        CHECK (status IN ('proposing', 'reviewing', 'applying', 'second_lap', 'done', 'abandoned')),

    budgets JSONB NOT NULL DEFAULT '{}'::jsonb,

    lease_holder TEXT,

    lease_expires_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT team_cleanup_runs_run_id_is_a_dated_scope
        CHECK (run_id ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),

    -- A holder without an expiry could never be taken over: the lease's free-or-expired guard
    -- compares NULL and never passes.
    CONSTRAINT team_cleanup_runs_lease_is_whole
        CHECK ((lease_holder IS NULL) = (lease_expires_at IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_runs_one_open
    ON team_cleanup_runs ((true))
    WHERE status IN ('proposing', 'reviewing', 'applying', 'second_lap');

DROP TRIGGER IF EXISTS update_team_cleanup_runs_updated_at
    ON public.team_cleanup_runs;

CREATE TRIGGER update_team_cleanup_runs_updated_at
    BEFORE UPDATE ON public.team_cleanup_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE team_cleanup_runs IS
  'Weekly team-cleanup runs, mirrored from each run''s run.json. At most one is open; an applier '
  'holds the open run through lease_holder and lease_expires_at.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so
-- without these a browser could open a run, or take or clear an applier's lease.

ALTER TABLE team_cleanup_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_runs_deny_all" ON team_cleanup_runs;
CREATE POLICY "team_cleanup_runs_deny_all" ON team_cleanup_runs
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_runs_deny_all" ON team_cleanup_runs IS
  'Blocks all direct Data API access. Only the service role reads or writes runs.';

DROP POLICY IF EXISTS "team_cleanup_runs_service_role_all" ON team_cleanup_runs;
CREATE POLICY "team_cleanup_runs_service_role_all" ON team_cleanup_runs
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_runs_service_role_all" ON team_cleanup_runs IS
  'Service role has full access: the cleanup loop opens runs and its applier takes the lease.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched. The text key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_runs FROM anon, authenticated;
