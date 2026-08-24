# Spec: Navigation auth — middleware-resolved + code-split to remove sitewide Supabase chunk

**Status**: PARKED (2026-04-19) — see note below
**Parked because**: Architectural cost grew disproportionate to the ~0.6–1.0s LCP win. The bigger lever is the 473 KB React Query bundle (61% of blocking JS vs this spec's 39%). Decision: ship React Query split first, then revisit nav with a simpler approach (lazy-load whole `<Navigation />` via `next/dynamic` with static skeleton; accept brief flash; skip middleware-headers + PPR complexity). This spec is preserved as a reference artifact for the full architectural refactor if ever needed.
**Owner**: Dallas Heidt
**Origin**: Phase 2 carry-over from Week 4 of `docs/superpowers/specs/2026-04-16-seo-roadmap-design.md`
**Date**: 2026-04-19

---

## Problem

`frontend/components/Navigation.tsx` is a `'use client'` component rendered in the root layout (`frontend/app/layout.tsx`) on every page. It imports `useUser`, which imports `createClientSupabase`, which imports `@supabase/supabase-js`. Result: a ~50 KB Supabase JS chunk ships on **every page load** for **cookie-less (logged-out) visitors** — including anonymous SEO traffic to `/blog/*`, `/rankings/*`, and marketing pages, where most visitors are not signed in and the chunk does nothing useful.

Recent measurement (PR #644 PSI medians, mobile, 3 runs each):

| Template | LCP | PSI score |
|---|---|---|
| `/` | 6.1s | 73 |
| `/rankings/co` | 2.6s | 97 (good) |
| `/rankings/tx/u14/boys` | 5.4s | 75 |
| `/blog/youth-soccer-pa-club-rankings` | 5.8s | 74 |
| `/teams/[id]` (sample) | 6.3s | 71 |

The LCP element on every tested template is the page H1 (Oswald 700 text). The 2.35s "element render delay" is hydration-time main-thread blocking by ~128 KB JS — 50 KB Supabase (this spec), 473 KB React Query bundle (separate future work), 64 KB gtag (already `afterInteractive`, not a CWV factor).

The single highest-ROI change available is **getting the 50 KB Supabase chunk off the critical path for cookie-less visitors**, because cookie-less visitors ARE the entire point of the 20-week SEO roadmap. Removing 50 KB of 128 KB total blocking JS is ~39% — best case ~0.6–1.0s LCP improvement, not enough alone to push templates into the "good" zone (<2.5s). That requires the React Query work as well, which is gated to a separate session.

---

## Goal

Cookie-less page loads ship **zero** `@supabase/*` JS via `Navigation` (verified in DevTools Network HAR). Authed page loads keep working (sign-out, signed-in dropdown). Median PSI LCP improves measurably across the templates currently in the "needs improvement" range. Pages stay statically generated (no ISR/SSG regression). The "good zone" LCP target is deferred to a Phase 3 milestone gated on React Query removal.

## Non-goals

- React Query bundle (473 KB). Separate future session.
- `gtag` loading. Already deferred via `afterInteractive`.
- `frontend/lib/api.ts`. Per memory `gotcha_supabase_ssr_shared_modules.md`, this module is imported by both Server and Client Components and must keep using vanilla `createClient`. Out of scope.
- Login/logout flows. The `/login` page itself, `/auth/callback`, password reset — all unchanged.
- Other consumers of `useUser` (10 files: mission-control, upgrade, watchlist, TeamHeader, TeamInsightsCard, NotificationBell, MergeTeamsDialog, useWatchlistMigration, etc.). They are on premium/protected/interactive routes where the Supabase chunk is correctly part of their bundle. No changes.
- Profile fetching (`user_profiles` table). Stays in `useUser` for the consumers that need plan/stripe info. Navigation only needs `user.email`.

## Constraints

- **PPR is required**: Without Next.js 16 Partial Prerendering enabled, calling `headers()` in any Server Component descendant of a route marks the **entire route** as dynamic — defeating the static-generation goal. This spec REQUIRES `experimental.ppr = 'incremental'` in `next.config.ts` plus `export const experimental_ppr = true` on each target page (`/blog/[slug]`, `/rankings/[region]`, `/rankings/[region]/[ageGroup]/[gender]`, `/teams/[id]`). Verified that the project is on Next.js 16.2.1 (PPR-stable). Without PPR, the approach must be reworked.
- **Single source of auth resolution**: middleware is the only place that calls `supabase.auth.getUser()`. Layout-side reads use the request header set by middleware. Avoid duplicating Supabase Auth round-trips.
- **Static generation must be preserved**: `app/blog/[slug]/page.tsx`, `app/teams/[id]/page.tsx`, `app/rankings/[region]/page.tsx`, and `app/rankings/[region]/[ageGroup]/[gender]/page.tsx` all use `generateStaticParams` + `revalidate = 3600`. The root layout MUST stay sync and MUST NOT call `cookies()`. With PPR enabled and per-route opt-in, the static shell of each page renders at build time; only the nav slot (inside `<Suspense>`) is dynamically streamed.
- **Internal headers are not authoritative for authorization**: The `x-pr-internal-*` headers set by middleware are for nav cosmetics ONLY (display the email in the dropdown). Any authorization decision (premium gating, admin checks) MUST continue to call `supabase.auth.getUser()` server-side. Documented to prevent future code from misusing these headers.

---

## Approach

Four coordinated changes (one new file, three modifications, one route used as-is):

### 1. Middleware sets user-info request headers

`frontend/middleware.ts` already calls `supabase.auth.getSession()` + `supabase.auth.getUser()` on every non-static request. After the existing call:

- If `user` is non-null, set two request headers on the forwarded request: `x-pr-user-id: <user.id>` and `x-pr-user-email: <user.email ?? ''>`. (Set on the `request.headers` clone used for `NextResponse.next({ request: { headers } })`.)
- If `user` is null, set `x-pr-user-id` to empty / omit. The downstream layout will treat absence as "anonymous."
- These headers are server-side only (forwarded to the Next.js renderer, not sent to the browser).

No new Supabase call. No latency added — middleware already does this work.

### 2. Root layout stays sync; new Suspense-wrapped Server Component reads headers

`frontend/app/layout.tsx`:

- **Stays sync**. No `await cookies()`, no `await getUser()`, no `async`. This preserves static generation for all pages underneath.
- Replace `<Navigation />` with `<Suspense fallback={<NavigationSkeleton />}><NavigationContainer /></Suspense>`.

`frontend/components/NavigationContainer.tsx` (new, **Server Component**, async):

- Reads `await headers()` — this marks *only this subtree* as dynamic, not the whole page.
- Wrapped in try/catch + 200ms timeout (`Promise.race`) around the header read. On failure or absence, defaults to `initialUser: null` (renders anonymous nav). Worst case during a Supabase outage: a logged-in user briefly sees the "Sign in" button until the next request — recoverable, not a blank site.
- Renders `<Navigation initialUser={…} />` with a minimal serializable payload: `{ id, email } | null`.
- Sets `Cache-Control: private` on this subtree's response (Vercel honors per-segment cache headers; prevents downstream proxy caching of personalized nav HTML).

A simple `<NavigationSkeleton />` Client Component renders a fixed-height nav bar matching the live nav (logo + reserved space) so the streaming-in nav doesn't cause CLS.

### 3. `Navigation` becomes server-decided, two branches; switch to `ssr: true`

`frontend/components/Navigation.tsx` (still `'use client'` — owns mobile menu state, links, search):

- Accept `initialUser: { id: string; email: string | null } | null` prop.
- Remove `useUser` import. Remove `handleSignOut`.
- `if (!initialUser)` → render the existing signed-out variant (links + GlobalSearch + "Sign in" button). **Zero Supabase imports** in this branch.
- `if (initialUser)` → render the same shell, with `<AuthedNavigation initialUser={initialUser} />` mounted in the auth slot via `next/dynamic(() => import('./AuthedNavigation'), { ssr: true, loading: () => <AuthSlotSkeleton /> })`.
- **`ssr: true`** is critical: the server already knows the user is authed and renders the dropdown markup directly. No flash. Anonymous tree-shaking still works because the conditional branch `if (initialUser)` returns nothing on the server when user is absent — the `next/dynamic` import is never evaluated in that path, and Webpack/Turbopack split AuthedNavigation into its own chunk that's never loaded on anon requests.

### 4. `AuthedNavigation` — minimal, no client Supabase

`frontend/components/AuthedNavigation.tsx` (new, `'use client'`):

- Receives `initialUser: { id: string; email: string | null }`.
- Renders the existing signed-in dropdown markup (email label + sign-out button) for both desktop and mobile slots.
- **Sign-out via `<form action="/logout" method="POST">`** — POSTs to the existing `app/logout/route.ts` which already handles server-side `supabase.auth.signOut()` and redirect. No JS required. No `createClientSupabase` import.
- **Cross-tab sync**: registers a thin `supabase.auth.onAuthStateChange` listener that calls `router.refresh()` on `SIGNED_OUT` and `SIGNED_IN` events. This re-renders the layout on the server with the new auth-cookie state, so a sign-out in another tab brings this tab's nav back to anon on next render. Listener teardown on unmount.
- The listener requires `createClientSupabase` — so this component DOES import Supabase. But because of the `ssr: true` code-split + tree-shaking on the anon branch, Supabase is only loaded for authed users. Chunk size: <2 KB for the dropdown markup + listener wiring + the form (Supabase chunk is loaded lazily by the listener).

Trade-off: the listener brings back ~50 KB of Supabase JS for authed users. That's acceptable because (a) authed users are a small fraction of traffic, (b) the SEO win is on cookie-less pages, (c) the alternative (no listener) breaks cross-tab sync. The chunk only loads after first paint of authed nav, doesn't block LCP.

### 5. `useUser` hook — unchanged

`frontend/hooks/useUser.ts` keeps its current logic. Other consumers (mission-control, upgrade, watchlist, etc.) keep using it as-is. The hook is just no longer in the sitewide bundle path because `Navigation` no longer imports it.

---

## Behavior decisions

| Question | Decision | Rationale |
|---|---|---|
| Where does auth get resolved? | **Middleware → request header** | Middleware already calls `getUser()`. Header pass-through avoids duplicate Supabase round-trips and keeps root layout sync. |
| Does root layout become async? | **No, stays sync** | Async layout + `cookies()` opts every descendant page out of static generation. This is a P0 regression on the very pages we're optimizing. |
| `next/dynamic` `ssr` setting for AuthedNavigation | **`ssr: true`** | Server already knows the user is authed. Rendering on the server eliminates the flash. Anon entry stays Supabase-free via the conditional branch + tree-shaking. |
| Sign-out mechanism | **`<form action="/logout" method="POST">`** | Existing route handler does server-side signOut. No client Supabase needed for the sign-out path itself. Works without JS. |
| Cross-tab sync | **`onAuthStateChange` in AuthedNavigation, calls `router.refresh()`** | Brings ~50 KB Supabase JS back for authed users only. Acceptable: SEO win is on cookie-less traffic. |
| When does AuthedNavigation chunk load? | **Only when server resolves an authed user** | Cookie-less = chunk never loads. Sign-in transitions through `/login` → `router.refresh()` → next render brings in chunk. |
| Caching for `headers()` in NavigationContainer | **`Cache-Control: private` on subtree response** | Layout stays static; nav slot is dynamic and private. No service worker present (verified) — only edge proxies to worry about. |
| Hydration safety | **Server renders the matching variant directly (`ssr: true`)** | Server-decided, server-rendered. Client receives matching JSX. Zero hydration mismatch. |
| AuthedNavigation payload | **`{ user: { id, email } }` only** | Navigation only uses `user.email?.split('@')[0]`. Profile (plan, stripe) stays fetched on-page where consumers actually need it. No extra DB query in middleware/layout. |
| Supabase outage handling | **try/catch + 200ms timeout in NavigationContainer, fall back to anonymous nav** | Worst case: logged-in user sees "Sign in" briefly during outage. Better than blank site. |
| What "anonymous" means in acceptance criteria | **Cookie-less visitor (no Supabase auth cookie)** | Aligns with SEO traffic which is the actual goal. A signed-in user reading a blog post still triggers AuthedNavigation chunk by design. |

---

## Out-of-scope decisions captured for later

- **`Providers` wrapper trim.** `Providers` brings React Query (~473 KB). It's the next biggest LCP lever. Separate session. The "good zone" LCP target lives there.
- **Server-fetching `user_profiles` in NavigationContainer.** Would let us show plan badge in nav. Adds ~10–30ms per authed request. Defer until product asks for it.
- **AuthedNavigation prefetch on /login mount.** Could trigger the dynamic import when the user opens `/login` so the chunk is warm. Deferred — small flash is acceptable; sign-in is rare.
- **PPR adoption for `/blog/*` and `/rankings/*`.** Possible after this work because the layout stays static. Tracked as a future LCP lever.

---

## Files in scope

| File | Change |
|---|---|
| `frontend/middleware.ts` | After existing `getUser()` call, set `x-pr-user-id` + `x-pr-user-email` headers on the forwarded request. |
| `frontend/app/layout.tsx` | Replace `<Navigation />` with `<Suspense fallback={<NavigationSkeleton />}><NavigationContainer /></Suspense>`. Layout stays sync. |
| `frontend/components/NavigationContainer.tsx` | **New.** Async Server Component. Reads `await headers()` with try/catch + 200ms timeout, sets `Cache-Control: private`, renders `<Navigation initialUser={...} />`. |
| `frontend/components/NavigationSkeleton.tsx` | **New.** Client component (or static markup). Reserves nav-bar height + logo to prevent CLS while NavigationContainer streams in. |
| `frontend/components/Navigation.tsx` | Accept `initialUser` prop; drop `useUser` import; drop `handleSignOut`; conditionally render `<AuthedNavigation />` via `next/dynamic({ ssr: true })` when `initialUser` is non-null. |
| `frontend/components/AuthedNavigation.tsx` | **New.** Owns signed-in dropdown markup, `<form action="/logout">` for signout, and a thin `onAuthStateChange` listener that calls `router.refresh()` on `SIGNED_OUT`/`SIGNED_IN`. |
| `frontend/app/logout/route.ts` | **No change** — POST handler already does server-side `supabase.auth.signOut()` + redirect. Used as-is. |
| `frontend/hooks/useUser.ts` | No change. |
| `frontend/lib/supabase/server.ts` | No change. |
| `frontend/lib/supabase/client.ts` | No change. |
| `frontend/lib/api.ts` | **MUST NOT TOUCH** — see memory `gotcha_supabase_ssr_shared_modules.md`. |

---

## Acceptance criteria

### Functional
- Cookie-less user loads `/`, `/blog/[slug]`, `/rankings/[state]/[age]/[gender]` — sees the "Sign in" button. Sign in → /login → after auth, sees signed-in dropdown with email and Sign out button.
- Signed-in user clicks Sign out → form posts to `/logout`, redirects to `/`, returns to anon nav variant.
- Cross-tab smoke: open `/blog/foo` (Tab A, anon → sign in) and `/mission-control` (Tab B, authed). Sign out from Tab B. Tab A's nav reflects sign-out within ~1s without manual reload.
- Mobile menu open/close still works in both anon and authed variants.
- Existing protected pages (mission-control, upgrade, watchlist) still gate on `useUser` correctly.
- Sign-out works **without JavaScript** (form submits to `/logout` route).

### Static generation preserved
- `next build` output for `/blog/[slug]`, `/rankings/[region]`, `/rankings/[region]/[ageGroup]/[gender]`, `/teams/[id]` shows them as `○` (Static) or `●` (SSG with revalidate), NOT `λ` (Dynamic).
- Build log does NOT show "Page changed from Static to Dynamic" warnings for any of the above.

### Performance — bundle (cookie-less visitor)
- DevTools Network HAR on cookie-less load of `/` and `/blog/youth-soccer-pa-club-rankings`: zero requests for any chunk containing `@supabase/*` modules.
- Bundle analysis (`ANALYZE=true next build` with `@next/bundle-analyzer`): no chunk loaded by the cookie-less request to `/blog/[slug]` contains `@supabase/supabase-js` or `@supabase/ssr` imports.

### Performance — LCP delta (median of 3 PSI runs each, mobile, per memory `feedback_psi_lab_variance.md`)
- Baseline: PSI medians captured in `.turbo/seo-week4/pagespeed-audit.md` after PR #644 shipped.
- Target: median LCP improves by **≥0.6s on at least 3 of the 4 currently-stuck templates** (`/`, `/rankings/tx/u14/boys`, `/blog/youth-soccer-pa-club-rankings`, `/teams/[id]` sample).
- No template regresses LCP by more than **0.3s**.
- Server-response-time metric does not regress (validates the static-generation preservation).
- The `<2.5s` "good zone" target is **explicitly out of scope for this PR** and tracked as a Phase 3 milestone gated on React Query bundle removal.
- Note: `/teams/[id]` is premium-gated upstream (per memory `gotcha_team_detail_premium_gated.md`); for cookie-less measurement use a public template route. If `/teams/[id]` is unreachable as cookie-less, the target reduces to "≥3 of the 3 reachable templates."

### Quality
- Zero hydration warnings in the browser console on cookie-less and authed loads.
- TypeScript: `tsc --noEmit` clean.
- ESLint clean.
- No new flash of unauthenticated content on `/mission-control` or `/teams/[id]` for already-signed-in users (verify `useUser`-driven UI on those pages still resolves user within one render).

---

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Layout becomes accidentally dynamic (e.g., reviewer adds `cookies()` later) | Medium | Inline comment in `app/layout.tsx` explaining "DO NOT add `await cookies()` here — see spec nav-auth-server-resolve.md, breaks ISR." Build-log check in acceptance catches it. |
| `headers()` in NavigationContainer adds noticeable TTFB to nav slot streaming | Low | Header read is in-process (set by middleware on same request). No network call. <1ms cost. Suspense streaming hides it from initial paint. |
| Supabase outage hangs NavigationContainer indefinitely | Low | 200ms timeout via `Promise.race`. Falls back to anonymous nav. Worst case: logged-in user sees "Sign in" briefly. |
| Hydration mismatch between server-rendered nav variant and client | Very Low | Server-decided variant + `ssr: true`. Server rendered the dropdown markup directly. Client receives matching JSX by construction. Verified by zero console warnings in acceptance. |
| Anonymous Supabase chunk leaks back via transitive import (`Providers` adds something) | Medium | Bundle-analyzer step in acceptance catches transitive imports. Not just the network tab. |
| AuthedNavigation chunk size grows unexpectedly | Low | Estimated <2 KB for form + listener wiring. The Supabase listener triggers a separate ~50 KB chunk lazy-loaded after first paint. Measure post-implementation, update memory. |
| Cross-tab listener fires before cookie cleared, causing race | Low | Listener calls `router.refresh()`. Server re-resolves user from cookie. If cookie still present (race), no-op. Next event triggers another refresh. Eventually consistent. |
| Service worker caches nav HTML and serves wrong variant | None today | No SW present (verified). Document `Cache-Control: private` requirement so future SW work doesn't regress. |
| `useUser` consumers regress because singleton init shifts later in render tree | Low | Acceptance includes manual smoke on `/mission-control`, `/teams/[id]`. If flash appears, fix is to also pass `initialUser` via Context from layout (deferred unless symptom appears). |
| Existing protected pages do their own `useUser` and trigger the chunk | Expected | Correct behavior. Protected pages need Supabase. Anonymous pages don't. |
| LCP improvement underwhelms (PR fails delta target) | Medium | Median-of-3 PSI per memory `feedback_psi_lab_variance.md`. If single-run noise obscures, run 5+ runs. If genuine miss, escalate by also moving React Query into the same session (out-of-scope expansion). |

---

## Verification steps

After implementation:

1. **Build check.** Run `next build` from `frontend/`. Inspect output:
   - `/blog/[slug]` shows as `○` Static or `●` SSG.
   - `/rankings/[region]`, `/rankings/[region]/[ageGroup]/[gender]` show same.
   - `/teams/[id]` shows `●` SSG with revalidate.
   - No "Page changed from Static to Dynamic" warnings.

2. **Bundle analysis.** Run `ANALYZE=true next build` (or `npx @next/bundle-analyzer next build` per project setup). Confirm:
   - The page-level chunk for `/blog/[slug]` does not contain `@supabase/*`.
   - A separate `AuthedNavigation` chunk exists.
   - The Supabase listener path is in a third chunk loaded only after AuthedNavigation mounts.

3. **Network check (cookie-less).** Open `/` and `/blog/youth-soccer-pa-club-rankings` in an incognito window. DevTools → Network → save HAR → grep for "supabase". Expect zero matches.

4. **Network check (authed).** Sign in. Reload `/`. Expect to see one request for the AuthedNavigation chunk on first authed nav, then a separate request for the Supabase listener chunk after first paint.

5. **PSI median run.** Run PageSpeed Insights 3 times each on the 4 currently-stuck templates. Take median per template. Compare to PR #644 baseline in `.turbo/seo-week4/pagespeed-audit.md`. Verify ≥0.6s LCP improvement on ≥3 of 4 templates and no regression >0.3s on any.

6. **Functional smoke.**
   - Sign in via /login → land on rankings → see dropdown.
   - Open `/mission-control` (authed) — no flash of unauthenticated content.
   - Open `/teams/[id]` (authed) — no flash of unauthenticated content.
   - Sign out via dropdown → form posts → redirected to / → see Sign in button.
   - Disable JS in browser. Sign in via /login (server-side flow). Sign out via the form button. Confirm sign-out works.

7. **Cross-tab smoke.**
   - Tab A: sign in, navigate to `/mission-control`.
   - Tab B: open `/blog/youth-soccer-pa-club-rankings` (you're authed, so see dropdown).
   - In Tab A, click Sign out.
   - Switch to Tab B within 2 seconds. Nav should reflect signed-out state without manual reload.

8. **Cache header check.** `curl -I https://www.pitchrank.io/` and confirm response includes the expected `Cache-Control` header behavior (page itself: cacheable; nav slot: private). Adjust strategy if Vercel doesn't honor per-segment cache as expected.

9. **Console check.** Page load on `/`, `/rankings/co`, `/blog/youth-soccer-pa-club-rankings`, `/mission-control` (authed), `/upgrade` (authed). Zero hydration warnings in console.

10. **Update memory.** After verification, update `seo_roadmap_status.md` to mark Tier 2 LCP work shipped, update `gotcha_supabase_nav_useuser_lcp.md` to reflect the fix (anon = zero, authed = lazy ~50 KB), and add a new memory note documenting the middleware-headers pattern as the canonical way to pass server-resolved auth into a static layout.

---

## References

- SEO roadmap: `docs/superpowers/specs/2026-04-16-seo-roadmap-design.md` (this is Phase 2 carry-over from Week 4)
- PR #644: font weight cleanup (already shipped, the prerequisite)
- Memory: `gotcha_supabase_nav_useuser_lcp.md`, `gotcha_supabase_ssr_shared_modules.md`, `feedback_psi_lab_variance.md`, `seo_roadmap_status.md`, `gotcha_team_detail_premium_gated.md`
- Week 4 artifacts: `.turbo/seo-week4/pagespeed-audit.md`
- Vercel skill guidance consulted: `vercel:nextjs` (async-patterns, rsc-boundaries, hydration-error, bundling), `vercel:auth` (server-resolve-then-pass-prop pattern)
- Existing route used as-is: `frontend/app/logout/route.ts` (POST handler does server-side signOut)
