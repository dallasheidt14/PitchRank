# Infra Hardening Q2

Three infrastructure improvements to harden PitchRank's API security, rate limiting, and payment reliability.

## 1. API Auth Hardening

### Problem

`frontend/middleware.ts:139` excludes all `/api` paths via negative lookahead in the matcher:

```
matcher: ['/((?!_next/static|_next/image|favicon.ico|logos|api|auth/callback).*)']
```

Every API route must self-enforce auth. Two routes have gaps:

| Route | Issue |
|-------|-------|
| `/api/chat` | Zero auth — public read/write to mission chat messages |
| `/api/game-explainability/[teamId]` | Zero auth — exposes Glicko rating/sigma data via service-role client |

### Auth Guards Available

Four guards exist at different locations:

| Guard | File | Behavior |
|-------|------|----------|
| `requireAdmin` | `frontend/lib/supabase/admin.ts` | 403 if plan !== 'admin' |
| `requirePremium` | `frontend/lib/api/requirePremium.ts` | 403 if plan not in ['premium', 'admin'] |
| `requireAuth` | `frontend/lib/api/requireAuth.ts` | 401 if not authenticated (any plan) |
| `optionalAuth` | `frontend/lib/api/optionalAuth.ts` | Returns null user if not authenticated (no error) |

### Current Route Auth Inventory

**Admin-protected (requireAdmin):** agent-activity, agent-status, analytics/funnel, analytics/search-console, analytics/traffic, announcements (POST only), create-team, instagram-review, link-opponent, link-opponent/preview, scrape-missing-game, team-aliases/[teamId], team-merge, team-merge/list, team-merge/suggestions

**Premium-protected (requirePremium):** insights/[teamId], match-prediction, watchlist, watchlist/add, watchlist/init, watchlist/remove

**Auth-protected (requireAuth):** notifications/preferences, notifications/subscribe, stripe/portal

**Optional auth (optionalAuth):** stripe/checkout, stripe/sync

**Custom auth:** agent-webhook (Bearer token via AGENT_WEBHOOK_SECRET), process-missing-games (CRON_SECRET), stripe/webhook (Stripe signature verification)

**Intentionally public:** rankings/national, rankings/state, teams/search, announcements (GET), newsletter

**Unprotected (needs fixing):** chat, game-explainability/[teamId], reports/team-card

### Changes Required

| Route | Action | Guard | Rationale |
|-------|--------|-------|-----------|
| `/api/chat` | Add guard | `requireAdmin` | Mission chat is admin-only feature |
| `/api/game-explainability/[teamId]` | Add guard | `requirePremium` | Rating/sigma data is premium content |
| `/api/reports/team-card` | Add guard | `optionalAuth` | Public access OK but track authenticated users |

**game-explainability dual-client pattern:** This route uses `createServiceSupabase()` (bypasses RLS). Adding `requirePremium()` creates a second user-scoped client via `createServerSupabase()` internally. The correct pattern is **gate-only**: keep `createServiceSupabase()` for data access, use `requirePremium()` purely as an access gate. Do not switch to user-scoped client — no RLS policy exists for `game_explainability` table, so it would return zero rows.

### Verification

After adding guards:
- `curl -X POST /api/chat` without auth → 401
- `curl -X POST /api/game-explainability/[teamId]` without auth → 401
- `curl -X POST /api/game-explainability/[teamId]` with premium auth → 200
- Existing admin/premium routes continue to work
- Run `tsc --noEmit` to catch import errors

### Known Limitations

- **No feature-flag rollback**: If Supabase auth has an outage, newly-guarded routes become inaccessible. Acceptable risk — chat is admin-only and game-explainability is premium-only, neither is critical-path.
- **Middleware still excludes /api**: This spec hardens route-level guards only. Middleware-level API protection is a larger architectural change deferred to a future spec.

---

## 2. Rate Limiter Replacement

### Problem

`frontend/lib/api/rateLimit.ts` uses an in-memory `Map<string, { count: number; resetAt: number }>` for rate limiting. On Vercel serverless, each cold start gets a fresh Map — rate limits are effectively unenforced in production.

Current signature:
```typescript
function checkRateLimit(ip: string, maxRequests = 5, windowMs = 60000): boolean
```

Three consumers:

| Route | Call | Limits |
|-------|------|--------|
| `/api/match-prediction` | `checkRateLimit(ip, 10, 60_000)` | 10 req/60s |
| `/api/reports/team-card` | `checkRateLimit(ip, 3, 60000)` | 3 req/60s |
| `/api/newsletter` | `checkRateLimit(ip)` | 5 req/60s (defaults) |

### Solution

Replace with `@upstash/ratelimit` backed by Upstash Redis (Vercel Marketplace integration).

**New signature (breaking change — sync → async):**

```typescript
async function checkRateLimit(ip: string, namespace: string, maxRequests = 5, windowSec = 60): Promise<boolean>
```

Key changes:
- **Returns `Promise<boolean>`** instead of `boolean` — all 3 consumers must add `await`
- **New `namespace` parameter** — each route gets its own rate limit bucket (e.g., `"match-prediction"`, `"team-card"`, `"newsletter"`)
- **Window unit changes** from milliseconds to seconds (Upstash convention)
- **Algorithm**: Sliding window (more accurate than fixed window)

### Consumer Updates

All 3 call sites need two changes: add `await` and add namespace.

