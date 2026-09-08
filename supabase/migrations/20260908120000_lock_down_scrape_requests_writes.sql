-- Make the scrape queue server-only.
--
-- 20251113150557 shipped this table with "Enable insert for all users" — FOR INSERT with no
-- TO clause, so it applies to PUBLIC, and WITH CHECK (true). pg_default_acl then grants anon
-- and authenticated arwdDxtm on every new public relation in this project, so grant and
-- policy both permitted the write. RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE
-- or REFERENCES, so REVOKE ALL rather than a policy is what removes those. There is no
-- sequence to revoke: id is uuid DEFAULT gen_random_uuid(), so pg_get_serial_sequence is
-- NULL and REVOKE ALL ON SEQUENCE would error.
--
-- error_message is written from raw exception text at scripts/process_missing_games.py
-- (`except Exception as e: error_msg = str(e)`), which is why reads close too — see the
-- policy COMMENT below.
--
-- Two operator scripts fall back to the anon key when SUPABASE_SERVICE_ROLE_KEY is absent and
-- read this table: scripts/retire_stranded_scrape_requests.py (fetch_stranded) and
-- scripts/audit_user_interest_teams.py. Both now abort with PostgREST 42501 in that mode
-- rather than returning an empty result — neither has an except around the read, so it
-- surfaces as a traceback, not as a silent "nothing found". Run them with the service-role
-- key. retire_stranded's --execute path already refused without it.
--
-- claim_queue_items keeps its service_role grant. Note for whoever supersedes it: CREATE OR
-- REPLACE preserves the ACL, but a DROP + CREATE resets EXECUTE to PUBLIC and would undo the
-- revoke below.
--
-- Hand-applied, like the rest of this family; record it afterwards with
--   supabase migration repair --status applied 20260908120000
--
-- AFTER APPLYING, verify against the live catalog rather than the file. The text guard in
-- tests/unit/test_scrape_requests_rls_migration.py reads migration text and deliberately does
-- not model views, SECURITY DEFINER functions, or role membership — these queries do, and are
-- what actually establish the table is closed:
--
--   -- anon and authenticated must be absent, or present with no privileges
--   SELECT relacl FROM pg_class WHERE relname = 'scrape_requests';
--   -- deny-all must be permissive = false; no other policy may name a browser role
--   SELECT policyname, cmd, permissive, roles FROM pg_policies WHERE tablename = 'scrape_requests';
--   -- every function reaching the table: none may grant EXECUTE to public/anon/authenticated
--   SELECT p.proname, p.prosecdef, p.proacl FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--    WHERE n.nspname = 'public' AND pg_get_functiondef(p.oid) ILIKE '%scrape_requests%';
--   -- any view over the table re-exposes it: expect zero rows
--   SELECT viewname FROM pg_views WHERE schemaname = 'public' AND definition ILIKE '%scrape_requests%';
--   -- roles anon/authenticated belong to: a grant to any of them reaches the browser
--   SELECT r.rolname, m.rolname AS member_of FROM pg_auth_members am
--     JOIN pg_roles r ON r.oid = am.member JOIN pg_roles m ON m.oid = am.roleid
--    WHERE r.rolname IN ('anon', 'authenticated');

DROP POLICY IF EXISTS "Enable insert for all users" ON public.scrape_requests;
DROP POLICY IF EXISTS "Enable read for authenticated users" ON public.scrape_requests;
DROP POLICY IF EXISTS "Service role update" ON public.scrape_requests;

-- RESTRICTIVE, not the default permissive: permissive policies combine with OR, so a
-- USING (false) among them denies nothing and a later permissive policy added through the
-- Dashboard — which is how the three dropped above arrived — would simply out-vote it.
-- Restrictive policies AND together, and apply only to the roles they name, so the
-- service_role policy below is unaffected.
DROP POLICY IF EXISTS "scrape_requests_deny_all" ON public.scrape_requests;
CREATE POLICY "scrape_requests_deny_all" ON public.scrape_requests
    AS RESTRICTIVE
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "scrape_requests_deny_all" ON public.scrape_requests IS
  'Blocks all Data API access for the browser roles. Writes were reachable with the public '
  'anon key, and error_message carries raw exception text — the ZenRows key travels in a '
  'query string, so a connection failure serialises it into that column — which is why reads '
  'are closed too.';

DROP POLICY IF EXISTS "scrape_requests_service_role_all" ON public.scrape_requests;
CREATE POLICY "scrape_requests_service_role_all" ON public.scrape_requests
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "scrape_requests_service_role_all" ON public.scrape_requests IS
  'The only reader and writer. Every enqueue path, both drainers and the four frontend '
  'routes hold the service-role key after making their own auth and rate-limit checks.';

REVOKE ALL ON public.scrape_requests FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.claim_queue_items(uuid, integer) FROM PUBLIC, anon, authenticated;

-- priority carried its 1-5 range in a COMMENT only. This is not what closes the priority-1
-- lane — 1 is the legitimate value user clicks use, and the REVOKE above is what stops an
-- outsider sending it. This rejects 0 and 6+, which no caller produces and which would sort
-- outside the drainer's ordering. Every existing row already satisfies it, so the ADD
-- validates in place without a NOT VALID pass.
ALTER TABLE public.scrape_requests
  DROP CONSTRAINT IF EXISTS scrape_requests_priority_check;

ALTER TABLE public.scrape_requests
  ADD CONSTRAINT scrape_requests_priority_check
  CHECK (priority BETWEEN 1 AND 5);

COMMENT ON COLUMN public.scrape_requests.priority IS
  'Lower number = higher priority. 1=user-clicked, 2=daily and operator enqueues '
  '(yesterday-games, active teams, viewed teams, stranded merge fixtures), 3=discovery, '
  '4=safety-net, 5=default. Enforced by scrape_requests_priority_check.';
