---
status: done
---

# Plan: Fix mobile perf — age-group rankings jank + slow homepage

## Context

A trial user canceled citing a "too laggy" UI. Live PSI median-of-3 (mobile, 2026-06-14) confirms two page-specific problems on production:

| Page (mobile) | Score | LCP | TBT | TTI |
|---|---|---|---|---|
| Homepage `/` | 66 | **9.2s** | 179ms | **9.2s** |
| `/rankings/ny/u14/male` (age group) | 72 | 3.6s | **650ms** | 8.0s |
| `/rankings/co` (state, healthy control) | 90 | 3.5s | 0ms | 3.5s |

CrUX field data is unavailable (site below traffic threshold; confirmed 2026-05-07), so PSI **lab mobile** is the only proxy — always median-of-3 (lab variance ±3–4s).

**Root causes (confirmed in code, verified against `origin/main` @ d5f9ef1c6):**

1. **Age-group page jank (650ms TBT).** The RSC page server-fetches the full cohort (`api.getRankings(..., {limit:2000})`) for SEO and discards it, then the client `RankingsTable` **re-fetches the same cohort** via `useRankings` (React Query, 1000-row batches) and runs a full-array `.sort()` on every render. The duplicate client fetch + parse + sort is the main-thread block. The table already virtualizes (`@tanstack/react-virtual`), so DOM row count is NOT the issue.
2. **Homepage slow load (9.2s LCP/TTI).** `page.tsx` is already an RSC (hero `<h1>` = LCP element), but two above-the-fold `'use client'` children sabotage it: `HomeStats` calls Supabase `get_db_stats` on mount, and `RecentMovers` client-fetches the **entire** national cohort (1000-row batches) just to show 5 movers.

**Approach decided with the user:** Age-group table = **Option A** (seed from server, keep instant client search/sort; no UX change) with progressive/server-side-search (Option B) documented as the fallback if measured TBT misses target. Homepage = server-fetch the above-the-fold data in the RSC (purely technical, no UX change). Frontend rendering only — engine/DB/rankings algorithm code is out of scope.

## Pattern Survey

All anchors verified against `origin/main` @ d5f9ef1c6. Working tree is on a stale branch (`fix/modular11-events-division-mapping`, 2026-06-03) and differs on `RankingsTable.tsx` + `Navigation.tsx` — **build on `origin/main`, not the working tree.**

### Analogous Features
- **Healthy state page = the model to mirror for the homepage:** `frontend/app/rankings/[region]/page.tsx:130` is an RSC that server-fetches a small slice (`limit: 3`), renders static HTML, mounts no client data component → TBT 0ms. The age-group page differs only by handing off to a client table that re-fetches.
- **Age-group render chain (the TBT path):** `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx:106` (RSC, fetches `allTeams` at :122-125, uses it only for SEO at :153/:215, discards) → `frontend/components/RankingsPageContent.tsx:17` (`'use client'`, passes only `{region,ageGroup,gender}`) → `frontend/components/RankingsTable.tsx` (`'use client'`, calls `useRankings` at :94, full-array sort `useMemo` at :131, filter at :180, virtualizer at :201).
- **Homepage children:** `frontend/components/HomeStats.tsx` (`'use client'`, `useEffect`→`createClientSupabase`→`rpc('get_db_stats')` at :17-49) and `frontend/components/RecentMovers.tsx` (`'use client'`, module-cache + `/api/rankings/national` batch fetch at :27-87, movers computed in `useMemo` at :185-207).

### Reusable Utilities
- `frontend/lib/api.ts` — `api.getRankings(region, age, gender, {limit})` (:67), `api.getRankingsCount` (:185), `api.getActiveRankingsCount` (:254). State path uses `rpc('get_state_rankings')`; national uses `rpc('get_national_rankings')` (rankings_view fallback). **Same RPCs the client `/api/rankings/state|national` routes use → identical shape & order → safe to seed.** `lib/api.ts` uses vanilla `createClient` and is already called from RSCs (do not change its client per `gotcha_supabase_ssr_shared_modules`).
- `frontend/components/skeletons/RankingsTableSkeleton.tsx:1` — canonical SSR-safe skeleton via `useSyncExternalStore` (no `animate-pulse` in SSR; avoids Soft 404).
- `frontend/lib/utils.ts` — `formatPowerScore`, `composeTeamDisplay`, `normalizeAgeGroup`; `frontend/types/RankingRow.ts` — shared `RankingRow` type.

