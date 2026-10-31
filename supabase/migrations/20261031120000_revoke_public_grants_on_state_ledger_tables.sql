-- Take back the default grants anon and authenticated still hold on the team-state provenance tables
-- (20260829120000_add_team_state_provenance.sql) and on the sequences behind the ledgers.
--
-- pg_default_acl grants anon and authenticated every privilege on a new public relation. RLS
-- governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policies these tables
-- ship with leave TRUNCATE and REFERENCES in that grant. team_state_audit is the append-only ledger
-- revert_team_states reads to put a state back, and team_state_review_queue holds the decisions the
-- sweep reads back as an operator's approval, so emptying either is not recoverable. A BIGSERIAL
-- sequence carries its own default grant, which a table REVOKE does not reach: that includes
-- team_state_probe_log's, whose table its own migration already revoked. tgs_events has an INTEGER key
-- and no sequence.
--
-- The scheduled jobs, the dashboard and the weekly cleanup read and write these as service_role, which
-- keeps its own grant, and the state functions are SECURITY INVOKER with EXECUTE for service_role
-- only. A hand run of a script that falls back to the public SUPABASE_KEY now gets "permission denied"
-- here instead of the empty result the deny-all policy gave it.
--
-- Hand-applied: run it in the SQL editor, then record it with
--   supabase migration repair --status applied 20261031120000

REVOKE ALL ON public.team_state_audit FROM anon, authenticated;
REVOKE ALL ON public.team_state_review_queue FROM anon, authenticated;
REVOKE ALL ON public.tgs_events FROM anon, authenticated;

REVOKE ALL ON SEQUENCE public.team_state_audit_id_seq FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.team_state_review_queue_id_seq FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.team_state_probe_log_id_seq FROM anon, authenticated;
