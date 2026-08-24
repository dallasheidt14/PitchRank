---
status: done
---

# Plan: Fix rank_change_7d apples-to-oranges bug

## Context

The "rank-change" arrow next to a team's rank on the public rankings page is wrong for top-of-cohort teams. The trigger case: Illinois Magic FC 2014 (u12 male, team_id `36d80476-f198-4b2c-bdf6-ac5a52dbf99f`) shows `#1 ↓16`. Stored value: `rankings_full.rank_change_7d = -16`. With `rank_in_cohort_final = 1` today, that math is impossible — historical rank would have to be -15.

Root cause traced: `calculate_rank_changes` runs inside `compute_rankings_with_ml` (the per-cohort pass) at `src/rankings/calculator.py:2209-2226`. At that point the DataFrame is `teams_with_ml`, which does **not** yet have `rank_in_cohort_final` populated — that column is set later in `compute_all_cohorts` at lines `3111-3134` (post-concat, after monotonicity enforcement). So `calculate_rank_changes` falls back to `rank_in_cohort_ml` for the "current" rank (today: 23 for this team), while `get_historical_ranks` resolves the historical side to `rank_in_cohort_final` from the snapshot 7 days ago (then: 7). Result: `7 − 23 = -16`, stored on a row whose displayed rank is then overridden to `#1` by the later final-rank pass.

The fix is to relocate the `calculate_rank_changes` call into `compute_all_cohorts`, immediately after `rank_in_cohort_final` is computed and before the anchor-integrity sample / final clip / combined snapshot save. Both sides of the delta then resolve to `rank_in_cohort_final` and the math becomes apples-to-apples.

Scope is forward-only. Existing wrong values in `rankings_full` self-correct on the next ranking job; historical `ranking_history.rank_change_*` rows are not backfilled (they only feed the 30-day trend chart, which rolls forward in 30 days).

## Pattern Survey

**Baseline:** `HEAD` (working tree at `C:/PitchRank`). All line numbers below were grep-verified against the current file state at draft time. Verify against `origin/main` before editing — line numbers shift.

### Analogous Features
- `src/rankings/calculator.py:2627-2707` — Pass 3 SOS norm/rank: post-concat block guarded by `if not teams_combined.empty and "sos" in teams_combined.columns:`, sets `state_code` via `team_state_map`, derives Active-mask from `status` column, writes new columns directly on `teams_combined`. Closest structural template for the new step.
- `src/rankings/calculator.py:3073-3110` — Anchor integrity + monotonicity enforcement on `teams_combined`, guarded by `if "power_score_true" in teams_combined.columns`. Recomputes `power_score_final` at line 3108; this is the upstream dependency that must run before `rank_in_cohort_final`.
- `src/rankings/calculator.py:3111-3134` — Canonical `rank_in_cohort_final` computation. Uses `status == "Active"` mask, groups by `["age_num", "gender"]`, sorts by `["power_score_true", "team_id"]`, writes `Int64` ranks. Closing log line at 3134: `"  Published rank_in_cohort_final computed for ... Active teams"`. The new step inserts immediately after this line.
- `src/rankings/calculator.py:3136-3151` — Anchor integrity sample (top 3 per age group). Pure logging, no DataFrame mutation. The new `calculate_rank_changes` call must go *before* this block so the post-concat pipeline reads top-to-bottom as: rank_final → rank_changes → anchor sample → clip → snapshot save.
- `src/rankings/calculator.py:3153-3166` — Final PowerScore clip step, guarded by `if not teams_combined.empty:`. Runs after the new insertion point.
- `src/rankings/calculator.py:3168-3180` — Combined snapshot save (`save_ranking_snapshot` + `_save_prediction_feature_snapshot_safe`), each passing `snapshot_date=_normalize_snapshot_date(today)` inline. This is the call shape the new `calculate_rank_changes` invocation will mirror for snapshot-date plumbing.
- `src/rankings/calculator.py:2209-2226` (current location to remove) and `2228-2243` (per-cohort snapshot save, untouched) — Existing wrap pattern: `if calculate_rank_changes_enabled:` branch with `_section(timing_report, "rank_changes")`, else-branch backfills the 4 result columns with `None`. The else-branch logic (lines 2218-2226) is the contract callers depend on when the feature is disabled.

