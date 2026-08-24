---
type: plan
status: draft
---

# Plan: Quick-Wins Batch (April 2026)

## Context

Four independent, small-scope improvements pulled from `.turbo/improvements.md` during the April 2026 backlog triage. Each stands alone — the batch groups them to reduce planning overhead, not because they share implementation. All four were validated against the current codebase as active (described problem still present).

Ordered by blast radius, smallest first:
1. TEAM_COLORS dedup (pure Python refactor, one import line)
2. Client-side premium gate on `useGameExplainability` (frontend-only, one caller)
3. `user_id` column on `report_card_leads` (Supabase migration + route wire-up, deploy-ordering matters)
4. Stripe reverse-sync for orphaned customers (new script + GH Actions workflow, report-only — no writes)

Product decisions resolved during planning:
- Item 1 hook stays auth-agnostic; `isPremium` is derived in the caller (`GameHistoryTable.tsx`), matching the strong `frontend/lib/hooks.ts` convention.
- Item 2 gets no per-user SELECT RLS — service-role-only reads, matching existing `newsletter_subscribers` / `report_card_leads` patterns. Defer until a "My Reports" UI is scoped.
- Item 4 is **report-only** (log + Resend alert; zero writes). No auto-backfill of `stripe_customer_id`, no `auth.admin.createUser`. Cron daily at 06:00 UTC.
- Item 3 scoped to the two files in the task description; 2 additional `TEAM_COLORS` duplicates in `scripts/` are left for a future pass.

## Pattern Survey

### Analogous Features

**1. Client-side premium gate for useGameExplainability**
- `C:\PitchRank\frontend\app\watchlist\page.tsx:56-80` — Derives `isPremium = hasPremiumAccess(profile)` from `useUser()` inside the component and passes `enabled: !userLoading && isPremium && !!user` to `useQuery`. Exact gating shape the hook could mirror (note: also guards on `!userLoading` to avoid flicker).
- `C:\PitchRank\frontend\components\TeamInsightsCard.tsx:42-76` — Premium-gated feature uses `useUser()` + `hasPremiumAccess(profile)` internally; early-returns `if (!isPremium) return;` in the fetch callback and also guards `useEffect(...)` on `isPremium && teamId`.
- `C:\PitchRank\frontend\components\TeamHeader.tsx:62,120,145,180,205` — Same `const isPremium = !userLoading && hasPremiumAccess(profile);` idiom; multiple effects gated on `isPremium`.
- `C:\PitchRank\frontend\components\NotificationBell.tsx:17,28,39,118` — Component-level `const isPremium = !userLoading && hasPremiumAccess(profile);` pattern.
- `C:\PitchRank\frontend\hooks\useWatchlistMigration.ts:33` — Hook that accepts `profile` as an arg and calls `hasPremiumAccess(profile)` internally — existing precedent for **hook takes profile/params, not a derived boolean prop**.
- `C:\PitchRank\frontend\components\GameBreakdownPanel.tsx:12` and `C:\PitchRank\frontend\components\GameBreakdownPanel.test.tsx:71,89` — Downstream consumer of explainability already has an `isPremium: boolean` prop on its interface (currently unused in render body but tested with true/false).
- `C:\PitchRank\frontend\components\GameHistoryTable.tsx:10,178` — Current single caller of `useGameExplainability`; passes `highlightedGameIds.length > 0` as the 3rd `enabled` arg. Does not currently compute `isPremium`.
- `C:\PitchRank\frontend\lib\hooks.ts:89-101` — Existing signature already accepts `enabled: boolean` from the caller; other hooks in the same file (`useTeam`, `useTeamTrajectory`, `useTeamGames`, `useRankHistory`, `useCommonOpponents`) use `enabled: !!id` style — **none of them read context/premium internally**.

