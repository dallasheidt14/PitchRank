---
status: done
---

# Plan: Fix Supabase RPC statement timeouts (error 57014) on rankings RPCs

## Context

During Vercel builds the rankings pages pre-fetch data through four Postgres RPCs
(`get_national_rankings`, `get_national_rankings_count`, `get_state_rankings`,
`get_state_rankings_count`). These run under the **anon** Postgres role, which has a
**3-second `statement_timeout`**. The latest production build logged **121** `57014`
("canceling statement due to statement timeout") errors; the build still deploys
(pages are wrapped in try/catch), but pages that timed out render with **empty rankings
data** for up to an hour (ISR `revalidate=3600`).

Root cause (confirmed via `EXPLAIN ANALYZE` on project `pfkrhmprwxtghtpinrot`): the age
filter inside these RPCs is a **non-sargable regex** on `rankings_full.age_group`
(`CASE WHEN age_group ~ '^[uU][0-9]+$' THEN regexp_replace(...)::int ... END = <age>`),
so the planner **cannot use** `idx_rankings_full_age_gender (age_group, gender)` and does
a full parallel seq scan of the 126k-row table (joined to 173k `teams`). Warm/isolated
that is ~0.1–0.5 s, but cold cache (right after the weekly ranking refresh) plus ~8
concurrent RPCs per SSG page pushes it past the 3 s anon ceiling.

**Fix (scope-limited, database-only):** rewrite the age predicate in all four RPCs to a
**sargable equality list** so the planner uses the existing composite index. Nothing else
changes — output columns, row ordering, and every call site stay identical. Empirically
validated: the sargable list returns the **identical row set** the regex returns (all 9
stored age forms round-trip), and the planner switches from Seq Scan to **Bitmap Index
Scan** on `idx_rankings_full_age_gender`.

**Explicitly out of scope** (deliberately cut after blast-radius analysis):
- No change to ordering / no new sort index. Every build caller passes an age + gender, so
  cohorts are small and sort in memory once the index narrows them; the only case that
  would benefit from a sort index is a fully-unfiltered national list, which the build
  never calls. Touching `ORDER BY` carries divergence risk against the `rankings_view`
  fallback for no build-time benefit.
- No change to the anon role `statement_timeout`.
- No service-role routing / no `frontend/lib/api.ts` change.
- No change to any function's `RETURNS TABLE` columns, the `has_modular11_alias` EXISTS
  subquery, the gender filter, or the output `normalized_age`/`age` projection.

## Pattern Survey

**Analogous features (current RPC definitions — copy each verbatim, change only the age WHERE):**
- `get_national_rankings` — `supabase/migrations/20260505000000_add_league_distinction_to_rankings_rpcs.sql:9-217`. Age predicate to replace: lines **134-154** (`an.age_val IS NULL OR <regex CASE> = an.age_val`). `age_norm` CTE already remaps param 18→19 (lines 52-58). Output `normalized_age` regex at lines 80-96 — **leave untouched**. `ORDER BY b.rank_in_cohort_final ASC NULLS LAST, b.team_id_master ASC` (lines 209-211) — **leave untouched**.
- `get_state_rankings` — `supabase/migrations/20260505200000_fix_state_rankings_age_cast.sql:13-186` (this hotfix supersedes the copy in `20260505000000`). Age predicate: the `(<regex CASE>) = p_age::INTEGER` block (≈ lines 110-116). Confirm whether it applies the 18→19 remap; if it casts `p_age::INTEGER` directly, the new predicate must remap on the param side (see Step 2).
- `get_national_rankings_count` — `supabase/migrations/20260406000000_add_get_national_rankings_rpc.sql:212-260`. Age predicate: lines **231-251**. Uses the same `age_norm` 18→19 CTE.
- `get_state_rankings_count` — `supabase/migrations/20260325000000_merge_u18_into_u19_age_remap.sql:429-467`. Age predicate with explicit 18→19 remap on both sides (≈ lines 439-462).

