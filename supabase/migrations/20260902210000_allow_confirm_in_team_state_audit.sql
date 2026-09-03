-- A provider record that agrees with the stored state is written as action 'confirm':
-- apply_team_state() with the stored state on both sides, so state_source becomes tier_a
-- without the value moving. log_team_state_update fires on a provenance change as well as
-- a state change, which is right -- a confirm is evidence and belongs in the ledger -- but
-- the action check predates the action and refuses the row.
--
-- A confirm row carries old_state_code = new_state_code and old_source = whatever the value
-- had before, so revert_team_states() undoes one by restoring the earlier provenance and
-- leaving the state where it was. No other reader keys on the action list.
--
-- Hand-applied, like the rest of this family; record it afterwards with
--   supabase migration repair --status applied 20260902210000

ALTER TABLE public.team_state_audit
  DROP CONSTRAINT IF EXISTS team_state_audit_action_check;

ALTER TABLE public.team_state_audit
  ADD CONSTRAINT team_state_audit_action_check
  CHECK (action IN ('fill', 'correct', 'approve', 'revert', 'external', 'confirm'));

COMMENT ON COLUMN public.team_state_audit.action IS
  'fill: a blank written; correct: a value replaced; approve: a queued proposal an operator '
  'accepted; revert: the undo of an earlier batch; confirm: a provider record that agreed '
  'with the stored value, recorded as provenance without a state change; external: any '
  'write that did not go through apply_team_state().';