### Convention Anchors
- React-Query is NOT sitewide: `SiteProviders` (`frontend/app/providers.tsx`) wraps only `TooltipProvider`; `DataProviders` (react-query) is mounted per-section (`frontend/app/rankings/layout.tsx:36`). Homepage `/` is intentionally react-query-free — keep it that way (RecentMovers already avoids react-query).
- Both rankings pages use `export const revalidate = 3600` (ISR) + `generateStaticParams`.
- SSR SEO content rendered BEFORE client components (`gotcha_ssr_content_order`); age-group page already emits server `<h1>` + intro + `sr-only` top-25 before the client table.

### Proposed Alignment
- **Problem 1:** Do NOT add virtualization (already present). Eliminate the duplicate client fetch by passing the RSC's already-fetched `allTeams` into the table as React Query `initialData`, and remove the redundant initial sort. Mirror existing `RankingRow`/`api.getRankings` contracts.
- **Problem 2:** Mirror the state-region page — server-fetch in the `Home` RSC and pass props; convert `HomeStats`/`RecentMovers` off client fetching. Keep homepage react-query-free.

## Implementation Steps

> **Setup (local-state hazard):** The working tree is on stale branch `fix/modular11-events-division-mapping` and differs on `RankingsTable.tsx`/`Navigation.tsx`. Branch from origin/main: `cd /c/PitchRank && git fetch origin && git switch -c perf/mobile-rankings-homepage origin/main`. Confirm the in-scope files match origin/main before editing (`git diff origin/main -- frontend/components/RankingsTable.tsx` is empty).

### Phase 0 — Confirm root cause (no code changes)
1. **Capture the before-state.** Re-run PSI median-of-3 mobile (see Verification) on `/`, `/rankings/ny/u14/male`, `/rankings/co` to refresh the baseline table above. In a browser DevTools Network tab on the live age-group page, confirm an `/api/rankings/state` XHR fires on load (the duplicate fetch); on `/`, confirm `get_db_stats` and `/api/rankings/national` fire. This proves the redundant-fetch root cause before changing anything.

### Phase 1 — Age-group table (Option A: seed + cheaper sort)
2. **Add `initialData` to `useRankings`** (`frontend/hooks/useRankings.ts:111`). Add an optional 4th param `initialData?: RankingRow[]`. Pass to `useQuery`: `initialData`, and set `initialDataUpdatedAt: () => (initialData ? Date.now() : undefined)` so seeded data counts as fresh under the existing `staleTime: 2*60*1000` and the client does **not** refetch on mount. Preserve existing `queryKey`, `staleTime`, `gcTime`, `retry`, `retryDelay`. **Edge case — national cohorts >2000 (these ARE prebuilt: `national` is in `generateStaticParams`).** The server seed is capped at `limit:2000` while a client fetch pages beyond it. When `initialData.length >= 2000`, omit `initialDataUpdatedAt` so React Query background-refetches the full set; otherwise suppress the refetch. Expected behavior for such cohorts: the table shows the top 2000 on first paint, then the row count / SOS "out of N" / schema total briefly update when the full set lands (minor reflow). State-level cohorts are well under 2000, so they get the full set immediately with no reflow. If the first-paint truncation on national is judged unacceptable, that is the trigger to escalate to Option B.
3. **Thread the data down (no new fetch):**
   - `frontend/components/RankingsTable.tsx`: add `initialData?: RankingRow[]` to `RankingsTableProps`; pass it as the 4th arg to `useRankings(region, ageGroup, gender, initialData)`.
   - `frontend/components/RankingsPageContent.tsx:11`: add `initialRankings?: RankingRow[]` to props; forward as `<RankingsTable initialData={initialRankings} ... />` (:60).
   - `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx:231`: pass the already-fetched `allTeams` → `<RankingsPageContent initialRankings={allTeams} key={routeKey} ... />`. Reuse the existing `allTeams` (:119-128); do not add a fetch.
