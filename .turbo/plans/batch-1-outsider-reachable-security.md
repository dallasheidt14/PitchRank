---
status: ready
---

# Plan: Lock down anonymous queue writes, and stop mailing a live account token

## Context

A verification sweep of the improvement backlog on 2026-09-08 checked all 97 live entries
against the code, and the database ones against the production database rather than the
migration history. This plan carries the two findings that survived review as code changes:
IMP-168 and IMP-091.

**IMP-168 — anyone can inject queue work.** `scrape_requests` carries
`"Enable insert for all users"` (`FOR INSERT`, role `public`, `WITH CHECK (true)`,
`supabase/migrations/20251113150557_add_scrape_requests.sql:28-29`) and its live ACL is
`anon=arwdDxtm`. Grant and policy both permit it, so anyone holding the public key can
insert rows at any `priority` — the column is `smallint NOT NULL DEFAULT 5` with no CHECK —
into the same priority-1 lane a paying subscriber's click uses, at ZenRows cost.

**IMP-091 — a live account token is mailed to a shared mailbox.**
`scripts/check_stuck_signups.py` mints an unsolicited 24-hour recovery token for every
paying-but-never-signed-in customer and mails it to `pitchrankio@gmail.com` for an admin to
forward. That token grants a full session on a paid account, so anyone with access to the
mailbox, a forwarded copy, or Resend's delivery history can take the account over. This is a
custody problem: the credential is real, it is minted without the customer asking, and it
comes to rest somewhere with none of an account's protections.

The remedy is to stop minting it and add no replacement email. The customer already receives
a working set-password link at checkout — `sendPasswordSetupEmail` at
`frontend/app/api/stripe/webhook/route.ts:416` — and anyone still locked out can self-serve
through `/forgot-password`. IMP-091 suggests calling `reset_password_for_email` instead;
that is deliberately **not** being done, because it would mail an unrequested reset every six
hours to someone who already has a link.

### What this plan deliberately excludes

**IMP-090 (PKCE `?code=` redeemed on GET) is parked, not deferred for scheduling reasons —
the fix as conceived cannot work.** `@supabase/ssr` 0.9.0 hardcodes `detectSessionInUrl` and
`flowType: "pkce"` (caller options are spread *before* those keys, so they are not
overridable), `@supabase/auth-js` 2.100.1 `_isPKCECallback` fires on
`!!(params.code && verifier)` reading `url.searchParams`, and the root layout renders
`Navigation` → `useUser` → a browser client on **every** route. So serving
`/auth/confirm?code=` would spend the code on page load, before any button. Separately,
`frontend/middleware.ts:35` exempts `/auth/confirm` only when a `token_hash` is present, and
its own comment predicts the infinite redirect loop that routing a `code` there would create.
The threat model in the entry is also wrong: the auto-exchange needs the verifier from *that
browser's* storage, so a mail scanner cannot redeem the code at all. See the entry's
2026-09-08 update.

**IMP-153 is out too.** `anon` does hold DELETE and TRUNCATE on `user_profiles`, but the
table's single policy is `FOR SELECT`, RLS denies a command with no permissive policy, and
`anon` is not a login role, so PostgREST is the only path and it never issues TRUNCATE. It
moved to batch 4's hardening bundle with IMP-152.

### Decisions taken with the user

1. **Queue reads stay open; only writes are locked down.** See the Realtime note in Blast
   Radius — the feature this protects is already broken, and the decision stands anyway
   because the information is low-value and the smaller change is the safer one.
2. **The digest drops the link and sends no new email**, per the reasoning above.

## Pattern Survey

### Analogous Features

**RLS tightening / lockdown migrations**

- `supabase/migrations/20260903120000_add_team_page_views.sql:55-82` — **the template.**
  `ALTER TABLE … ENABLE ROW LEVEL SECURITY` → `DROP POLICY IF EXISTS` + `CREATE POLICY` →
  `COMMENT ON POLICY` → the same pair for the service-role policy → `REVOKE ALL ON
  public.<table> FROM anon, authenticated;`. Note it drops each policy it is about to create
  (`:57`, `:69`), which is what makes a second application safe.
