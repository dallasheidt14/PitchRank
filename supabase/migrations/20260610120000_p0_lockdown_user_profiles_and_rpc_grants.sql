-- P0 security lockdown (audit 2026-06-10)
--
-- P0-1: user_profiles allowed anon/authenticated to UPDATE every column on the
-- caller's own row — including plan, stripe_customer_id, subscription_status —
-- via the unrestricted self-update RLS policy plus table-wide column grants.
-- Any signed-in user could self-promote to plan='admin'/'premium', defeating
-- requireAdmin()/requirePremium() on every gated surface. All legitimate
-- writes go through the service role (webhook/sync/checkout routes now use the
-- admin client), so API roles need no INSERT/UPDATE at all. Profile creation
-- happens in the SECURITY DEFINER handle_new_user trigger.

REVOKE INSERT, UPDATE ON public.user_profiles FROM anon, authenticated;

-- The write policies are unreachable without privileges; drop them so a future
-- table-level re-grant cannot silently reopen the escalation path.
DROP POLICY IF EXISTS "Users can update own profile" ON public.user_profiles;
DROP POLICY IF EXISTS "Enable insert for authenticated users" ON public.user_profiles;

-- P0-2: these RPCs were executable by PUBLIC/anon/authenticated.
-- link_game_team/unlink_game_team are SECURITY DEFINER (they bypass RLS and
-- the immutable-game trigger), so any visitor could rewrite team-game
-- mappings directly. The merge/enqueue functions are SECURITY INVOKER but
-- have no business being callable by API roles either. Every legitimate
-- caller (Next.js service-client routes, dashboard.py, the enqueue_* scripts
-- in GitHub Actions) uses the service role, which keeps its explicit grant.

REVOKE EXECUTE ON FUNCTION public.link_game_team(uuid, uuid, boolean) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.unlink_game_team(uuid, uuid, boolean) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.execute_team_merge(uuid, uuid, text, text, double precision, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.revert_team_merge(uuid, text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint) FROM PUBLIC, anon, authenticated;