4. **Remove the redundant initial sort** in `RankingsTable.tsx` `sortedRankings` `useMemo` (:131). The RPC returns rank-ordered rows, and the default sort is `rank`/`asc`, so short-circuit: when `sortField === 'rank' && sortDirection === 'asc'`, return `rankings` unchanged (skip the full-array sort entirely on first paint). For the real (non-default) sort path, keep the existing `[...rankings].sort(...)` — the measured win is the short-circuit, not the sort method (avoids an ES2023 `toSorted` lib assumption for no benefit). Wrap user-initiated sort changes in `handleSort` (:212) with `startTransition` so taps stay responsive (`rerender-transitions`) — add `startTransition` to the React import (current import is `{ useDeferredValue, useMemo, useState, useRef, memo, useCallback, useEffect }`); the search filter is already `useDeferredValue` (:88) — leave it.
5. **(Optional, measure first) Trim the serialized payload.** Seeding puts `allTeams` into the RSC/Flight payload. If Phase-1 measurement shows payload/parse is now the bottleneck, map `allTeams` to only the load-bearing `RankingRow` fields before passing (`server-serialization`): `team_id_master, team_name, club_name, league, distinction, has_modular11_alias, power_score_final, rank_in_state_final, rank_in_cohort_final, sos_rank_state, sos_rank_national, state, rank_change_7d, rank_change_state_7d, last_calculated` (the search haystack reads `league`+`distinction`; `composeTeamDisplay` short-circuits on `has_modular11_alias` for MLS NEXT teams; rows render `state`, the rank-change arrows read `rank_change_state_7d ?? rank_change_7d`, the header reads `last_calculated`; the sort + sr-only list read the rest). **Safer than hand-maintaining this keep-list:** start from the full `RankingRow` and drop only obviously-unused large fields, after verifying `composeTeamDisplay` + row render + search still work. Skip the trim entirely if measurement is already on target.

### Phase 2 — Homepage (server-fetch above-the-fold data)
6. **Make `Home` an async RSC** (`frontend/app/page.tsx:8`). Change to `export default async function Home()` and add `export const revalidate = 3600;` (mirror rankings ISR). **Preserve** all existing hero markup, the three CTA buttons, and `<HowWeRank/>` + `<FeatureShowcase/>` exactly. **Wrap the server-side fetches (steps 7-8) in try/catch** so a failed fetch degrades to fallbacks rather than failing the static render (mirror the pattern at `page.tsx:121-128`). Note: these run with the anon-key client at build/revalidate, subject to the anon **3s `statement_timeout`** (`gotcha_supabase_statement_timeout_roles`); the rankings pages already do the same `limit:2000` fetch and build fine, but confirm the homepage build does not trip error 57014.
7. **Server-fetch stats for `HomeStats`.** `api.getDbStats()` **already exists** (`frontend/lib/api.ts:1312`) and returns `{ totalGames, totalTeams }` via direct count queries on `games` + `rankings_view` (teams = non-null `power_score_final`) — **reuse it; do NOT add a new one and do NOT introduce a second "total teams" definition.** It **throws** on error, so call it inside the Home RSC's try/catch (step 6) and fall back to HomeStats' default numbers on failure. Render `<HomeStats totalGames={...} totalTeams={...} />`. Rewrite `frontend/components/HomeStats.tsx`: **drop** `'use client'`, the `useEffect`, the `createClientSupabase` import, and all client state; accept `{ totalGames, totalTeams }` props (keep `fallback*` defaults). It becomes a presentational server component — removing an above-the-fold client Supabase fetch. Preserve the existing 3-column stat markup (incl. the static "50 States").
8. **Server-compute `RecentMovers`.** `RecentMovers` **stays a `'use client'` component** — it keeps the 7d/30d toggle state, the onClick handlers, and the localStorage `useEffect`; only its **data source** changes from client-fetch to server-computed props. (Contrast with `HomeStats`, which genuinely becomes a server component.) In `Home`, fetch the **full** national cohort server-side — `api.getRankings(null, 'u12', 'M')` with **no `limit`** (do NOT cap at 2000: the national U12/M cohort is ~9,055 rows and the biggest movers sit beyond rank 2000, so a cap changes 3 of 5 displayed movers — matching the current unbounded `RecentMovers` fetch is required to avoid a regression). The anon 3s `statement_timeout` is **per-statement**, so the sequential 1000-row batch fetch (~9 RPC calls, each ~238ms) is safe at build/revalidate. Then compute the top-5 movers for BOTH windows using the exact filter/sort/slice from `RecentMovers.tsx:185-207` (min 8 games, exclude "Not Enough Ranked Games", sort by `|rank_change_7d|` / `|rank_change_30d|`, slice 5). Pass as `initialMovers7d` / `initialMovers30d` props (5 rows each). Rewrite `frontend/components/RecentMovers.tsx`: **remove** the module-level cache, `fetchNationalRankings`, `getOrFetchRankings`, the fetch `useEffect`, and `rankings`/`isLoading` state; accept the two prebuilt arrays; the 7d/30d toggle selects between them. **Fix hydration:** initialize `timeWindow` to `defaultTimeWindow` (NOT from `localStorage` in the `useState` initializer, per `gotcha_matchmedia_ssr_hydration`); read `localStorage` in a `useEffect` after mount. Keep the toggle buttons, the empty-state, and the row markup (`composeTeamDisplay`, rank-change badges).
9. **Loading states.** With server data, `HomeStats`/`RecentMovers` render real content in the initial HTML — no skeleton needed on first paint. Do not introduce any `animate-pulse` skeleton in SSR (`gotcha_animate_pulse_soft404`). Server content already precedes client components (`gotcha_ssr_content_order`) — preserve that order.