**2. user_id column + RLS on report_card_leads**
- `C:\PitchRank\supabase\migrations\20260408020000_create_match_prediction_shadow_log.sql:4` — `user_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL` — closest analog to a nullable lead-capture FK (also allows anonymous rows).
- `C:\PitchRank\supabase\migrations\20260206000002_add_notification_system.sql:11,22,32-42` — `user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE` with per-user RLS policies `auth.uid() = user_id`, an index `idx_push_subscriptions_user ON push_subscriptions(user_id)`, and explicit `GRANT ... TO authenticated`.
- `C:\PitchRank\supabase\migrations\20260329000000_create_report_card_leads.sql` — Current RLS on `report_card_leads` is **insert-only for anon** (`CREATE POLICY "Allow anonymous inserts" ON report_card_leads FOR INSERT TO anon WITH CHECK (true);`); no SELECT policy exists (service-role-only reads).
- `C:\PitchRank\supabase\migrations\20250204000000_create_newsletter_subscribers.sql` — Precedent for a lead-capture table *without* a `user_id` FK (only `email`); uses "Allow public inserts" for `anon, authenticated` and an authenticated-reads policy.
- `C:\PitchRank\frontend\app\api\reports\team-card\route.ts:21,178-191` — Route already calls `await optionalAuth()` but **discards the return value**; insert payload at line 180-187 has no `user_id` field.
- `C:\PitchRank\frontend\app\api\stripe\checkout\route.ts:19` and `C:\PitchRank\frontend\app\api\stripe\sync\route.ts:19` — Canonical `optionalAuth()` destructure: `const { user, supabase } = await optionalAuth();` then attach `user?.id` to downstream records.
- Last 5 migration filenames (sorted alphabetically, which is how Supabase runs them):
  - `C:\PitchRank\supabase\migrations\20260408000000_create_prediction_feature_history.sql`
  - `C:\PitchRank\supabase\migrations\20260408010000_add_prediction_evidence_fields.sql`
  - `C:\PitchRank\supabase\migrations\20260408020000_create_match_prediction_shadow_log.sql`
  - `C:\PitchRank\supabase\migrations\20260410000000_create_prospective_match_predictions.sql`
  - `C:\PitchRank\supabase\migrations\20260411000000_create_game_explainability.sql`
- Standing `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` precedents: `C:\PitchRank\supabase\migrations\20260220000000_add_game_exclusion.sql:4`, `C:\PitchRank\supabase\migrations\20260402000000_add_league_column.sql:2`, `C:\PitchRank\supabase\migrations\20260404000000_add_rank_in_cohort_final.sql:4`, `C:\PitchRank\supabase\migrations\20260404000002_add_rank_final_to_history.sql:2`.

**3. TEAM_COLORS dedup**
- `C:\PitchRank\src\models\game_matcher.py:61-78` — 16-color `set` (mutable). Used at lines 282, 322, 352.
- `C:\PitchRank\src\utils\team_name_utils.py:28-50` — 19-color `frozenset` (superset: adds `royal`, `crimson`, `teal`). Used at lines 458, 494, 524, 592.
- `C:\PitchRank\scripts\find_queue_matches.py:172,211,442` — Third copy of TEAM_COLORS (`set`) in scripts layer, referenced alongside `TEAM_DIRECTIONS`. **Out of scope** for this plan.
- `C:\PitchRank\scripts\find_fuzzy_duplicate_teams.py:44,299` — Fourth copy (`frozenset`). **Out of scope**.
- Mutation check: `grep TEAM_COLORS\.(add|remove|update|discard)` across the entire repo returns **no matches** — none of the call sites mutate the set.
- `royal`/`crimson`/`teal` only appear inside the `frozenset` definition at `C:\PitchRank\src\utils\team_name_utils.py:46-48` — not referenced elsewhere as standalone tokens, so converting `game_matcher.py` to the superset is a no-op in practice.

**4. Reverse-sync orphan Stripe customers**
- `C:\PitchRank\scripts\reconcile_stripe_subscriptions.py` — Full forward-sync script (DB→Stripe reconciliation). Argparse single flag `--dry-run` (store_true, default live/apply mode, exits 1 on dry-run-with-mismatches, exits 2 on missing env). Logger is `logging.getLogger(__name__)` with `level=INFO, format="%(message)s"`. Supabase via `supabase.create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)` (falls back to `SUPABASE_SERVICE_ROLE_KEY`). Stripe via `stripe.api_key = STRIPE_SECRET_KEY`. Resend alert email via HTTP POST.
- `C:\PitchRank\.github\workflows\reconcile-stripe-daily.yml` — Cron `0 */6 * * *` (every 6 hours despite filename "daily"), `workflow_dispatch` with `dry_run` choice input, exports `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`, `RESEND_API_KEY`; Python 3.11 + `pip install -r requirements.txt`.
- `C:\PitchRank\dashboard.py:1580-1615` — Existing precedent for **orphan detection**: reads `user_profiles` + `db.auth.admin.list_users()`, computes `orphan_ids = auth_ids - profile_ids`, surfaces as "auth user(s) missing from user_profiles". This is the existing "orphan" terminology in the codebase.
- `C:\PitchRank\frontend\app\api\stripe\webhook\route.ts:158-221` — Canonical "Stripe customer → Supabase user" linking flow: looks up existing profile by email with `.from('user_profiles').select('id, stripe_customer_id').eq('email', email).maybeSingle()`. For the report-only reverse-sync this is the **lookup** pattern we mirror; the full createUser/link flow is **intentionally not replicated** — operators fix manually after review.
- No existing test file for `reconcile_stripe_subscriptions.py` (`grep reconcile_stripe` in `tests/` → no files). New script follows precedent: ships without tests.
- No existing script uses `stripe.customers.list` / `stripe.Customer.list` — the forward script only calls `stripe.Subscription.list(customer=customer_id, limit=1)`. Reverse-sync adds this new usage.