- `supabase/migrations/20260610120000_p0_lockdown_user_profiles_and_rpc_grants.sql:12-17` —
  the only migration that tightens an already-permissive table. REVOKE first, then
  `DROP POLICY IF EXISTS` on the now-unreachable write policies, deliberately "so a future
  table-level re-grant cannot silently reopen the escalation path". Line 31 revoked
  `enqueue_scrape_request`'s EXECUTE from `anon`/`authenticated`.
- The `_deny_all` / `_service_role_all` naming originates in
  `supabase/migrations/20240215000000_add_row_level_security.sql:250` and `:329`.
- There is no `ALTER POLICY` anywhere in the tree.

**CHECK constraints on live tables**

- `supabase/migrations/20260902210000_allow_confirm_in_team_state_audit.sql:14-19` — the
  template: `ALTER TABLE … DROP CONSTRAINT IF EXISTS <name>;` then a separate
  `ALTER TABLE … ADD CONSTRAINT <name> CHECK (…);`. Plain add.
- Checkable negative: `grep -rn "NOT VALID\|VALIDATE CONSTRAINT" supabase/ scripts/ tests/`
  returns nothing. The two-phase add is not used here.

**Transactional email**

- `frontend/app/api/stripe/webhook/route.ts:397-421` — generates a recovery link, builds a
  `token_hash` URL pointed at `/auth/confirm`, and sends to the customer at `:416`, with
  `notifyAdmin` only on failure. The comment at `:406-411` records why `token_hash` and not
  the PKCE `action_link`: a link opened on a different device than checkout has no
  `code_verifier` cookie and would strand the customer.
- Checkable negative: `reset_password_for_email` is never called from Python, and no Python
  script mails an end user — every Python mailer targets an operator via a raw
  `requests.post` to the Resend API.

### Reusable Utilities

- `tests/unit/test_team_page_views_migration.py:33-64` — `_executable()` (strips `--`
  comments), `_flat()`, `_migrations()` (`sorted(MIGRATIONS.glob("*.sql"))`), `_tree()`,
  `_newest_statement(pattern)`. Copy these into the new guard rather than importing across
  test modules, matching how `test_team_state_provenance_migration.py` does it.

### Convention Anchors

- **Migration filenames**: `YYYYMMDDHHMMSS_snake_case_description.sql`. Every policy gets a
  `COMMENT ON POLICY` stating the security property.
- **Objects are superseded, never edited in place.** Guard tests resolve by NAME across
  `MIGRATIONS.glob("*.sql")` and take the newest definition; never pin a guard to a filename
  (`tests/unit/test_team_page_views_migration.py:19-21`).
- **The GRANT trap is `pg_default_acl`, not `DROP POLICY`.** `DROP POLICY` does not touch
  GRANTs. Per `20260903120000:45-46`, this project's `pg_default_acl` grants
  `anon`/`authenticated` `arwdDxtm` on every new public relation, and RLS governs
  SELECT/INSERT/UPDATE/DELETE but **not** TRUNCATE or REFERENCES — so a policy change alone
  leaves TRUNCATE reachable, which is why the REVOKE is load-bearing.
- **Migration guard tests** live at `tests/unit/test_<subject>_migration.py`, are pure text
  (CI applies no SQL), open with a docstring enumerating which silent failure each assertion
  stands in for, run every behavioural assertion through `_executable()` so a commented-out
  clause cannot satisfy it, and close with a count-against-allowance test
  (`test_team_page_views_migration.py:141-157`) so a later migration forces the guard to be
  widened deliberately.
- **Python script tests**: `tests/unit/test_check_stuck_signups.py` mocks the Supabase client
  and asserts exact literal URLs. It imports `LINK_FAILED` at module scope (`:12`) and uses
  it at `:163`.

### Blast radius, resolved during planning

- **No Python script writes the queue with the anon key.** `enqueue_active_teams.py:105`,
  `enqueue_viewed_teams.py:137`, `discover_teams_from_opponents.py:365` and
  `src/tournaments/seeding_enqueue.py:163` all go through the `enqueue_scrape_request` RPC,
  whose EXECUTE `anon` lost at `20260610120000:31`.
  `retire_stranded_scrape_requests.py` reads the table at `:74` (a `.select()`) and is the
  only direct writer, at `:123` (an `.update()`) — and it refuses `--execute` without the
  service-role key at `:174-176`.
