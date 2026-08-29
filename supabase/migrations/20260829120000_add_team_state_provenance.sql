-- Make teams.state_code auditable and reversible.
--
-- Nothing here changes behaviour. It adds the provenance columns a state write records
-- itself in, the ledger every write lands in, the queue a decision waits in when it is
-- not safe to auto-apply, and the TGS event table the tournament-vs-league gate reads.
-- The tool that uses them ships separately: .turbo/specs/team-state-assignment.md, PR4.
--
-- Four constraints shaped this file.
--
-- 1. THE LEDGER IS WRITTEN BY A TRIGGER, not by the write function. Roughly 22 code
--    paths write state_code and only a trigger catches all of them — including the
--    discovery path's INSERTs, which created 66,380 of the table's teams.
--
-- 2. THE ACTOR AND ACTION ARRIVE AS TRANSACTION-LOCAL GUCs. A session GUC does not
--    survive PostgREST, verified twice against this project: set_config(..., false) on
--    backend pid 3262723, then current_setting() returning NULL on pid 3262724 on the
--    very next request. Where the pool does hand back the same backend the value
--    lingers instead and mis-stamps unrelated later writes. So apply_team_state() sets
--    both with the transaction-local flag and does the UPDATE itself, in the same
--    transaction. Writes from any other path leave them unset and are stamped with the
--    database role name and action 'external', which is the point of logging at all.
--
-- 3. TWO TRIGGERS, NOT ONE. PostgreSQL rejects an INSERT OR UPDATE trigger whose WHEN
--    clause references OLD, and the WHEN clauses are not optional: teams takes roughly
--    3,840 last_scraped_at writes a day from the scrapers, and an unconditional trigger
--    would fire on every one. Moving the test into the function body is not equivalent —
--    that reintroduces a per-row function call on the same hot path.
--
-- 4. NO BULK WORK INSIDE A FUNCTION. pg_db_role_setting carries statement_timeout=8s for
--    `authenticator` and has no service_role entry, and SET ROLE does not re-apply
--    per-role settings, so a service-role RPC gets 8 seconds — and `SET LOCAL
--    statement_timeout` in a function body is inert, because the timer is armed once per
--    top-level client command. revert_team_states() therefore takes (p_after,
--    p_batch_size) and returns a cursor for the caller to loop on, like
--    refresh_team_scrape_activity().
--
-- RLS ships with the tables. pg_default_acl grants arwdDxtm to anon on every new public
-- relation in this project, which is how team_merge_audit and team_link_audit reached
-- the security advisory.

-- Nothing here rewrites a table, but the column adds and both trigger swaps take
-- ACCESS EXCLUSIVE on teams. Queued behind an open transaction that lock would hold
-- every scraper write behind it, so give up instead and retry between drains.
SET lock_timeout = '5s';

-- ============================================================================
-- PROVENANCE COLUMNS ON teams
-- ============================================================================

ALTER TABLE teams ADD COLUMN IF NOT EXISTS state_source TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS state_confidence NUMERIC(3,2);
ALTER TABLE teams ADD COLUMN IF NOT EXISTS state_assigned_at TIMESTAMPTZ;

COMMENT ON COLUMN teams.state_source IS
  'Evidence tier that produced state_code, named by the assignment tool. NULL for every '
  'state written before that tool existed and for every write that does not go through '
  'apply_team_state() — so it is a provenance record, not a completeness measure.';

COMMENT ON COLUMN teams.state_confidence IS
  'Confidence of the tier named in state_source. NULL wherever state_source is NULL.';

COMMENT ON COLUMN teams.state_assigned_at IS
  'When state_code was last written through apply_team_state(). NULL means no such write '
  'has happened, not that the value is new.';