### Reusable Utilities

- `C:\PitchRank\frontend\hooks\useUser.ts:25-28` — `hasPremiumAccess(profile: UserProfile | null): boolean` — returns true for `'premium' | 'admin'`. Canonical premium predicate.
- `C:\PitchRank\frontend\hooks\useUser.ts:48` — `useUser()` — hook exposing `{ user, profile, session, isLoading, error, signOut, refreshUser }`. `UserProfile.plan: 'free' | 'premium' | 'admin'` at line 11. No React Context provider — plain hook re-invoked per component.
- `C:\PitchRank\frontend\lib\api\optionalAuth.ts:13` — `optionalAuth()` — returns `{ user, supabase }` or `{ null, null }`; already imported at `C:\PitchRank\frontend\app\api\reports\team-card\route.ts:4` but destructured discard at line 21. Drop-in for wiring `user?.id` into the lead insert.
- `C:\PitchRank\src\utils\team_name_utils.py:28-50` — `TEAM_COLORS` `frozenset` — already the superset; `from src.utils.team_name_utils import TEAM_COLORS` is the import direction consistent with existing code.
- `C:\PitchRank\scripts\reconcile_stripe_subscriptions.py:48-56` — `stripe_status_to_plan(status)` — status→plan mapping, reusable by the reverse-sync script.
- `C:\PitchRank\scripts\reconcile_stripe_subscriptions.py:186-246` — `send_alert_email(mismatches, dry_run)` — reference for the Resend HTTP POST shape but **is not called** by the reverse-sync script (its `m['before']`/`m['after']` dict shape would raise `KeyError` on the orphan payload). Define a parallel `send_orphan_alert_email` with a bespoke HTML body that reuses only the transport (ALERT_EMAIL + FROM_EMAIL constants, Authorization header, 10s timeout, response-code check).

### Convention Anchors

- **Hook gating style (hooks.ts)**: Hooks in `C:\PitchRank\frontend\lib\hooks.ts` are auth-agnostic — callers pass `enabled: boolean`. Premium derivation lives in the **component**. `useGameExplainability` already follows this; the change is in the caller (`GameHistoryTable.tsx`), not the hook.
- **Premium derivation pattern**: `const { profile, isLoading: userLoading } = useUser(); const isPremium = hasPremiumAccess(profile);` — used verbatim in ≥4 components. Guard on `!userLoading` when correctness during initial render matters.
- **Migration filename format**: `YYYYMMDDHHMMSS_verb_noun.sql`, 14-digit UTC timestamp prefix. Column adds use verb `add_<col>_to_<table>`; table creates use `create_<table>`.
- **Migration idempotency**: Column adds consistently use `ALTER TABLE <t> ADD COLUMN IF NOT EXISTS <col>`.
- **auth.users FK policy**: Optional/audit-log rows that should survive user deletion use `NULL REFERENCES auth.users(id) ON DELETE SET NULL` (`match_prediction_shadow_log`). Lead-capture semantics match this.
- **Index naming**: Short `idx_<table_abbrev>_<col>` style already in use for `report_card_leads` (`idx_rcl_email`, `idx_rcl_team`). Follow with `idx_rcl_user_id`.
- **API route auth wiring**: `optionalAuth()` is the correct tool for routes that accept anonymous traffic but want to attach `user?.id` when present. Destructure `const { user } = await optionalAuth();` and pass `user?.id ?? null` into inserts.
- **Python cross-module imports in `src/`**: `src/models/game_matcher.py:26-48` already imports from `src/utils/` — extend the existing import block. Pattern is a `try/except ImportError` with a flag for graceful degradation.
- **Python script CLI conventions**: `argparse --dry-run` as `action="store_true"`, **default is live/apply mode**; `logging.basicConfig(level=INFO, format="%(message)s")`; `dotenv` with `.env.local` override preference; `sys.path.append(str(Path(__file__).parent.parent))`; `sys.exit(2)` for missing env, `sys.exit(1)` for findings in dry-run, `sys.exit(0)` for clean.
- **Stripe/Supabase env vars**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (preferred) with fallback to `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`, `RESEND_API_KEY`, `ALERT_EMAIL`. Supabase client: `from supabase import create_client`.
- **GH Actions workflow shape**: `runs-on: ubuntu-latest`, `timeout-minutes: 15`, `actions/checkout@v5` + `actions/setup-python@v6` with `python-version: '3.11'` and `cache: 'pip'`, explicit "Verify secrets" step before run, `workflow_dispatch` with `dry_run` choice input.

