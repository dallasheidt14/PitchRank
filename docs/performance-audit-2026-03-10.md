# PitchRank Performance Audit Report

**Date:** 2026-03-10
**Scope:** Full-stack performance audit — backend ranking engine, frontend, database, scraping pipeline, and CI/CD

---

## Executive Summary

This audit identified **40+ performance issues** across the PitchRank stack. The highest-ROI improvements fall into three categories:

1. **Backend vectorization** — Replace `.iterrows()` and `.apply(axis=1)` with vectorized pandas/numpy operations (est. 30-50% ranking engine speedup)
2. **Async/parallel I/O** — Sequential Supabase queries in data adapter and ranking calculator should be parallelized (est. 50-100x speedup on metadata fetches)
3. **Frontend overfetching** — `.select('*')` on large tables and fetching all rankings when only 15-20 are visible (bandwidth + memory reduction)

**Estimated total impact:** Ranking pipeline from ~35 min → ~10 min; frontend TTFB reduced 200-500ms on key pages.

> **⚠️ REVISION NOTE (Deep Review, 2026-03-10):** Items marked with ❌ or ⚠️ below were
> downgraded after senior full-stack code review found ripple effects, breaking changes,
> or insufficient ROI. See "Deep Review Findings" appendix at bottom for full analysis.

---

## Top 10 High-ROI Improvements (Prioritized — Revised)

### 1. Parallelize Sequential Supabase Batch Fetches ✅
- **Files:** `src/rankings/data_adapter.py:251-269`, `scripts/calculate_rankings.py:470-488`
- **Problem:** Team metadata fetched sequentially in 100-ID batches via for-loop. With 100K teams, this is 1,000+ serial API calls.
- **Fix:** Use `asyncio.gather()` with 10-20 concurrent batches.
- **Impact:** **CRITICAL** — 50-100x faster metadata fetching (from ~15 min to ~15 sec)
- **Effort:** Medium

### 2. Vectorize `.apply(axis=1)` in v53e Engine ⚠️ PARTIAL
- **File:** `src/etl/v53e.py:1002-1006, 787, 1021, 1415-1416`
- **Problem:** Adaptive K-factor, context multipliers, and power mapping use row-by-row `.apply()` and `.map(lambda)`. Called on 100K+ game rows.
- **Fix:** Replace with vectorized `.map(dict)`, `np.where()`, and direct column arithmetic.
- **Impact:** **HIGH** — 10-30% speedup on v53e calculation (5-15 min savings)
- **Effort:** Medium
- **⚠️ Deep Review:** `adaptive_k` is safely vectorizable via `.map()`. `context_mult` has multiplicative conditional logic (`mult *= A; mult *= B`) that risks subtle math bugs if vectorized incorrectly. Only vectorize `adaptive_k`; leave `context_mult` unless profiling proves it's a bottleneck.

### 3. ❌ ~~Use TRUNCATE Instead of Delete-All for Rankings~~ — REJECTED
- **File:** `scripts/calculate_rankings.py:245`
- **Original suggestion:** Use Supabase RPC to call `TRUNCATE rankings_full` directly.
- **❌ Deep Review:** Current `.delete().neq('team_id', '00000000...')` is an **intentional safeguard** — it excludes the null UUID sentinel. TRUNCATE bypasses RLS policies, could cascade through foreign keys, and breaks the downstream deprecated-team cleanup logic (lines 333-348). **Keep current approach.**

### 4. Optimize Frontend Middleware Auth Checks ⚠️ LIMITED
- **File:** `frontend/middleware.ts:67-68, 97-101`
- **Problem:** Calls `getSession()` AND `getUser()` on every request. Premium route check adds a DB query.
- **Impact (revised):** ~50ms savings (not 100-300ms as originally estimated)
- **Effort:** Low
- **⚠️ Deep Review:** `getSession()` **refreshes expired auth tokens** via cookie updates. Skipping it on public routes causes token expiry → unexpected logouts when navigating to protected routes. **Only safe optimization:** skip the premium profile DB query (lines 97-101) on non-premium routes. Keep `getSession()`/`getUser()` on ALL routes.

