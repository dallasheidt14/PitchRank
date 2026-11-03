---
status: done
---

# Plan: Fill fixtures stored under merged-away teams

## Context

A blank fixture saved before a team merge keeps the pre-merge team id, because games are immutable and
`execute_team_merge` never rewrites them. When the result arrives, the importer's fixture fill in
`_check_duplicates_by_master_ids` (`src/etl/enhanced_pipeline.py:1647`) compares the stored row's
**raw** master ids with the incoming game's canonical ids. They differ, so the fill misses and the
result is inserted as a second row. The team page then lists the game twice, once blank and once
scored.

Reported case (verified 2026-11-02): Canton Sports Academy U12 Black (`ccdaf1b2-…`) vs Valeo FC
U12 Bayern (`d030acf0-…`), 2026-11-01.
- Blank row `053239d9-…` was saved 2026-09-14 under `54cae677-…`, which was merged into
  `ccdaf1b2-…` on 2026-10-29.
- The scored 4-1 row `aed21402-…` was inserted 2026-11-02.

Measured with merge-resolved pairs:
- **Blank copies beside exactly one scored copy, and nothing else that day:**
  - since 2026-08-01: 1,432 GotSport, 113 Affinity OR, 2 Affinity UT. No group with two or more
    scored rows exists.
  - 2025-08-01 to 2026-07-31: 113 more.
- **The same raw-id comparison also lets an unchanged re-scrape after a merge be stored again**
  (since 2026-08-01):
  - 17 fixtures stored as two blanks;
  - 6 scored games stored twice.
- `team_merge_map` holds 27,129 rows, 1,998 of them from the last 30 days.

**Owner decisions (2026-11-02):**
- **Scope of the importer fix:** make the whole stored-row pairing merge-aware. That covers fills,
  unchanged repeats (blank and scored) and the fill guards, not the fill alone.
- **Cleanup range:** all seasons, no `--since`.

## Pattern Survey

Survey of `origin/main` before this change; line numbers are from that tree, and "As built" at the
end records what changed.

### Analogous Features
- **`src/etl/enhanced_pipeline.py:1647-1946`, `_check_duplicates_by_master_ids`**, the target.
  - **Fetch (`:1731-1757`).** It queries `games` per date, 50 teams per `or_()` call, over the
    incoming games' ids only.
  - **Keys (`:1773-1800`).** It builds `existing_master_keys`, `scored_pairs`, `scored_rows` and
    `unscored_fixtures` from the stored row's raw ids. The fixture orientation flag at `:1795-1797`
    is computed from the same ids.
  - **Fill tag (`:1848-1874`).** It sets `_fixture_score_update`.
  - **Correction branch (`:1885-1940`)** calls `_scored_row_to_correct` (`:1948-1975`), whose
    orientation check compares `sorted_ids[0]` with the stored row's raw `home_team_master_id`.
  - **Errors (`:1942-1944`).** The per-date body is one `try`. Any exception quietly turns into
    an insert.
- **`src/etl/enhanced_pipeline.py:952-955` → `_backfill_scores` (`:2007`)** consumes the fill tag.
  It writes through the `batch_backfill_null_scores` RPC by `game_uid` only, with a both-scores-null
  guard (`supabase/migrations/20260602000000_add_batch_backfill_null_scores.sql`). It never touches
  the master id columns, so a filled row keeps its pre-merge ids. That is fine: ranking reads
  resolve merges.
- **`PROVIDER_ID_CORRECTION_PROVIDERS` (`:45-48`, TGS and Kitman) with `_scored_rows_by_provider_ids`
  (`:1977-2005`)** is the existing answer to "a merge left the row under an old id". It does not
  suit fills:
  - It returns only this provider's **scored** rows.
  - The common GotSport merge (registration-id placeholder into the real team id,
    `scripts/find_regid_duplicate_merges.py`) changes provider team ids, so the stored blank carries
    an id the survivor's scrape never reports.
