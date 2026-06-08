-- Decommission the retired "openclaw" multi-agent / Mission Control task-board system.
-- Drops the 5 openclaw tables and their dependent objects (view, functions, RLS policy,
-- realtime-publication memberships, and the update_updated_at triggers via CASCADE).
--
-- INTENTIONALLY PRESERVED (shared with live KEEP code — must NOT be dropped):
--   * announcements                 -- public announcements feed (api/announcements)
--   * update_updated_at_column()    -- shared trigger function still used by KEEP tables
--
-- The /mission-control route is a live admin ML-ops dashboard (prospective predictions +
-- model_training_runs) and does NOT use any object dropped here. Idempotent: safe to re-run.

-- 1. Dependent view.
DROP VIEW IF EXISTS active_agent_sessions;

-- 2. Dependent functions. DROP FUNCTION resolves by argument type: get_agent_status is
--    defined as get_agent_status(p_agent_name TEXT), so the drop MUST name (text) — a
--    zero-arg drop would silently no-op and leave the real function orphaned.
--    cleanup_old_sessions() is genuinely zero-arg.
DROP FUNCTION IF EXISTS get_agent_status(text);
DROP FUNCTION IF EXISTS cleanup_old_sessions();

-- 3. Detach from the realtime publication and drop the agent_activity RLS policy, each
--    guarded so the migration stays idempotent (a bare ALTER PUBLICATION ... DROP TABLE
--    errors when the table is not a member, and DROP POLICY ... ON <table> errors when the
--    table is already gone on a re-run). mission_chat has no RLS policy, so none is dropped.
--    The DROP TABLE ... CASCADE below also removes these, but doing it explicitly keeps the
--    publication change visible and order-independent.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_publication_tables
             WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'agent_activity') THEN
    ALTER PUBLICATION supabase_realtime DROP TABLE agent_activity;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_publication_tables
             WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'mission_chat') THEN
    ALTER PUBLICATION supabase_realtime DROP TABLE mission_chat;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_policies
             WHERE schemaname = 'public' AND tablename = 'agent_activity'
               AND policyname = 'Allow all operations on agent_activity') THEN
    DROP POLICY "Allow all operations on agent_activity" ON agent_activity;
  END IF;
END $$;

-- 4. Drop the five openclaw tables. CASCADE clears the update_updated_at triggers on
--    agent_tasks/agent_sessions, the task_comments -> agent_tasks FK, the agent_activity
--    RLS policy, and any remaining dependents — without touching the preserved objects.
DROP TABLE IF EXISTS mission_chat, task_comments, agent_activity, agent_tasks, agent_sessions CASCADE;