### Out of scope (flagged, not in this plan)
- `Navigation` → `useUser` → `createClientSupabase` ships a ~50 KB Supabase chunk on **every** page (incl. `/`). It's the remaining sitewide LCP lever; the parked spec `.turbo/specs/nav-auth-server-resolve.md` covers it. Not touched here.

## Verification

> PSI reads a **deployed** URL, so verification requires a Vercel preview/prod deploy of the branch. Build locally first; if building in a worktree, copy env first (`cp C:/PitchRank/frontend/.env.local <worktree>/frontend/.env.local`, per `gotcha_worktree_env_local`).

1. **Build & type-check.** `cd frontend && npm run build` — confirm `/`, `/rankings/[region]`, `/rankings/[region]/[ageGroup]/[gender]` still report as Static `○` / SSG `●` (NOT Dynamic `λ`); no "Page changed from Static to Dynamic" warnings. Run `npx tsc --noEmit` clean (`feedback_eslint_tsc_safety`). Trust CI for prettier/ruff formatting (`gotcha_windows_prettier_crlf`).
2. **PSI median-of-3, mobile** on the deployed URL:
   ```
   RUNS=3 STRATEGY=mobile NODE_EXTRA_CA_CERTS="C:/Users/Dallas Heidt/win_ca_bundle.pem" \
     node "C:/Users/Dallas Heidt/psi_check.mjs" \
     "<deployed>/" "<deployed>/rankings/ny/u14/male" "<deployed>/rankings/co"
   ```
   **Targets:** age-group TBT well under 200ms (from 650ms); homepage LCP & TTI materially down (from 9.2s); CLS stays 0.000; `/rankings/co` does NOT regress (TBT 0ms / LCP ~3.5s control).
3. **Network checks (DevTools, mobile emulation):**
   - `/rankings/ny/u14/male`: NO `/api/rankings/state` XHR on initial load (table is seeded).
   - `/`: NO `get_db_stats` and NO `/api/rankings/national` XHR on initial load (server-rendered).
4. **Functional smoke:** age-group table — sort columns + type-to-search still work and match prior results; switching cohorts still loads. Homepage — stats show real numbers (not just 16000/2800 fallback); RecentMovers 7d/30d toggle swaps lists; team links work.
5. **Hydration:** zero hydration warnings in console on `/` and the age-group page (watch the RecentMovers `localStorage` path).
6. **Fallback gate:** if age-group TBT is still above target after Phase 1, escalate to **Option B** (server-render first ~50–100 rows, progressive load, server-side search) — re-plan that as a follow-up; do not expand scope mid-implementation.

## Context Files

Read in full before starting:
- `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx` — RSC that already fetches `allTeams` (the data to seed) and renders the SEO modules + sr-only list.
- `frontend/components/RankingsPageContent.tsx` — client wrapper that mounts the table; the prop pass-through point.
- `frontend/components/RankingsTable.tsx` — the TBT hotspot (sort/filter/virtualizer); read from `origin/main` (working tree differs).
- `frontend/hooks/useRankings.ts` — the React Query hook to extend with `initialData`.
- `frontend/lib/api.ts` (`getRankings` :67, counts :185/:254) — server fetch helpers; confirms RPC/shape parity with the client routes.
- `frontend/app/page.tsx`, `frontend/components/HomeStats.tsx`, `frontend/components/RecentMovers.tsx` — the homepage RSC + the two client children to convert.
- `frontend/app/rankings/[region]/page.tsx` — the healthy server-render-only pattern to mirror for the homepage.
- `frontend/components/skeletons/RankingsTableSkeleton.tsx` — SSR-safe skeleton pattern if any loading state is needed.
- `.turbo/seo-week4/pagespeed-audit.md` — prior audit history (Tier 1/2 attempts) for context.