### Proposed Alignment

1. **Item 1** — Caller-derives pattern. `GameHistoryTable.tsx` calls `useUser() + hasPremiumAccess(profile)` and folds `isPremium` into the `enabled` boolean already passed to `useGameExplainability`. Hook signature unchanged.
2. **Item 2** — Mirror `match_prediction_shadow_log` column shape (`NULL ... ON DELETE SET NULL`) with idempotent `ADD COLUMN IF NOT EXISTS`. Index `idx_rcl_user_id`. **No new RLS policy.** Route destructures the already-discarded `optionalAuth()` return and adds `user_id: user?.id ?? null` to the insert payload.
3. **Item 3** — Extend `src/models/game_matcher.py`'s existing `src.utils.team_name_utils` import to include `TEAM_COLORS`; delete the local 16-color set literal. Superset is safe (no mutation, no conflicting tokens).
4. **Item 4** — New script `scripts/reverse_sync_stripe_orphans.py` next to `reconcile_stripe_subscriptions.py`. Report-only: iterate `stripe.Subscription.list(status='all').auto_paging_iter()` (bounded by active-subscription count, not total customer count), filter to `status in ('active', 'trialing', 'past_due')` mirroring `stripe_status_to_plan`, resolve each sub's customer, and look up `user_profiles` by normalized email → flag customers whose qualifying subscription exists but whose `user_profiles.stripe_customer_id` is null, mismatched, or whose email maps to multiple profiles. Reuse `stripe_status_to_plan` and define a bespoke `send_orphan_alert_email`. Default `--dry-run` emits report only; without `--dry-run` still writes nothing (live mode = send Resend alert). Clone `.github/workflows/reconcile-stripe-daily.yml` → `reverse-sync-stripe.yml` with cron `30 6 * * *` (offset from forward reconcile to avoid Stripe rate-limit contention).

## Implementation Steps

1. **Item 3 — TEAM_COLORS dedup** (smallest, lowest risk)
   - Open `C:/PitchRank/src/models/game_matcher.py` and extend the existing `try: from src.utils.team_name_utils import ...` block at lines 38-52 to include `TEAM_COLORS`.
   - **Add a graceful-degradation fallback** in the `except ImportError` branch: `TEAM_COLORS = frozenset()`. This preserves the existing `HAVE_TEAM_NAME_UTILS = False` degradation pattern — if the utils module fails to import, the color-token checks at lines 282/322/352 become no-ops rather than raising `NameError`.
   - Delete the local `TEAM_COLORS = {...}` set literal at `src/models/game_matcher.py:61-78`.
   - Verify the three call sites at `game_matcher.py:282, 322, 352` still work — they perform membership checks (`token in TEAM_COLORS`), which behave identically for `frozenset`.
   - No callers mutate `TEAM_COLORS` (repo-wide grep for `.add(`/`.remove(`/`.discard(` on `TEAM_COLORS` returns zero matches).

2. **Item 1 — Client-side premium gate** (frontend-only)
   - In `C:/PitchRank/frontend/components/GameHistoryTable.tsx:10` area, import `useUser` from `@/hooks/useUser` and `hasPremiumAccess` (same module).
   - Inside `GameHistoryTable`, add `const { profile, isLoading: userLoading } = useUser(); const isPremium = !userLoading && hasPremiumAccess(profile);` near existing state.
   - At `GameHistoryTable.tsx:178`, fold `isPremium` into the 3rd argument passed to `useGameExplainability` — i.e. change `highlightedGameIds.length > 0` to `isPremium && highlightedGameIds.length > 0` (exact expression depends on current shape; preserve existing condition as an AND).
   - Leave `frontend/lib/hooks.ts:89-101` (`useGameExplainability`) unchanged — it already accepts `enabled: boolean`, and the auth-agnostic convention is intact.
   - Context: the entire team detail page is premium-gated upstream (free users cannot reach `GameHistoryTable`), so this gate is a pure performance optimization against admin-tier or edge paths, not a free-tier leak defense. `GameBreakdownPanel` declares an `isPremium` prop at line 12 but does not destructure it in the body (line 32) — it is a dead prop, no gating to double.