- **All frontend writers already use the service role**: `scrape-missing-game/route.ts:69`,
  `create-team/route.ts:189`, `watchlist/add/route.ts:163`,
  `process-missing-games/route.ts:43`. Python: `drain_queue.py:568`,
  `process_missing_games.py:794`.
- **`claim_queue_items` keeps EXECUTE and updates this table.**
  `supabase/migrations/20260526100000:57` grants EXECUTE `TO authenticated, service_role`
  (`prosecdef = false`, so it runs as the caller). It is not exploitable today because RLS
  blocks the underlying UPDATE, and less so after step 1 removes the table grant. **Verify
  the live ACL for `anon` on this function before deciding**: if `anon` holds EXECUTE from a
  default ACL rather than this migration, revoke it in the same migration, following the
  precedent at `20260610120000:31`. Do not assert it is granted here — the migration text
  grants only `authenticated` and `service_role`.
- **No sequence to revoke.** `scrape_requests.id` is `uuid NOT NULL DEFAULT
  gen_random_uuid()` and `pg_get_serial_sequence` returns NULL, so the `REVOKE ALL ON
  SEQUENCE` half of the house template does **not** apply. Adding one will error.
- **The CHECK validates cleanly.** All 217,446 live rows are priority 1-5 (1: 883,
  2: 166,121, 3: 47,824, 4: 2,404, 5: 214), and no priority constraint exists today, so
  `DROP CONSTRAINT IF EXISTS` is a no-op and the plain `ADD` succeeds.
- **The Realtime toast this SELECT decision protects has never fired.** The
  `supabase_realtime` publication contains exactly one public table, `announcements`;
  `scrape_requests` is not a member and no migration adds it (`grep supabase_realtime
  supabase/migrations/` finds only the two `DROP TABLE` calls in `20260608000000`).
  `frontend/hooks/useScrapeRequestNotifications.ts:43-96` subscribes via `postgres_changes`
  only, with no polling fallback. Keeping SELECT open is still the decision, but do not
  expect a working toast to smoke-test, and do not debug the migration when none appears.
  For whoever fixes the toast later: `relreplident` is `d`, so an RLS-gated subscription may
  additionally need `REPLICA IDENTITY FULL`.

## Implementation Steps

Branch from `origin/main`. Before editing, confirm the working tree is clean against it with
`git fetch --all --prune && git status -sb && git diff --stat origin/main`. Modified `.turbo/`
files are the planning session's backlog updates; `probe_57f45121.py` and `reports/seeding/`
belong to another session and must be left alone. Nothing else in scope should differ.

1. **Migration: lock down `scrape_requests` writes, keep reads**
   - New `supabase/migrations/<timestamp>_lock_down_scrape_requests_writes.sql`, following
     `20260903120000_add_team_page_views.sql:55-82` in shape but not verbatim — this table
     keeps SELECT, so it gets no `_deny_all` policy.
   - `DROP POLICY IF EXISTS "Enable insert for all users" ON public.scrape_requests;` and the
     same for `"Enable read for authenticated users"` and `"Service role update"`. Plain
     `DROP POLICY IF EXISTS` is idempotent and the table survives, so the procedural
     `DO $$ … pg_policies … END $$;` form is not needed here.
   - `DROP POLICY IF EXISTS "scrape_requests_read_all" …` **then** `CREATE POLICY
     "scrape_requests_read_all" ON public.scrape_requests FOR SELECT TO anon, authenticated
     USING (true);` plus a `COMMENT ON POLICY` recording that queue contents are deliberately
     public. Dropping before creating is what makes a second application succeed.
   - The same drop-then-create pair for `"scrape_requests_service_role_all"` — `FOR ALL TO
     service_role USING (true) WITH CHECK (true)` — with its own `COMMENT ON POLICY`.
   - `REVOKE ALL ON public.scrape_requests FROM anon, authenticated;` then
     `GRANT SELECT ON public.scrape_requests TO anon, authenticated;`. Order matters:
     `REVOKE ALL` is what removes TRUNCATE, which RLS does not govern, and the GRANT restores
     exactly the one privilege the reader needs.
   - No `REVOKE ALL ON SEQUENCE` — there is no sequence.
   - `ALTER TABLE public.scrape_requests DROP CONSTRAINT IF EXISTS
     scrape_requests_priority_check;` then a separate `ALTER TABLE … ADD CONSTRAINT
     scrape_requests_priority_check CHECK (priority BETWEEN 1 AND 5);`.
   - Resolve the `claim_queue_items` question from Blast Radius and, if `anon` holds EXECUTE,
     revoke it here.
   - Preserve everything else about the table: do not restate its columns, its indexes
     (including `idx_scrape_requests_pending_team`), or its FK to `teams`.