### 5. Replace `.select('*')` with Column-Specific Queries ⚠️ PARTIAL
- **File:** `frontend/lib/api.ts:48, 99-101, 140, 379, 495, 677, 683`
- **Problem:** 7+ queries fetch all columns from teams, rankings_full, and games tables.
- **Impact:** **HIGH** — 40-70% bandwidth reduction on safe queries
- **Effort:** Low
- **⚠️ Deep Review:** `getTeam()` (lines 99-101) has cascading fallback chains across 3+ data sources (`rankingData?.power_score_final ?? stateRankData?.power_score_final ?? ...`). Missing a column silently returns `undefined`. **Only safe for:** `getTeamGames()`, `getRankings()`, and `team_merge_map` queries. Leave `getTeam()` alone.

### 6. Remove Debug Console Logging from useRankings ✅
- **File:** `frontend/hooks/useRankings.ts:19-207`
- **Problem:** 16 console statements execute on every query.
- **Fix:** Remove 14 `console.log` statements. Keep 2 `console.error` statements (lines 79, 94).
- **Impact:** **LOW** (dev cleanup only — Next.js compiler already strips `console.log` in production via `removeConsole` config)
- **Effort:** Trivial
- **✅ Deep Review:** E2E test `homepage.spec.ts:70-71` filters the 2 `console.error` patterns — do NOT remove those.

### 7. ❌ ~~Cache Team State Metadata Across Ranking Passes~~ — UNNECESSARY
- **File:** `src/rankings/calculator.py:569-585`
- **Original suggestion:** Reuse Pass 1 state_code in Pass 3.
- **❌ Deep Review:** The two fetches serve **different architectural purposes** (Fetch 1: SCF algorithm input; Fetch 2: SOS output enrichment). Both are read-only, no writes between them. However, Fetch 2 only takes ~10 seconds for 10K teams — **not a bottleneck**. Merging them adds complexity for negligible gain. **Skip this optimization.**

### 8. ❌ ~~Increase Batch Size from 100 to 200 UUIDs~~ — UNSAFE
- **File:** `src/rankings/data_adapter.py:249`
- **Original suggestion:** Change `batch_size = 100` to `batch_size = 200`.
- **❌ Deep Review:** Requires coordinated changes across **11+ files** (data_adapter, calculator, ranking_history, scrapers, scripts). At batch_size=180 with combined filters (`.in_().eq().gte().lte()`), URI reaches ~6.85KB against 8KB limit — only 1.15KB margin. Silent failures return empty results (no exception), causing **undetected data corruption** in rankings. **Keep at 100, or standardize to 150 max** (already proven safe in 3 scripts).

### 9. Add pip Caching to GitHub Actions ✅ (no npm needed)
- **Files:** 5 workflows missing caching: `calculate-rankings.yml`, `process-missing-games.yml`, `tgs-event-scrape-import.yml`, `auto-gotsport-event-scrape.yml`, `scrape-specific-event.yml`
- **Problem:** 5/16 workflows install dependencies from scratch; 4 workflows have redundant `pip install` after `requirements.txt`.
- **Fix:** Add `cache: 'pip'` to `setup-python`; remove redundant installs; standardize to `@v5`.
- **Impact:** **MEDIUM** — `process-missing-games.yml` (hourly) alone saves ~120-180 min/week
- **Effort:** Low
- **✅ Deep Review:** No npm workflows exist (Vercel handles frontend). Requires removing redundant `pip install scrapy twisted` and `pip install beautifulsoup4 lxml` from 4 workflows (packages already in requirements.txt).

### 10. Consolidate groupby-concat Patterns in v53e ✅
- **File:** `src/etl/v53e.py:738, 868, 873, 977, 980`
- **Problem:** Five separate `pd.concat([fn(grp) for _, grp in df.groupby()])` patterns create N temporary DataFrames.
- **Fix:** Use `.groupby().transform()` or `.groupby().apply()` with return.
- **Impact:** **MEDIUM** — 10-20% memory reduction, faster execution
- **Effort:** Medium

