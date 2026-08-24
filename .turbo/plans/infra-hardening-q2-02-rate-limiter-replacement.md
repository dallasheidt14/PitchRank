---
type: shell
status: draft
spec: .turbo/specs/infra-hardening-q2.md
depends_on: [infra-hardening-q2-01-api-auth-hardening]
---

# Plan: Rate Limiter Replacement

## Context

PitchRank's rate limiter uses an in-memory Map that resets on every Vercel serverless cold start, making it effectively unenforced in production. Three routes rely on it: match-prediction, reports/team-card, and newsletter. This shell replaces the in-memory implementation with `@upstash/ratelimit` backed by Upstash Redis, migrates all consumers to the new async signature, and adds graceful degradation that distinguishes production from development environments.

This shell depends on Shell 01 (API Auth Hardening) because the auth audit determines whether rate-limited routes also need auth changes. Shell 01's addition of `optionalAuth` to `/api/reports/team-card` means this shell's consumer update for that route must account for the auth guard already being present.

## Produces

- Rewritten `rateLimit.ts` module using `@upstash/ratelimit` with sliding window algorithm
- Async `checkRateLimit()` function with namespace parameter
- Graceful degradation: production fail-open with error logging, development in-memory fallback
- Updated consumer call sites in 3 routes (async + namespace)
- Package dependencies: `@upstash/ratelimit`, `@upstash/redis`

## Consumes

- Auth-guarded `/api/reports/team-card` route — from Shell 01 (optionalAuth already added)
- Existing rate limiter module — from existing codebase (`frontend/lib/api/rateLimit.ts`)
- Existing consumer routes — from existing codebase (match-prediction, reports/team-card, newsletter)
- Upstash Redis credentials — provisioned via Vercel Marketplace (manual step, not code)

## Covers Spec Requirements

- Spec §2: Rate Limiter Replacement — Problem (replace in-memory Map)
- Spec §2: Rate Limiter Replacement — Solution (Upstash Redis, async signature, namespace)
- Spec §2: Rate Limiter Replacement — Consumer Updates (all 3 routes)
- Spec §2: Rate Limiter Replacement — Graceful Degradation (production vs development)
- Spec §2: Rate Limiter Replacement — Infrastructure Setup (package additions + Upstash Redis provisioning prerequisite)
- Spec §2: Rate Limiter Replacement — Verification

## Implementation Steps (High-Level)

1. **Add Upstash dependencies**
   - Install `@upstash/ratelimit` and `@upstash/redis` in frontend package

2. **Rewrite rateLimit.ts**
   - Replace in-memory Map with `@upstash/ratelimit` sliding window
   - New signature: `async function checkRateLimit(ip, namespace, maxRequests?, windowSec?): Promise<boolean>`
   - Add environment detection: production fail-open with `console.error`, development in-memory fallback with `console.warn`

3. **Update match-prediction consumer**
   - Change `checkRateLimit(ip, 10, 60_000)` to `await checkRateLimit(ip, "match-prediction", 10, 60)`

4. **Update reports/team-card consumer**
   - Change `checkRateLimit(ip, 3, 60000)` to `await checkRateLimit(ip, "team-card", 3, 60)`

5. **Update newsletter consumer**
   - Change `checkRateLimit(ip)` to `await checkRateLimit(ip, "newsletter")`

6. **Run TypeScript compilation check**
   - Run `tsc --noEmit` to verify async changes compile cleanly

7. **Verify rate limiting behavior**
   - Test that rate limits are enforced and persist across cold starts (preview deployment)
   - Test local dev fallback without Upstash credentials
   - Test production error logging when env vars are missing

## Open Questions

None

## Expansion Deferred

The following are filled in when `/expand-plan-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path:line_number` references for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
