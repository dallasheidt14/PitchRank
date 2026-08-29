-- Give the state review queue a consumer.
--
-- Without these the queue is write-only: the sweep files decisions it will not take on
-- its own authority, and nothing can accept or refuse them. The suppression rule that
-- stops a rejected proposal being re-raised every week also depends on a `rejected`
-- status that nothing could set.
--
-- An approval is a teams write like any other, so it goes through apply_team_state and
-- is logged with action 'approve' and the approver's name. It applies the change first
-- and marks the row second, mirroring approve_team_match
-- (20240201000003_add_match_review_queue.sql:21-69), which is the shape the dashboard
-- already expects.
--
-- The rankings mirror is here rather than in the caller because this one is a Postgres
-- function: the boards read rankings_full.state_code, refreshed Mondays, so an approval
-- without it would change the team page and leave the state board showing the value the
-- operator just rejected, for up to a week. An UPDATE, never an upsert -- Monday's run
-- re-derives the column from teams, and an inserted row would be a ranking no run
-- produced.

CREATE OR REPLACE FUNCTION public.approve_team_state(
  p_review_id bigint,
  p_approver text
)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_row public.team_state_review_queue%ROWTYPE;
  v_applied boolean;
BEGIN
  IF COALESCE(p_approver, '') = '' THEN
    RAISE EXCEPTION 'approve_team_state requires an approver: the ledger stamps it';
  END IF;

  -- FOR UPDATE, so an approve and a reject of the same row cannot both observe it
  -- pending and both report success. One operator makes concurrency unlikely rather
  -- than impossible, and the loser here waits rather than losing its answer.
  SELECT * INTO v_row
  FROM public.team_state_review_queue
  WHERE id = p_review_id AND status = 'pending'
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'State review % not found or already reviewed', p_review_id;
  END IF;

  -- The queue row's current_state_code is the pre-image: what the team looked like when
  -- the decision was filed. A team another writer has moved since is not the team the
  -- operator is looking at, so the approval fails rather than overwriting the newer value.
  v_applied := public.apply_team_state(
    v_row.team_id_master,
    v_row.current_state_code::text,
    v_row.proposed_state_code::text,
    'tier_' || lower(v_row.tier),
    v_row.confidence,
    p_approver,
    'approve',
    'approved review ' || p_review_id::text
  );

  IF NOT v_applied THEN
    RAISE EXCEPTION
      'Team % has moved or gone since review % was filed; re-run the sweep rather than approving a stale decision',
      v_row.team_id_master, p_review_id;
  END IF;

  UPDATE public.rankings_full
  SET state_code = v_row.proposed_state_code
  WHERE team_id = v_row.team_id_master;

  UPDATE public.team_state_review_queue
  SET status = 'approved',
      reviewed_by = p_approver,
      reviewed_at = now()
  WHERE id = p_review_id;

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.approve_team_state(bigint, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.approve_team_state(bigint, text) TO service_role;

COMMENT ON FUNCTION public.approve_team_state(bigint, text) IS
  'Apply a pending state review and mark it approved, writing through apply_team_state '
  'so the change is logged as action ''approve'' by the approver, and mirroring the new '
  'state into rankings_full so the board and the team page agree today. Raises if the '
  'review is gone, already reviewed, or the team has moved since it was filed.';

CREATE OR REPLACE FUNCTION public.reject_team_state(
  p_review_id bigint,
  p_reviewer text
)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF COALESCE(p_reviewer, '') = '' THEN
    RAISE EXCEPTION 'reject_team_state requires a reviewer: the suppression rule reads it';
  END IF;

  UPDATE public.team_state_review_queue
  SET status = 'rejected',
      reviewed_by = p_reviewer,
      reviewed_at = now()
  WHERE id = p_review_id AND status = 'pending';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'State review % not found or already reviewed', p_review_id;
  END IF;

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.reject_team_state(bigint, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reject_team_state(bigint, text) TO service_role;

COMMENT ON FUNCTION public.reject_team_state(bigint, text) IS
  'Mark a pending state review rejected, changing no team. The sweep reads these: a '
  'rejected proposal is not raised again while the same state is proposed for the same '
  'team, which is the only thing that stops a refused decision returning every week.';