---

## All Issues by Category

### A. Backend Ranking Engine (`src/etl/v53e.py`)

| # | Issue | Lines | Impact | Type |
|---|-------|-------|--------|------|
| 1 | `.apply(axis=1)` for adaptive K (called 2x) | 1002-1006 | HIGH | Vectorization |
| 2 | `.map(lambda)` for power mapping | 1415-1416 | MEDIUM | Vectorization |
| 3 | `.apply(axis=1)` context multipliers (duplicated) | 787, 1021 | MEDIUM | Redundancy |
| 4 | 5× groupby-concat patterns | 738-980 | MEDIUM | Memory |
| 5 | Iterative SOS with dictionary rebuilds | 1184-1244 | MEDIUM-HIGH | Loop optimization |
| 6 | 23+ unnecessary `.copy()` calls | Throughout | MEDIUM | Memory |
| 7 | `.iterrows()` for isolated team logging | 610-615 | LOW | Vectorization |

### B. Ranking Orchestrator (`src/rankings/calculator.py`)

| # | Issue | Lines | Impact | Type |
|---|-------|-------|--------|------|
| 8 | `.iterrows()` in ML batch loop | 47-53 | MEDIUM | Vectorization |
| 9 | Nested loops building global strength map | 480-486 | MEDIUM | Vectorization |
| 10 | Row-by-row fallback anchor scaling | 867-891 | MEDIUM-HIGH | Vectorization |
| 11 | Multiple `.iterrows()` in metadata loops | 433-548 | MEDIUM | Vectorization |
| 12 | Nested groupby for SOS normalization | 624-658 | MEDIUM | Query optimization |
| 13 | Redundant team metadata fetch (Pass 1 → Pass 3) | 569-585 | MEDIUM | Caching |

### C. ML Layer 13 (`src/rankings/layer13_predictive_adjustment.py`)

| # | Issue | Lines | Impact | Type |
|---|-------|-------|--------|------|
| 14 | `pd.concat` list comprehension for team aggregation | 604-612 | MEDIUM | Aggregation |
| 15 | Dict building from groupby loop | 296-300 | LOW-MEDIUM | Vectorization |

### D. Data Adapter (`src/rankings/data_adapter.py`)

| # | Issue | Lines | Impact | Type |
|---|-------|-------|--------|------|
| 16 | `.iterrows()` for game row conversion | 498-548 | MEDIUM-HIGH | Vectorization |
| 17 | Sequential batch metadata fetching | 251-269 | CRITICAL | Async I/O |
| 18 | Conservative batch size (100 vs 200) | 249 | MEDIUM | Configuration |
| 19 | `time.sleep()` blocking event loop | 57 | MEDIUM | Async pattern |

### E. Scraping Pipeline

| # | Issue | File | Lines | Impact |
|---|-------|------|-------|--------|
| 20 | Sequential team UPDATE calls | `scripts/scrape_games.py` | 126-135 | HIGH |
| 21 | Per-team scrape date lookups (25K extra API calls) | `src/scrapers/base.py` | 149-157 | HIGH |
| 22 | Club name not shared across concurrent batches | `src/scrapers/gotsport.py` | 301-321 | MEDIUM |

### F. Ranking Calculation Script

| # | Issue | File | Lines | Impact |
|---|-------|------|-------|--------|
| 23 | Sequential metadata batch fetching | `scripts/calculate_rankings.py` | 470-488 | CRITICAL |
| 24 | Delete-all rankings (full table scan) | `scripts/calculate_rankings.py` | 245 | HIGH |
| 25 | Sequential writes to two tables | `scripts/calculate_rankings.py` | 120-161 | MEDIUM |
| 26 | No v53e cache reuse for ML re-runs | `src/rankings/calculator.py` | 143-150 | MEDIUM |

### G. Frontend — Network & Data Fetching

