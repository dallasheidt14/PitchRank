-- Carry a reverted state onto the board with the team.
--
-- revert_team_states restored teams.state_code and stopped there, so the boards -- which
-- read rankings_full.state_code and are refreshed only by Monday's ranking run -- kept
-- showing the value the operator had just rejected, for up to a week. The undo looked
-- like it had not worked to the one audience that matters.
--
-- Superseding the whole function rather than patching it: this repo replaces a function
-- by redefining it in a later migration, and everything below except the mirror is
-- unchanged from 20260829120000_add_team_state_provenance.sql.
--
-- An UPDATE, never an upsert. Monday's run re-derives the column from teams, and an
-- inserted row would be a ranking no run produced.

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
  -- LIMIT NULL -- no limit at all, the whole-batch scan the 8s budget cannot afford --
  -- or an empty page, which ends the caller's walk on its first call. Both report a
  -- successful revert of nothing.
  IF p_applied_by IS NULL OR p_applied_after IS NULL OR p_applied_before IS NULL
     OR COALESCE(p_reverted_by, '') = '' OR COALESCE(p_batch_size, 0) < 1 THEN
    RAISE EXCEPTION 'revert_team_states requires p_applied_by, p_applied_after, p_applied_before, p_reverted_by and a positive p_batch_size';
  END IF;

  FOR v_row IN
    WITH batch AS (
      SELECT a.team_id_master,
             a.old_state_code,
             a.old_source,
             a.old_confidence,
             a.new_state_code,
             a.applied_at,
             a.id
      FROM public.team_state_audit a
      WHERE a.applied_by = p_applied_by
        AND a.applied_at >= p_applied_after
        AND a.applied_at < p_applied_before
        -- A revert is not itself a batch a later date-scoped revert can undo.
        AND a.action <> 'revert'
    ),
    -- The cursor and the limit come first, so a call windows one page of ledger rows
    -- rather than every row the batch wrote. team_id_master is the partition key below,
    -- so narrowing to these teams cannot change either window's answer for them.
    page_teams AS (
      SELECT DISTINCT b.team_id_master
      FROM batch b
      WHERE p_after IS NULL OR b.team_id_master > p_after
      ORDER BY b.team_id_master
      LIMIT p_batch_size
    ),
    scope AS (
      SELECT b.team_id_master,
             b.old_state_code,
             b.old_source,
             b.old_confidence,
             ROW_NUMBER() OVER (
               PARTITION BY b.team_id_master ORDER BY b.applied_at, b.id
             ) AS rn,
             -- The state the batch left behind, which the restore below requires the
             -- team to still be sitting on. The frame is not optional: LAST_VALUE
             -- defaults to a frame ending at the current row, so on rn = 1 it would
             -- return the batch's first write rather than its last.
             LAST_VALUE(b.new_state_code) OVER (
               PARTITION BY b.team_id_master ORDER BY b.applied_at, b.id
               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
             ) AS batch_state_code
      FROM batch b
      JOIN page_teams pt ON pt.team_id_master = b.team_id_master
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
      -- The board reads its own copy and only Monday refreshes it, so an undo that stops
      -- at teams leaves the rejected state on display all week.
      UPDATE public.rankings_full
      SET state_code = v_row.old_state_code
      WHERE team_id = v_row.team_id_master;

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
  'logged — as action ''revert'', which the scope excludes — and mirroring each restored '
  'value into rankings_full so the board stops showing the rejected one. A team whose '
  'state has moved since the batch wrote it is skipped rather than dragged back. Returns '
  'the number of rows written and the page''s last team_id_master; p_dry_run returns the '
  'count without writing. Called in a loop, because one whole-batch call would be '
  'cancelled by the 8s statement_timeout a service-role PostgREST request inherits.';