**Reusable utilities / convention anchors:**
- Index already present: `idx_rankings_full_age_gender ON rankings_full (age_group, gender)` (`supabase/migrations/20250120130000_create_rankings_full.sql:75-81`). The fix relies on this — **no new index needed**.
- Prior art for sargable age equality in an RPC: `get_team_state_rank` already does `rf.age_group = ti.age_group` (`supabase/migrations/20260404000001_update_views_use_rank_final.sql:429,437`).
- Migration naming: `YYYYMMDDHHMMSS_snake_case.sql`; new file must sort **after** `20260505200000`. Functions are superseded with `CREATE OR REPLACE` (no `DROP` needed here — signatures and return columns are unchanged) and a re-issued `GRANT EXECUTE ... TO anon; ... TO authenticated;` per function. No `CONCURRENTLY`, no functional indexes exist in the tree (none needed).

**Proposed alignment:** one new migration `supabase/migrations/20260603000000_sargable_age_filter_rankings_rpcs.sql` containing `CREATE OR REPLACE` for all four functions (bodies copied verbatim from the sources above with only the age WHERE predicate swapped) plus the four GRANT pairs.

## Blast Radius (verified — why this is safe)

- **Consumers of the 4 RPCs are frontend-only:** `frontend/lib/api.ts:90,124,197,211`,
  `frontend/app/api/rankings/national/route.ts:42`, `frontend/app/api/rankings/state/route.ts:43`
  (`useRankings.ts` calls those routes). **No** Python, scripts, edge functions, views,
  triggers, RLS policies, or other SQL functions reference them by name (only their own
  GRANTs). None are edited by this plan.
- **Callers always send `p_age` as a bare integer string** (`"14"`, or `""` for national
  "all ages") via `normalizeAgeGroup` (`frontend/lib/utils.ts:219-249`). The new predicate
  must reconstruct the stored form (`'u'||N`) — callers do **not** send `"u14"`.
- **Ordering / pagination:** callers page in 1000-row batches relying on the
  `team_id_master ASC` final tiebreak — preserved (ORDER BY untouched).
- **Pre-existing state list/count 18→19 divergence (NOT introduced here).** `get_state_rankings`
  does **not** remap `u18`→19 while `get_state_rankings_count` does (see Step 2). So whenever
  `u18` rows exist, the state count already includes them in the U19 cohort and the state list
  already excludes them — they diverge today. This plan **preserves** each function's existing
  behavior (Group A vs Group B in Step 2); it does **not** try to reconcile them. Aligning the
  two would be a separate, deliberate behavior change, out of scope here.
- **Behavior-preserving on current data (empirically verified):**
  - All 9 stored `age_group` forms (`u10`–`u17`, `u19`) round-trip: `'u'||regex_norm = age_group` is true for every one; zero digit-only / uppercase / other forms; zero `u18` rows currently. Because there are **zero `u18` rows now**, the Group A vs Group B difference is unobservable today — it only matters if `u18` rows reappear before the next ranking run.
  - Within the RPC universe (89,876 rows): bare `rank_in_cohort_final` is identical to the
    `COALESCE` expression (`active_null_final=0`, `nonactive_with_final=0`, fallback fires 0×) — relevant only as confirmation that we are NOT relying on this for the cut sort change.

## Implementation Steps

1. **Create the migration file**
   - New file `supabase/migrations/20260603000000_sargable_age_filter_rankings_rpcs.sql`.
   - Header comment summarizing the change (sargable age filter; no output/ordering change).
   - For each of the four functions, paste its **current full definition** copied verbatim
     from the source migration cited in Pattern Survey, as `CREATE OR REPLACE FUNCTION ...`.
     Do **not** alter `RETURNS TABLE`, the SELECT projection, the `EXISTS has_modular11_alias`
     subquery, the gender filter, or the `ORDER BY`.
   - Use `CREATE OR REPLACE` **only — no `DROP FUNCTION`**. The source migrations led with
     `DROP FUNCTION IF EXISTS` solely because they were changing the return columns (adding
     `league`/`distinction`), which `CREATE OR REPLACE` cannot do. This change keeps every
     signature and `RETURNS TABLE` identical, so `CREATE OR REPLACE` is sufficient and
     preserves existing GRANTs. Do not mirror the local `DROP` convention (a `DROP` would
     briefly remove the function + its GRANTs mid-deploy).

