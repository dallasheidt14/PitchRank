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

---

## Top 10 High-ROI Improvements (Prioritized)

### 1. Parallelize Sequential Supabase Batch Fetches
- **Files:** `src/rankings/data_adapter.py:251-269`, `scripts/calculate_rankings.py:470-488`
- **Problem:** Team metadata fetched sequentially in 100-ID batches via for-loop. With 100K teams, this is 1,000+ serial API calls.
- **Fix:** Use `asyncio.gather()` with 10-20 concurrent batches.
- **Impact:** **CRITICAL** — 50-100x faster metadata fetching (from ~15 min to ~15 sec)
- **Effort:** Medium

### 2. Vectorize `.apply(axis=1)` in v53e Engine
- **File:** `src/etl/v53e.py:1002-1006, 787, 1021, 1415-1416`
- **Problem:** Adaptive K-factor, context multipliers, and power mapping use row-by-row `.apply()` and `.map(lambda)`. Called on 100K+ game rows.
- **Fix:** Replace with vectorized `.map(dict)`, `np.where()`, and direct column arithmetic.
- **Impact:** **HIGH** — 10-30% speedup on v53e calculation (5-15 min savings)
- **Effort:** Medium

### 3. Use TRUNCATE Instead of Delete-All for Rankings
- **File:** `scripts/calculate_rankings.py:245`
- **Problem:** Deletes all rows with `.delete().neq('team_id', '00000000...')` — full table scan on 1M+ rows.
- **Fix:** Use Supabase RPC to call `TRUNCATE rankings_full` directly.
- **Impact:** **HIGH** — 2-5 min savings per ranking run
- **Effort:** Low

### 4. Optimize Frontend Middleware Auth Checks
- **File:** `frontend/middleware.ts:67-68, 97-101`
- **Problem:** Calls `getSession()` AND `getUser()` on **every request** (including public pages). Premium route check adds a third DB query.
- **Fix:** Only check auth on protected routes; remove redundant `getSession()` when `getUser()` is called.
- **Impact:** **HIGH** — 100-300ms reduction on every page load
- **Effort:** Low

### 5. Replace `.select('*')` with Column-Specific Queries
- **File:** `frontend/lib/api.ts:48, 99-101, 140, 379, 495, 677, 683`
- **Problem:** 7+ queries fetch all columns from teams, rankings_full, and games tables. These tables have 50+ columns; most views need 5-10.
- **Fix:** Specify exact columns needed per query.
- **Impact:** **HIGH** — 40-70% bandwidth reduction on team detail and rankings pages
- **Effort:** Low

### 6. Remove Debug Console Logging from useRankings
- **File:** `frontend/hooks/useRankings.ts:19-207`
- **Problem:** 12+ `console.log` statements execute on every query, including full result dumps.
- **Fix:** Remove or gate behind `process.env.NODE_ENV === 'development'`.
- **Impact:** **MEDIUM** — Immediate production perf improvement, DevTools won't slow down
- **Effort:** Trivial

### 7. Cache Team State Metadata Across Ranking Passes
- **File:** `src/rankings/calculator.py:569-585`
- **Problem:** Team state metadata is fetched in Pass 1, then fetched again identically in Pass 3.
- **Fix:** Store result from Pass 1 and reuse in Pass 3.
- **Impact:** **MEDIUM** — Eliminates ~1,000 redundant Supabase API calls per ranking run
- **Effort:** Low

### 8. Increase Batch Size from 100 to 200 UUIDs
- **File:** `src/rankings/data_adapter.py:249`
- **Problem:** Batch size of 100 UUIDs (~3.6KB) is conservative; Supabase supports 8KB URIs (~200 UUIDs safely).
- **Fix:** Change `batch_size = 100` to `batch_size = 200`.
- **Impact:** **MEDIUM** — 50% fewer API calls for team metadata fetches
- **Effort:** Trivial

### 9. Add pip/npm Caching to GitHub Actions
- **Files:** `.github/workflows/calculate-rankings.yml:70-71`, all frontend workflows
- **Problem:** Every workflow run installs all dependencies from scratch.
- **Fix:** Add `cache: 'pip'` to `setup-python` and `cache: 'npm'` to `setup-node`.
- **Impact:** **MEDIUM** — 3-5 min saved per workflow run × 15+ workflows/week
- **Effort:** Trivial

### 10. Consolidate groupby-concat Patterns in v53e
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

## Implementation Roadmap

### Phase 1 — Quick Wins (1-2 days, highest ROI)
- [ ] Remove debug logging from useRankings (#32)
- [ ] Replace `.select('*')` with specific columns (#27)
- [ ] Optimize middleware to skip auth on public routes (#28)
- [ ] Increase batch size to 200 (#18)
- [ ] Add pip/npm caching to workflows (#39, #40)
- [ ] Use TRUNCATE instead of delete-all (#24)
- [ ] Cache team metadata across ranking passes (#13)

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
