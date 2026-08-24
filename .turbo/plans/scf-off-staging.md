---
status: done
---

# Plan: Config-gated SCF-off staging run + scorecard

## Context

The bubble-team investigation (`scripts/diagnose_bubble_teams.py`) plus an 8/8 read-only hotspot backtest (`baseline_prod` vs `abl_no_scf`: log-loss 0.6310→0.5671, accuracy 67.85%→71.60% +3.74 pts, ordering +3.42 pts across 13,702 holdout games on u17F/u16M) established that SCF base-shaping — not ML Layer 13 — drives "high-SOS / mediocre-record teams ranked too high." Positive ML is near-inert (329/59,600 teams get +ML ≥ 0.01; stripping it would slightly *worsen* the bubble), so the "reduce positive ML" idea is rejected. See memory `scf_bubble_investigation_2026_06`.

This plan does NOT ship an engine change. It produces a **staging-only, zero-prod-write SCF-off ranking board** and scores it with two existing harnesses, so the decision to ship full SCF-off (or fall back to tuning SCF strength dials) is made on real published-ordering evidence — not just the prediction-accuracy backtest. The deliverable is an SCF-off **scorecard**: does the bubble-guardrail count drop from the 27/12-cohort SCF-on baseline (hotspots u17F=7, u16M=5), and is the SCF-off→SCF-on board churn a legitimate strength re-coupling rather than a publish-artifact scramble (the failure mode of the rejected publish-only SCF, run #885).

The lever is the existing prod config flag `SCF_ENABLED` (`src/etl/glicko_config.py:86`, default `True`), gated in `src/etl/glicko_engine.py` (the `if cfg.SCF_ENABLED` checks around `apply_scf_dampening`). Because `compute_all_cohorts` builds `GlickoConfig()` internally with no injection seam, the flip is done via an **env-backed default** on that field (default unchanged when the env var is unset) plus a custom staging driver that sets the override only for its own process.

### Baseline & local-state hazard (read before any edit)

The working tree is on the **diverged feature branch** `fix/modular11-events-division-mapping`, whose copies of `calculator.py`, `glicko_engine.py`, `glicko_config.py`, `config/settings.py`, and `ranking_stability_check.py` **differ from `origin/main`**. The index also holds **unrelated staged work** (`config/settings.py` mod, a staged `docs/superpowers/specs/2026-05-28-somsports-...md` add, modified `CLAUDE.md`). `scripts/diagnose_bubble_teams.py` is **untracked** (exists only in the working tree, confirmed absent on `origin/main`).

Therefore:

- **Build this work in a git worktree off `origin/main`** (matches the user's worktree-discipline exception: unrelated staged work + HEAD on an unrelated branch → branching in place would bundle/conflict). Do NOT branch in place; do NOT include the unrelated staged `config/settings.py` / somsports spec / `CLAUDE.md` changes.
  - `git fetch origin main` then `git worktree add ../pitchrank-scf-off origin/main -b scf-off-staging`.
  - The worktree lacks `.env.local`, deps, etc. — copy `C:/PitchRank/.env.local` into it (needs `DATABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`), or run the staging driver from the main `C:/PitchRank` checkout once the (engine-identical) code is committed (see Step 7).
  - Carry the untracked `scripts/diagnose_bubble_teams.py` into the worktree (`cp` it in; it gets committed on `scf-off-staging`).
- **All `file_path:line` anchors below are origin/main-based** (verified via `git show origin/main:<path>`). The user's working-tree line numbers differ because of the divergence. **Grep-confirm every cited symbol on the fresh `origin/main` checkout before editing** — match by symbol, not line number.
- Before editing, verify the worktree tree is clean against `origin/main`: `git -C ../pitchrank-scf-off status -sb` shows only the intended new/modified files.

## Pattern Survey

**Analogous Features**

- **Offline backtest A/B (closest prior art; working-tree only, untracked on origin/main):** `experiments/glicko_backtest/backtest.py:71` defines variant `"abl_no_scf": ({"SCF_ENABLED": False}, {})`; `:182,192` does `cfg = ExpGlickoConfig(**cfg_overrides)` then `compute_rankings_v2(...)`; reads parquet (`:82,84`), writes no DB. Uses a **forked** `ExpGlickoConfig`/`glicko_engine_exp.py`, NOT the prod config — a model for read-only config-override scoring, not a reusable component.
- **Dry-run rankings run:** `scripts/calculate_rankings.py` `--dry-run` (:685), `--engine glicko|v53e` (:696), `--ml` (:680), `--force-rebuild` (:687). **Trap:** `--dry-run` gates only `save_rankings_to_supabase` (`:987/:997`); it does NOT pass `save_snapshot=False`/`persist_*=False` into `compute_all_cohorts`, so a bare `--dry-run` still writes the `ranking_history` snapshot + residual/explainability rows. The staging driver must NOT rely on `--dry-run`.
- **Two scoring harnesses (psycopg2 / `DATABASE_URL`, read-only SELECTs):** `scripts/ranking_stability_check.py` and `scripts/diagnose_bubble_teams.py`.

**Reusable Utilities**

- `src/rankings/calculator.py:2441` — `compute_all_cohorts(...)` (async). Accepts `v53_cfg`, `layer13_cfg`, `persist_game_residuals=True` (:2454), `persist_game_explainability=True` (:2455), `calculate_rank_changes_enabled=True` (:2456), `save_snapshot=True` (:2457) — but **no `glicko_cfg` param**. It fans out to per-cohort workers (`compute_rankings_with_ml` via `RankingContext`); the bare `GlickoConfig()` constructions live in that worker (`:2050` `glicko_cfg = GlickoConfig() if use_glicko else None`, `:2196` `cfg=glicko_cfg or GlickoConfig()`), with one more in `compute_all_cohorts` itself (`:2867` `GlickoConfig().EVIDENCE_GATE_FROZEN_REF`). All constructions are at call time (no module-level instances), so an env-backed default on the field is read at every one regardless of function. Returns `result["teams"]` (the in-memory engine board). Setting the four write-flags `False` makes it DB-read-only while still returning the board.
- `src/rankings/data_adapter.py` — `v53e_to_rankings_full_format(rankings_df, teams_metadata_df)`: the transform `calculate_rankings.py` applies to the engine board before writing `rankings_full`. It **derives `age_group` from the engine board's `age` field** (":736-739", `"ALWAYS derive age_group from the actual 'age' field"`) and **computes `win_percentage`** (and populates `national_power_score` = powerscore_ml/adj). The raw `result["teams"]` board carries `age`, NOT `age_group`, and has no `win_percentage` — so the board must pass through this formatter before it is bubble-filter-compatible.
- `src/rankings/calculator.py` — `save_ranking_snapshot(...)` calls at `:2354` and `:3330` (the only writes to `ranking_history`), gated solely by `save_snapshot` (`if save_snapshot ...` at ~:2350 and ~:3328). Residual gate ~:2290, explainability gate ~:2308. (Grep `save_ranking_snapshot` / `save_snapshot` to confirm exact lines on the checkout.)
- `src/rankings/calculator.py:2115-2147` — the `data/cache` parquet cache. The cache key **includes `SCF_ENABLED`**: `_cfg_dict` (`:2115`) contains `"scf": getattr(_ecfg, "SCF_ENABLED", True)` (`:2121`), hashed to `_cfg_fp` (`:2144`) and appended to `hash_input` (`:2145`) → final `cache_key` (`:2147`). An SCF-off run therefore writes to a **different** `rankings_<hash>_teams.parquet` filename and physically cannot overwrite the prod SCF-on cache entry. `force_rebuild=True` additionally skips the read. (Writes at `:2222/2226/2230`.)
- `scripts/calculate_rankings.py` `main()` (~:678): builds the service-role client (~:702-709), `MergeResolver` (~:712-713), fetches teams metadata (`team_id_master, age_group, gender, state_code`), calls `compute_all_cohorts(...)` (~:744/756), then `v53e_to_rankings_full_format(...)` before the (dry-run-gated) `save_rankings_to_supabase`. The staging driver mirrors this setup up to and including the formatter, then dumps instead of saving.
- `scripts/ranking_stability_check.py:79` `_open_connection()` → `psycopg2.connect(DATABASE_URL)`. Three checks: `check_nonplaying_churn` (:96, filters `cur.last_game <= prev` at :105/117), `check_stage_shift` (:138, computes `abs(rank_in_cohort - rank_in_cohort_final)` **within one board** at :142), `check_top100_churn` (:159). Prior snapshot auto-resolved from `ranking_history` at :87.
- `scripts/diagnose_bubble_teams.py:108` `_open_connection()` (same pattern); `_decomp_cte()` builds the bubble/attribution CTE with `board AS (... FROM rankings_full ...)`; the bubble filter selects `age_group`, `win_percentage`, `rank_in_cohort_final`, `sos_norm`, etc. (~:121-127); SELECT-only.

**Convention Anchors**

- **Env-override of engine knobs = `os.getenv` at config load, default to current value** — `config/settings.py:107-221` (`RANKING_CONFIG`/`ML_CONFIG`, e.g. `ML_ALPHA` :216). `GlickoConfig` is the lone exception (hardcoded defaults, no `os.getenv`). Step 2 brings `SCF_ENABLED` in line with this convention.
- **Read-only DB scoring scripts:** top-level `_open_connection()` + `psycopg2` + `DATABASE_URL` + SELECT-only; snapshot table `ranking_history`, live board `rankings_full`. Neither harness has an existing identifier-validation / `psycopg2.sql.Identifier` precedent — the table-name parameterization in Steps 5/6 is written from scratch.
- **Per-team parquet dump:** the only in-repo mechanism is `data/cache/rankings_{cache_key}_teams.parquet`; there is no standalone board-export script.
- **No Supabase dev-branch or staging-table precedent** exists in the ranking path — confirming the scratch-table approach over a Supabase branch.

**Proposed Alignment**

Do not edit engine logic. (a) Produce the board read-only via `compute_all_cohorts(..., save_snapshot=False, persist_game_residuals=False, persist_game_explainability=False, calculate_rank_changes_enabled=False, force_rebuild=True)` with `SCF_ENABLED=False` resolved through a new env-backed default, then pass `result["teams"]` through `v53e_to_rankings_full_format(...)` (with the fetched teams metadata) and dump that full `rankings_full`-shaped board to parquet. (b) Load the parquet into a **persistent scratch table** `rankings_full_scf_off` (`LIKE rankings_full`) and score with the existing harnesses via a new `--rankings-table` arg + a board-vs-board stability mode; drop the table after. This reuses the already-validated SQL (the 27-team baseline came from `diagnose_bubble_teams.py`'s SQL on the 2026-06-16 prod board) instead of re-deriving it in pandas.

## Implementation Steps

1. **Set up the isolated workspace off origin/main**
   - `git fetch origin main`; `git worktree add ../pitchrank-scf-off origin/main -b scf-off-staging`.
   - Copy `C:/PitchRank/.env.local` into the worktree (or plan to run the driver from `C:/PitchRank` after committing the engine-identical code there — see Step 7 note).
   - Copy the untracked `scripts/diagnose_bubble_teams.py` into the worktree.
   - Confirm clean baseline: `git -C ../pitchrank-scf-off status -sb` lists only intended files; the unrelated staged `config/settings.py` / somsports spec / `CLAUDE.md` changes must NOT be present.

2. **Add an env-backed default for `SCF_ENABLED` (the only engine-file edit)**
   - In `src/etl/glicko_config.py`: add `import os` at the top (preserve existing imports incl. `from dataclasses import dataclass, field`). Replace the `:86` field with:
     ```python
     SCF_ENABLED: bool = field(
         default_factory=lambda: os.getenv("SCF_ENABLED", "true").strip().lower() not in ("0", "false", "no")
     )
     ```
   - **Preserve every other field and the `@dataclass` decorator** — change only this one field and add `import os`. Default resolves to `True` when the env var is unset → prod behavior is byte-identical.
   - Grep-confirm `SCF_ENABLED` is still the only definition and that `glicko_engine.py`'s `if cfg.SCF_ENABLED` gates read this field (no second hardcoded source).

3. **Write the staging driver `scripts/run_scf_off_staging.py`**
   - Mirror `scripts/calculate_rankings.py` `main()` setup: load `.env.local`, build the service-role Supabase client, `MergeResolver`, and fetch the teams metadata DataFrame (`team_id_master, age_group, gender, state_code`). Run with `C:/Python313/python.exe`.
   - **Before importing/constructing any config**, set `os.environ["SCF_ENABLED"] = "false"` (in-process only) so the env-backed default resolves to `False` for every internal `GlickoConfig()`. Log the effective value (`GlickoConfig().SCF_ENABLED`) and **assert it is `False`**; abort loudly otherwise.
   - `await compute_all_cohorts(client, ..., use_glicko=True, force_rebuild=True, save_snapshot=False, persist_game_residuals=False, persist_game_explainability=False, calculate_rank_changes_enabled=False)` (match the exact kwargs/await pattern from `calculate_rankings.py`). No `data/cache` backup is needed — the cache key includes `SCF_ENABLED`, so this run writes a distinct SCF-off cache file that cannot touch the prod cache (the SCF-off cache file may be deleted in teardown; it is harmless either way).
   - **Capture the isolation signal first (staging-only):** before formatting, grab `iso = result["teams"][["team_id", "scf", "is_isolated"]]`. The engine board carries `scf` (float; <1 = SOS dampened) and `is_isolated` (bool) at `glicko_engine.py:1342/1344`, but `v53e_to_rankings_full_format` DROPS both (not in its `expected_columns`). They are required so the scorecard can attribute upward movers in Step 6 Check 1 — the `rankings_full`-shaped board alone cannot tell which movers are isolated/dampened.
   - **Pass the board through the prod formatter:** `formatted = v53e_to_rankings_full_format(result["teams"], teams_metadata_df)` — the same transform `calculate_rankings.py` runs before writing `rankings_full`. This derives `age_group` (from `age`), computes `win_percentage`, and populates `national_power_score`. Merge `iso` back onto `formatted` on `team_id` (staging-only columns), then dump to `data/staging/scf_off_teams.parquet` (create `data/staging/`).
   - **Column verification gate:** fail fast unless `formatted` contains every column the harnesses need: `team_id, age_group, gender, status, games_played, win_percentage, rank_in_cohort, rank_in_cohort_final, sos_norm, powerscore_adj, powerscore_ml, positive_ml_evidence_scale, publication_cap_score, power_score_true, last_game, national_power_score`, plus the staging-only `scf` and `is_isolated` merged above. The formatter always emits `last_game` (it is in `expected_columns`), so the real risk is the column being present but all-NULL; if so, populate it by joining `max(game_date)` per team from the `games` table before dumping (it is a `rankings_full` column the stability Check 1 carries for context).

4. **Load the parquet into a persistent scratch table**
   - In the driver (or a small `_load_scratch_table()` helper): `DROP TABLE IF EXISTS rankings_full_scf_off; CREATE TABLE rankings_full_scf_off (LIKE rankings_full INCLUDING DEFAULTS); ALTER TABLE rankings_full_scf_off ADD COLUMN scf double precision, ADD COLUMN is_isolated boolean;` (the two staging-only columns do not exist on `rankings_full`) then bulk-insert the dumped rows including `scf`/`is_isolated` (psycopg2 `execute_values` or `COPY`). Because the board is now the full `rankings_full` shape (incl. `national_power_score`, which is `FLOAT NOT NULL` with no default on `rankings_full` — migration `20250120130000_create_rankings_full.sql:69`), a full-column insert satisfies all NOT-NULL constraints. If any `rankings_full` NOT-NULL column is genuinely not produced by the formatter, `ALTER TABLE rankings_full_scf_off ALTER COLUMN <col> DROP NOT NULL` for just those columns before inserting.
   - Use a **persistent** table (not `TEMP`): the harnesses run as separate psycopg2 processes, so a session-temp table would vanish with the loader's connection.

5. **Add `--rankings-table` to `scripts/diagnose_bubble_teams.py`**
   - Add an argparse `--rankings-table` (default `rankings_full`) and thread it into `_decomp_cte()` so the `board AS (... FROM <table> ...)` source is parameterized. Table names can't be psycopg2 bind params; validate with a `^[a-z_][a-z0-9_]*$` whitelist AND interpolate via `psycopg2.sql.Identifier(...)` (belt-and-suspenders — there is no existing in-repo identifier-guard pattern to mirror).
   - **Preserve** all existing CTEs, the percentile/`cf_rank` logic, the three views, the verdict thresholds, and default behavior (no arg → reads `rankings_full` exactly as today).

6. **Add a board-vs-board mode to `scripts/ranking_stability_check.py`**
   - Add `--compare-table <name>` (validate via whitelist + `psycopg2.sql.Identifier`). Keep the existing snapshot-vs-prod default mode and its FAIL/exit-code gating untouched. In compare mode the baseline is **current `rankings_full`** and the candidate is `--compare-table` (e.g. `rankings_full_scf_off`) — NOT a `ranking_history` snapshot. Reframe the three checks for a *legitimate engine change* (movement is expected → INFO/characterization, not FAIL):
     - **Check 1 — movement magnitude (from `check_nonplaying_churn`, :96):** join candidate vs prod on `team_id`; report the per-cohort distribution of `|rank_cand − rank_prod|`. This is a same-snapshot board-vs-board diff, so **drop** the original function's `prev_date` parameter and its `WHERE cur.last_game <= prev` non-playing filter — both boards are current, there is no prior date, and the "did a non-playing team move" framing does not apply. (`last_game` stays on the candidate board for context/joins, not for filtering.) Confirm flagged bubble teams (high-SOS/mediocre-record) move DOWN; and, using the **staging-only `is_isolated`/`scf` columns** (Step 3), confirm isolated / low-`scf` teams do NOT spike UP (the #885 signature). This sub-check is only possible because Step 3 merged `scf`/`is_isolated` onto the board — the `rankings_full` shape drops them, so without that merge the harness can measure movement but cannot attribute upward movers.
     - **Check 2 — mu→published decoupling (from `check_stage_shift`, :142):** this is a *within-board* metric (`abs(rank_in_cohort − rank_in_cohort_final)`), so it does NOT take a "prev source." Run it independently on each board and **diff the aggregates** (SCF-off decoupling vs SCF-on decoupling); a healthy SCF-off board should not decouple more.
     - **Check 3 — top-N composition delta (from `check_top100_churn`, :159):** new entrants/exits in each cohort's top 50/100, candidate vs prod.
   - **Preserve** the original snapshot-based mode and its checks; the new mode is additive.

7. **Score and produce the SCF-off scorecard**
   - Run, against `rankings_full_scf_off`: `diagnose_bubble_teams.py --rankings-table rankings_full_scf_off` and `ranking_stability_check.py --compare-table rankings_full_scf_off`.
   - Compare to the SCF-on baseline: bubble-guardrail total (vs 27/12 cohorts) and hotspots (vs u17F=7, u16M=5); confirm the count drops and hotspot cohorts re-couple. Capture the board-vs-board movement profile.
   - Run the driver and both harnesses **from the worktree** with `C:/Python313/python.exe` — its deps (psycopg2/pandas/supabase/dotenv) live in the global Python313 install, not a per-checkout venv, so a fresh worktree needs only `.env.local` (copied in Step 1), not a dependency install. Do NOT fall back to running from the main `C:/PitchRank` checkout: it sits on the dirty, diverged feature branch and would reintroduce exactly the contamination the worktree isolation prevents. If a dep is genuinely missing, install it into Python313 (or point `PYTHONPATH` at the worktree), rather than switching checkouts.

8. **Teardown & safety confirmation**
   - The scratch table **persists by default** — the produce/load driver must NOT auto-drop it. Step 7 scores it from separate harness processes, so a `finally`-drop inside the driver would race and leave Step 7 querying a vanished table. Drop it only as an explicit step AFTER scoring is confirmed: a dedicated `--teardown` driver mode, or a one-line `DROP TABLE rankings_full_scf_off;`. Optionally delete the SCF-off `data/cache/rankings_<hash>_teams.parquet` the run created.
   - Confirm zero prod mutation: `rankings_full`, `current_rankings`, `ranking_history`, and `games` residual columns unchanged; the prod (SCF-on) `data/cache` files' mtimes unchanged; `SCF_ENABLED` env var not set in any prod environment.

### Out of scope (deferred)

- **Shipping** SCF-off (a separate PR: flip the env/default on a clean branch, run the full unit suite ~10 min, code review, guarded prod run). This plan ends at the scorecard + a ship/tune-down recommendation.
- **Tune-down fallback** (raise `SCF_FLOOR` / `SCF_DIVERSITY_DIVISOR` in `glicko_config.py`) — only if full-off proves too blunt on the scorecard.
- **Permanent `glicko_cfg` injection seam** (the cleaner DI refactor) — only if this staging path becomes a recurring experiment harness; retire the env seam then.
- Do NOT reopen publish-only SCF (scrambled the board, run #885).

## Verification

- **Prod-safety (must pass before trusting any output):**
  - After the run, `SELECT max(last_calculated) FROM rankings_full` and `SELECT max(snapshot_date) FROM ranking_history` are unchanged from pre-run values (no new prod write).
  - The prod (SCF-on) `data/cache` parquet files are unchanged (compare mtimes/listing); the SCF-off run only added a new distinct-hash cache file (or none, with `force_rebuild`).
  - Driver log shows `effective SCF_ENABLED = False` and the `False` assertion passed.
- **Board produced:** the driver dumped the `v53e_to_rankings_full_format` output (full `rankings_full` shape); the column-verification gate passed (all required columns incl. `age_group`, `win_percentage`, `last_game`, `national_power_score`, plus the staging-only `scf`/`is_isolated`); `rankings_full_scf_off` row count ≈ active-team count on the prod board.
- **Bubble guardrail (the headline):** `diagnose_bubble_teams.py --rankings-table rankings_full_scf_off` total < 27 and hotspots < (u17F 7 / u16M 5); the human-review list confirms previously-flagged teams dropped out of the top 50.
- **Stability (board-vs-board):** Check 1 movement concentrates on high-SOS/mediocre-record teams moving DOWN and genuinely-strong teams moving UP; isolated / low-`scf` teams (identified via the staging-only columns) do NOT spike up (distinct from #885). Check 2 decoupling on the SCF-off board is not worse than prod. Check 3 top-N churn is explainable.
- **Sanity:** spot-check 2–3 original human-review teams (e.g. the u17 Male Vancouver Whitecaps case) — their `rank_in_cohort_final` on `rankings_full_scf_off` should be materially worse than on `rankings_full`.
- **Edge cases:** cohorts with <12-game teams still produce sane percentiles; a cohort with zero bubble teams reports cleanly; `--rankings-table`/`--compare-table` reject non-whitelisted identifiers.

## Context Files

- `src/rankings/calculator.py` — `compute_all_cohorts` (:2441) signature + the four write-flag gates (~:2290/:2308/:2354/:3330); the `GlickoConfig()` constructions in the per-cohort worker `compute_rankings_with_ml` (:2050/:2196) and in `compute_all_cohorts` (:2867); the SCF-keyed cache logic (:2115-2147). (Differs from origin/main on this branch — read the origin/main copy.)
- `src/rankings/data_adapter.py` — `v53e_to_rankings_full_format` (the `age_group`/`win_percentage`/`national_power_score` derivation, ~:736-739 + win% calc); the keystone transform the driver must run before dumping.
- `src/etl/glicko_config.py` — the `GlickoConfig` dataclass and `SCF_ENABLED` field (:86); target of Step 2. (Differs vs origin/main — use the clean checkout.)
- `src/etl/glicko_engine.py` — the `if cfg.SCF_ENABLED` gates (~:919/:1719) and `apply_scf_dampening` (~:1320); confirms flipping the field is sufficient. Also the source of the board's `scf` (:1342) and `is_isolated` (:1344) columns that Step 3 captures as staging-only (the formatter drops them). (Differs vs origin/main.)
- `scripts/calculate_rankings.py` — `main()` setup (client/resolver/teams-metadata fetch), the `compute_all_cohorts` call + the `v53e_to_rankings_full_format` step the driver mirrors; the `--dry-run` trap. (Unchanged vs origin/main.)
- `scripts/diagnose_bubble_teams.py` — `_decomp_cte()` + the bubble filter/attribution SQL; target of Step 5; encodes the 27-team baseline logic. (Untracked — carry into the worktree.)
- `scripts/ranking_stability_check.py` — the three checks (:96 `last_game`-based, :138/:142 within-board, :159) and `_open_connection`; target of Step 6. (Differs vs origin/main — verify against the checkout.)
- `experiments/glicko_backtest/backtest.py` — the `abl_no_scf` override + read-only scoring pattern (:71/:182/:192); the model the staging driver follows. (Working-tree only.)
- `config/settings.py` — the `os.getenv` env-override convention (:107-221) Step 2 mirrors. (Differs vs origin/main.)
- `supabase/migrations/20250120130000_create_rankings_full.sql` — the `rankings_full` schema, incl. `national_power_score FLOAT NOT NULL` (:69), for the scratch-table create.
- Memory `scf_bubble_investigation_2026_06` — why SCF (not ML) is the lever; the SCF-on baseline numbers to beat.