-- ============================================================================
-- team_state_audit — one row per state_code write, from every path
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_state_audit (
    id BIGSERIAL PRIMARY KEY,

    team_id_master UUID NOT NULL,

    -- 'fill' and 'correct' are the tool's own writes, 'approve' a queued decision the
    -- operator accepted, 'revert' the undo of an earlier batch, and 'external' anything
    -- that reached teams without going through apply_team_state().
    action TEXT NOT NULL
        CHECK (action IN ('fill', 'correct', 'approve', 'revert', 'external')),

    old_state_code CHAR(2),
    new_state_code CHAR(2),
    old_source TEXT,
    new_source TEXT,
    old_confidence NUMERIC(3,2),
    new_confidence NUMERIC(3,2),

    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_team_state_audit_team
ON team_state_audit(team_id_master);

-- Scoping key of a revert: one actor's writes over one window.
CREATE INDEX IF NOT EXISTS idx_team_state_audit_batch
ON team_state_audit(applied_by, applied_at DESC);

-- "Has this exact value already been reverted for this team?" — asked before every
-- auto-apply, and it reads old_state_code because a revert row records the value being
-- undone there and the value being restored in new_state_code.
CREATE INDEX IF NOT EXISTS idx_team_state_audit_revert
ON team_state_audit(team_id_master, old_state_code)
WHERE action = 'revert';

COMMENT ON TABLE team_state_audit IS
  'Append-only ledger of teams.state_code writes, written by the log_team_state_* '
  'triggers and by nothing else. team_id_master carries no foreign key so the ledger '
  'outlives whatever happens to the team row. id is a sequence rather than a uuid '
  'because applied_at defaults to NOW(), which is transaction time and therefore ties '
  'for rows written together; restoring the oldest row per team needs a tiebreaker.';

COMMENT ON COLUMN team_state_audit.old_confidence IS
  'Confidence in force before the write. A revert restores it, including when it is '
  'lower than the confidence it replaces — which is why no write path may guard on '
  'confidence increasing.';

-- ============================================================================
-- team_state_review_queue — decisions that must not auto-apply
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_state_review_queue (
    id BIGSERIAL PRIMARY KEY,

    team_id_master UUID NOT NULL REFERENCES teams(team_id_master),
    current_state_code CHAR(2),
    proposed_state_code CHAR(2) NOT NULL,
    tier TEXT NOT NULL,
    confidence NUMERIC(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reason TEXT,

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_team_state_review_status
ON team_state_review_queue(status);

-- Suppression key: a rejected proposal must not be re-raised while the same state is
-- being proposed for the same team, and a pending one must be updated rather than
-- duplicated. Deliberately not unique — the queue keeps its history.
CREATE INDEX IF NOT EXISTS idx_team_state_review_team_proposal
ON team_state_review_queue(team_id_master, proposed_state_code);

COMMENT ON TABLE team_state_review_queue IS
  'Proposed state changes awaiting operator review. It borrows the shape of '
  'team_match_review_queue — a status flipped by approve/reject RPCs — but none of its '
  'columns, and explicitly not its CHECK (confidence_score >= 0.75 AND < 0.90), which '
  'would reject both confidences queued here.';

COMMENT ON COLUMN team_state_review_queue.proposed_state_code IS
  'The state that would have been written. NOT NULL because the suppression read keys on '
  'it: a NULL would never match itself, so a rejected row would re-queue every sweep.';

-- ============================================================================
-- tgs_events — event metadata that exists nowhere in the database today
-- ============================================================================

CREATE TABLE IF NOT EXISTS tgs_events (
    event_id INTEGER PRIMARY KEY,
    name TEXT,
    event_type_id INTEGER,
    state_code TEXT,
    city TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tgs_events IS
  'One row per scraped TGS event, from the provider''s get-event-details payload. games '
  'persists no event metadata beyond event_name, so without this table an event cannot '
  'be told from a league.';

COMMENT ON COLUMN tgs_events.event_type_id IS
  'Provider eventTypeID: 1 tournament, 2 league. A league''s state names the sanctioning '
  'office rather than where anyone played, so the two must be distinguishable.';

COMMENT ON COLUMN tgs_events.state_code IS
  'The provider''s own stateCode, stored verbatim rather than as CHAR(2): it is a '
  'cross-check against states derived from participants, not an authority, and a scrape '
  'must not fail on an unexpected value.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE team_state_audit ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_state_audit_deny_all" ON team_state_audit;
CREATE POLICY "team_state_audit_deny_all" ON team_state_audit
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_state_audit_deny_all" ON team_state_audit IS 'Blocks all access to the state ledger for non-service roles';

DROP POLICY IF EXISTS "team_state_audit_service_role_all" ON team_state_audit;
CREATE POLICY "team_state_audit_service_role_all" ON team_state_audit
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_state_audit_service_role_all" ON team_state_audit IS 'Service role has full access to the state ledger for ETL operations';

ALTER TABLE team_state_review_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_state_review_queue_deny_all" ON team_state_review_queue;
CREATE POLICY "team_state_review_queue_deny_all" ON team_state_review_queue
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_state_review_queue_deny_all" ON team_state_review_queue IS 'Blocks all access to the state review queue for non-service roles';

DROP POLICY IF EXISTS "team_state_review_queue_service_role_all" ON team_state_review_queue;
CREATE POLICY "team_state_review_queue_service_role_all" ON team_state_review_queue
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_state_review_queue_service_role_all" ON team_state_review_queue IS 'Service role has full access to the state review queue for ETL operations';

ALTER TABLE tgs_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tgs_events_deny_all" ON tgs_events;
CREATE POLICY "tgs_events_deny_all" ON tgs_events
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "tgs_events_deny_all" ON tgs_events IS 'Blocks all access to TGS event metadata for non-service roles';

DROP POLICY IF EXISTS "tgs_events_service_role_all" ON tgs_events;
CREATE POLICY "tgs_events_service_role_all" ON tgs_events
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "tgs_events_service_role_all" ON tgs_events IS 'Service role has full access to TGS event metadata for ETL operations';

-- ============================================================================
-- THE LEDGER TRIGGER
-- ============================================================================

-- SECURITY INVOKER (the default) is load-bearing: a definer function would report its
-- own owner as the actor for every write that arrives without the GUCs set, which is
-- exactly the population the fallback exists to identify. Only roles that bypass RLS can
-- write teams, so the insert below cannot be blocked by the ledger's own policies.
CREATE OR REPLACE FUNCTION public.log_team_state_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_old_state_code character(2);
  v_old_source text;
  v_old_confidence numeric(3,2);
BEGIN
  -- OLD is unassigned in an INSERT trigger and reading a field of it raises, so the
  -- prior values are read once here rather than inline below.
  IF TG_OP = 'UPDATE' THEN
    v_old_state_code := OLD.state_code;
    v_old_source     := OLD.state_source;
    v_old_confidence := OLD.state_confidence;
  END IF;

  INSERT INTO public.team_state_audit (
    team_id_master,
    action,
    old_state_code,
    new_state_code,
    old_source,
    new_source,
    old_confidence,
    new_confidence,
    applied_by,
    reason
  )
  VALUES (
    NEW.team_id_master,
    COALESCE(NULLIF(current_setting('pitchrank.action', true), ''), 'external'),
    v_old_state_code,
    NEW.state_code,
    v_old_source,
    NEW.state_source,
    v_old_confidence,
    NEW.state_confidence,
    COALESCE(NULLIF(current_setting('pitchrank.actor', true), ''), current_user::text),
    NULLIF(current_setting('pitchrank.reason', true), '')
  );

  RETURN NULL;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.log_team_state_change() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.log_team_state_change() TO service_role;

COMMENT ON FUNCTION public.log_team_state_change() IS
  'Append one team_state_audit row for a state_code write. Reads the actor and action '
  'from transaction-local GUCs set by apply_team_state(), falling back to the database '
  'role name and action ''external'' for writes from any other path.';

-- The provenance columns are in the WHEN clause too, because a write that re-sources a
-- state it agrees with changes only those and would otherwise succeed unlogged. They
-- cost nothing on the hot path: nothing but this file's own write function touches them.
DROP TRIGGER IF EXISTS log_team_state_update ON teams;
CREATE TRIGGER log_team_state_update
    AFTER UPDATE ON teams
    FOR EACH ROW
    WHEN (OLD.state_code IS DISTINCT FROM NEW.state_code
       OR OLD.state_source IS DISTINCT FROM NEW.state_source
       OR OLD.state_confidence IS DISTINCT FROM NEW.state_confidence)
    EXECUTE FUNCTION public.log_team_state_change();

DROP TRIGGER IF EXISTS log_team_state_insert ON teams;
CREATE TRIGGER log_team_state_insert
    AFTER INSERT ON teams
    FOR EACH ROW
    WHEN (NEW.state_code IS NOT NULL)
    EXECUTE FUNCTION public.log_team_state_change();

-- ============================================================================
-- THE WRITE PATH
-- ============================================================================

CREATE OR REPLACE FUNCTION public.apply_team_state(
  p_team_id uuid,
  p_expected_state_code text,
  p_state_code text,
  p_source text,
  p_confidence numeric,
  p_actor text,
  p_action text,
  p_reason text DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_updated integer;
BEGIN
  IF COALESCE(p_actor, '') = '' OR COALESCE(p_action, '') = '' THEN
    RAISE EXCEPTION 'apply_team_state requires p_actor and p_action: the ledger stamps both';
  END IF;

  -- Transaction-local, so the trigger below sees them and nothing outside this
  -- transaction does.
  PERFORM set_config('pitchrank.actor', p_actor, true);
  PERFORM set_config('pitchrank.action', p_action, true);
  PERFORM set_config('pitchrank.reason', COALESCE(p_reason, ''), true);

  UPDATE public.teams
  SET state_code = p_state_code,
      state_source = p_source,
      state_confidence = p_confidence,
      state_assigned_at = now()
  WHERE team_id_master = p_team_id
    AND state_code IS NOT DISTINCT FROM p_expected_state_code::character(2);

  GET DIAGNOSTICS v_updated = ROW_COUNT;

  -- The AFTER trigger has already fired, so the stamps come off again here: a caller
  -- that runs several statements in one transaction must not have a later write to
  -- teams inherit this one's actor.
  PERFORM set_config('pitchrank.actor', '', true);
  PERFORM set_config('pitchrank.action', '', true);
  PERFORM set_config('pitchrank.reason', '', true);

  RETURN v_updated > 0;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.apply_team_state(uuid, text, text, text, numeric, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_team_state(uuid, text, text, text, numeric, text, text, text) TO service_role;

COMMENT ON FUNCTION public.apply_team_state(uuid, text, text, text, numeric, text, text, text) IS
  'Write one team''s state_code, state_source, state_confidence and state_assigned_at, '
  'stamping the ledger with p_actor and p_action. Returns true when the row was written '
  'and false when it was not, which happens when state_code no longer matches '
  'p_expected_state_code — the pre-image every caller holds: the sweep''s snapshot, the '
  'queue row''s current_state_code, or the value a revert is undoing. That predicate is '
  'what keeps another weekly writer''s change from being silently overwritten between a '
  'decision and its apply. Every write path goes through here; a direct UPDATE is logged '
  'as ''external'' with no actor.';

-- ============================================================================
-- REVERT
-- ============================================================================

CREATE OR REPLACE FUNCTION public.revert_team_states(
  p_applied_by text,
  p_applied_after timestamptz,
  p_applied_before timestamptz,
  p_reverted_by text,
  p_after uuid DEFAULT NULL,
  p_batch_size integer DEFAULT 500,
  p_dry_run boolean DEFAULT false,
  p_revert_reason text DEFAULT NULL
)
RETURNS TABLE (rows_changed integer, last_team_id uuid)
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_changed integer := 0;
  v_last uuid;
  v_row record;
BEGIN
  -- Every argument below fails silently rather than loudly when it is missing: a NULL
  -- bound matches no ledger row, and a NULL or non-positive p_batch_size is either
  -- LIMIT NULL — no limit at all, the whole-batch scan the 8s budget cannot afford —
  -- or an empty page, which ends the caller's walk on its first call. Both report a
  -- successful revert of nothing.
  IF p_applied_by IS NULL OR p_applied_after IS NULL OR p_applied_before IS NULL
     OR COALESCE(p_reverted_by, '') = '' OR COALESCE(p_batch_size, 0) < 1 THEN
    RAISE EXCEPTION 'revert_team_states requires p_applied_by, p_applied_after, p_applied_before, p_reverted_by and a positive p_batch_size';
  END IF;

  FOR v_row IN
    WITH scope AS (
      SELECT a.team_id_master,
             a.old_state_code,
             a.old_source,
             a.old_confidence,
             ROW_NUMBER() OVER (
               PARTITION BY a.team_id_master ORDER BY a.applied_at, a.id
             ) AS rn,
             -- The state the batch left behind, which the restore below requires the
             -- team to still be sitting on. The frame is not optional: LAST_VALUE
             -- defaults to a frame ending at the current row, so on rn = 1 it would
             -- return the batch's first write rather than its last.
             LAST_VALUE(a.new_state_code) OVER (
               PARTITION BY a.team_id_master ORDER BY a.applied_at, a.id
               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
             ) AS batch_state_code
      FROM public.team_state_audit a
      WHERE a.applied_by = p_applied_by
        AND a.applied_at >= p_applied_after
        AND a.applied_at < p_applied_before
        -- A revert is not itself a batch a later date-scoped revert can undo.
        AND a.action <> 'revert'
    ),
    -- rn = 1 is the OLDEST row in scope for the team, which is what returns it to its
    -- pre-batch state where a batch wrote it more than once.
    page AS (
      SELECT s.team_id_master,
             s.old_state_code,
             s.old_source,
             s.old_confidence,
             s.batch_state_code
      FROM scope s
      WHERE s.rn = 1
        AND (p_after IS NULL OR s.team_id_master > p_after)
      ORDER BY s.team_id_master
      LIMIT p_batch_size
    )
    -- LEFT JOIN so a team that has since disappeared still carries the cursor forward
    -- instead of ending the caller's walk early. `restorable` is the same test
    -- apply_team_state applies below, so the dry run cannot disagree with the write:
    -- a team another writer has moved on since the batch is skipped, not dragged back.
    SELECT p.team_id_master,
           p.old_state_code,
           p.old_source,
           p.old_confidence,
           p.batch_state_code,
           (t.team_id_master IS NOT NULL
            AND t.state_code IS NOT DISTINCT FROM p.batch_state_code) AS restorable
    FROM page p
    LEFT JOIN public.teams t ON t.team_id_master = p.team_id_master
    ORDER BY p.team_id_master
  LOOP
    v_last := v_row.team_id_master;

    IF p_dry_run THEN
      IF v_row.restorable THEN
        v_changed := v_changed + 1;
      END IF;
    ELSIF public.apply_team_state(
            v_row.team_id_master,
            v_row.batch_state_code::text,
            v_row.old_state_code::text,
            v_row.old_source,
            v_row.old_confidence,
            p_reverted_by,
            'revert',
            p_revert_reason
          ) THEN
      v_changed := v_changed + 1;
    END IF;
  END LOOP;

  RETURN QUERY SELECT v_changed, v_last;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.revert_team_states(text, timestamptz, timestamptz, text, uuid, integer, boolean, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.revert_team_states(text, timestamptz, timestamptz, text, uuid, integer, boolean, text) TO service_role;

COMMENT ON FUNCTION public.revert_team_states(text, timestamptz, timestamptz, text, uuid, integer, boolean, text) IS
  'Restore state_code, state_source and state_confidence for one keyset page of the '
  'teams written by p_applied_by between p_applied_after and p_applied_before, oldest '
  'ledger row per team, writing through apply_team_state() so the restore is itself '
  'logged — as action ''revert'', which the scope excludes. A team whose state has moved '
  'since the batch wrote it is skipped rather than dragged back. Returns the number of rows '
  'written and the page''s last team_id_master; p_dry_run returns the count without '
  'writing. Called in a loop, because one whole-batch call would be cancelled by the 8s '
  'statement_timeout a service-role PostgREST request inherits.';