3. **Item 2a — Supabase migration** (apply before route change)
   - Create `C:/PitchRank/supabase/migrations/<YYYYMMDDHHMMSS>_add_user_id_to_report_card_leads.sql` where `<YYYYMMDDHHMMSS>` is the **current UTC timestamp down to the minute** (e.g., `20260416143200`), not midnight. Must sort after the existing `20260411000000_*` migration. Avoid using `00:00:00` as the HHMMSS suffix — recent migrations cluster at midnight UTC, and a same-day collision is possible.
   - Content mirrors `match_prediction_shadow_log`:
     - `ALTER TABLE report_card_leads ADD COLUMN IF NOT EXISTS user_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL;`
     - `CREATE INDEX IF NOT EXISTS idx_rcl_user_id ON report_card_leads(user_id);`
   - **Do not** add SELECT RLS policy (product decision). Existing insert-only anon policy remains.
   - Confirm migration naming matches the `add_<col>_to_<table>` convention.

4. **Item 2b — Route wire-up** (apply after migration)
   - Open `C:/PitchRank/frontend/app/api/reports/team-card/route.ts`.
   - Replace `await optionalAuth();` at `route.ts:21` with `const { user } = await optionalAuth();`. **Do not destructure `supabase`** — the route creates its own `supabase` client at `route.ts:35` via `createServerSupabase()`, and destructuring would shadow / collide.
   - Immediately after that, capture `const userId = user?.id ?? null;` so the value is resolved synchronously before the non-awaited insert callback runs.
   - **Preserve the existing non-awaited fire-and-forget insert pattern** at `route.ts:178-191` (`supabase.from(...).insert([...]).then(...)`). Add `user_id: userId` to the insert payload object inside lines 180-187. Do **not** convert the `.then()` callback to `await` — that would serialize the insert against PDF generation/email and regress latency.
   - No other behavior changes — the route still accepts anonymous submissions.

