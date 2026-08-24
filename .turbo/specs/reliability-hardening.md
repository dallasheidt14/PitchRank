# Reliability Hardening

Harden PitchRank across three independent surfaces: close auth gaps in API routes, replace the ineffective in-memory rate limiter with a serverless-compatible store, and add a reverse-sync to detect orphaned Stripe customers.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth strategy | Per-route enforcement | Lower risk than modifying middleware matcher; each route declares its own auth requirement explicitly |
| `/api/chat` auth | `requireAdmin()` | Admin-only internal chat feature |
| `/api/game-explainability/[teamId]` auth | `requirePremium()` | Premium tooltip feature visible to subscribers |
| Rate limiter backend | Upstash Redis via Vercel Marketplace | Zero-config provisioning, `@upstash/ratelimit` has native sliding window, generous free tier covers current traffic |
| Stripe reverse-sync behavior | Alert-only (v1) | Log orphans and send email via Resend; manual investigation. No auto-linking or auto-creation. |
| ML training fix | Deferred | Skipped from this session per user decision |

## 1. API Auth Hardening

### Problem

`frontend/middleware.ts` excludes all `/api` paths from auth middleware via its matcher pattern. This pushes auth responsibility entirely to route handlers. A full audit of ~41 API routes found 2 unprotected routes that should have auth enforcement:

| Route | Methods | Current Auth | Required Auth | Risk |
|-------|---------|-------------|---------------|------|
| `/api/chat` | GET, POST | None | `requireAdmin()` | Anyone can read/write mission_chat table |
| `/api/game-explainability/[teamId]` | POST | None | `requirePremium()` | Anyone can trigger computation and read team data |

All other routes are properly protected (~31 protected, ~8 intentionally public).

### Auth Patterns in Use

The codebase has established auth guard functions in two locations:

- **`requireAdmin()`** (`frontend/lib/supabase/admin.ts`) — Checks Supabase auth + admin role. Returns 401/403 on failure. Used by ~20 routes.
- **`requirePremium()`** (`frontend/lib/api/requirePremium.ts`) — Checks subscription status. Returns `{ user, supabase, error }`. Used by ~6 routes (insights, match-prediction, watchlist/*).
- **`requireAuth()`** (`frontend/lib/api/requireAuth.ts`) — Basic logged-in check. Used by ~3 routes (notifications/*, stripe/portal).
- **`optionalAuth()`** (`frontend/lib/api/optionalAuth.ts`) — Allows anonymous + authenticated. Used by 2 Stripe routes.

### Changes Required

**`frontend/app/api/chat/route.ts`**
- Import `requireAdmin` from `@/lib/supabase/admin`
- Add `requireAdmin()` check at the top of both GET and POST handlers
- Return 401/403 on auth failure (matching existing pattern in other admin routes)
- Use the supabase client returned from `requireAdmin()` (`auth.supabase`) for subsequent DB queries. Remove the standalone `createServerSupabase()` call — `requireAdmin()` already creates an identical server client internally.

**`frontend/app/api/game-explainability/[teamId]/route.ts`**
- Import `requirePremium` from `@/lib/api/requirePremium`
- Add `requirePremium()` check at the top of the POST handler
- Return 401/403 on auth failure (use `auth.error` early return)
- **Gate-only pattern:** Keep the existing `createServiceSupabase()` call for DB queries. Use `requirePremium()` solely as an auth gate — discard its returned `supabase` client. This differs from the match-prediction pattern (which uses the returned client) because the game-explainability table may not have RLS policies granting premium user access.

### Verification

- Confirm both routes reject unauthenticated requests (401)
- Confirm `/api/chat` rejects non-admin authenticated users (403)
- Confirm `/api/game-explainability/[teamId]` rejects non-premium users (403)
- Confirm all ~8 intentionally public routes still work without auth (webhooks, rankings, search, newsletter)

## 2. Rate Limiter Replacement

### Problem

`frontend/lib/api/rateLimit.ts` uses an in-memory `Map<string, { count: number; resetAt: number }>` for rate limiting. On Vercel's serverless platform, each function invocation gets a fresh Node.js process, making the Map ineffective — rate limits reset on every cold start.

### Current API Surface

```typescript
export function checkRateLimit(ip: string, maxRequests = 5, windowMs = 60000): boolean
```

Returns `true` if allowed, `false` if rate-limited. **Note:** The replacement will change this to `async` returning `Promise<boolean>` — see Solution section. Three consumers:

| Route | Limit | Window | Purpose |
|-------|-------|--------|---------|
| `/api/newsletter` | 5 req | 60s | Public signup spam prevention |
| `/api/match-prediction` | 10 req | 60s | Premium feature, lenient |
| `/api/reports/team-card` | 3 req | 60s | Heavy computation (PDF gen), strictest |

All routes extract IP from `x-forwarded-for` header with fallback to `'unknown'`.

### Solution: Upstash Redis via Vercel Marketplace

**New dependencies:**
- `@upstash/redis` — Redis client optimized for serverless (HTTP-based, no persistent connections)
- `@upstash/ratelimit` — Sliding window rate limiter built on `@upstash/redis`

**Provisioning:**
- Add Upstash Redis via Vercel Marketplace integration
- Environment variables `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` auto-provisioned by Vercel

**New `rateLimit.ts` implementation:**
- Replace the `Map` with `@upstash/ratelimit` using a sliding window algorithm
- **Signature change:** `async function checkRateLimit(ip, maxRequests, windowMs)` returns `Promise<boolean>`. The `@upstash/ratelimit` `limit()` method is async (HTTP call to Redis).
- All 3 consuming routes are already `async` functions — they only need `await` added before `checkRateLimit()` calls
- Create a single Redis client instance (module-level, reused across invocations within the same process)
- **Namespace isolation:** Lazily create and cache `Ratelimit` instances keyed by the `(maxRequests, windowMs)` tuple. Each instance must set a unique `prefix` (e.g., `ratelimit:${maxRequests}:${windowMs}`) to avoid cross-route key collision — the `@upstash/ratelimit` default prefix is shared across all instances, so without explicit prefixes, a request from the same IP on different routes would read/write the same Redis key. Use IP as the rate limit identifier.
- **Fail-open on Redis errors:** Wrap the `limit()` call in a try/catch. If the Upstash HTTP call fails (network timeout, Upstash outage), return `true` (allow the request). Rate limiters should fail-open — blocking all users because Redis is down is worse than temporarily allowing excess requests.
- **Test update required:** `frontend/app/api/match-prediction/__tests__/route.test.ts` mocks `checkRateLimit` with synchronous `mockReturnValue()`. After the async change, update to `mockResolvedValue(true)` / `mockResolvedValue(false)`. Without this, the 429 rate-limit test assertion will fail.

**Graceful degradation:**
- If `UPSTASH_REDIS_REST_URL` is not set **and** `VERCEL` env var is not set (local dev only), fall back to the current in-memory Map. Log a warning on first fallback.
- If `UPSTASH_REDIS_REST_URL` is not set **but** `VERCEL` env var is set (production), log at **error** level on every request. This prevents silently running without rate limiting in production due to a misconfigured environment.

### Verification

- Confirm rate limiting persists across multiple serverless invocations (not just within one process)
- Confirm each route's limits are respected (3, 5, 10 per minute)
- Confirm all 3 consuming routes correctly `await` the new async `checkRateLimit()`
- Confirm local development works without Upstash configured (in-memory fallback)
- Confirm production without `UPSTASH_REDIS_REST_URL` logs at error level (not silent fallback)
- Confirm no regressions in the 3 consuming routes

## 3. Stripe Reverse-Sync for Orphaned Customers

### Problem

`scripts/reconcile_stripe_subscriptions.py` runs every 6 hours and only performs forward-sync: it queries `user_profiles` rows WHERE `stripe_customer_id IS NOT NULL` and compares against Stripe. If a webhook fails during anonymous checkout (e.g., Supabase is down when creating the user), the customer pays in Stripe but has no `stripe_customer_id` in the DB. These orphans are invisible to the current reconciliation.

### Failure Scenarios

**Scenario A — Partial creation, self-healing retry (most common):**
```
1. Anonymous user completes Stripe checkout
2. Stripe fires checkout.session.completed webhook
3. handleCheckoutCompleted() calls auth.admin.createUser() → succeeds (auth user created)
4. handle_new_user trigger inserts user_profiles row with (id, email) — no stripe fields yet
5. Profile .update() with stripe fields fails (DB timeout, constraint error)
6. Webhook handler throws → returns 500
7. Stripe retries → existingProfile lookup by stripe_customer_id returns NULL (update never set it)
8. profileByEmail lookup FINDS the trigger-created row by email
9. Takes "existing user — link" branch (line 164) → updates profile successfully → returns 200
```
This scenario **self-heals** on retry. The `isPermanentError("already been registered")` path is never reached because `createUser()` is not called again — the retry finds the profile by email and takes the link branch. Orphans from this path are unlikely unless the retry also fails (e.g., sustained DB outage across all retries).

**Scenario B — Full Supabase outage (slower, up to ~3 days):**
```
1. Anonymous user completes Stripe checkout
2. Stripe fires checkout.session.completed webhook
3. handleCheckoutCompleted() calls auth.admin.createUser() → Supabase unavailable → throws
4. Webhook returns 500 on every retry
5. Stripe retries for up to ~3 days, then gives up
6. Result: no auth user, no user_profiles row, active Stripe subscription
```

### Solution: Reverse-Sync Script (Alert-Only v1)

**New script:** `scripts/reverse_sync_stripe_orphans.py`

**Flow:**
1. Paginate through ALL active Stripe subscriptions via `stripe.Subscription.list(status='active', limit=100)` using cursor-based pagination (`starting_after` parameter set to the last subscription ID of each page)
2. Also include `status='trialing'` and `status='past_due'` (customers who should have DB records) — three separate paginated queries
3. Collect all unique `customer` IDs from subscriptions. **Deduplicate across all three status queries before proceeding** — a single customer can have subscriptions in different statuses simultaneously. Track the set of subscription statuses per customer for the alert email.
4. Batch-query `user_profiles` for matching `stripe_customer_id` values. Use `.in('stripe_customer_id', batch)` with batches of ~200 IDs to stay within PostgREST URL length limits. (The `.range()` pagination from the forward-sync's 1000-row issue does not apply here since we're filtering by specific IDs, not scanning the full table.)
5. Identify orphans: Stripe customers with active subscriptions but no matching DB row
6. For each orphan, fetch customer email from Stripe
7. Cross-reference email against `user_profiles.email` to distinguish:
   - **Email match found**: User exists but `stripe_customer_id` not linked (partial failure)
   - **No email match**: User never created in DB (full failure)
8. Send alert email via Resend with orphan details (customer ID, email, subscription status, failure type)
9. Log all findings to stdout for GitHub Actions summary

**Rate limiting:**
- 0.1s sleep between Stripe API calls (matching existing reconciliation pattern)
- Batch DB queries to minimize Supabase round-trips

**CLI interface:**
- `--dry-run`: Report findings without sending alerts
- `--verbose`: Detailed logging

### Integration with Existing Workflow

Add reverse-sync as a step in `.github/workflows/reconcile-stripe-daily.yml` after the forward-sync step. Same schedule (every 6 hours), same secrets. Reverse-sync runs independently — forward-sync failure doesn't block it.

### Data Model

No schema changes required. The reverse-sync only reads from `user_profiles` and Stripe API. Alert-only means no writes to the database.

**Columns queried:**
- `user_profiles.stripe_customer_id` — primary lookup
- `user_profiles.email` — secondary lookup for orphan classification

### Verification

- Confirm the script paginates through all Stripe subscriptions (not just first page)
- Confirm orphan detection works for both failure types (email match vs no match)
- Confirm email alerts are sent with actionable information
- Confirm dry-run mode produces output without side effects
- Confirm the script integrates into the existing GitHub Actions workflow

## Execution Order and Dependencies

```
1. Auth Hardening (standalone, no dependencies)
   └── 2 route files, ~10 lines each

2. Rate Limiter Replacement (standalone, requires Upstash provisioning)
   └── 1 library file + verify 3 consumers
   └── Provisioning: Vercel Marketplace → Upstash Redis

3. Stripe Reverse-Sync (standalone, no dependencies)
   └── 1 new script + workflow update
```

Items 1 and 2 both touch frontend API infrastructure but don't conflict. Item 3 is entirely independent (backend script). All three can be implemented in parallel or in any order.

## Open Questions

None — all decisions resolved during discussion and review:
- Auth guard import paths: resolved (correct paths documented per guard)
- game-explainability RLS: resolved (gate-only pattern, keep service client)
- Rate limiter async signature: resolved (async with await, consumer updates documented)
- Production fallback behavior: resolved (error-level logging when VERCEL is set without Upstash)
