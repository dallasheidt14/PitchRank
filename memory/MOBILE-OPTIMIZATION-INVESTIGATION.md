# Mobile Optimization Investigation Report

> Date: 2026-03-13
> Branch: `claude/mobile-optimization-investigation-RXApq`

---

## Executive Summary

The PitchRank frontend has **solid mobile foundations** — proper viewport config, responsive breakpoints, virtualized tables, touch targets, safe areas, and font-swap. However, there are **7 actionable optimization opportunities** that can meaningfully improve mobile performance without risking breaking changes.

Severity scale: **P0** (critical) | **P1** (high impact) | **P2** (medium) | **P3** (low/nice-to-have)

---

## Current Strengths (What's Working Well)

| Area | Implementation | File |
|------|---------------|------|
| Viewport config | `device-width`, `viewportFit: cover`, `userScalable: true` | `app/layout.tsx:107-114` |
| Font loading | `display: "swap"` on all 3 fonts (Oswald, DM Sans, JetBrains Mono) | `app/layout.tsx:12-34` |
| Table virtualization | `@tanstack/react-virtual` with 60px rows, overscan=5 | `components/RankingsTable.tsx:197-202` |
| Touch targets | 44x44px minimum on all interactive mobile elements | `components/Navigation.tsx:154` |
| Safe areas | `env(safe-area-inset-*)` for notched devices | `app/globals.css:160-174` |
| iOS zoom prevention | 16px inputs on mobile | `app/globals.css:177-185` |
| Momentum scrolling | `-webkit-overflow-scrolling: touch` | `app/globals.css:112, 155` |
| Reduced motion | `prefers-reduced-motion: reduce` respected | `app/globals.css:121-128` |
| Tree-shaking | `optimizePackageImports` for recharts, lucide-react, date-fns | `next.config.ts:21-23` |
| Lazy Fuse.js | Dynamic import only when search is used | `components/GlobalSearch.tsx:72-78` |
| Team prefetch | `onMouseEnter` prefetch for team pages | `components/RankingsTable.tsx:466` |
| GA strategy | `afterInteractive` script loading | `components/GoogleAnalytics.tsx:49-51` |
| Console removal | Production builds strip `console.log` | `next.config.ts:12-18` |
| Suspense boundaries | `RankingsTable` wrapped in Suspense with skeleton | `components/RankingsPageContent.tsx:63-68` |
| Lazy team page charts | Dynamic imports for TrajectoryChart, MomentumMeter, etc. | `components/TeamPageShell.tsx:18-36` |

---

## Optimization Opportunities

### 1. [P1] Mobile Navigation: No Enter/Exit Animation

**File:** `components/Navigation.tsx:169`

**Issue:** The mobile menu renders with a hard cut (`{mobileMenuOpen && ...}`). No transition animation on open/close, which feels jarring on mobile. More critically, the menu DOM is fully unmounted/remounted on every toggle, causing layout recalculation.

**Recommendation:** Add a CSS transition (slide-down or fade) using Tailwind's `animate-` utilities or a `data-state` pattern. This is purely visual polish — low risk of breaking anything.

**Risk level:** Very low. Purely additive CSS.

---

### 2. [P1] Home Page: Duplicate Rankings Fetch on Mobile

**File:** `components/HomeLeaderboard.tsx:22` and `components/RecentMovers.tsx:52`

**Issue:** Both `HomeLeaderboard` and `RecentMovers` call `useRankings(null, 'u12', 'M')` with the **exact same parameters**. React Query deduplicates the network request (good), but both components independently compute `computedNationalRanks` via `useMemo` — sorting the full array twice.

On a dataset of ~500-2000 teams, this means:
- 2 full array copies (`[...rankings].sort(...)`)
- 2 Map constructions
- All on the main thread during initial render

**Recommendation:** Extract rank computation into a shared hook (e.g., `useComputedRanks`) that memoizes the result once for the query key. Or lift the computation to a parent component and pass down.

**Risk level:** Low. Internal refactor, no API or UI changes.

---

### 3. [P1] GlobalSearch: Eagerly Fetches ALL Teams on Mount

**File:** `hooks/useTeamSearch.ts:14-115`

**Issue:** `useTeamSearch()` fetches the **entire teams table** (potentially 25K+ teams in batches of 1000) as soon as `GlobalSearch` mounts. Since `GlobalSearch` is in the Navigation (rendered on every page), this triggers on every page load.