### Reusable Utilities
- `src/rankings/ranking_history.py:433-601` — `calculate_rank_changes(supabase_client, current_rankings_df, reference_date)` — Already prefers `rank_in_cohort_final` (lines 524-527), falls back to `rank_in_cohort_ml` then `rank_in_cohort`. Requires columns: `team_id`, `rank_in_cohort_final` (preferred), `rank_in_cohort_ml`, `rank_in_cohort`, `state_code` + `power_score_final` + `status` (for state ranks via `_compute_state_ranks`), `age_group`/`age`, `gender`. Returns same df with `rank_change_7d/30d/state_7d/state_30d` added (numeric coerced).
- `src/rankings/ranking_history.py` (top of file) — `_compute_state_ranks(df, active_mask, score_col)` — Per-state-cohort rank computation; called internally when `state_code` + `power_score_final` are present.
- `src/rankings/calculator.py:68` — `_normalize_snapshot_date(today)` — Date-normalization helper. Used inline by the combined snapshot save at lines 3174, 3179. The new `calculate_rank_changes` call uses the same idiom for `reference_date=`.
- `src/rankings/calculator.py:61` — `_section(timing_report, name, **metadata)` — Context-manager helper used throughout for timing instrumentation; existing `rank_changes` section name at line 2212 is the natural label to reuse.
- `src/rankings/calculator.py:23` — Existing import `from src.rankings.ranking_history import calculate_rank_changes, save_ranking_snapshot` — already in scope, no new imports required.

### Convention Anchors
- **Post-concat ordering**: Steps mutating `teams_combined` run in two distinct nested sections. (a) Pass 3 SOS at lines 2629-2714 — a top-level `if not teams_combined.empty and "sos" in teams_combined.columns:` block at indent-4, closed before line 2715. (b) Final scoring section at line 2845: `if not teams_combined.empty:` at indent-4 → `else:` branch at line 2851 (the `age_num`-present path of `if "age_num" not in teams_combined.columns:` at 2849) at indent-8, containing all the 12-space-indent sibling blocks: monotonicity recompute (3073-3110), `rank_in_cohort_final` (3119-3134), anchor integrity sample (3137-3151). After both sections, at indent-4: final clip (3153-3166) → combined snapshot save (3168-3180). The new `calculate_rank_changes` call belongs at indent-12 inside the line-2851 `else`, between the `rank_in_cohort_final` block (ending at line 3134) and the anchor integrity sample (starting at line 3137).
- **Empty/columnar guards**: Every post-concat block opens with `if not teams_combined.empty:` and inner column-existence guards. The new call should follow the same shape.
- **Timing wrapper**: Long async/IO steps are wrapped in `with _section(timing_report, "<name>"):`. Reuse the `"rank_changes"` label at the new site.
- **Snapshot-date plumbing**: `compute_all_cohorts` does NOT have `snapshot_date` as a local — the function uses `_normalize_snapshot_date(today)` inline at both existing snapshot-save call sites (lines 3174, 3179). The new `calculate_rank_changes` call must mirror this idiom (`reference_date=_normalize_snapshot_date(today)`), NOT assume a local `snapshot_date` exists. (`snapshot_date` IS a local in `compute_rankings_with_ml` at line 1924 — that's the per-cohort pass we're removing the call from.)
- **Caller inventory**: `compute_rankings_with_ml` is invoked from `compute_all_cohorts` (lines 2470, 2539) in production, and monkey-patched in `tests/unit/test_glicko_sos_role.py` (3 fakes at function-def lines 251, 360, 592; `monkeypatch.setattr` sites at 322, 426, 659). No `scripts/` or `frontend/` code invokes it directly. `scripts/calculate_rankings.py:744,757` and `scripts/backfill_prediction_feature_history.py:144` go through `compute_all_cohorts`. The backfill explicitly passes `calculate_rank_changes=False` (line 155). Safe to drop the per-cohort call entirely.
- **Test idiom for ranking_history**: `tests/unit/test_ranking_history_na_safety.py` defines local helper-replica functions that mirror production NA-handling logic — it does NOT import or exercise `calculate_rank_changes` directly. It is a useful reference for the `pd.array(..., dtype="Int64")` fixture idiom and Int64 NA handling, but NOT for the call style of the new test. The new test in Step 5 (which calls `calculate_rank_changes` directly with `AsyncMock`-patched `get_historical_*` helpers and a `@pytest.mark.asyncio` marker) establishes a new convention. For asyncio marker style, reference `tests/unit/test_glicko_engine.py` or the project's `tests/conftest.py`.
- **Column availability at insertion (between line 3134 and line 3136) on `teams_combined`**: `team_id`, `age`/`gender`/`age_num`, `state_code` (set in Pass 3 SOS block at line ~2637), `status` (per-cohort output, used at lines 2654-2657 and 3121), `power_score_final` (recomputed line 3108), `power_score_true` (per-cohort), `rank_in_cohort` and `rank_in_cohort_ml` (per-cohort outputs), `rank_in_cohort_final` (line 3120 + assignment loop 3122-3133). All inputs for `calculate_rank_changes` are present. `rank_in_cohort_final` is `Int64` with `<NA>` for non-Active teams — `calculate_rank_changes` handles via `pd.notna()` fallback at lines 524-527.