2. **Migration guard test**
   - New `tests/unit/test_scrape_requests_rls_migration.py`, built on the helpers at
     `tests/unit/test_team_page_views_migration.py:33-64`. Resolve every object by name
     across all migrations, newest definition wins.
   - **The role filter must not be the whole test.** All three policies being removed are
     `TO public` — `20251113150557:28-37` writes no `TO` clause at all. An assertion that
     filters on the literal role names `anon|authenticated` is blind to the most likely
     regression, which is someone re-adding the very statement being deleted. Treat a policy
     with no `TO` clause, or an explicit `TO public`, as browser-reachable, and assert that no
     such policy grants INSERT on this table.
   - Assert the newest `GRANT … ON … scrape_requests` names `SELECT` and nothing else, and
     that a `REVOKE ALL … FROM anon, authenticated` precedes it in the same file.
   - Extract the `ADD CONSTRAINT …;` statement and assert `BETWEEN 1 AND 5` against that
     statement alone — asserting against the whole file lets the migration's own header
     comment satisfy it.
   - **Close with an allowance count, not a filename comparison.** "Scan migrations newer
     than this one" cannot be written without pinning the guard to its own filename, which
     contradicts the resolve-by-name rule above and is unknowable at plan time. Use the
     count-against-allowance pattern at `test_team_page_views_migration.py:141-157`. The
     allowance is **not 1**: `ALTER TABLE … scrape_requests` already appears in
     `20251113150557` (ENABLE RLS) and `20260520001858` (add `priority`), and step 1 adds two
     more. Count the current occurrences and set the allowance from that.
   - The allowance test must also catch a later `DROP CONSTRAINT scrape_requests_priority_check`.
     Scanning only for `GRANT` and `CREATE POLICY` leaves every assertion green while the
     database again accepts invalid priorities — resolve the constraint's effective final
     state, or fail on any later statement altering it.
   - Module docstring: state that this guard covers migration text only, and that the live ACL
     must be re-checked after any table rebuild, because `pg_default_acl` re-grants
     `arwdDxtm` on new relations.

3. **Stop the digest carrying a live credential**
   - `scripts/check_stuck_signups.py`. Delete `generate_recovery_link` at **`:155-180`** —
     the range ends at `:180` (`return LINK_FAILED`); stopping at `:179` leaves an orphaned
     `return` and a `SyntaxError`.
   - Delete the call site at `:140` and the `"action_link": action_link` field it feeds at
     `:148`.
   - Delete `LINK_FAILED` at **`:59`**.
   - `build_digest_html` spans **`:183-227`**. Remove the `Recovery` column header at
     **`:220`** and the matching row cell, and rewrite the body prose at **`:209-211`**,
     which currently instructs the reader to "Forward each the set-password link below so
     they can get in. Always use the latest alert: links from earlier alerts stop working."
     That instruction is the behaviour being removed.
   - `SITE_URL` at **`:49`** becomes unreferenced once the function is gone — ruff will not
     flag it. Remove it.
   - Update the module docstring: **`:6`** and **`:10`** both describe the link, not only the
     summary line at `:9`.
   - Simplify the dry-run block at `:302-308`; its "recovery links redacted from logs" note
     and `link_ok` reporting describe machinery that no longer exists.
   - Leave `send_alert_email` and `ALERT_EMAIL` alone. The operator digest is wanted; only the
     credential inside it is not.