- **`scripts/exclude_unscored_fixture_twins.py` (#1219)** is the twin cleanup to extend.
  - **What it reads.** `fetch_unscored` reads past-dated blanks. `fetch_scored_for` reads scored
    rows by `.in_("home_team_master_id", <the date's raw ids>)`.
  - **Pairing.** `pair_key` uses raw ids. `select_twins` takes the blanks whose pair has at least
    as many scored rows, skipping rematch providers.
  - **Guards and output.** `cascade_collisions` refuses `--execute`. The log is written before the
    first update.
  - **Why it misses this case.** The blank and the scored copy have different raw pairs, and the
    scored copy is fetched only when the shared opponent is home.
- **`scripts/exclude_merge_duplicate_games.py`** is the merge-aware sibling, for scored games only.
  - `load_merge_map` (`:103-115`) pages and orders.
  - It groups on resolved ids and keeps the trigger collision check on raw ids (`:362-376`).
- **`supabase/migrations/20260325000000_propagate_game_exclusion.sql`** defines
  `trg_propagate_game_exclusion`. It excludes rows on the same date with the same **raw** pair and
  `IS NOT DISTINCT FROM` scores. A hidden blank can therefore only cascade to other blanks under
  the same raw pair, never to its scored copy.
- **GotSport same-day rematch handling (#1386).** GotSport is in `SCHEDULE_ID_SUFFIX_PROVIDERS`,
  not `REMATCH_PROVIDERS`, so fills stay enabled for it.
  `tests/unit/test_enhanced_pipeline_gotsport_rematch.py:201` pins that a repeat-day result fills
  the pair's one stored fixture.

### Reusable Utilities
- **`scripts/enqueue_helpers.py:46`, `resolve_merges(supabase, team_ids)`.** A raw→canonical map,
  read with `.in_("deprecated_team_id", …)` in batches of 100.
- **`scripts/enqueue_helpers.py:66`, `expand_to_aliases(supabase, canonical)`.** Extends that map
  to every predecessor of each canonical id. `scripts/enqueue_yesterday_games.py:229-237` (#1390)
  uses the pair the same way. `src/` already imports from `scripts.*`
  (`src/models/affinity_ut_matcher.py:28`).
- **`scripts/exclude_merge_duplicate_games.py:103`, `load_merge_map(sb)`.** The whole map, ordered
  and paged. Fine for a one-shot script.
- **`scripts/exclude_none_opponent_games.py:111-131`, `cascade_collisions`**, which the twins
  script already imports.
- **`src/utils/merge_resolver.py`, `MergeResolver`**, deliberately **not** used in the pipeline.
  - It loads all 27K rows per pipeline, in pages with no `.order()`, so pages can skip or repeat
    rows.
  - It swallows any load error into an empty map.
  - The targeted helpers read only the ids in the batch.

### Convention Anchors
- **Resolve stored team ids in both directions.** CLAUDE.md, Common Pitfall 2.
- **Fills and corrections are passed downstream as tags** (`_fixture_score_update`,
  `_scored_row_correction`), not written directly. The correction payload carries the stored
  row's own raw ids and uid.
- **Operator cleanup scripts:**
  - a dry run unless `--execute`;
  - `--out` must not already exist;
  - the log is written before the first update;
  - updates go in batches of 100 by `id`, re-guarded on current state.
- **Pipeline test doubles** are in `tests/unit/test_enhanced_pipeline_fixture_score_fill.py`.
  - `_DB.table` asserts `games`/`providers` at `:113`.
  - `_Query` models `select/eq/in_/or_` only.
  - `_Rpc` mirrors the RPC's uid and null-score guard.
  - `test_enhanced_pipeline_gotsport_rematch.py:25-34` has an autouse guard against a swallowed
    dedup error.
- **Cleanup test doubles** are in `tests/unit/test_exclude_unscored_fixture_twins.py`. They accept
  any table name, and a missing table returns `[]`.

### Proposed Alignment
- **Importer:** keep `_check_duplicates_by_master_ids` as it is. Feed every pair key and orientation
  check through one merge map built from the incoming ids and their predecessors, and widen the
  fetch to those predecessors. Leave correction payloads on the stored row's raw ids.
- **Cleanup:** extend `exclude_unscored_fixture_twins.py` to pair on resolved ids and fetch scored
  rows under canonical and predecessor ids. Keep the trigger collision check on raw ids.

## Implementation Steps

0. **Branch setup.** Work in a worktree off `origin/main`
   (`git worktree add <path> -b fix/fill-fixtures-under-merged-teams origin/main`), because the shared
   checkout holds unrelated staged work.

1. **Build one merge map for the batch** (`src/etl/enhanced_pipeline.py`).
   - Add a method `_merge_map_for(self, master_ids: set[str]) -> Dict[str, str]`. It returns
     `expand_to_aliases(self.supabase, resolve_merges(self.supabase, master_ids))`, imported from
     `scripts.enqueue_helpers`.
   - The result maps every incoming id, and every predecessor of their canonical ids, to its
     canonical id.
   - On any exception, log a `warning` naming the failure and return an identity map over
     `master_ids`. That keeps today's raw-id behaviour, so a lookup failure is never worse than now.
   - In `_check_duplicates_by_master_ids`, call it once after `games_by_date` is built (`:1710`).
     Pass every incoming home and away master id across all dates. Do not call it per date.
   - Bind `resolve = lambda tid: merge_map.get(tid, tid)` for the steps below.

2. **Widen the stored-row fetch** (`:1731-1757`).
   - For each date, the batched `or_()` id set becomes the incoming ids plus every `merge_map` key
     whose value is one of that date's incoming canonical ids.
   - Keep 50 teams per call and the `rows_by_id` dedupe.
   - This finds a fixture stored with **both** sides under pre-merge ids. Today that fixture is
     never fetched.

3. **Resolve every pair key and orientation flag.**
   - **Stored-row loop (`:1773-1800`).** Set `h_master = resolve(row["home_team_master_id"])` and
     `a_master = resolve(row["away_team_master_id"])` before computing `sorted_ids`, the key and the
     `(game_uid, sorted_ids[0] == h_master)` fixture tuple. `existing_master_keys`, `scored_pairs`,
     `scored_rows` and `unscored_fixtures` then all key on resolved pairs.
     - This is the owner-approved "fills + repeats" scope: an unchanged blank or scored re-scrape
       after a merge becomes a master-level duplicate instead of a second row.
   - **Incoming games.** Resolve their ids the same way wherever a pair key or orientation is
     computed:
     - the `reported_results` loop (`:1803-1813`);
     - the per-game key (`:1816-1830`);
     - `same_orientation` in the fill (`:1858`).
   - **`_scored_row_to_correct` (`:1948-1975`).** Its two orientation comparisons must use resolved
     ids:
     - `incoming_first` comes from the resolved incoming home;
     - `sorted_ids[0] == row["home_team_master_id"]` becomes `sorted_ids[0] == resolve(row[...])`.
     - Pass `resolve` in as a parameter.
   - Leave the `_scored_row_correction` payload (`:1920-1934`) on the stored row's raw ids and uid.
   - Leave the provider-id path (`by_provider_ids`) unchanged.

4. **Pipeline tests** (`tests/unit/test_enhanced_pipeline_fixture_score_fill.py`).
   - **Extend the double.**
     - Add a `team_merge_map` table to `_DB`. Allow the name at `:113`.
     - Model the `.in_("deprecated_team_id"|"canonical_team_id", …)` reads.
     - Record calls at `execute()`.
   - **Keep other doubles working.** Derive the list of other pipeline test doubles that assert
     table names with `git grep -n 'assert name in' -- tests/unit/test_enhanced_pipeline_*.py`.
     Make each accept `team_merge_map` returning no rows, so the merge lookup succeeds rather than
     being swallowed.
   - **New tests**, each with a stored row under a deprecated id and seeded merges:
     1. A blank under a deprecated home id plus an incoming canonical result. The fixture is filled
        through the RPC by its own uid, and nothing is inserted (the reported case).
     2. A blank with **both** sides under deprecated ids is filled. This is the widened fetch.
     3. A blank under a deprecated id, stored home/away reversed against the incoming result. The
        scores are swapped onto the stored sides.
     4. An incoming blank re-scrape after a merge is a master-level duplicate. No insert.
     5. An unchanged scored re-scrape after a merge is a master-level duplicate. No insert.
     6. A scored row under a deprecated id plus a blank under the canonical id, and an incoming
        result. No fill: the resolved `scored_pairs` blocks it.
     7. A merge lookup that raises. The import completes on raw ids, logs the warning, and the
        existing fill on canonical ids still works.
   - **Corrections.** In `tests/unit/test_enhanced_pipeline_tgs_merged_uid_correction.py`, add a
     case with the merge map seeded. The stored TGS row under deprecated ids is corrected through
     the master path with the right orientation, and no second row is inserted.
   - Copy the autouse "no swallowed dedup error" guard from
     `test_enhanced_pipeline_gotsport_rematch.py:25-34` into the fill test module.

5. **Merge-aware twin cleanup** (`scripts/exclude_unscored_fixture_twins.py`).
   - **Load the map once.** In `main`, load it via
     `scripts.exclude_merge_duplicate_games.load_merge_map(sb)`. Build `resolve` (one hop; the map
     is flat by `execute_team_merge`) and a canonical→predecessors index.
   - **`pair_key`** takes `resolve` and keys on resolved ids. `select_twins` passes it through.
     Keep the rematch-provider and "not its own result" rules.
   - **`fetch_scored_for`'s team set.** In `main`, extend each date's set with each id's canonical
     and all of that canonical's predecessors. A scored copy under canonical ids is then found
     whichever side is home.
   - **Keep `cascade_collisions` on raw ids.** It mirrors the trigger, which keys on raw pairs.
   - **The `results` lookup** for the printed sample (`results = {pair_key(g): g …}`) uses the
     resolved key.
   - **Dry-run output.** Print how many selected twins needed merge resolution: those whose raw
     pair differs from their scored copy's raw pair.
   - **Docstring.** Update it to name the merge case alongside the provider-id-uid case.
   - Leave the update batch, its re-guard, the log-before-write and `--out` refusal unchanged.

6. **Cleanup tests** (`tests/unit/test_exclude_unscored_fixture_twins.py`).
   - Seed `team_merge_map` and drive `main` (or the fetch-plus-select composition), not
     `select_twins` alone, so the fetch expansion is exercised.
   - Cover:
     - a blank under a deprecated id with its scored copy under canonical ids, the shared opponent
       **away** on the scored row. It is selected;
     - a blank with no scored copy after resolution. It is not selected;
     - a blank under a deprecated id plus a scored copy from a rematch provider. It is not selected;
     - a collision case still refuses `--execute`.

7. **Backlog note.** Add `- **Update (2026-11-02)**:` to IMP-137 in `.turbo/improvements.md`:
   - The importer now matches stored rows on merge-resolved ids, so a game re-imported after a
     merge no longer adds a copy.
   - Duplicates created **by** a merge (two rows already stored before it) still need
     `exclude_merge_duplicate_games.py`, so the entry stays `open`.

## Verification

- **Tests:**
  - `python -m pytest tests/unit/test_enhanced_pipeline_fixture_score_fill.py tests/unit/test_enhanced_pipeline_tgs_merged_uid_correction.py tests/unit/test_enhanced_pipeline_gotsport_rematch.py tests/unit/test_exclude_unscored_fixture_twins.py -q`
    passes.
  - So does the CI form, `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.
- **Mutation checks.** Revert one change at a time, and confirm the named **new** test is among the
  failures, not just that the suite reddens:
  - drop the widened fetch → test 2;
  - orientation from raw stored ids → test 3;
  - raw ids in `existing_master_keys` → tests 4 and 5;
  - raw ids in `scored_pairs` → test 6;
  - raw `row["home_team_master_id"]` in `_scored_row_to_correct` → the new TGS case;
  - cleanup `pair_key` on raw ids, or no team-set expansion → the deprecated/away cleanup test.
- **Cleanup dry run against production.** Run `python scripts/exclude_unscored_fixture_twins.py`.
  - Expect about 1,660 twins (≈1,547 this season + ≈113 last season, plus any older), nearly all
    flagged as needing merge resolution, and 0 cascade collisions.
  - Confirm blank `053239d9-1738-499f-b6b0-422a84ad9ca7` is listed with kept row `aed21402-…` 4-1.
  - Hand the `--execute` run to the owner after the dry run is reviewed.
- **Production check after deploy**, about a week later, from the data rather than run logs:
  - New scored rows on dates whose resolved pair already holds a blank under a pre-merge id should
    be 0 for rows created after the merge commit.
  - Blank rows under pre-merge ids that have since gained a score (fills) should be greater than 0.
  - Re-run the merge-resolved twin query from Context and compare it with the post-cleanup baseline.

## Context Files

- `src/etl/enhanced_pipeline.py` (`:1647-2005` on `origin/main`): the dedup, fill and correction
  logic being changed.
- `scripts/enqueue_helpers.py`: `resolve_merges` and `expand_to_aliases`.
- `scripts/exclude_unscored_fixture_twins.py`: the cleanup being extended.
- `scripts/exclude_merge_duplicate_games.py` (`:80-115`, `:292-376`): `load_merge_map`, resolved
  grouping, raw-id collision rule.
- `tests/unit/test_enhanced_pipeline_fixture_score_fill.py`: the pipeline double and fill tests to
  extend.
- `tests/unit/test_exclude_unscored_fixture_twins.py`: the cleanup double and tests.
- `supabase/migrations/20260325000000_propagate_game_exclusion.sql`: why a hidden blank cannot take
  its scored copy with it.

## As built (2026-11-02)

- **Importer** (`_check_duplicates_by_master_ids`, `src/etl/enhanced_pipeline.py`):
  - **Merge lookup:** Steps 1–3 as written, except as below.
  - **Departure from step 3, found in review:** resolving alone let a copy a merge left under other
    ids block a fill (a third row) or a correction (a second scored row). So each blank is kept as an
    `UnscoredFixture` carrying `own_pair`, the row's own sorted ids. Where merges
    gather several rows onto one pair, only those saved under the result's own ids count, both as
    fill candidates and as scored rows to correct. A blank blocks a correction only when it shares
    saved ids with the result or with a scored row.
  - **Deliberate differences from main:**
    - A scored row under a merged-away id blocks a fill (step 4, test 6).
    - A blank that shares saved ids with a scored row under merged-away ids now blocks a TGS/Kitman
      correction that main made through provider ids. This matches main's own rule for unmerged
      pairs.
- **Cleanup** (`exclude_unscored_fixture_twins.py`):
  - It pairs on merge-resolved ids. Each date's scored-row fetch covers the survivor and all its
    merged-away ids.
  - The dry-run line "saved under a team since merged away" counts twins whose own ids include a
    merged-away id. That differs from step 5's "raw pair differs from its scored copy", and it is
    pinned by tests.
- **Step 4 "other doubles":** only the fill module's `_DB` needed `team_merge_map`. The doubles that
  assert `name == "games"` never reach the master-id stage. The TGS module imports the autouse
  swallowed-error guard. The Kitman module keeps its own `OLD_*` ids; that file is outside this
  change.
- **Verified:**
  - **Mutations:** 28 single-line mutations, each killed by the new test written for it.
  - **Test suite:** 12,515 passed. `tests/unit/test_compare_predictor_bridge.py` was left out: it
    needs `frontend/node_modules`, which a fresh worktree lacks.
  - **Production dry runs, write-guarded:**
    - The cleanup found 1,700 twins, 1,660 of them under merged-away teams, with 0 collisions. The
      reported Canton blank was selected.
    - The importer filled blank `17956b4c` (saved under a merged-away id); unchanged main inserted a
      duplicate for the same input.
- **Not done here:**
  - the cleanup `--execute`, which is the owner's;
  - the post-deploy data check, about a week after merge.
- **Backlog:**
  - IMP-392: MergeResolver pages without an order.
  - IMP-393: a dry-run import writes `build_logs`.
  - IMP-137 updated.