| # | Issue | File | Lines | Impact |
|---|-------|------|-------|--------|
| 27 | `.select('*')` overfetching (7 queries) | `frontend/lib/api.ts` | 48-683 | HIGH |
| 28 | Middleware auth checks on every request | `frontend/middleware.ts` | 67-68 | HIGH |
| 29 | Fetches all rankings instead of visible page | `frontend/hooks/useRankings.ts` | 50-191 | MEDIUM |
| 30 | Redundant merge map fetches (4 locations) | `frontend/lib/api.ts` | 156-655 | MEDIUM |
| 31 | Dependent queries causing waterfall | `frontend/lib/api.ts` | 138-153 | MEDIUM |

### H. Frontend — Rendering

| # | Issue | File | Lines | Impact |
|---|-------|------|-------|--------|
| 32 | 12+ console.log in useRankings (production) | `frontend/hooks/useRankings.ts` | 19-207 | MEDIUM |
| 33 | Missing useCallback on sort handler | `frontend/components/RankingsTable.tsx` | 204-224 | MEDIUM |
| 34 | Inline IIFEs in virtualized rows | `frontend/components/RankingsTable.tsx` | 438-507 | MEDIUM |
| 35 | No React.memo on row components | `frontend/components/RankingsTable.tsx` | 408-511 | LOW-MEDIUM |
| 36 | Rankings page unnecessarily 'use client' | `frontend/app/rankings/page.tsx` | 1 | LOW |

### I. Frontend — Static Generation & Caching

| # | Issue | File | Lines | Impact |
|---|-------|------|-------|--------|
| 37 | No generateStaticParams for popular teams | `frontend/app/teams/[id]/page.tsx` | 15 | MEDIUM |
| 38 | Inconsistent React Query staleTime | `frontend/lib/hooks.ts` | 40 | LOW |

### J. CI/CD & Infrastructure

| # | Issue | File | Impact |
|---|-------|------|--------|
| 39 | Missing pip cache in GitHub Actions | `.github/workflows/calculate-rankings.yml` | MEDIUM |
| 40 | Missing npm cache in GitHub Actions | Frontend workflows | MEDIUM |
| 41 | Rankings workflow doesn't block on active scrapes | `.github/workflows/calculate-rankings.yml:89-101` | MEDIUM |
| 42 | Suboptimal game lookup composite index | `supabase/migrations/20251126...` | MEDIUM |

---

## Implementation Roadmap (Revised After Deep Review)