2. **Replace only the age WHERE predicate in each function** with a sargable equality list.
   **CRITICAL — the predicate is differentiated per function by that function's _current_
   18→19 behavior. Do not apply one blanket predicate to all four.** Verified from source:
   - `get_national_rankings` (`20260505000000:138-153`), `get_national_rankings_count`
     (`20260406000000:231-251`), and `get_state_rankings_count` (`20260325000000:442-458`)
     **fold `u18`→19 today** (their regex CASE remaps the stored side and the param side).
   - `get_state_rankings` (`20260505200000:109-116`) does **NOT** remap — it compares
     `<regex> = p_age::INTEGER` with no `=18 THEN 19` wrapper, so a U19 request matches only
     `u19` rows. (Callers already pre-remap 18→19 in `normalizeAgeGroup`, so the param side
     never sees `18` in practice; the point is the **stored** side must not start folding
     `u18` into 19 where it currently doesn't.)

   **Group A — fold 18→19 (national list, national count, state count).** Let `N` be the
   function's existing **remapped** age target (`an.age_val` for national list + national
   count; the `CASE WHEN ... = 18 THEN 19 ELSE ... END` param expression for state count).
   Replace the regex predicate with `rf.age_group = ANY(CASE WHEN N = 19 THEN
   ARRAY['u19','U19','19','u18','U18','18'] ELSE ARRAY['u'||N::text,'U'||N::text,N::text] END)`.
   **Whether that clause is wrapped in the `an.age_val IS NULL OR ...` all-ages branch is
   per-function — do not generalize "count = no wrapper":**
   - **`get_national_rankings` AND `get_national_rankings_count`** — both have the `age_norm`
     CTE and an "all ages" mode (called with `p_age=''`, `api.ts:124,211`), so both **keep**
     the wrapper:
     ```sql
     AND (
       an.age_val IS NULL
       OR rf.age_group = ANY (
            CASE WHEN an.age_val = 19
                 THEN ARRAY['u19','U19','19','u18','U18','18']
                 ELSE ARRAY['u'||an.age_val::text, 'U'||an.age_val::text, an.age_val::text]
            END
          )
     )
     ```
     (Dropping the wrapper on `get_national_rankings_count` would make the national all-ages
     count return 0 and break every "showing X of Y" total.)
   - **`get_state_rankings_count` ONLY** — has no "all ages" mode (`p_state`+`p_age` always
     supplied), so it **omits** the wrapper and uses the bare clause, with `N` = its existing
     remapped param expression `CASE WHEN p_age::INTEGER = 18 THEN 19 ELSE p_age::INTEGER END`:
     ```sql
     AND rf.age_group = ANY (
          CASE WHEN (CASE WHEN p_age::INTEGER = 18 THEN 19 ELSE p_age::INTEGER END) = 19
               THEN ARRAY['u19','U19','19','u18','U18','18']
               ELSE ARRAY['u'||(p_age::INTEGER)::text, 'U'||(p_age::INTEGER)::text, (p_age::INTEGER)::text]
          END
        )
     ```
     (`p_age::INTEGER` is used directly in the ELSE branch — the 18→19 remap is a no-op for
     every non-19 cohort, and `get_state_rankings_count` has no `age_norm`/`N` binding.)

   **Group B — NO remap (state list `get_state_rankings` only).** Let `N = p_age::INTEGER`
   (the function's current target, un-remapped). The list is **always** the three plain forms
   — it must **never** include `u18`, so the U19 cohort stays `u19`-only exactly as today:
   ```sql
   AND rf.age_group = ANY (ARRAY['u'||N::text, 'U'||N::text, N::text])
   ```

   - **Rationale / contract:** `age_group` is contractually `uNN` lowercase — the ranking
     pipeline writes it as `f"u{int(float(x))}"` (`src/rankings/data_adapter.py:714-716`).
     There is **no DB CHECK constraint** enforcing the format (`rankings_full.age_group` is
     just `TEXT NOT NULL`, `20250120130000_create_rankings_full.sql:8`), so the `uNN` shape
     is a convention. The tolerant list (`'u'||N`,`'U'||N`,`N::text`) covers the realistic
     non-canonical forms while staying sargable (verified: Bitmap Index Scan on
     `idx_rankings_full_age_gender`). It **intentionally drops the regex's third arm**
     (`age_group ~ '[0-9]+'` substring, which matched embedded-digit junk like `u14b` /
     `14-ECNL`) — keeping it would force a non-sargable scan and defeat the fix. This narrows
     the predicate vs. the regex, but it **fails closed** (an unmatched row is omitted, not
     mis-bucketed) and matches zero rows today (live data is 100% `u10`–`u17`,`u19`).
   - **Watch item:** `scripts/backfill_rankings_full.py:112` copies raw `teams.age_group`
     into `rankings_full` with no normalization — the one path that could introduce a messy
     form a sargable list would silently drop. Out of scope here, but normalize there (or add
     a CHECK) if non-`uNN` forms ever appear.
   - Leave the output `normalized_age` / `age` projection regex **unchanged** so returned
     `age` values are byte-identical.

3. **Re-issue GRANTs** at the end of the migration for all four functions:
   `GRANT EXECUTE ON FUNCTION <name>(<arg types>) TO anon;` and `... TO authenticated;`
   (match the exact argument-type signatures from each source migration).

4. **Apply the migration** to project `pfkrhmprwxtghtpinrot` (Supabase MCP `apply_migration`
   or the CLI). Prefer a window when the weekly ranking job is **not** writing
   `rankings_full`. `CREATE OR REPLACE FUNCTION` takes only a brief lock; no table rewrite.

## Verification

Run against project `pfkrhmprwxtghtpinrot` after applying:

1. **Planner uses the index (the actual fix).** For a representative cohort:
   ```sql
   EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM get_national_rankings('12','M',1000,0);
   ```
   Expect a **Bitmap Index Scan on `idx_rankings_full_age_gender`** (not a Seq Scan on
   `rankings_full`) and execution time in the low tens of ms.

2. **Row-set + ordering parity (regression guard).** Before applying, snapshot current output
   for several cohorts spanning the edge cases — e.g. `('12','M')`, `('12','F')`,
   `('19','M')` (U18/U19 merge), `('14','')` national all-genders, and a state call
   `get_state_rankings('AZ','14','M',2000,0)` — into temp tables. After applying, re-run and
   diff: the team sets, the `age` column, and the row order (by returned position) must be
   **identical**. Pay special attention to the `19` cohort count being unchanged.

3. **Count == list parity (with one known exception).** For each cohort tested,
   `get_*_rankings_count(...)` should equal the number of rows `get_*_rankings(...)` returns
   with a large limit, so the UI "showing X of Y" stays correct. **Do not treat the U19 state
   cohort as a hard parity gate:** `get_state_rankings` (no remap) and `get_state_rankings_count`
   (remaps 18→19) diverge there *by design / pre-existing behavior* if any `u18` rows exist
   (see Blast Radius). With current data (0 `u18` rows) they match exactly; assert parity for
   all national cohorts and non-19 state cohorts, and verify the 19-cohort numbers equal the
   pre-change baseline (snapshot in step 2) rather than equal each other.

4. **Build-time confirmation.** Trigger a production build and confirm the build log no longer
   contains `57014` / "statement timeout" for the rankings RPCs (latest build had 121).

Edge cases to spot-check: empty `p_age` (national "all ages") still returns the full national
set; gender `''` still returns both; an age with zero teams returns an empty list (not an error).

## Context Files

- `supabase/migrations/20260505000000_add_league_distinction_to_rankings_rpcs.sql` — current `get_national_rankings` (and the superseded state copy); the age predicate and output projection to preserve.
- `supabase/migrations/20260505200000_fix_state_rankings_age_cast.sql` — current `get_state_rankings`; confirm its exact age/remap expression.
- `supabase/migrations/20260406000000_add_get_national_rankings_rpc.sql` — current `get_national_rankings_count`.
- `supabase/migrations/20260325000000_merge_u18_into_u19_age_remap.sql` — current `get_state_rankings_count` and the canonical 18→19 remap logic to mirror.
- `supabase/migrations/20250120130000_create_rankings_full.sql` — confirms `idx_rankings_full_age_gender` and the `rankings_full` column list.
- `frontend/lib/api.ts` — the only consumer (read to confirm `p_age` is a bare integer string and ordering/pagination assumptions; not edited).
