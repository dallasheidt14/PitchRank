-- Record every GotSport state probe, including the ones that change nothing.
--
-- team_state_audit only ever sees a probe that moved a state_code: it is written by the
-- log_team_state_* triggers, which fire on a change, and state_source = 'tier_a' is
-- stamped only by apply_team_state(), which only runs on a write. So a paid call that
-- agrees with what we store, that 404s, or that fails leaves no trace anywhere.
--
-- A probe that changes nothing still matches the selector on the next run and still
-- sorts to the same place, so an unrecorded agreement is re-bought forever.
--
-- This table is the record of the observation, not of the write. One row per probe.

CREATE TABLE IF NOT EXISTS team_state_probe_log (
    id BIGSERIAL PRIMARY KEY,

    team_id_master UUID NOT NULL,

    provider TEXT NOT NULL DEFAULT 'gotsport',

    -- Nullable on purpose: a selected candidate with no provider alias never reaches the
    -- probe, and it needs a row precisely so it stops being re-selected forever.
    provider_team_id TEXT,

    -- The raw per-probe string, not the run's histogram category: the fan-in loop
    -- collapses 'request failed (ConnectionError)' to 'request failed', and that
    -- distinction separates a transient failure from a durable one.
    outcome TEXT NOT NULL,

    reported_state_code CHAR(2),
    stored_state_code CHAR(2),

    -- NULL when either side is absent, so "the provider agreed with us" is distinguishable
    -- from "nobody answered". Without this column the ledger reproduces, in a new table,
    -- the blind spot it exists to close.
    agreed BOOLEAN,

    probed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    probed_by TEXT NOT NULL
);

-- The only read: when was this team last probed, and with what outcome.
CREATE INDEX IF NOT EXISTS idx_team_state_probe_log_team
ON team_state_probe_log(team_id_master, probed_at DESC);

COMMENT ON TABLE team_state_probe_log IS
  'Append-only record of every GotSport team_association probe, whatever it returned. '
  'team_id_master carries no foreign key, matching team_state_audit: the observation '
  'outlives whatever happens to the team row. Grows by one row per probe, including one '
  'per selected candidate that turned out to have no provider alias.';

COMMENT ON COLUMN team_state_probe_log.agreed IS
  'Whether the provider reported the state we already store. TRUE is the case no other '
  'table can hold, because a probe that agrees writes nothing and so fires no trigger.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project,
-- which is how team_merge_audit and team_link_audit reached the security advisory.

ALTER TABLE team_state_probe_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_state_probe_log_deny_all" ON team_state_probe_log;
CREATE POLICY "team_state_probe_log_deny_all" ON team_state_probe_log
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_state_probe_log_deny_all" ON team_state_probe_log IS 'Blocks all access to the probe ledger for non-service roles';

DROP POLICY IF EXISTS "team_state_probe_log_service_role_all" ON team_state_probe_log;
CREATE POLICY "team_state_probe_log_service_role_all" ON team_state_probe_log
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_state_probe_log_service_role_all" ON team_state_probe_log IS 'Service role has full access to the probe ledger for ETL operations';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so a deny-all policy
-- leaves the TRUNCATE in that default grant untouched. This table is append-only and
-- every row in it was paid for, so emptying it is not recoverable by re-deriving --
-- only by spending the money again, and it would read as "nobody was ever probed".
REVOKE ALL ON public.team_state_probe_log FROM anon, authenticated;