The paginated fetch means potentially **25+ sequential Supabase API calls** on first page load, fetching data the user may never need (most users don't search).

**Recommendation:**
- Add `enabled: false` by default, only enable when search input is focused or has 2+ characters
- Or use a server-side search endpoint (Supabase full-text search) instead of client-side Fuse.js
- At minimum, add a `staleTime` check — the data already has `staleTime: 10min`, but the initial fetch is still eager

**Risk level:** Low-medium. Changing `enabled` requires testing that the search still works when triggered. The Fuse.js approach would remain intact.

---

### 4. [P2] RankingsTable: `hover:scale-[1.01]` on Every Row

**File:** `components/RankingsTable.tsx:423`

**Issue:** Each virtualized row has `hover:scale-[1.01]` which triggers a CSS `transform` on hover. On mobile:
- Hover states don't apply the same way (touch-and-hold triggers it)
- `scale` transforms force GPU layer creation for EVERY row, even virtualized ones
- Combined with `transition-all duration-200`, this creates unnecessary composite layers

**Recommendation:** Remove `hover:scale-[1.01]` or scope it to desktop only with `md:hover:scale-[1.01]`. The `hover:bg-accent/70 hover:shadow-md` effects are sufficient visual feedback. Alternatively, use `will-change: transform` only on active hover.

**Risk level:** Very low. Visual-only change, no functional impact.

---

### 5. [P2] `transition-all` Overuse Across Components

**Files:** Multiple — `app/globals.css:102,110,130`, `components/RankingsTable.tsx:422`, `components/Navigation.tsx:37`

**Issue:** `transition-all` and `transition-colors duration-300` are applied broadly:
- `html` element: `transition-colors duration-300` (line 102)
- `body` element: `transition-colors duration-300` (line 110)
- `main` element: `transition-colors duration-300` (line 130)
- Every table row: `transition-all duration-200`
- Navigation header: `transition-colors duration-300`

`transition-all` is expensive because the browser must check ALL CSS properties for changes on every frame. On mobile devices with limited GPU, this causes jank during scrolling.

**Recommendation:**
- Replace `transition-all` with specific properties: `transition-[background-color,box-shadow]`
- Remove transitions from `html`, `body`, and `main` — there's no dark mode toggle, so these transitions serve no purpose
- On table rows, use `transition-colors` instead of `transition-all`

**Risk level:** Very low. Only affects animation smoothness, not functionality.

---

### 6. [P2] Service Worker: Push-Only, No Caching

**File:** `public/sw.js`

**Issue:** The service worker only handles push notifications — no asset caching, no API response caching, no offline fallback. Every mobile revisit fetches everything fresh.

**Recommendation:** Add a lightweight cache-first strategy for static assets (CSS, JS, fonts, images) and a stale-while-revalidate strategy for API responses. Consider using Workbox for a proven solution.

**Risk level:** Medium. Service worker caching bugs can serve stale content. Needs careful cache versioning. Not recommended as a quick win — save for a dedicated sprint.

---

### 7. [P3] Three Google Fonts = Three Network Requests

**File:** `app/layout.tsx:12-34`

**Issue:** Three Google Fonts are loaded (Oswald, DM Sans, JetBrains Mono) each with 4 weights. Next.js optimizes these via `next/font/google` (self-hosted, no external requests), but the combined font payload is significant:
- Oswald: ~60KB (4 weights)
- DM Sans: ~80KB (4 weights)
- JetBrains Mono: ~90KB (4 weights)

JetBrains Mono is used only for `font-mono` (PowerScore numbers, code blocks). Loading 4 weights for occasional number display is expensive.

**Recommendation:** Reduce JetBrains Mono to weights `[400, 700]` only (removing 500, 600). Consider if Oswald really needs weight 400 (it's used for bold headlines). Each dropped weight saves ~15-25KB.

**Risk level:** Very low. Font weight changes only affect text rendering for those specific weights.

---

## Findings That Do NOT Need Changes

These items looked concerning but are actually fine:

| Item | Why It's OK |
|------|------------|
| `useRankings` 2-min staleTime | Rankings update weekly; 2 min is aggressive but fine for filter switching UX |
| `canvas-confetti` in bundle | Only imported conditionally in HomeLeaderboard; Next.js tree-shakes it |
| `html2canvas` in bundle | Only used in infographics route (dynamic import via TeamPageShell) |
| `stripe` in bundle | Server-side only in API routes, not shipped to client |
| Multiple Supabase clients | Necessary pattern — browser, server, SSR each need separate instances |
| `resend` in bundle | Server-side only for email, not in client bundle |
| No `memo()` on RankingsTable | The component is already behind Suspense + the expensive parts use `useMemo`/`useCallback` |
| Recharts bundle size | Already tree-shaken via `optimizePackageImports`; only used on team detail pages (lazy-loaded) |

---

## Priority Implementation Order

| Priority | Item | Effort | Impact | Risk |
|----------|------|--------|--------|------|
| 1 | Remove `hover:scale` on mobile rows (#4) | 5 min | Medium | None |
| 2 | Replace `transition-all` with specific properties (#5) | 15 min | Medium | None |
| 3 | Lazy-load team search data (#3) | 30 min | High | Low |
| 4 | Deduplicate rank computation (#2) | 30 min | Medium | Low |
| 5 | Add mobile menu animation (#1) | 20 min | Low (UX polish) | None |
| 6 | Trim font weights (#7) | 5 min | Low-Medium | None |
| 7 | Service worker caching (#6) | 2-4 hours | High | Medium |

---

## Metrics to Track

Before implementing, consider adding Web Vitals monitoring to measure the impact:

- **LCP** (Largest Contentful Paint) — hero section text/image
- **FID/INP** (Interaction to Next Paint) — filter dropdowns, sort buttons, search input
- **CLS** (Cumulative Layout Shift) — font swap, skeleton → content transitions
- **TTFB** (Time to First Byte) — middleware processing overhead

Next.js supports this via `next/web-vitals` or the `web-vitals` npm package reporting to Google Analytics.

---

## Summary

The frontend is in good shape for mobile. The biggest wins with lowest risk are:
1. **Lazy-loading the team search data** (stop fetching 25K teams on every page load)
2. **Removing `transition-all` and `hover:scale`** from virtualized rows (GPU savings)
3. **Trimming unused font weights** (bandwidth savings)

None of these require architectural changes or risk breaking existing functionality.
