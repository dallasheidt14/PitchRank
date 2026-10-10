-- The owner's standing decisions on team-cleanup proposals. A review page keeps its choices
-- in its own store, which no scan reads, so without this table a pair the owner kept
-- separate is proposed again by the next scan of its state.
--
-- A decision is retired by stamping superseded_at rather than deleted, so the owner's
-- changes of mind are kept; the partial unique index below allows at most one active
-- decision per subject.

CREATE TABLE IF NOT EXISTS team_cleanup_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    stage TEXT NOT NULL CHECK (stage IN ('reconcile', 'clubs', 'states', 'ages', 'merges')),

    -- For a merge, both team ids sorted and joined with '|'; for a single team, the team id
    -- and the field, so one team can hold a decision per field.
    subject_key TEXT NOT NULL,

    team_id_master UUID NOT NULL,

    other_team_id UUID,

    field TEXT,

    proposed_value TEXT,

    decision TEXT NOT NULL CHECK (decision IN ('keep_separate', 'dont_apply', 'apply', 'unsure')),

    note TEXT,

    decided_at TIMESTAMPTZ NOT NULL,

    source TEXT NOT NULL,

    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    superseded_at TIMESTAMPTZ,

    CONSTRAINT team_cleanup_decisions_merge_names_a_pair
        CHECK (stage <> 'merges' OR other_team_id IS NOT NULL),

    CONSTRAINT team_cleanup_decisions_pair_is_two_teams
        CHECK (other_team_id IS DISTINCT FROM team_id_master),

    -- The one-active-decision index holds only if every writer spells a pair's key the same way.
    CONSTRAINT team_cleanup_decisions_merge_key_is_the_sorted_pair
        CHECK (
            stage <> 'merges'
            OR subject_key = LEAST(team_id_master::text COLLATE "C", other_team_id::text COLLATE "C")
                || '|' || GREATEST(team_id_master::text COLLATE "C", other_team_id::text COLLATE "C")
        ),

    CONSTRAINT team_cleanup_decisions_keep_separate_is_a_merge_decision
        CHECK (decision <> 'keep_separate' OR stage = 'merges')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_cleanup_decisions_active_subject
    ON team_cleanup_decisions (stage, subject_key)
    WHERE superseded_at IS NULL;

COMMENT ON TABLE team_cleanup_decisions IS
  'The owner''s decisions on team-cleanup proposals. Scans read the active rows so a declined '
  'proposal is not raised again. team_id_master and other_team_id carry no foreign key, '
  'matching team_ranking_exclusions: a decision outlives a merge of either team, and readers '
  'resolve both ids through team_merge_map.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so
-- without these a browser could forge or erase the owner's decisions.

ALTER TABLE team_cleanup_decisions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_cleanup_decisions_deny_all" ON team_cleanup_decisions;
CREATE POLICY "team_cleanup_decisions_deny_all" ON team_cleanup_decisions
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_cleanup_decisions_deny_all" ON team_cleanup_decisions IS
  'Blocks all direct Data API access. Only the service role reads or writes decisions.';

DROP POLICY IF EXISTS "team_cleanup_decisions_service_role_all" ON team_cleanup_decisions;
CREATE POLICY "team_cleanup_decisions_service_role_all" ON team_cleanup_decisions
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_cleanup_decisions_service_role_all" ON team_cleanup_decisions IS
  'Service role has full access: the cleanup scripts write decisions and the scanners read them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched. The uuid key has no sequence to revoke.
REVOKE ALL ON public.team_cleanup_decisions FROM anon, authenticated;
