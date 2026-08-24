---
type: shell
status: done
spec: .turbo/specs/infra-hardening-q2.md
depends_on: []
---

# Plan: API Auth Hardening

<!-- Expanded from: .turbo/specs/infra-hardening-q2.md -->

## Context

PitchRank's middleware excludes all `/api` paths, so every API route must self-enforce authentication. An audit revealed three routes with missing or insufficient auth: `/api/chat` (admin feature with zero auth), `/api/game-explainability/[teamId]` (premium Glicko data with zero auth), and `/api/reports/team-card` (public but should track authenticated users). This shell adds the correct auth guard to each route, following the gate-only pattern for routes that use service-role Supabase clients.

## Pattern Survey

### Analogous Features

**Routes using `requireAdmin` (20 routes; 5 sampled):**

| Route | Guard placement | Client usage | Notes |
|-------|----------------|--------------|-------|
| `app/api/announcements/route.ts` (POST) | First line inside try | `auth.supabase` (user-scoped) | GET is intentionally public |
| `app/api/agent-status/route.ts` (GET) | First line inside try | `auth.supabase` | Destructures `{ supabase }` |
| `app/api/create-team/route.ts` (POST) | First line inside try | `createServiceSupabase()` separately | **Gate-only pattern** |
| `app/api/team-merge/route.ts` (POST, DELETE, GET) | First line inside try per method | `createServiceSupabase()` | All 3 methods guarded separately |
| `app/api/analytics/traffic/route.ts` (GET) | First line, outside try-catch | No supabase client | Guard is only auth check |

Universal 2-line idiom: `const auth = await requireAdmin(); if (auth.error) return auth.error;`

**Routes using `requirePremium` (6 routes; 5 sampled):**

| Route | Guard placement | Client usage | Notes |
|-------|----------------|--------------|-------|
| `app/api/match-prediction/route.ts` (POST) | After rate limit and body parse | `auth.supabase` | Rate limit runs first (cheap reject) |
| `app/api/insights/[teamId]/route.ts` (GET) | First inside try | `auth.supabase` | Destructures `{ supabase }` |
| `app/api/watchlist/route.ts` (GET) | First inside try | `auth.supabase` | Destructures `{ user, supabase }` |
| `app/api/watchlist/add/route.ts` (POST) | First inside try | `auth.supabase` | Destructures `{ user, supabase }` |
| `app/api/watchlist/init/route.ts` (POST) | First inside try | `auth.supabase` | Destructures `{ user, supabase }` |

Same 2-line idiom. Exception: `match-prediction` runs rate limiting before auth as optimization.

**Routes using `optionalAuth` (2 routes):**

| Route | Guard placement | Client usage | Notes |
|-------|----------------|--------------|-------|
| `app/api/stripe/sync/route.ts` (POST) | First inside try, no error check | Branches on `if (user && supabase)` | Falls back to `getSupabaseAdmin()` |
| `app/api/stripe/checkout/route.ts` (POST) | First inside try, no error check | Branches on `if (user && supabase)` | Anonymous checkout supported |

Convention: `const { user, supabase } = await optionalAuth();` — never has `.error`.

### Reusable Utilities

| Module | Path | Return type |
|--------|------|-------------|
| `requireAdmin` | `frontend/lib/supabase/admin.ts:14` | `{ user, supabase, error: null }` or `{ ..., error: NextResponse }` |
| `requirePremium` | `frontend/lib/api/requirePremium.ts:15` | Same discriminated union |
| `optionalAuth` | `frontend/lib/api/optionalAuth.ts:13` | `{ user: ... \| null, supabase: ... \| null }` (never errors) |
| `createServiceSupabase` | `frontend/lib/supabase/service.ts:9` | `SupabaseClient` (bypasses RLS) |

### Convention Anchors

- **Import style**: All routes use `@/` alias. `requireAdmin` from `@/lib/supabase/admin`, others from `@/lib/api/*`.
- **Error response format**: `NextResponse.json({ error: '<message>' }, { status: <code> })` — consistent `error` key.
- **Handler structure**: auth guard → input validation → data operations → response. Rate limiting precedes auth when present (cheap reject first).
- **Gate-only pattern**: `requireAdmin`/`requirePremium` for identity check, then `createServiceSupabase()` for data. Guard's `.supabase` is discarded.

## Implementation Steps

1. **Add `requireAdmin` to `/api/chat` GET handler**
   - Open `frontend/app/api/chat/route.ts:8` (the `GET` function)
   - Add import: `import { requireAdmin } from '@/lib/supabase/admin'`
   - Insert at line 10 (first line inside try block, before `createServerSupabase()`):
     ```typescript
     const auth = await requireAdmin();
     if (auth.error) return auth.error;
     ```
   - Replace the manual `createServerSupabase()` call at line 10 with `const supabase = auth.supabase;` — the guard already provides a user-scoped client. Note: `mission_chat` has no RLS, so the swap from `createServerSupabase()` to `auth.supabase` is behavior-neutral
   - Remove the `createServerSupabase` import (will be unused after both handlers are updated)

2. **Add `requireAdmin` to `/api/chat` POST handler**
   - In the same file at `frontend/app/api/chat/route.ts:37` (the `POST` function)
   - Insert at line 39 (first line inside try block, before `createServerSupabase()`):
     ```typescript
     const auth = await requireAdmin();
     if (auth.error) return auth.error;
     ```
   - Replace the manual `createServerSupabase()` call at line 39 with `const supabase = auth.supabase;`
   - Verify the `createServerSupabase` import from `@/lib/supabase/server` can now be removed (no remaining usages in this file)