### Phase 1 — Quick Wins (1-2 days, highest ROI)
- [ ] Remove 14 debug `console.log` from useRankings; keep 2 `console.error` (#32) ✅
- [ ] Replace `.select('*')` in `getTeamGames()` and `getRankings()` only (#27) ⚠️
- [ ] Skip premium profile DB query on non-premium routes in middleware (#28) ⚠️
- [ ] Add `cache: 'pip'` to 5 uncached workflows; remove 4 redundant installs (#39) ✅
- ~~[ ] Increase batch size to 200 (#18)~~ ❌ REJECTED — URI overflow risk
- ~~[ ] Use TRUNCATE instead of delete-all (#24)~~ ❌ REJECTED — bypasses safeguards
- ~~[ ] Cache team metadata across ranking passes (#13)~~ ❌ UNNECESSARY — only saves ~10s

### Phase 2 — Vectorization (3-5 days)
- [ ] Vectorize adaptive K calculation (#1)
- [ ] Vectorize context multipliers (#3)
- [ ] Replace `.map(lambda)` with `.map(dict)` (#2)
- [ ] Convert `.iterrows()` to vectorized operations (#8, #9, #10, #11, #16)
- [ ] Consolidate groupby-concat patterns (#4, #14)

### Phase 3 — Async I/O (3-5 days)
- [ ] Parallelize data adapter metadata fetches (#17)
- [ ] Parallelize ranking script metadata fetches (#23)
- [ ] Parallelize table uploads (#25)
- [ ] Replace `time.sleep()` with `asyncio.sleep()` (#19)
- [ ] Batch UPDATE calls in scraper (#20)

### Phase 4 — Frontend Optimization (2-3 days)
- [ ] Implement server-side pagination for rankings (#29)
- [ ] Add useCallback to sort handlers (#33)
- [ ] Extract row IIFEs to memoized helpers (#34)
- [ ] Add generateStaticParams for top teams (#37)
- [ ] Cache merge map resolution (#30)

### Phase 5 — Database & Infrastructure (1-2 days)
- [ ] Add composite indexes for team game lookups (#42)
- [ ] Block rankings workflow on active scrapes (#41)
- [ ] Eliminate redundant per-team scrape lookups (#21)

---

## Expected Outcomes

| Metric | Current (est.) | After Phase 1-3 | Improvement |
|--------|---------------|-----------------|-------------|
| Ranking pipeline runtime | ~35 min | ~10 min | 3.5x faster |
| Scraping pipeline runtime | ~60 min | ~20 min | 3x faster |
| Frontend rankings TTFB | ~800ms | ~300ms | 2.5x faster |
| Team detail page bandwidth | ~500KB | ~150KB | 70% reduction |
| GH Actions workflow time | ~8 min avg | ~5 min avg | 37% faster |
| Peak memory (ranking engine) | ~4GB | ~2.5GB | 37% reduction |

---

## Deep Review Findings (Appendix)

### Batch Size 100→180/200: REJECTED

**Problem:** Not an isolated config change — requires coordinated updates across 11+ files:
- `src/rankings/data_adapter.py:249`, `calculator.py:540,571`, `ranking_history.py:185,285`
- `scripts/calculate_rankings.py:76,101,475`, `scrapers/base.py:108`, `merge_suggester.py:341`
- Several queries combine `.in_()` with `.eq()`, `.gte()`, `.lte()` — adding filter overhead to URI

**URI math at batch_size=180:** ~6.85KB used / 8KB limit = only 1.15KB margin.
**Failure mode:** Silent empty results (no exception) → undetected ranking data corruption.
**Recommendation:** Keep 100 everywhere, or standardize to 150 (proven safe in 3 scripts).

### Middleware Auth Optimization: LIMITED SCOPE

**Problem:** `getSession()` in middleware refreshes expired Supabase auth tokens via cookie updates.
**Failure scenario:** Skip on public routes → token expires during browsing → user navigates to protected route → unexpected logout.
**Safe optimization:** Only skip the premium profile DB query (lines 97-101) on non-premium routes. Keep `getSession()`/`getUser()` on ALL page routes.
**Revised impact:** ~50ms savings (not 100-300ms originally estimated).

### Cache Team Metadata: UNNECESSARY

**Finding:** Two fetches serve different architectural purposes:
- Fetch 1 (line 413): SCF algorithm input (pre-ranking)
- Fetch 2 (line 568): SOS output enrichment (post-ranking)
- No writes to `teams` table between them (confirmed safe)
- **But Fetch 2 only takes ~10 seconds** — not a bottleneck vs. Pass 1/2 (minutes)

### Console.log Removal: ALREADY HANDLED

**Finding:** `next.config.ts` has `compiler.removeConsole` that strips `console.log` in production.
Only `console.error` and `console.warn` survive to production. Removal is dev cleanup only.
**Critical:** 2 `console.error` statements (lines 79, 94) are filtered by E2E test `homepage.spec.ts:70-71` — do NOT remove.

### GH Actions Caching: SAFE BUT COMPLEX

**Findings:**
- No npm workflows exist (Vercel handles frontend deployment)
- 5/16 workflows lack pip caching entirely
- 4 workflows have redundant `pip install` after `requirements.txt` (packages already included)
- `process-missing-games.yml` runs hourly — biggest win (~120-180 min/week saved)
- Mixed `setup-python@v4` vs `@v5` — should standardize to `@v5`
- 6 workflows use selective `pip install pkg1 pkg2` instead of `requirements.txt` — poor cache key match