5. **Item 4a — Reverse-sync script**
   - Before writing the new script, re-verify that these reference points still live at their cited locations in `scripts/reconcile_stripe_subscriptions.py` (treat symbols as anchors, line numbers as hints): `stripe_status_to_plan` (near lines 48-56), `time.sleep(0.1)` inside `check_stripe_subscription` (near line 116), `send_alert_email` definition (near lines 186-246). If any drifted, adjust the mirrored code — do not blindly copy a line range.
   - Create `C:/PitchRank/scripts/reverse_sync_stripe_orphans.py`.
   - Copy the module-level setup block from `scripts/reconcile_stripe_subscriptions.py` verbatim: dotenv loading, env var reads (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY` with `SUPABASE_SERVICE_ROLE_KEY` fallback, `STRIPE_SECRET_KEY`, `RESEND_API_KEY`, `ALERT_EMAIL`), logger setup, `sys.path.append`, `stripe.api_key = ...`, `create_client(...)`.
   - Import `stripe_status_to_plan` from `reconcile_stripe_subscriptions`. **Do not import `send_alert_email`** — its dict shape expects `m['before']`/`m['after']` which the orphan payload does not have and would raise `KeyError`. Define a bespoke `send_orphan_alert_email(orphans: list, dry_run: bool, db_lookup_errors: int, stripe_errors: int, skipped_no_email: int, run_truncated_at: int | None) -> bool`:
     - **Returns**: `True` on successful dispatch (HTTP 200 from Resend), or `True` immediately in dry-run (dispatch-skipped counts as success for exit-code purposes). Returns `False` on non-200 response, Resend exception, or missing `RESEND_API_KEY`. Do **not** swallow non-200 silently as the forward script does at `reconcile_stripe_subscriptions.py:245-246` — log the status code / response body at `ERROR` level and return `False` so the caller can set a non-zero exit.
     - **Subject line**: `f"{'[DRY RUN] ' if dry_run else ''}PitchRank: {len(orphans)} Stripe orphan(s) detected"` — mirrors the `[DRY RUN]` prefix convention at `reconcile_stripe_subscriptions.py:193`.
     - **HTML body shape**: a single table with columns `Classification | Email | Stripe Customer ID | Subscription ID | Status | Created`, rows sorted by classification then `created_at desc`. Below the table, a counter summary block: `Skipped (no email): N`, `DB lookup errors: M`, `Stripe errors: P`, `Run truncated: yes/no at sub K`. If `run_truncated_at is not None`, render a prominent "⚠️ RUN TRUNCATED AT SUBSCRIPTION {n}" banner above the table.
     - **Zero-orphan dispatch rule**: if `len(orphans) == 0` **and** `db_lookup_errors == 0` **and** `stripe_errors == 0` **and** `skipped_no_email == 0` **and** `run_truncated_at is None`, skip dispatch entirely in live mode (all-clear run = no email, no stale-inbox noise). Any non-zero counter still sends the email so operators see the error signal.
     - **Transport reuse**: reuse the forward script's Resend constants + HTTP shape — `ALERT_EMAIL` + `FROM_EMAIL`, Authorization header, 10s timeout, explicit 200 check. Only the dispatch-success contract (`bool` return, error-level logging on failure) deviates.
   - Main loop (subscription-first, bounded by active-sub count, not full customer universe):
     - Iterate `for current_sub_index, sub in enumerate(stripe.Subscription.list(status='all', limit=100).auto_paging_iter()):` — maintains a running index so the outer broad-except handler below can set `run_truncated_at = current_sub_index` without a `NameError`. `status='all'` returns all subscriptions; filter in Python to `sub.status in ('active', 'trialing', 'past_due')` to mirror `stripe_status_to_plan` at `reconcile_stripe_subscriptions.py:54`. Skipping `status='active'` alone would miss `trialing` — the most common real-world orphan class (abandoned email verification).
     - Trade-off note: `status='all'` + Python filter keeps iteration single-pass; at the cost of paging through `canceled` / `incomplete` / `incomplete_expired` / `unpaid` / `paused` subs. If the Stripe account accumulates a large `canceled` backlog (e.g., >10K), consider replacing with three targeted `stripe.Subscription.list(status='active' | 'trialing' | 'past_due')` calls and chaining the iterators. Current volume is fine.
     - For each included subscription, resolve the customer via `sub.customer` (a string id) and call `stripe.Customer.retrieve(sub.customer)` to fetch the email. Add `time.sleep(0.1)` between Stripe API calls to respect the 100 req/s shared rate limit, mirroring `reconcile_stripe_subscriptions.py:116`.
     - Wrap per-subscription Stripe calls (`stripe.Customer.retrieve`, any nested Stripe lookups) in `try/except stripe.error.InvalidRequestError` and `except stripe.error.StripeError`. On error (e.g., customer deleted mid-run), increment a `stripe_errors` counter, log `WARN` with the customer/subscription id, and `continue` the loop.
     - Wrap the Supabase lookups (`.ilike(...)` and the `.eq('stripe_customer_id', ...)` fallback below) in their own per-iteration `try/except` that catches `httpx.RequestError`, `postgrest.exceptions.APIError`, and a broad `Exception` fallback. On error (connection blip, PostgREST restart, row timeout), increment a `db_lookup_errors` counter, log `WARN` with the subscription id and error, and `continue` the loop.
     - Wrap the outer iteration in a broad `try/except Exception` that catches anything still unhandled (e.g., Stripe pagination errors, unexpected SDK state). On catch: set `run_truncated_at = current_sub_index`, log the exception with full traceback, and fall through to `send_orphan_alert_email` with the partial `orphans` list and counters. **Exit non-zero regardless of live/dry-run mode** when `run_truncated_at is not None` — truncation is a signal operators must see.
     - If the customer has no email, increment a `skipped_no_email` counter and continue. The summary must include: `"Skipped: {skipped_no_email} (no email), DB lookup errors: {db_lookup_errors}, Stripe errors: {stripe_errors}, Run truncated: {'yes at sub ' + str(run_truncated_at) if run_truncated_at is not None else 'no'}"` — surfaces blind spots the operator would otherwise miss.
     - Look up `user_profiles` by normalized email: `supabase.table('user_profiles').select('id, stripe_customer_id').ilike('email', email.strip()).limit(2).execute()`. Using `ilike` + `.strip()` absorbs case/whitespace drift between Stripe's verbatim email and Supabase's normalized form.
     - Inspect `len(response.data)`:
       - `0` rows → fallback: `supabase.table('user_profiles').select('id, stripe_customer_id').eq('stripe_customer_id', sub.customer).limit(2).execute()`. (`stripe_customer_id` is an opaque Stripe-generated identifier written verbatim by the webhook — no case/whitespace normalization needed; `.eq()` is correct.) Inspect `len(response.data)` the same three-way way:
         - `0` rows → classify `NO_USER_PROFILE`.
         - `1` row → classify `MISSING_LINK` / `MISMATCHED_LINK` / `OK` per the link-state logic below. Reaching this branch means email didn't match — set an extra `email_mismatch: true` field on the output row so operators see the profile was linked by customer_id but the Stripe and Supabase emails differ.
         - `2`+ rows → classify `DUPLICATE_PROFILES` (reuse existing bucket; `profile_ids` captures the duplicate set).
       - `1` row → proceed to the link-state logic below.
       - `2`+ rows → classify `DUPLICATE_PROFILES`, include all matching profile ids in the report. Rare; surfaced for manual cleanup.
     - For the single-row case, classify:
       - `MISSING_LINK` — `stripe_customer_id` is null on the matched profile.
       - `MISMATCHED_LINK` — `stripe_customer_id` is set but different from `sub.customer`.
       - `OK` — matches (skip).
     - Append non-OK rows to an `orphans` list with `(stripe_customer_id, email, subscription_id, status, created_at, classification, profile_ids)`.
   - CLI: argparse `--dry-run` matching the forward script's convention (`action="store_true"`, default = live mode). "Live mode" means "send Resend alert" — **no DB or Stripe writes** in any mode.
   - Exit codes (the caller inspects `send_orphan_alert_email`'s bool return + `run_truncated_at`):
     - `0` in live mode when dispatch succeeded (HTTP 200 from Resend), no orphans, no errors, no truncation. Also `0` when the all-clear dispatch-skip rule applied (zero orphans, zero counters, zero truncation).
     - `1` in live mode when Resend dispatch failed (non-200, Resend exception, or missing `RESEND_API_KEY`).
     - `1` in live mode when `run_truncated_at is not None`, regardless of dispatch outcome.
     - `1` in live mode when `db_lookup_errors > 0` or `stripe_errors > 0` (surfaces silent partial-run failures; otherwise dry-run and live mode would treat error counters asymmetrically).
     - `0` in dry-run when no orphans and no errors and no truncation.
     - `1` in dry-run when orphans are found or `db_lookup_errors > 0` or `stripe_errors > 0` or `run_truncated_at is not None` (surfaces findings and partial-run signals to local runs).
     - `2` on missing required env (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STRIPE_SECRET_KEY`).
     - Rationale: live mode treats "dispatch succeeded" (HTTP 200 from Resend) as success, not "alert sent" in the aspirational sense. This keeps cron green on healthy clean runs and surfaces both orphans-found-but-dispatch-failed and iteration-truncated as non-zero exits the operator can react to.
   - Report output: log summary by classification (count per bucket + `skipped_no_email` + `db_lookup_errors` + `stripe_errors` + `run_truncated_at`), print top N rows, and in live mode POST to Resend via `send_orphan_alert_email` (subject to the zero-orphan dispatch-skip rule above).
   - **No writes** to Stripe or Supabase. No `auth.admin.createUser`. Operators fix manually.

