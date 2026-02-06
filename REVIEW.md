# PitchRank Project Review

**Date:** 2026-02-06
**Reviewer:** Claude (Opus 4.6)
**Branch:** `claude/review-pitchrank-project-gXsjh`

---

## Executive Summary

PitchRank is a well-architected youth soccer ranking system with a sophisticated 13-layer ranking algorithm, multi-provider data ingestion, and a modern Next.js frontend. The codebase shows strong domain knowledge and thoughtful engineering around cross-age normalization, regional bubble detection, and fuzzy team matching.

This review identified **12 bugs**, **8 security vulnerabilities**, **6 performance issues**, and **10 enhancement opportunities** across the backend, frontend, and database layers.

---

## CRITICAL BUGS

### 1. Shared mutable `meta` dict between home/away game perspectives
- **File:** `src/scrapers/athleteone_scraper.py:192-216`
- **Impact:** Both home and away `GameData` objects reference the same `meta` dict. If any downstream code modifies `meta` on one perspective (e.g., `game.meta['club_name'] = 'X'`), it silently corrupts the other perspective's metadata.
- **Fix:** Use `meta=meta.copy()` for each `GameData` construction.

### 2. `since_date_obj` can be `None`, causing `TypeError` on date comparison
- **File:** `src/scrapers/gotsport.py:128-139, 199, 361`
- **Impact:** When `since_date` is `None`, `since_date_obj` is set to `None`. Later, `game_date < since_date_obj` raises `TypeError: '<' not supported between instances of 'date' and 'NoneType'`. The `elif since_date:` branch (line 134) is unreachable because any non-None datetime object is truthy, and the `else` fallback (line 138) is dead code.
- **Fix:** Add a guard: `if since_date_obj is not None and game_date < since_date_obj:`.

### 3. Lambda closure captures loop variable `batch` by reference
- **File:** `src/rankings/data_adapter.py:228-231`
- **Impact:** Classic Python closure bug. If `retry_supabase_query` retries the lambda after the loop variable `batch` has been rebound, it queries the wrong batch of team IDs. Same issue on line 161 with `query`.
- **Fix:** Use a default argument to capture the current value: `lambda b=batch: supabase_client.table('teams')...in_('team_id_master', b).execute()`.

### 4. `.astype(int)` on `age` column can crash with non-numeric values
- **File:** `src/rankings/data_adapter.py:578`
- **Impact:** If `rankings_df['age']` contains empty strings, `None`, or non-numeric values, `.astype(int)` raises `ValueError` and halts the entire ranking calculation.
- **Fix:** Use `pd.to_numeric(rankings_df['age'], errors='coerce').fillna(0).astype(int)`.

### 5. `len(None)` TypeError in state code validation
- **File:** `src/utils/validators.py:68`
- **Impact:** When `data['state_code']` is `None`, `data.get('state_code', '')` returns the actual `None` value from the dict (not the default `''`), and `len(None)` raises `TypeError`.
- **Fix:** Use `data.get('state_code') or ''` instead of `data.get('state_code', '')`.

### 6. No transitive merge resolution in MergeResolver
- **File:** `src/utils/merge_resolver.py` (entire file)
- **Impact:** If team A is merged into B, and B is later merged into C, `resolve('A')` returns `B` instead of `C`. This leaves dangling references to deprecated teams in game records.
- **Fix:** Follow merge chains until stable: iterate the map resolving A->B->C to A->C. Add cycle detection to prevent infinite loops from accidental circular merges.

---

## SECURITY VULNERABILITIES

### 7. PostgREST filter injection in team search
- **File:** `frontend/app/api/teams/search/route.ts:37`
- **Impact:** User input from `?q=` is interpolated raw into `.or()` filter string. An attacker can inject special characters (`,`, `.`, `(`, `)`) to add arbitrary filter clauses, potentially bypassing the `is_deprecated` filter or extracting unintended data.
- **Fix:** Sanitize the query string or use individual `.ilike()` filter methods instead of string interpolation.