| Route | Before | After |
|-------|--------|-------|
| match-prediction:19 | `checkRateLimit(ip, 10, 60_000)` | `await checkRateLimit(ip, "match-prediction", 10, 60)` |
| reports/team-card:16 | `checkRateLimit(ip, 3, 60000)` | `await checkRateLimit(ip, "team-card", 3, 60)` |
| newsletter:9 | `checkRateLimit(ip)` | `await checkRateLimit(ip, "newsletter")` |

### Graceful Degradation

If `UPSTASH_REDIS_REST_URL` is unset:
- **In production** (detected via `process.env.VERCEL` truthy): log at `console.error` level and **allow the request** (fail-open). Do not fall back to in-memory — that's the broken state we're replacing.
- **In development** (no `VERCEL` env var): fall back to in-memory Map with `console.warn`. This preserves local dev experience without requiring Redis setup.

### Infrastructure Setup

1. Provision Upstash Redis via Vercel Marketplace (auto-sets `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`)
2. Add `@upstash/ratelimit` and `@upstash/redis` to `frontend/package.json`
3. No database migration needed

### Verification

- Deploy to preview, hit rate-limited endpoint repeatedly → 429 after limit
- Verify rate limit persists across multiple serverless invocations (not reset by cold start)
- Verify local dev works without Upstash credentials (in-memory fallback)
- Verify production logs error if env vars are missing
- Run `tsc --noEmit` — async signature change must compile cleanly

---

## 3. Stripe Reverse-Sync

### Problem

If the `checkout.session.completed` webhook fails after Stripe creates the customer but before the DB profile is updated, an orphan is created: the customer pays in Stripe but has no `stripe_customer_id` in `user_profiles`. The existing reconciliation script (`scripts/reconcile_stripe_subscriptions.py:66`) only queries users with non-null `stripe_customer_id`:

```python
.not_.is_("stripe_customer_id", "null")
```

These orphans are invisible to reconciliation.

### Failure Scenarios

Orphans can be created faster than initially expected. The webhook handler's `isPermanentError()` function (`frontend/app/api/stripe/webhook/route.ts:14-21`) returns HTTP 200 (stopping Stripe retries) for `"already exists"` errors. If the first attempt partially creates an auth user but fails on the profile update, the retry hits "already exists" and stops. **Orphans can be created after 1-2 webhook attempts, not days.**

```typescript
function isPermanentError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    msg.includes('No user profile found for Stripe customer') ||
    msg.includes('already been registered') ||
    msg.includes('already exists')
  );
}
```

### Solution

Add a reverse-sync script that queries Stripe for all active customers and checks for missing DB links.

**Logic:**

1. **Fetch all active Stripe subscriptions** using cursor-based pagination (`starting_after` parameter, 100 per page)
2. **For each subscription**, extract `customer.id` and `customer.email`
3. **Batch-query `user_profiles`** for matching `stripe_customer_id` values (use `.range()` for batches of 1000 to avoid Supabase API limits)
4. **Identify orphans**: Stripe customers with active subscriptions whose `customer.id` does not appear in any `user_profiles.stripe_customer_id`
5. **Auto-link by email**: If a `user_profiles` row exists with matching email but null `stripe_customer_id`, link it automatically
6. **Alert on remaining orphans**: Send email via Resend to `ALERT_EMAIL` (default: `pitchrankio@gmail.com`)

### Integration

- **New script**: `scripts/reverse_sync_stripe.py`
- **GitHub Actions workflow**: `reconcile-stripe-reverse-sync.yml`, runs daily (less frequent than forward-sync's 6-hour cycle)
- **Relationship to forward-sync**: Reverse-sync runs after forward-sync. A race condition where forward-sync fixes an orphan mid-run could produce a false-positive alert — this is acceptable for an alert-only v1 and noted as a known limitation.

### Alert Fallback

If Resend email delivery fails:
1. **Fail the GitHub Actions step** (exit code 1) so the workflow shows red in the Actions dashboard
2. Log orphan details to stdout (captured in workflow logs)

### Pagination Mechanics

**Stripe API**: Use `stripe.Subscription.list(status="active", limit=100, starting_after=last_sub_id)`. Loop until `has_more` is false.

**Supabase batch queries**: Use `.in_("stripe_customer_id", batch)` with `.range(0, 999)` for batches of 1000 customer IDs. Iterate if more than 1000 Stripe customers exist.

### Verification

- Run with `--dry-run` flag → outputs orphans without linking or emailing
- Manually create a test orphan (Stripe customer with no DB link) → script detects it
- Verify email sends via Resend test mode
- Verify GitHub Actions workflow completes successfully

### Known Limitations

- **Race condition with forward-sync**: Forward-sync may fix an orphan during reverse-sync's run, producing a false-positive alert. Acceptable for v1.
- **Email-only alerting**: If Resend is down, orphans are detected but notification relies on GitHub Actions failure status. No secondary notification channel in v1.

---

## Implementation Order

1. **API Auth Hardening** — security fix, smallest scope, no new dependencies
2. **Rate Limiter Replacement** — requires Upstash provisioning, async signature migration
3. **Stripe Reverse-Sync** — new script + workflow, can be developed independently

Items 1 and 2 both touch frontend API infrastructure. The auth audit (item 1) should complete first since its findings (e.g., whether rate-limited routes also need auth) may affect item 2's implementation. Item 3 is fully independent.

## Open Questions

None — all review findings from the prior session have been resolved inline:
- Auth guard import paths corrected (P1)
- Async signature change documented with consumer updates (P1)
- game-explainability gate-only pattern specified (P1)
- isPermanentError orphan timing corrected (P1)
- Production detection for missing env vars specified (P2)
- Pagination mechanics specified (P2)
- Alert fallback specified (P2)
- Known limitations documented (P3s)
