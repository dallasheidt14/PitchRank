-- Server-only tables: no page reads them in the browser, so the browser roles get nothing.
--   team_link_audit   the admin link, create-team and unlink routes record each action on the service role
--   team_merge_audit  a team merge, run on the service role, snapshots the merged-away team row
--   scheduled_games   a standalone GotSport upcoming-match scraper fills it over a direct database
--                     connection, and creates the table itself
-- games_with_resolved_teams, recent_merge_activity and exclude_games_for_team_in_range run as their
-- owner, so their own grant is all that decides who reaches them; nothing outside the service role
-- uses any of them.
-- No migration creates scheduled_games or games_with_resolved_teams, so their statements run only
-- where the object exists.

ALTER TABLE public.team_link_audit ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_link_audit_deny_all" ON public.team_link_audit;
CREATE POLICY "team_link_audit_deny_all" ON public.team_link_audit
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS "team_link_audit_service_role_all" ON public.team_link_audit;
CREATE POLICY "team_link_audit_service_role_all" ON public.team_link_audit
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.team_link_audit FROM anon, authenticated;

ALTER TABLE public.team_merge_audit ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_merge_audit_deny_all" ON public.team_merge_audit;
CREATE POLICY "team_merge_audit_deny_all" ON public.team_merge_audit
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS "team_merge_audit_service_role_all" ON public.team_merge_audit;
CREATE POLICY "team_merge_audit_service_role_all" ON public.team_merge_audit
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.team_merge_audit FROM anon, authenticated;

DO $$
BEGIN
    IF to_regclass('public.scheduled_games') IS NOT NULL THEN
        ALTER TABLE public.scheduled_games ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS "scheduled_games_deny_all" ON public.scheduled_games;
        CREATE POLICY "scheduled_games_deny_all" ON public.scheduled_games
            FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

        DROP POLICY IF EXISTS "scheduled_games_service_role_all" ON public.scheduled_games;
        CREATE POLICY "scheduled_games_service_role_all" ON public.scheduled_games
            FOR ALL TO service_role USING (true) WITH CHECK (true);

        REVOKE ALL ON public.scheduled_games FROM anon, authenticated;
    END IF;

    IF to_regclass('public.scheduled_games_id_seq') IS NOT NULL THEN
        REVOKE ALL ON SEQUENCE public.scheduled_games_id_seq FROM anon, authenticated;
    END IF;

    IF to_regclass('public.games_with_resolved_teams') IS NOT NULL THEN
        REVOKE ALL ON public.games_with_resolved_teams FROM anon, authenticated;
    END IF;
END
$$;
REVOKE ALL ON public.recent_merge_activity FROM anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.exclude_games_for_team_in_range(uuid, date, date, boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.exclude_games_for_team_in_range(uuid, date, date, boolean) TO service_role;