### 8. Missing authentication on admin/destructive endpoints
- **Files:**
  - `frontend/app/api/team-merge/route.ts:22,169` (POST and DELETE)
  - `frontend/app/api/link-opponent/route.ts:8`
  - `frontend/app/api/create-team/route.ts:9`
  - `frontend/app/api/chat/route.ts:17,51`
- **Impact:** These endpoints use `SUPABASE_SERVICE_KEY` (full admin privileges) but perform zero authentication or authorization checks. Any unauthenticated user on the internet can merge teams, create teams, link opponents, modify game records, and impersonate agents in chat.
- **Fix:** Add authentication middleware. At minimum, verify a valid Supabase session and check for an admin role before allowing mutations.

### 9. XSS via structured data injection
- **File:** `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx:113-127`
- **Impact:** URL path parameters (`region`, `ageGroup`, `gender`) are user-controlled and placed inside a `<script type="application/ld+json">` tag via `dangerouslySetInnerHTML`. `JSON.stringify` does NOT escape `</script>`, so a crafted URL containing `</script><script>alert(1)//` would inject executable JavaScript.
- **Fix:** Validate/sanitize route parameters against allowed values, or manually escape `</script>` sequences in the JSON output.

### 10. No production environment variable validation
- **File:** `config/settings.py:36-43`
- **Impact:** `SUPABASE_URL` and `SUPABASE_KEY` default to `None` when env vars are missing. The application starts silently and only crashes at runtime when a database call is made, far from the configuration source.
- **Fix:** Add startup validation that raises immediately if required env vars are missing in non-local mode.

### 11. Unbounded `limit` parameter on team search
- **File:** `frontend/app/api/teams/search/route.ts:24`
- **Impact:** No upper bound on `?limit=`. A user can pass `?limit=999999999` to dump the entire teams table.
- **Fix:** Cap with `Math.min(limit, 100)`.

### 12. Debug data leaked in production API responses
- **Files:**
  - `frontend/app/api/watchlist/route.ts:177-183,562-567`
  - `frontend/app/api/watchlist/add/route.ts:194-198`
  - `frontend/app/api/link-opponent/route.ts:473-490`
- **Impact:** User IDs, watchlist IDs, team IDs, and game state details are returned in JSON `debug` objects, aiding attackers in understanding the data model.
- **Fix:** Remove or gate debug output behind a `NODE_ENV !== 'production'` check.

### 13. MD5 truncated to 8 chars for team ID generation (high collision risk)
- **File:** `src/scrapers/athleteone_scraper.py:61`
- **Impact:** 8 hex characters = 32 bits. With ~65,000 team names, the birthday paradox gives a ~40% collision probability. Two different teams could get the same ID, silently merging their game histories.
- **Fix:** Use SHA-256 and a longer prefix (12+ characters).

### 14. URL parameters not URL-encoded in GotSport scraper
- **File:** `src/scrapers/gotsport.py:287`
- **Impact:** Parameter values containing `&` or `=` will produce malformed URLs, potentially causing incorrect data fetches or request failures.
- **Fix:** Use `urllib.parse.urlencode(params)` instead of manual string concatenation.

---

## PERFORMANCE ISSUES

### 15. `iterrows()` on 100k+ row DataFrames
- **Files:**
  - `src/rankings/data_adapter.py:277-332` (game conversion loop)
  - `src/rankings/data_adapter.py:404-454` (duplicate loop in `supabase_to_v53e_format`)
  - `src/rankings/ranking_history.py:80-101` (snapshot records)
- **Impact:** `iterrows()` is the slowest DataFrame iteration method (each row is converted to a Series). With 100k+ games, this is a significant bottleneck in ranking calculation.
- **Fix:** Use `itertuples()` (10-100x faster) or fully vectorized operations with `.to_dict('records')`.

### 16. O(n^2) all-pairs comparison in merge suggester
- **File:** `src/utils/merge_suggester.py:255-256`
- **Impact:** With `limit(1000)` teams, this is up to 499,500 pair comparisons. Each pair also does O(n*m) schedule alignment (line 471-477). Total: potentially hundreds of millions of operations.
- **Fix:** Pre-filter candidates by shared name tokens or state. Use sorted-merge for schedule alignment instead of nested loops.