4. **Update the Python tests**
   - `tests/unit/test_check_stuck_signups.py` imports `LINK_FAILED` at **`:12`**, inside the
     `from scripts.check_stuck_signups import (…)` block, and uses it at `:163`. Remove both,
     or all 17 tests in the module error at collection — not the three that name the link.
   - **Do not assert absence against the existing fixture.** That fixture's link contains
     `/auth/callback` and neither `token_hash` nor `/auth/confirm`, so assertions phrased as
     "the digest contains no `token_hash`" and "no `/auth/confirm`" pass against the
     *unchanged* renderer — verified by executing them. Use a credential-bearing fixture and
     assert that its specific value and its anchor are both absent from the rendered digest.
   - Add positive assertions that the stuck account still appears in the digest, so the tests
     distinguish "the link is gone" from "the row is gone".
   - Assert that `find_stuck_users` never calls `auth.admin.generate_link`. Removing only the
     rendered column would leave token generation — and the invalidation of the customer's
     earlier checkout link that minting a new one causes — undetected.

5. **Close IMP-168 in this PR**
   - Set `- **Status**: done` with a `- **Refs**:` naming this PR, then run
     `python scripts/sweep_improvements.py` so it moves to the archive rather than
     hand-editing either file.
   - IMP-091 stays open until step 3 ships, then closes the same way. Its `Why` is accurate
     and must not be rewritten.
   - `scripts/sweep_improvements.py` exits 1 when a `done` entry lacks `Refs` (`:210`,
     `:228-231`) **even though it still archives**, so a non-zero exit here is not
     necessarily a failure — read the output.

## Verification

- `python -m pytest tests/unit/test_scrape_requests_rls_migration.py tests/unit/test_check_stuck_signups.py tests/unit/test_improvements_backlog.py -q`
- **Prove each guard can fail.** In a scratch copy, mutate and confirm the test reddens:
  delete the `REVOKE ALL` line; change `BETWEEN 1 AND 5` to `BETWEEN 0 AND 9`; append
  `DROP CONSTRAINT scrape_requests_priority_check`; re-add an INSERT policy **with no `TO`
  clause** (the shape being deleted, and the one a role-name filter misses). A guard that
  survives deleting its own fix is the failure mode this repo keeps hitting.
- **After applying the migration**, confirm from the database, not the run log:
  - `SELECT relacl FROM pg_class WHERE relname='scrape_requests';` — `anon` and
    `authenticated` read `r/postgres`, not `arwdDxtm`.
  - `SELECT policyname, cmd, roles FROM pg_policies WHERE tablename='scrape_requests';` —
    the three prose-named policies gone, the two new ones present.
  - An anon-key `POST /rest/v1/scrape_requests` is refused; an anon-key
    `GET /rest/v1/scrape_requests?select=id&limit=1` still succeeds.
  - An anon-key insert with `priority: 1` is refused specifically, not just any insert.
- Run the stuck-signup job with its dry-run flag and read the rendered digest: it names the
  stuck accounts and contains no link. Confirm from the log that no `generate_link` call was
  made.
- Do **not** smoke-test the missing-game toast as evidence this change is safe — it does not
  work today for unrelated reasons (see Blast Radius) and its absence proves nothing.
- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` plus the rest
  of the `ci.yml` gate.
- The migration is hand-applied, so repair the ledger:
  `supabase migration repair --status applied <version>`.

## Context Files

- `supabase/migrations/20260903120000_add_team_page_views.sql` — the lockdown template, including the drop-before-create that makes re-application safe.
- `supabase/migrations/20251113150557_add_scrape_requests.sql` — the three policies being replaced; note none carries a `TO` clause.
- `supabase/migrations/20260902210000_allow_confirm_in_team_state_audit.sql` — the CHECK-constraint template.
- `tests/unit/test_team_page_views_migration.py` — the guard-test helpers and the allowance-count closing pattern.
- `scripts/check_stuck_signups.py` — the file step 3 edits.
- `tests/unit/test_check_stuck_signups.py` — the module-scope import at `:12` that dictates step 4's first bullet.
- `frontend/app/api/stripe/webhook/route.ts:397-421` — why the customer already has a working link, and the token_hash-over-PKCE reasoning.