6. **Item 4b — GH Actions workflow**
   - Create `C:/PitchRank/.github/workflows/reverse-sync-stripe.yml` by cloning `.github/workflows/reconcile-stripe-daily.yml`.
   - Change the `name:`, job name, cron schedule to `30 6 * * *` (daily 06:30 UTC — offset 30 minutes from the forward reconcile's `0 */6 * * *` cadence, which runs at 00/06/12/18:00 UTC, to avoid concurrent Stripe rate-limit contention on the 06:00 slot), and the `python` command to invoke `scripts/reverse_sync_stripe_orphans.py`.
   - Clone the env block from `reconcile-stripe-daily.yml` verbatim (SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_SERVICE_ROLE_KEY, STRIPE_SECRET_KEY, RESEND_API_KEY, PYTHONUNBUFFERED). The template does **not** include `ALERT_EMAIL` — the script reads it via `os.environ.get('ALERT_EMAIL', 'pitchrankio@gmail.com')` default, which is sufficient. Add an explicit `ALERT_EMAIL: ${{ secrets.ALERT_EMAIL }}` entry only if overriding the default.
   - Keep the `workflow_dispatch` + `dry_run` choice input verbatim.
   - Keep `runs-on`, `timeout-minutes`, `actions/checkout@v5`, `actions/setup-python@v6` versions verbatim.
   - Note on `timeout-minutes: 15` (inherited from forward reconcile): reverse-sync runtime scales as ~2 Stripe API calls × 0.1s sleep × N qualifying subs. At current PitchRank volume this fits comfortably. If qualifying-sub count approaches ~5K (~17 min), raise this workflow's `timeout-minutes` to 30; at ~9K consider switching to batched iteration or async. No immediate change.

## Verification

**Item 3 — TEAM_COLORS dedup**
- `python -c "from src.models.game_matcher import TEAM_COLORS; print(len(TEAM_COLORS))"` returns `19` (not `16`), confirming the superset import is live.
- Run `pytest tests/ -k "game_matcher or team_name"` — should pass unchanged. No existing test failures introduced.
- `grep -rn "TEAM_COLORS = " C:/PitchRank/src/` returns a single definition (`src/utils/team_name_utils.py`), not two.

**Item 1 — Premium gate**
- `cd frontend && npx tsc --noEmit` passes.
- Run existing tests: `cd frontend && pnpm test -- GameHistoryTable` — exist test expectations should still pass. If `GameBreakdownPanel.test.tsx` has premium cases, they still pass.
- Manual smoke (dev server): log in as free-tier user, load a team page with game history — Network tab should show **zero** `/api/game-explainability/*` requests. Log in as premium user on same team — request fires and returns 200.

**Item 2 — user_id column + route**
- Migration: `cd C:/PitchRank && supabase db reset` (local) or apply via the project's standard migration runner. Then `psql -c "\d report_card_leads"` (or Supabase Studio) shows `user_id` column present.
- Route: submit the team-card lead form while **unauthenticated** — row inserts with `user_id IS NULL`. Submit while **authenticated** — `optionalAuth()` reads the request cookies and resolves the current `user.id`; the route attaches that value as a literal column in the insert payload. The insert uses the service-role Supabase client and bypasses RLS, so `auth.uid()` in the DB session is irrelevant — the binding is application-level.
- `cd frontend && npx tsc --noEmit` passes.
- Verify no existing insert-flow tests break: `cd frontend && pnpm test -- team-card`.

**Item 4 — Reverse-sync**
- `python scripts/reverse_sync_stripe_orphans.py --dry-run` in local env with `.env.local` populated — runs to completion, emits classification summary to stdout, exits 0 (no orphans) or 1 (orphans found). No Resend email sent in dry-run.
- `python scripts/reverse_sync_stripe_orphans.py` (live mode) with no orphans — exits 0, no alert email.
- Seed a test orphan (manually null a `stripe_customer_id` in a test project) — dry-run reports it; live mode sends Resend alert; no DB or Stripe writes.
- GH Actions: trigger the new workflow manually via `workflow_dispatch` with `dry_run=true` — green run; check logs for summary output.
- Note: the cloned workflow's checkout step uses `ref: main` (verbatim from `reconcile-stripe-daily.yml:36`). For a branch-only dry-run via `workflow_dispatch`, either merge the workflow file to `main` first, or temporarily drop the `ref: main` line on the feature branch so the action checks out the current ref.

**Deploy ordering reminder**
- Item 2a migration must be deployed/applied before Item 2b route code ships. If PR splits are used, land migration first. Rollback: revert the route code change only. **Leave the migration applied** — the `user_id` column is nullable with `ON DELETE SET NULL`, so it is backwards-compatible with the pre-change insert payload (which omits `user_id`). Do not drop the column as part of a rollback.

## Context Files

- `C:/PitchRank/CLAUDE.md` — Repo-wide conventions (test runners, Python/TS versions, Supabase tooling).
- `C:/PitchRank/frontend/CLAUDE.md` — Frontend conventions (hooks placement, API route auth helpers, vitest colocation).
- `C:/PitchRank/frontend/lib/hooks.ts` — Hook file the change does **not** modify; read to confirm the auth-agnostic convention before touching the caller.
- `C:/PitchRank/frontend/components/GameHistoryTable.tsx` — The one caller of `useGameExplainability`; the edit target for Item 1.
- `C:/PitchRank/frontend/hooks/useUser.ts` — Source of `useUser()` and `hasPremiumAccess()`; confirm signatures before importing.
- `C:/PitchRank/frontend/app/api/reports/team-card/route.ts` — Route-level edit target for Item 2b; read in full to understand the insert shape and `optionalAuth` usage.
- `C:/PitchRank/frontend/lib/api/optionalAuth.ts` — Confirms the `{ user, supabase }` destructure return shape.
- `C:/PitchRank/supabase/migrations/20260329000000_create_report_card_leads.sql` — Current table definition (indexes, RLS); read before writing the migration.
- `C:/PitchRank/supabase/migrations/20260408020000_create_match_prediction_shadow_log.sql` — Column template to mirror for Item 2a.
- `C:/PitchRank/src/models/game_matcher.py` — Edit target for Item 3; read the import block at lines 26-48 and the color-token usage at lines 282/322/352.
- `C:/PitchRank/src/utils/team_name_utils.py` — Source of the `TEAM_COLORS` frozenset import; confirm the superset contents.
- `C:/PitchRank/scripts/reconcile_stripe_subscriptions.py` — Module-level setup, CLI conventions, `stripe_status_to_plan`, and `send_alert_email` — read in full before writing the reverse-sync script.
- `C:/PitchRank/.github/workflows/reconcile-stripe-daily.yml` — Workflow template to clone for Item 4b; read to confirm action versions, env block, and input shape.
- `C:/PitchRank/frontend/app/api/stripe/webhook/route.ts` — Lines 158-221 show the canonical email-based `user_profiles` lookup to mirror in the Python reverse-sync script (lookup only; do **not** replicate the createUser/link flow).