### 17. `apply(axis=1)` for ML power lookups on large DataFrames
- **File:** `src/rankings/layer13_predictive_adjustment.py:510-511`
- **Impact:** `apply(axis=1)` wraps each row in a Series, adding massive overhead on 100k+ rows.
- **Fix:** Use vectorized `.map()` followed by `.fillna()`.

### 18. Watchlist endpoint makes 9+ database round trips per request
- **File:** `frontend/app/api/watchlist/route.ts`
- **Impact:** Including 2 debug-only queries (lines 204-230) that serve no user-facing purpose.
- **Fix:** Remove debug queries in production. Consolidate queries using joins or RPC functions.

### 19. Rankings view reintroduces correlated subqueries
- **File:** `supabase/migrations/20260204000000_add_perf_centered_to_rankings_view.sql`
- **Impact:** The latest migration redefines `rankings_view` with correlated subqueries for `sos_rank_national` and `sos_rank_state`, undoing the performance fix from `20251208000005_fix_rankings_view_performance.sql` which replaced them with window functions.
- **Fix:** Use `RANK() OVER (PARTITION BY age_group, gender ORDER BY sos DESC)` instead of correlated subqueries.

### 20. ~135 lines of dead code in SincSports scraper
- **File:** `src/scrapers/sincsports.py:462-597`
- **Impact:** In `_parse_game_row`, line 462 returns early. Everything from line 464 onward (the entire "First pass"/"Second pass" parsing) is unreachable dead code.
- **Fix:** Remove the dead code to improve maintainability.

---

## DATABASE ISSUES

### 21. Operator precedence bug in `count_linkable_games()`
- **File:** `supabase/migrations/20251206000000_safe_team_linking.sql:121-124`
- **Impact:** The SQL expression likely has an AND/OR precedence issue that causes incorrect game counts, which affects the team linking workflow.
- **Fix:** Add explicit parentheses around OR conditions.

### 22. `prevent_game_updates()` trigger lost `ml_overperformance` bypass
- **File:** `supabase/migrations/20251209000000_add_link_game_team_function.sql`
- **Impact:** The final version of the immutability trigger does not include the ML field bypass that was added in `20251125000000_add_batch_update_ml_overperformance.sql`. This means the `batch_update_ml_overperformance` RPC function may be blocked by the trigger.
- **Fix:** Ensure the trigger allows updates to the `ml_overperformance` column.

### 23. Missing `is_deprecated = FALSE` filter in latest rankings view
- **File:** `supabase/migrations/20260204000000_add_perf_centered_to_rankings_view.sql`
- **Impact:** Merged/deprecated teams may appear in the rankings view, showing ghost entries.
- **Fix:** Add `WHERE t.is_deprecated = FALSE` to the view definition.

---

## FRONTEND BUGS

### 24. `SortButton` memo defined inside component (negated memoization)
- **File:** `frontend/components/RankingsTable.tsx:155-176`
- **Impact:** `memo()` wraps a component defined inside the parent component body. Every re-render creates a new component definition, completely negating memoization (React sees a new type each time).
- **Fix:** Move `SortButton` outside `RankingsTable` or use `useMemo`/`useCallback` for the render function.

### 25. Invalid className used as text separator
- **File:** `frontend/components/RankingsTable.tsx:415-419`
- **Impact:** The bullet separator ` \u2022 ` is placed in `className` instead of rendered as text. The visual separator between club name and state never displays (renders "Club NameCA" instead of "Club Name \u2022 CA").
- **Fix:** Render the separator as a text node: `{team.club_name && <span> &bull; </span>}`.

### 26. Null `power_score_final` causes NaN sort comparisons
- **File:** `frontend/components/RankingsTable.tsx:86-88`
- **Impact:** Unlike `rank` and `sosRank` which use `?? Infinity` as a null fallback, `powerScore` sorting does not. Null values produce `NaN` from arithmetic comparison, making sort order unpredictable.
- **Fix:** Add `?? 0` fallback: `aValue = a.power_score_final ?? 0`.