### Proposed Alignment
Insert the new block at indent-12 between line 3134 and line 3136 in `compute_all_cohorts`, as a sibling to the `rank_in_cohort_final` block above and the anchor integrity sample below — all three live inside the line-2851 `else` branch (the `age_num`-present path inside `if not teams_combined.empty:` at line 2845). The new block's guard is `if calculate_rank_changes_enabled:` only — the outer empty/age_num preconditions are already enforced. Pass `reference_date=_normalize_snapshot_date(today)` inline (matching the snapshot-save idiom at lines 3174/3179) — do NOT reference a `snapshot_date` local (it doesn't exist in this function). Rename the `compute_all_cohorts` parameter `calculate_rank_changes` → `calculate_rank_changes_enabled` (Step 3) to avoid shadowing the imported function. In `compute_rankings_with_ml`, replace the entire if/else block at lines 2209-2226 with an unconditional 4-column `None` scaffold so per-cohort callers (tests) still see the columns. No new utilities needed — `calculate_rank_changes` already prefers `rank_in_cohort_final`.

## Implementation Steps

1. **Verify clean working tree against `origin/main` and re-confirm line numbers**
   - Run `git fetch --all --prune` and `git status` from `C:/PitchRank` before any edits.
   - Branch from `origin/main` (per `feedback_check_main_ci_baseline.md` and `git_squash_merge_drift.md`).
   - If `src/rankings/calculator.py` or test files have uncommitted modifications, stop and surface them — do not silently bundle.
   - Re-grep the anchor line numbers below before editing. The plan's line refs were captured at draft time and may have shifted since:
     ```
     grep -n "await calculate_rank_changes\|rank_in_cohort_final\"\] = pd.array\|Saving combined ranking snapshot\|teams_combined = pd.concat\|def compute_all_cohorts\|def compute_rankings_with_ml\|Published rank_in_cohort_final computed\|=== Anchor integrity sample" src/rankings/calculator.py
     ```
   - Use the grep-confirmed line numbers, not the plan's recorded numbers, if they have drifted.

2. **Replace per-cohort `calculate_rank_changes` block with a column scaffold in `compute_rankings_with_ml`**
   - File: `src/rankings/calculator.py`
   - Delete lines 2209-2226 (the entire `# Calculate rank changes using historical snapshots (7d and 30d)` comment + `if calculate_rank_changes_enabled: ... else: ...` block — both branches).
   - Replace with an unconditional scaffold (preserving the return contract for the 3 monkeypatched fakes in `tests/unit/test_glicko_sos_role.py` at function-def lines 251, 360, 592):
     ```python
     # Rank-change columns are populated in compute_all_cohorts after rank_in_cohort_final
     # is computed on teams_combined. Initialize as None here so per-cohort consumers
     # (tests, debugging) still see the columns on the returned DataFrame.
     for column in [
         "rank_change_7d",
         "rank_change_30d",
         "rank_change_state_7d",
         "rank_change_state_30d",
     ]:
         if column not in teams_with_ml.columns:
             teams_with_ml[column] = None
     ```
   - Preserve everything else in this function untouched (per-cohort snapshot save at lines 2228-2243 stays gated on `save_snapshot`, the return dict at lines 2245-2252 is unchanged).
   - `calculate_rank_changes_enabled` local at line 1914 is now unused in this function — leave the `RankingContext` field intact (other passes/tests reference it) but the variable can be deleted from the local unpacking at line 1914 only if grep confirms it isn't read elsewhere in this function body. If unsure, leave it.