3. **Add `requirePremium` to `/api/game-explainability/[teamId]` POST handler (gate-only)**
   - Open `frontend/app/api/game-explainability/[teamId]/route.ts:31` (the `POST` function)
   - Add import: `import { requirePremium } from '@/lib/api/requirePremium'`
   - Insert at line 33 (first line inside try block, before `teamId` destructuring):
     ```typescript
     const auth = await requirePremium();
     if (auth.error) return auth.error;
     ```
   - **Keep** `createServiceSupabase()` at line 37 (now ~39 after insertion) — do NOT replace with `auth.supabase`. The `game_explainability` table has no RLS policy; a user-scoped client would return zero rows
   - The `auth` variable is used only for the gate check; `auth.supabase` is intentionally discarded

4. **Update game-explainability tests to mock `requirePremium`**
   - Open `frontend/app/api/game-explainability/[teamId]/__tests__/route.test.ts`
   - Add a mock for `@/lib/api/requirePremium` alongside the existing `@/lib/supabase/service` mock:
     ```typescript
     vi.mock('@/lib/api/requirePremium', () => ({
       requirePremium: vi.fn().mockResolvedValue({
         user: { id: 'test-user-id', email: 'test@example.com' },
         supabase: {},
         error: null,
       }),
     }));
     ```
   - Add a test case verifying that an unauthenticated request returns 401:
     ```typescript
     it('returns 401 when requirePremium fails', async () => {
       const { requirePremium } = await import('@/lib/api/requirePremium');
       vi.mocked(requirePremium).mockResolvedValueOnce({
         user: null, supabase: null,
         error: NextResponse.json({ error: 'Not authenticated' }, { status: 401 }),
       });
       const response = await POST(makeRequest({ gameIds: [GAME_ID] }), {
         params: Promise.resolve({ teamId: TEAM_ID }),
       });
       expect(response.status).toBe(401);
     });
     ```
   - Run `cd C:/PitchRank/frontend && npx vitest run app/api/game-explainability` to confirm tests pass

5. **Add `optionalAuth` to `/api/reports/team-card` POST handler**
   - Open `frontend/app/api/reports/team-card/route.ts:13` (the `POST` function)
   - Add import: `import { optionalAuth } from '@/lib/api/optionalAuth'`
   - Insert after the rate-limit if-block's closing brace (after line 18) and before body parsing (line 20):
     ```typescript
     await optionalAuth();
     ```
   - No error check — `optionalAuth` never errors
   - No destructuring needed — the `report_card_leads` table has no `user_id` column (confirmed in migration `20260329000000_create_report_card_leads.sql`), so do NOT add `user_id` to the insert payload. Call `optionalAuth()` without destructuring to avoid an unused-variable ESLint error. The guard establishes the auth plumbing so tracking can be added in a future migration without another deploy
   - Keep the existing `createServerSupabase()` call at line 32 — this route's queries work without auth

6. **Run TypeScript and lint checks**
   - Run `cd C:/PitchRank/frontend && npx tsc --noEmit` to verify all imports resolve and types are correct
   - Run `cd C:/PitchRank/frontend && npm run lint` to catch unused variables and import issues
   - Confirm zero errors from both checks

## Verification

- **Chat admin guard**: `curl -X GET /api/chat` without auth cookie → 401 `{"error":"Not authenticated"}`
- **Chat admin guard**: `curl -X POST /api/chat` without auth cookie → 401
- **Chat admin guard**: authenticated admin user → 200 with messages (verify in Mission Control UI)
- **Game-explainability premium guard**: `curl -X POST /api/game-explainability/<teamId>` without auth → 401
- **Game-explainability premium guard**: authenticated premium user → 200 with breakdowns (verify in team detail UI)
- **Game-explainability gate-only**: confirm data is returned (service client bypasses RLS) — an empty response would indicate the client was accidentally switched to user-scoped
- **Reports/team-card optional auth**: unauthenticated request → 201 (still works, public access preserved)
- **Reports/team-card optional auth**: authenticated request → 201 (optionalAuth provides user context)
- **TypeScript**: `cd C:/PitchRank/frontend && npx tsc --noEmit` exits 0
- **ESLint**: `cd C:/PitchRank/frontend && npm run lint` exits 0 — catches unused variables from auth guard destructuring that `tsc` alone misses
- **Tests**: `cd C:/PitchRank/frontend && npx vitest run app/api/game-explainability` — all existing tests pass, new 401 test passes
- **Deployment**: All changes must ship in a single commit. Rollback: revert the commit

## Context Files

- `frontend/app/api/chat/route.ts` — target route, needs `requireAdmin` on both GET and POST
- `frontend/app/api/game-explainability/[teamId]/route.ts` — target route, needs `requirePremium` gate-only
- `frontend/app/api/reports/team-card/route.ts` — target route, needs `optionalAuth`
- `frontend/lib/supabase/admin.ts` — `requireAdmin` guard implementation and return type
- `frontend/lib/api/requirePremium.ts` — `requirePremium` guard implementation and return type
- `frontend/lib/api/optionalAuth.ts` — `optionalAuth` guard implementation and return type
- `frontend/app/api/create-team/route.ts` — reference for gate-only pattern (requireAdmin + createServiceSupabase)
- `frontend/app/api/announcements/route.ts` — reference for mixed public GET / admin POST pattern
- `frontend/app/api/stripe/checkout/route.ts` — reference for optionalAuth usage pattern