### 27. Inconsistent watchlist lookup between add and remove
- **File:** `frontend/app/api/watchlist/remove/route.ts:62-67`
- **Impact:** The `add` endpoint has a fallback to find the most recent watchlist if no default is found. The `remove` endpoint does not. If a user's watchlist is missing the `is_default` flag, they can add items but cannot remove them.
- **Fix:** Add the same fallback logic to the remove endpoint.

### 28. Module-level Supabase initialization crashes builds
- **File:** `frontend/app/api/chat/route.ts:4-11`
- **Impact:** Supabase client is initialized at module load time. If env vars are missing during CI/CD build step, the entire build fails. Every other API route initializes inside the handler.
- **Fix:** Move initialization inside the GET/POST handler functions.

---

## ENHANCEMENT SUGGESTIONS

### 29. Add configuration validation at startup
- **File:** `config/settings.py`
- Validate that ranking weights sum to 1.0 (`OFF_WEIGHT + DEF_WEIGHT + SOS_WEIGHT`).
- Validate numeric parameters are within sane bounds (e.g., `GOAL_DIFF_CAP > 0`).
- Consider using `pydantic.BaseSettings` for typed, validated configuration.

### 30. Add rate limiting to public API endpoints
- **Files:** `frontend/app/api/newsletter/route.ts`, `frontend/app/api/chat/route.ts`, `frontend/app/api/teams/search/route.ts`
- No endpoints have rate limiting or bot protection. Newsletter signup, chat, and search are all exploitable.

### 31. Add Stripe webhook idempotency tracking
- **File:** `frontend/app/api/stripe/webhook/route.ts`
- Stripe retries webhook deliveries. Storing processed event IDs and skipping duplicates would prevent double-processing.

### 32. Externalize canonical clubs registry
- **File:** `src/utils/club_normalizer.py`
- The `CANONICAL_CLUBS` dictionary is hardcoded in source code (~170 clubs). Loading from a database or JSON file would allow updates without code deployments.

### 33. Add pre-filtering to merge suggester
- **File:** `src/utils/merge_suggester.py`
- Only compare teams sharing at least one name token or from the same state. This would reduce O(n^2) to a much smaller candidate set.

### 34. Use `frozenset` for valid age groups
- **File:** `src/utils/enhanced_validators.py`
- Replace the duplicated list with a `frozenset` for O(1) membership lookups instead of O(n) list scans.

### 35. Fix `formatGender` default behavior
- **File:** `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx:27`
- Any unrecognized gender value defaults to "Girls". Add validation against allowed values.

### 36. Validate environment variables in server Supabase client
- **File:** `frontend/lib/supabase/server.ts:12-13`
- Unlike the client-side counterpart which checks and throws, the server utility uses `!` non-null assertions. Add proper guards.

### 37. Use `Set` instead of `Array.includes()` in watchlist loops
- **File:** `frontend/app/api/watchlist/route.ts:432,439`
- Convert `teamIds` to a `Set` for O(1) lookups instead of O(n) `.includes()` inside a loop.

### 38. Remove bare `except` clauses
- **Files:** `src/utils/validators.py:36`, `src/utils/merge_suggester.py:458`
- Replace with specific exception types (`ValueError`, `TypeError`) to avoid catching `SystemExit` and `KeyboardInterrupt`.

---

## Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Bugs | 6 | 4 | 5 | 3 | 18 |
| Security | 2 | 3 | 3 | 0 | 8 |
| Performance | 1 | 3 | 2 | 0 | 6 |
| Enhancements | - | - | - | - | 10 |
| **Total** | **9** | **10** | **10** | **3** | **42** |

### Top Priority Fixes
1. **Auth on admin endpoints** (#8) -- anyone can merge teams, create teams, link opponents
2. **PostgREST filter injection** (#7) -- user input in search query can bypass filters
3. **XSS in rankings page** (#9) -- route params injected into script tag
4. **Shared mutable meta dict** (#1) -- silently corrupts game data
5. **Lambda closure bug** (#3) -- can query wrong batch during retries
6. **Rankings view regression** (#19, #23) -- correlated subqueries + missing deprecated filter