3. **Rename `compute_all_cohorts`'s `calculate_rank_changes` parameter to avoid shadowing the import**
   - File: `src/rankings/calculator.py`
   - The function signature at line 2335 declares `calculate_rank_changes: bool = True`. This parameter shadows the imported async function `calculate_rank_changes` from `ranking_history` (imported at line 23) within the entire body of `compute_all_cohorts`. Any reference to `calculate_rank_changes` inside the function resolves to the bool — calling `await calculate_rank_changes(...)` would deterministically raise `'bool' object is not callable`.
   - Rename the parameter at line 2335: `calculate_rank_changes: bool = True` → `calculate_rank_changes_enabled: bool = True`.
   - Update both `RankingContext(...)` kwarg passes that forward this flag — at lines 2490 and 2561, change `calculate_rank_changes=calculate_rank_changes` → `calculate_rank_changes=calculate_rank_changes_enabled` (the `RankingContext` dataclass field stays named `calculate_rank_changes` — only the local parameter is renamed).
   - Grep-verify no other references in `compute_all_cohorts` body need updating: `grep -n "calculate_rank_changes" src/rankings/calculator.py` should show the import (line 23), the renamed parameter (2335), the two forwards (2490, 2561), and — after Step 4 — the new `await` call site. No other in-body usages should exist.
   - Naming note: `compute_rankings_with_ml` already has a local `calculate_rank_changes_enabled` at line 1914 (unpacked from `ctx.calculate_rank_changes`). The new parameter name in `compute_all_cohorts` matches that local — intentional consistency, not a collision (different function scopes).

4. **Insert the relocated `calculate_rank_changes` call in `compute_all_cohorts`**
   - File: `src/rankings/calculator.py`
   - Insert between line 3134 (the `logger.info(f"  Published rank_in_cohort_final computed for {active_mask.sum()} Active teams")` line — closes the `rank_in_cohort_final` block) and line 3136 (the `# === Anchor integrity sample (top 3 per age group) ===` comment).
   - **Indentation: place the new block at 12-space indent**, matching the sibling `# === Anchor integrity sample ===` block at line 3136. The insertion sits inside the `else:` branch at line 2851 (the `age_num`-present branch of the inner `if "age_num" not in teams_combined.columns:` check at line 2849), which itself nests inside the outer `if not teams_combined.empty:` at line 2845. All the post-concat scoring siblings — monotonicity recompute (line 3074), `rank_in_cohort_final` (line 3119), anchor integrity sample (line 3137) — live as 12-space-indent blocks inside that `else`. The Pass 3 SOS block at line 2629 is a separate, earlier section that has already closed by line 2715; it does NOT enclose the insertion point.
   - The outer guards (`not teams_combined.empty` at 2845, and `age_num` present via the line-2851 `else`) are already enforced. The new block's guard only needs to check the enable-flag (renamed in Step 3):
     ```python
     # Compute 7d/30d national + state rank deltas now that rank_in_cohort_final
     # is populated on teams_combined. Running this earlier (per-cohort) used
     # rank_in_cohort_ml for current vs rank_in_cohort_final for historical,
     # producing apples-to-oranges deltas (e.g. #1 teams showing negative change).
     if calculate_rank_changes_enabled:
         logger.info("📊 Calculating rank changes from historical data...")
         with _section(timing_report, "rank_changes"):
             teams_combined = await calculate_rank_changes(
                 supabase_client=supabase_client,
                 current_rankings_df=teams_combined,
                 reference_date=_normalize_snapshot_date(today),
             )
     ```
   - **Side effect to note:** the new call is skipped on runs where `teams_combined` is empty OR `age_num` is missing — same precondition that guards the `rank_in_cohort_final` block above it, so the two columns share the same skip condition and stay consistent. Operators debugging missing `rank_change_*` values should check those two conditions (empty result, missing `age_num`), not the SOS column. Not a regression; document only.
   - Preserve the existing `# === Anchor integrity sample ===` block (line 3136+), the final clip step (3153-3166), and the combined snapshot save (3168-3180). These are untouched.

5. **Add focused unit test for the relocated path**
   - File: `tests/unit/test_ranking_history_relocation.py` (new)
   - Test pattern: build a synthetic `teams_combined` DataFrame with two teams whose `rank_in_cohort_final` differs from their `rank_in_cohort_ml` (the exact bug shape). Monkeypatch `get_historical_ranks` and `get_historical_state_ranks` (via `unittest.mock.AsyncMock` patched onto the `src.rankings.ranking_history` module) to return canned dicts. Call `calculate_rank_changes` directly with this fixture and assert that the computed `rank_change_7d` uses `rank_in_cohort_final` as the current value, not `rank_in_cohort_ml`.
   - Specific assertion mirroring the live bug:
     - Fixture team A: `rank_in_cohort_final=1`, `rank_in_cohort_ml=23`. Mock `get_historical_ranks` returns `{team_A_id: 7}`.
     - Expected `rank_change_7d = 7 - 1 = 6` (NOT `7 - 23 = -16`).
   - Use `pd.array(..., dtype="Int64")` for nullable int columns (idiom reference: `tests/unit/test_ranking_history_na_safety.py`, even though that file does not exercise `calculate_rank_changes` directly).
   - Async test — use `@pytest.mark.asyncio`. Reference `tests/unit/test_glicko_engine.py` (or `tests/conftest.py` if the project configures `asyncio_mode = auto`) for the marker idiom. This test establishes a new convention: direct exercise of `calculate_rank_changes` with `AsyncMock`-patched dependencies.

