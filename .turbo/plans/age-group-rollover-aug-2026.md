---
status: done
---

> **PR 2 OPEN 2026-07-31** as [#942](https://github.com/dallasheidt14/PitchRank/pull/942) (commit `3e4b973eb`, branch `feat/age-group-rollover-2026-relabel`, worktree `C:/tmp/age-rollover`). Carries the migration, the rollback, the `find_queue_matches` season-year fix, four workflow gates and three test modules. 1842 unit tests pass. **Both PRs are code-complete; the remaining work is operational and unstarted:** apply the migration by hand, `supabase migration repair --status applied 20260801000000`, dispatch `calculate-rankings.yml`, verify boards, then set `AGE_ROLLOVER_FREEZE` to `'false'` in all FIVE workflows (`data-hygiene-weekly`, `unknown-opponent-hygiene-weekly`, `auto-merge-queue`, `tgs-event-scrape-import`, `fix-age-year-discrepancies`). The freeze now covers eight steps, not the two this plan describes.
>
> **PR 1 MERGED 2026-07-30** as [#941](https://github.com/dallasheidt14/PitchRank/pull/941) (merge `586099d13`). It carries **only** the cron freeze: `AGE_ROLLOVER_FREEZE: 'true'` gating Steps 2+3 of `data-hygiene-weekly.yml` and Step 2 of `fix-age-year-discrepancies.yml`, plus a `CLAUDE.md` schedule correction. Gates test `== 'false'` (fail-closed) rather than negating `!= 'true'` — verified on a real dispatch: Steps 2 and 3 SKIPPED, Steps 1/1b/4 SUCCESS, run green. **The PR 1 section below is historical; do not re-implement it.**
>
> **The `find_queue_matches.py` season-year fix was pulled out of PR 1** and belongs with PR 2. Review found that shipping the `+1` before the migration desyncs the ungated cron Step 4 from the deliberately-frozen `teams.age_group`, enabling the wrong-cohort auto-merge the freeze exists to prevent. Working copy of that change, its four boundary tests, and the patch are saved outside the repo; regenerate from this plan if lost. Six review findings travel with it: the 18→19 fold and band clamp at the three birth-year branches, call-time season year, the inline `--test` pairing that breaks Aug 1, season-pinned siblings for the two `event_team_matcher` tests, an end-to-end `find_best_match` test, and a test pinning the Aug 1 cutoff itself.

# Plan: Age-Group Rollover for the 2026-27 Season (Aug 1 2026)

On 2026-08-01 US youth soccer switches from calendar-birth-year cohorts to an Aug 1 – Jul 31 window. Every team moves up one age group. **Move each team up one cohort from where it is now** — one `UPDATE` per table. Nothing is deleted, no history moves, and the migration itself changes no ratings.

## The mapping

`u7→u8`, `u8→u9`, `u9→u10`, `u10→u11`, `u11→u12`, `u12→u13`, `u13→u14`, `u14→u15`, `u15→u16`, `u16→u17`, **`u17→u19`**, **`u18→u19`**.

`u19` stays `u19`. `u20`, `u21`, `u0`, `u3`–`u6` untouched.

Driven off the **current `age_group` label**, not `birth_year` — which is 91.22% NULL (157,076 / 172,201), so a birth-year approach would reach 8.8% of rows.

## Three things that are not optional

1. **Gate the Monday cron before Mon Aug 3, 11:00 UTC.** `data-hygiene-weekly.yml` (`cron: '0 11 * * 1'`) rolls the ~84% of teams whose *name* carries a birth year, freezes the rest, then runs `find_fuzzy_duplicate_teams.py --auto-merge` across the half-rolled buckets and can **permanently fuse two different teams**. On a scheduled run `github.event.inputs.dry_run` is empty (`:148`), so `AGE_FLAGS=""` and it all runs live. This happens whether or not you do the rollover.
2. **Never write `u20`.** A naive `+1` on u19 produces it; `src/rankings/calculator.py:2563-2590` (`VALID_AGE_MAX = 19`) quarantines those rows, then `scripts/calculate_rankings.py:539-547` `DELETE`s them from `rankings_full`. Irreversible. That is why the map is an explicit `WHEN` list and never arithmetic.
3. **Take a backup table first.** Nothing in the repo records prior values of `teams.age_group` — no audit trail, no history table. One `CREATE TABLE AS` is the entire rollback plan.

## Setup

`C:\PitchRank` is on `fix/modular11-events-division-mapping`, 84 commits behind `origin/main`, with ~25 unrelated files staged. Branching there would bundle someone else's work, so use a worktree:

```bash
cd /c/PitchRank && git fetch --all --prune
git worktree add /c/tmp/age-rollover origin/main -b fix/age-rollover-monday-cron-safety
git -C /c/tmp/age-rollover status --short      # expect empty
```

- Python: `C:/Python313/python` (the repo `venv` is a dead macOS symlink).
- `psql` is **not on PATH** — `C:/Program Files/PostgreSQL/17/bin/psql.exe` (16 also installed).
- Lint only: `ruff check`. **Never `ruff format`.**
- Run Python tests **in the worktree** — the main checkout can't contain the change, so a run there passes without exercising it.
- The suite is already red at baseline: **2 failures, both in `tests/integration/test_gotsport_tier_persistence.py`** (measured, not estimated). Only new failures matter. Full suite ~7 min — background it.
- `__pycache__/*.pyc` files are tracked despite being gitignored, so pytest dirties ~28. Stage explicit paths; never `git add -A`.

## PR 1 — Monday-cron safety (deadline Mon Aug 3, 11:00 UTC)

Branch `fix/age-rollover-monday-cron-safety`. Ship first, alone.

1. **Gate Steps 2 and 3 of `.github/workflows/data-hygiene-weekly.yml`.**
   - Add `AGE_ROLLOVER_FREEZE: 'true'` to the workflow `env:` block at `:55`.
   - Append `&& env.AGE_ROLLOVER_FREEZE != 'true'` to the `if:` at **`:146`** (Step 2, `fix_team_age_groups.py`) and **`:167`** (Step 3, the `--auto-merge`).
   - Pattern to copy: `.github/workflows/tgs-event-scrape-import.yml:238`.
   - **Do not** use the `skip_steps` input — `github.event.inputs` is empty on scheduled runs, so it cannot stop the cron.
   - Preserve each `if:`'s existing `skip_steps` expression; the gate is an added conjunct.
   - **The gate must lift by changing one value.** Keep it a single `env:` entry with no logic to unwind, and comment it with what lifts it and when, so the un-freeze is self-documenting rather than dependent on this file. Lifting is an operational step, not a build step — see *After the cutover* below.

2. **Fix the season-year derivation in `scripts/find_queue_matches.py`.** Step 4 of the cron runs it `--execute --yes` (`:227`, `:230`) and stays ungated, so it must be correct. `_current_season_year()` (`:562-570`) returns `date.today().year` and the age is computed with **no `+1`** at **three** sites:
   - `:597` — gender-prefixed 2-digit (`G13`)
   - `:603` — gender-prefixed 4-digit (`B2014`)
   - **`:610` — standalone 4-digit (`\b(20\d{2})\b`)** ← the most common name form; easy to miss
   
   Use `team_utils.CURRENT_YEAR` (import the **module**, not the constant) and `age = CURRENT_YEAR - year + 1`. Leave the U-age-token path at `:579-589` alone. Why it matters: `build_age_group_filter_clause` (`:62-68`) **hard-filters** the candidate pool on this cohort (`:933`, `:1000-1003`), so post-roll every affected team is matched against the wrong cohort and auto-merged.

   **The existing tests are an identity until Aug 1.** `tests/unit/test_event_team_matcher.py:18` and `:66` use `"Dynamos SC 2016 SC"` — the standalone form, so they cover `:610`. But in July both formulas give 10 (`2026-2016` and `2025-2016+1`), so they can't fail yet. Leave them as-is and **add** cases that pass the season year in explicitly, pinning 2026-07-31 → `u10` and 2026-08-01 → `u11`.

## PR 2 — The migration

Branch `feat/age-group-rollover-2026-relabel`. New file `supabase/migrations/20260801000000_age_group_rollover_2026_27.sql`, house style of `20260326000000_normalize_age_groups_season_year.sql`.

**No in-file `BEGIN`/`COMMIT`** — 0 of 139 migrations use one, and an in-file transaction can't be rehearsed. The operator supplies it.

```sql
-- Guard: a second run would double-roll everything.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_name = 'teams_age_rollover_backup_2026') THEN
    RAISE EXCEPTION 'Rollover already applied. Aborting.';
  END IF;
END $$;

CREATE TABLE teams_age_rollover_backup_2026 AS
  SELECT team_id_master, age_group, now() AS snapshot_at FROM teams;
CREATE TABLE rankings_full_age_rollover_backup_2026 AS
  SELECT team_id, age_group, now() AS snapshot_at FROM rankings_full;

UPDATE teams SET age_group = CASE age_group
    WHEN 'u7'  THEN 'u8'  WHEN 'u8'  THEN 'u9'  WHEN 'u9'  THEN 'u10'
    WHEN 'u10' THEN 'u11' WHEN 'u11' THEN 'u12' WHEN 'u12' THEN 'u13'
    WHEN 'u13' THEN 'u14' WHEN 'u14' THEN 'u15' WHEN 'u15' THEN 'u16'
    WHEN 'u16' THEN 'u17' WHEN 'u17' THEN 'u19' WHEN 'u18' THEN 'u19'
    ELSE age_group
  END
WHERE age_group IN ('u7','u8','u9','u10','u11','u12','u13','u14','u15','u16','u17','u18');

-- identical CASE + WHERE against rankings_full (keyed on team_id)

ANALYZE teams;
ANALYZE rankings_full;
```

- **One statement per table.** Sequential per-cohort updates would double-roll (`u9→u10` then `u10→u11`); a single `CASE` reads every row's old value at once.
- **No `is_deprecated` filter** — deprecated rows roll too, keeping backup and restore symmetric.
- **Don't set `updated_at`** — `update_teams_updated_at` (`20240101000000_initial_schema.sql:376`) is a `BEFORE UPDATE` trigger. Nothing in the repo filters teams by `updated_at`, so the bump wakes nothing.
- **`ANALYZE` is not optional.** Four indexes lead with `age_group` (`20250120130000_create_rankings_full.sql:75,79,80`; `20240101000000_initial_schema.sql:56`). `20260603000000_sargable_age_filter_rankings_rpcs.sql:3-9` documents that a bad plan on `idx_rankings_full_age_gender` caused 57014 timeouts and **rendered ranking pages empty during Vercel builds**. No migration in the repo runs `ANALYZE`, so autovacuum timing is the only other protection.
- Don't touch `ranking_history`, `games.age_group`, or `prediction_feature_history`.

### Apply

```
"/c/Program Files/PostgreSQL/17/bin/psql" "$DATABASE_URL"
  BEGIN;
  \i supabase/migrations/20260801000000_age_group_rollover_2026_27.sql
  -- run the count checks below
  COMMIT;
```

Don't use `--single-transaction -f` for the real apply — it commits at end-of-file, leaving nowhere to check first.

## Verify

**Census both tables first** and keep the numbers; assert against *those*, not the figures below.

```sql
SELECT age_group, COUNT(*) FROM teams GROUP BY 1 ORDER BY 1;
SELECT age_group, COUNT(*) FROM rankings_full GROUP BY 1 ORDER BY 1;
```

Reference values (2026-07-29): **`teams`** 172,201 active / 183,980 all (11,779 deprecated) — u7 1,208 · u8 1,432 · u9 5,339 · u10 22,439 · u11 22,210 · u12 22,970 · u13 20,870 · u14 19,940 · u15 15,555 · u16 13,705 · u17 11,182 · u18 2,512 · u19 11,711 · u20 1,063 · u21 8 · strays 65. Rolled 159,362 + untouched 12,839 = 172,201.

**Before `COMMIT`** — on `teams`:
- `u7` and `u18` → **0**.
- Each target == its source's pre-roll count (`u8 == old u7`, `u10 == old u9`, `u11 == old u10`, …). **This is the check that catches a double-roll.**
- `u19 == old u17 + old u18 + old u19`.
- Grand total unchanged; `u20`/`u21`/strays unchanged; nothing outside `^u[0-9]{1,2}$`.
- `COUNT(*)` of the backup == the pre-roll all-rows total.
- **RLS caveat:** an UPDATE without a matching SELECT policy returns 0 rows *with no error*. A clean exit proves nothing — the counts are the proof. Run as `postgres`/service-role.

On `rankings_full` — **different, not the same map.** It holds **118,309 rows, 0 below u10, and 0 `u18`** (`age_group_to_age` folds 18→19 at write time):
- `u10` → **0**, not 5,339. Nothing arrives from u9 because there are no u9 rows, while the existing 19,696 leave for u11. **The U10 board is empty until the next ranking run** — expected, see below.
- `u19 == old u17 + old u19` (no u18 term).

**After `COMMIT`**, each in its own transaction (their `RAISE EXCEPTION` / writes would poison the production transaction):
- Re-run the migration → must **abort** on the guard. Roll back.
- Run the rollback file → counts return to pre-roll. Roll back, leaving the roll in place.

**Then dispatch `calculate-rankings.yml`** (it accepts `workflow_dispatch`). This repopulates U10 from the newly-u10 teams, renumbers the merged u19 cohort, and re-anchors scores. Purge/redeploy before checking boards — ISR is `revalidate = 3600` and a stale page satisfies every check even if the run failed.

Expected afterwards, none of them faults: `🧊 Evidence-gate frozen rank reference: 0/… (0.0% coverage)`; visible PowerScore movement (largest in former-U12, which takes a +4.8% anchor step *and* crosses `TIER_MIN_AGE = 13` where league multipliers switch on); and large negative `rank_change_7d/30d` on ex-u17 teams, because the history lookup keys on `team_id` only, never cohort.

**Record `SELECT COUNT(*) FROM rankings_full WHERE age_group = 'u10'`.** If it's very low, the U10 boards are thin — worth a `noindex` follow-up.

Tests: `cd /c/tmp/age-rollover && C:/Python313/python -m pytest tests/ -v --tb=short --ignore=tests/test_enhanced_pipeline.py`, diffed against the recorded baseline.

## After the cutover

**Lift the cron gate.** Set `AGE_ROLLOVER_FREEZE` to `'false'` and confirm Steps 2 and 3 resume on the next run. Do this once boards are verified — the gate is otherwise permanent, and Step 2 becomes *correct* after Aug 1: `fix_team_age_groups.py:44-49` computes `CURRENT_YEAR - birth_year + 1` with an 18→19 remap and a 7–19 band, matching this roll, and `extract_birth_year`'s `2005 ≤ year ≤ 2018` window makes the unmapped edges skip rather than corrupt.

The lift is a one-value change in **both** workflows, on a branch (`CLAUDE.md` forbids committing to main). Monday's run will look completely normal with the freeze on — green check, skipped steps only visible inside the run — so nothing will prompt you. `CLAUDE.md` names the flag so it stays findable.

## Rollback

`scripts/migrations/rollback_age_group_rollover_2026.sql` (that directory already holds `add_team_name_original.sql`). Operator-supplied transaction, same as the migration.

```sql
UPDATE teams t SET age_group = b.age_group
FROM teams_age_rollover_backup_2026 b
WHERE t.team_id_master = b.team_id_master AND t.age_group <> b.age_group;
-- same for rankings_full from its backup
-- assert counts, THEN:
-- DROP TABLE teams_age_rollover_backup_2026, rankings_full_age_rollover_backup_2026;
```

Dropping the backups re-arms the migration's guard, so it's part of completing a rollback, not cleanup.

⏰ **Rollback expires at the first post-roll ranking run** — scores get re-anchored and the merged u19 normalizations recomputed, none of which a label restore undoes. That's your dispatch **or `cron: '30 12 * * 1'` — Mon Aug 3, 12:30 UTC, unattended.** Apply Saturday and wait, and the window closes by itself. Check for in-flight runs (`gh run list --workflow=calculate-rankings.yml`) before applying.

## Merged u19 ranks — DECIDED 2026-07-31: accept, no extra code

`rank_in_cohort_final` is stored and ordered by, so the merged u19 board briefly shows two teams at rank 1 (ex-u17 and ex-u19; `rankings_full` holds no u18). **Ruling: accept it and let the ranking run in the cutover sequence clear it.** No migration code for this.

Rationale: renumbering in SQL would order ex-u17 scores (compressed to a 0.981 anchor ceiling) against ex-u19 scores (1.000) and rank the u17 teams systematically too low. `power_score_true` would be fairer, but choosing between them is an engine judgement the migration should not make. The engine re-anchors both groups on one scale; hand-rolled SQL does not. Exposure is the gap between applying the migration and dispatching rankings, which the runbook does back to back.

## Cutover date — DECIDED 2026-07-31: run a day early

Running before Aug 1 is safe, verified rather than assumed:

- The migration is a fixed label map and never reads the clock — identical output any day.
- Nothing scheduled before Monday touches `age_group`: `process_missing_games.py` (every 15 min), `enqueue_active_teams.py` and `enqueue_yesterday_games.py` all have zero `age_group` references. `drain_queue.py` runs only via `clear-queue.yml`, and `auto-merge-queue.yml` is dispatch-only — so nothing can auto-merge in the window.
- The ranking path never reads the season year (zero hits for `CURRENT_YEAR`/`_soccer_season_year` under `src/rankings/` and `scripts/calculate_rankings.py`), so a ranking run today matches what it would produce tomorrow.

**One residual, accepted:** `CURRENT_YEAR` does not flip until Aug 1, so the `find_queue_matches` fix derives one cohort low until then. Nothing scheduled consumes it in that window (Step 4 runs Monday, after the flip), but **do not manually dispatch Step 4 or `auto-merge-queue.yml` before Aug 1**.

Upside of going early: a full weekend between the migration and Monday's ranking run, so a rollback has real time in it.

## Deferred

Discovered while planning; each needs its own pass. 1–2 are time-sensitive.

1. **`src/models/game_matcher.py:1083`** rejects a valid `provider_team_id` match when the provider reports a new age, then fuzzy-matches on that new age → duplicate team. 98.9% of aliases are `direct_id`, so this is the main path. **This is the self-healing layer that fixes teams the roll got wrong.**
2. **Modular11 alias keys bake the cohort in** — `src/models/modular11_matcher.py:1156-1226` builds `{club_id}_{AGE}_{DIV}`, so 2026-27 U13 games land on the 2013-born team. Needs a season segment. Other providers key on `provider_team_id` and are fine.
3. **Scrape exclusions are the 2025-26 literal** — `scripts/scrape_games.py:389` and `scripts/drain_queue.py:481` hardcode `birth_year in [2005, 2006, 2017, 2018, 2019]`, which now drops the new U10 cohort. Filter on `age_group not in AGE_GROUPS` instead. Check whether a copy lives in an RPC.
4. Widen the fuzzy fallback to `{incoming, incoming-1}` during the transition.
5. **`src/utils/team_utils.py:20,58`** — `current_year: int = CURRENT_YEAR` binds at import, so long-lived processes never roll and monkeypatching won't reach it.
6. **`config/settings.py:91-102`** `_BIRTH_YEARS` is a frozen 2025-26 map that never rolls.
7. Pre-existing bad labels: 1,063 `u20`, 8 `u21`, 65 strays. Retiring u20 touches the quarantine/delete path.
8. **Prediction calibration is keyed by cohort** — `margin_parameters_v2.json` (primary, `matchPredictor.ts:816-818`) and `age_group_parameters.json` (fallback, `:819-821`). Post-roll, former-U11 inherits U12's `margin_mult`. Regenerate via `scripts/calibrate_margin_v2.py`.
9. Two contradictory dual-age rules: `fix_team_age_groups.py:135,148` takes the older cohort, `team_name_utils.py:506-515` the younger.
10. **Make rank-change cohort-aware** — `ranking_history.py:277` omits `age_group` from the select and `:639`/`:649` subtract by team ID, so any cohort change publishes a bogus movement arrow.
11. **Cohort-specific content goes stale** — `pa-u10-boys-soccer-rankings.mdx` is a whole post about "371 active U10 boys teams" with a 2016-birth-year leaderboard; `blog-faqs.ts:591` claims U10 is the youngest ranked; ~14 state guides carry per-cohort counts. Refresh or season-label after the ranking run, then `npm run generate-llms`.
12. Add `freezegun`; 22 `_canonicalize_age_token` assertions live in `if __name__ == "__main__"` and are never collected.
13. `frontend/lib/utils.ts` has zero test coverage despite `soccerSeasonYear()` feeding 17 call sites.
14. Rankings routes don't validate the age-group segment — `/rankings/az/u18/male` returns 200.
15. A "2026-27 season" qualifier on the rankings H1 (`page.tsx:183-185`) and `<title>` (`:64`) — two separate literals.

## Reference

- `.turbo/age-rollover-2026-recommendation.md` — 2026-07-28 audit. Its blast-radius findings hold; its "backfill birth_year then derive" strategy does not (8.8% coverage). The `strategy-v2.md` it promises was never written; this replaces it.
- `supabase/migrations/20260326000000_normalize_age_groups_season_year.sql` — closest prior art, same operation, same column.
- `supabase/migrations/20260603000000_sargable_age_filter_rankings_rpcs.sql` — current `get_national_rankings` / `get_state_rankings`; the RPCs match `'u12'`, `'U12'` and `'12'` variants (`:162-167`), so if non-canonical labels ever appear they'd render on a board while the `WHERE` skipped them. None exist today — all labels are lowercase `u##`.
- Both `rankings_view` and `state_rankings_view` are plain `CREATE VIEW`, not materialized. No `REFRESH` needed.