6. **End-to-end smoke validation against dev data**
   - Run the calculator end-to-end via the production entrypoint at `scripts/calculate_rankings.py:744`/`757` (which calls `compute_all_cohorts`).
   - Query `rankings_full` for `team_id = '36d80476-f198-4b2c-bdf6-ac5a52dbf99f'` and confirm `rank_change_7d` is now a positive integer or null, not `-16`.
   - Run the same query for ~10 other u12 male teams across the rank distribution (top 5, middle, bottom) to confirm deltas look sensible.

## Verification

The distribution-check SQL below assumes the corrected calculator has been run end-to-end at least once. Pre-deploy or pre-first-run queries will still surface legacy bad values from the prior pipeline. Run the SQL checks AFTER the first post-deploy ranking job completes.

- **Unit test**: `pytest tests/unit/test_ranking_history_relocation.py -v` — passes. Asserts the moved call uses `rank_in_cohort_final` on both sides.
- **Existing tests stay green**: `pytest tests/unit/test_ranking_history_na_safety.py tests/unit/test_glicko_sos_role.py -v` — the 3 monkeypatched `compute_rankings_with_ml` fakes still get the 4 rank_change columns (now always `None` from the scaffold).
- **Calculator end-to-end runs without error**: `python scripts/calculate_rankings.py` completes; `rank_changes` timing section appears in the timing report under the `compute_all_cohorts` block, not the per-cohort block.
- **Targeted SQL spot-check** (the regression case, run after the first post-deploy ranking job):
  ```sql
  SELECT team_id, rank_in_cohort_final, rank_in_cohort_ml, rank_change_7d
  FROM rankings_full
  WHERE team_id = '36d80476-f198-4b2c-bdf6-ac5a52dbf99f';
  ```
  Expect `rank_in_cohort_final = 1` and `rank_change_7d >= 0` (or NULL). Was: `-16`.
- **Distribution check** (regression guard, run after the first post-deploy ranking job):
  ```sql
  SELECT COUNT(*) FROM rankings_full
  WHERE rank_in_cohort_final = 1 AND rank_change_7d < 0;
  ```
  Expect `0`. A #1 team can't have moved down.
- **Edge cases to spot-check**:
  - Teams that just entered a cohort (no 7d snapshot) — expect `rank_change_7d IS NULL`, not a spurious value.
  - Teams with `status != 'Active'` — expect `rank_in_cohort_final IS NULL`; `calculate_rank_changes` falls back to ML/raw rank for these, which is unchanged behavior.
  - State rank deltas (`rank_change_state_7d`) — verify a few rows where state rank changed; the move shouldn't have altered state-rank math since `state_code` + `power_score_final` were already on `teams_combined` before the insertion point.

## Context Files

- `src/rankings/calculator.py` (lines 1876-2253 for `compute_rankings_with_ml`, and 2320-3188 for `compute_all_cohorts`) — Both edit sites + the post-concat pipeline surrounding the insertion point. Read in full to internalize the order of `teams_combined` mutations.
- `src/rankings/ranking_history.py` — `calculate_rank_changes`, `get_historical_ranks`, `get_historical_state_ranks`, `_compute_state_ranks`. The column-fallback logic at lines 524-548 is the crux of why this bug exists; understanding it confirms the fix is sufficient.
- `tests/unit/test_ranking_history_na_safety.py` — Test idiom reference for the `pd.array(..., dtype="Int64")` fixture style and Int64 NA handling ONLY. Does NOT exercise `calculate_rank_changes` directly — the new test in Step 4 establishes that convention.
- `tests/unit/test_glicko_sos_role.py` (function-def lines 251, 360, 592 and `monkeypatch.setattr` sites at 322, 426, 659) — Confirm the scaffold preserves the return contract these fakes implicitly rely on.
- `tests/unit/test_glicko_engine.py` and/or `tests/conftest.py` — Async marker idiom reference for the new test.
- `scripts/calculate_rankings.py:744,757` — Production caller path for end-to-end smoke.
- `scripts/backfill_prediction_feature_history.py:144-155` — Confirms the `calculate_rank_changes=False` path still works after the move (this caller now exercises the new column-scaffold path through `compute_all_cohorts`).
