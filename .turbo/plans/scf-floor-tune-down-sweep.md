---
status: done
---

# Plan: SCF_FLOOR tune-down sweep (softer SCF, not zero)

## Context

The completed SCF-off staging run (`.turbo/plans/scf-off-staging.md` [done]; scorecard `.turbo/scf-off-staging-scorecard.md`; memory `scf_bubble_investigation_2026_06`) proved that **fully disabling SCF is too blunt**: the bubble guardrail barely moved (27→25), u17/Female *regressed* (7→8), and the 5 biggest risers were all *losing* teams vaulted into their cohort's top decile, with inflation shifting to ML. Conclusion: SCF is the right lever, but the fix is a **softer SCF, not zero SCF**.

This plan sweeps the SCF strength dial — `SCF_FLOOR ∈ {0.55, 0.60, 0.65, 0.70}` at the current `SCF_DIVERSITY_DIVISOR=4.0`, SCF **on** for every candidate — to find the *lowest* floor that fixes the published-board bubble problem without re-creating the full-off pathologies, while retaining the prediction gain that made SCF-off attractive. It reuses and extends the staging harness already committed on `scf-off-staging` (`85e2c6a18`). The deliverable is a tune-down scorecard naming the recommended floor (or concluding none passes → escalate). Shipping the winner to prod is a separate guarded PR, out of scope here.

`SCF_FLOOR` raises the dampening floor: `scf = max(SCF_FLOOR, min(weighted_unique_states / SCF_DIVERSITY_DIVISOR, 1.0))` (`src/etl/glicko_engine.py:975-982`). Higher floor = less dampening = behavior closer to SCF-off; lower floor = closer to current prod. The current prod default is `SCF_FLOOR=0.4`. (Side effect to keep in mind: the floor also caps the top of the `SCF_ZERO_BRIDGE_FLOOR`→`SCF_FLOOR` ramp for under-bridged teams, `glicko_engine.py:979-981`.)

### Locked decisions (do not re-open)

- **Dials:** `SCF_FLOOR ∈ {0.55, 0.60, 0.65, 0.70}`, `SCF_DIVERSITY_DIVISOR=4.0`, SCF on for all candidates.
- **One fixed snapshot — fetch ONCE, reuse for all 5 boards.** The staging harness builds each board with `fetch_from_supabase=True`, so 5 sequential ~35-min runs would each re-fetch live games and re-introduce the very confound this is meant to kill. Instead: **fetch the games dataset once** (pin `today`), persist it to a snapshot parquet, and build the SCF-on baseline (floor 0.4) AND all 4 floor candidates from that **identical** dataset via `compute_all_cohorts(games_df=<snapshot>, fetch_from_supabase=False, today=<fixed>)`. Only then is every delta pure dial effect (vs the 3-day confound the staging run had — verified moderate, ~5.4% of active teams differed). This is load-bearing: without the single prefetch the "same-snapshot" promise is not actually delivered.
- **Winner rule:** recommend the **lowest** floor that passes all 4 criteria (max prediction retention while still fixing the board).
- **Both scorers:** every candidate scored on the published board AND with the prediction backtest.

### Pass criteria (a floor must satisfy all four)

1. **Bubble count materially improves** — `diagnose_bubble_teams.py` total on the floor board is below the same-snapshot SCF-on baseline's total, with no hotspot (u16M, u17F) regressing.
2. **u17/Female does not regress** — floor-board u17F bubble count ≤ the same-snapshot baseline's u17F count.
3. **No losing team in the cohort top decile** — zero Active teams with `win_percentage < 45` ranked in the top 10% (`rank_in_cohort_final ≤ ceil(0.10 × cohort_active_count)`) of any cohort, OR no more than the baseline already has (this is the full-off failure mode: 5/5 risers were sub-.500 teams in the top 10-19%).
4. **Prediction stays meaningfully better than prod (numeric gate).** On the u17F+u16M holdout backtest (8 cells = 2 cohorts × 4 cutoffs), vs the `baseline_prod` variant the floor must: (a) win accuracy in **≥6/8 cells**, (b) post a **pooled accuracy delta ≥ +1.5 pts** (≈40% of the SCF-off `abl_no_scf` +3.74-pt reference), and (c) have **pooled log-loss no worse** than baseline. These are the proposed thresholds (the ship PR may revisit) — their purpose is to make "lowest passing floor" deterministic rather than a judgment call. Report each floor's magnitude vs both `baseline_prod` and the +3.74 reference.

## Pattern Survey

**Analogous Features**

- `scripts/run_scf_off_staging.py` (worktree HEAD `85e2c6a18`) — the direct prior art and baseline. Forces SCF off via `os.environ["SCF_ENABLED"]="false"` **after** dotenv-load (~line 65), asserts the effective value (`_assert_scf_off`, ~103-108), builds a board zero-prod-write through `compute_all_cohorts(..., force_rebuild=True, save_snapshot=False, persist_game_residuals=False, persist_game_explainability=False, calculate_rank_changes_enabled=False)` (~219-231), formats via `v53e_to_rankings_full_format` (~239), and loads one fixed scratch table `rankings_full_scf_off` created `LIKE rankings_full INCLUDING DEFAULTS` (~179-201). `--teardown` drops it (~277-285). To become a sweep it needs: per-candidate floor/divisor env-forcing, an SCF-on mode, and a parameterized scratch-table name (currently the module constant `SCRATCH_TABLE`, ~line 68). **Grep-confirm all line numbers — the implementer extends this file.**
- `experiments/glicko_backtest/backtest.py:57-78` (**MAIN CHECKOUT ONLY** — see Convention Anchors) — the `VARIANTS` dict maps name → `(cfg_field_overrides, run_kwargs_overrides)`; `"abl_no_scf": ({"SCF_ENABLED": False}, {})` (line 71) is the dial-exposure pattern. A floor sweep adds entries like `"scf_floor_055": ({"SCF_FLOOR": 0.55, "SCF_DIVERSITY_DIVISOR": 4.0}, {})` plus the existing `baseline_prod` (line 58, `({},{})`). `run_variant` does `cfg = ExpGlickoConfig(**cfg_overrides)` then `compute_rankings_v2(...)` (~181-192) — overrides flow straight in as dataclass kwargs.

**Reusable Utilities**

- `src/etl/glicko_config.py:87-89` — the `SCF_ENABLED` env-backed `field(default_factory=lambda: os.getenv(...))` template (added in the staging session). `SCF_DIVERSITY_DIVISOR` (~line 101, plain `4.0`) and `SCF_FLOOR` (~line 102, plain `0.4`) are currently **non-env plain defaults** — to mirror the seam they become `field(default_factory=lambda: float(os.getenv("SCF_FLOOR", "0.4")))` and likewise for the divisor. `import os` is already present.
- `src/etl/glicko_engine.py:975-982` — consumption: `scf_raw = min(weighted_unique_states / cfg.SCF_DIVERSITY_DIVISOR, 1.0); scf = max(cfg.SCF_FLOOR, scf_raw)`. Reads both off `cfg`, so an env-backed default propagates with **zero engine-logic edits**.
- `scripts/run_scf_off_staging.py` `_load_scratch_table` (~179-201, DROP IF EXISTS → CREATE LIKE → `execute_values`) and `_verify_board_columns` + `HARNESS_REQUIRED_COLUMNS`/`HARNESS_NULLABLE_COLUMNS` (~74-92, ~148-160) — reusable per-candidate once `SCRATCH_TABLE` is a parameter.
- `scripts/diagnose_bubble_teams.py` `--rankings-table` (~298-307; default `rankings_full`, regex-validated `[a-z_][a-z0-9_]*` + `sql.Identifier`) — score each candidate board by name. **Confirmed present** (added this session).
- `scripts/ranking_stability_check.py` `--compare-table` (~346-355; board-vs-board, additive, INFO-only, same regex guard) — compares a candidate to a baseline that is currently **hardcoded to `rankings_full`** in the `compare_*` functions. **Confirmed present.**
- `experiments/glicko_backtest/glicko_engine_exp.py` — `ExpGlickoConfig(GlickoConfig)` (~30-37) adds only `SELECTION_OUTCOME_BLIND`/`PROVISIONAL_SHRINK_TO_MEAN`/`TIER_MULT_CENTERED`/`CROSS_AGE_UNIFIED`/`SCF_PUBLISH_ONLY`, but **inherits `SCF_FLOOR`/`SCF_DIVERSITY_DIVISOR`** from `GlickoConfig`, so `ExpGlickoConfig(SCF_FLOOR=0.55, SCF_DIVERSITY_DIVISOR=4.0)` is already valid — **no fork field addition needed**. The fork's floor logic (~1035-1042) is byte-identical to prod (`glicko_engine.py:975-982`).

**Convention Anchors**

- **Cache fingerprint is load-bearing and INCOMPLETE for this sweep.** `src/rankings/calculator.py:2115-2143` `_cfg_dict` keys on `"scf"` (SCF_ENABLED), `scf_po`/`scf_lf`/`scf_lc` — but **`SCF_FLOOR` and `SCF_DIVERSITY_DIVISOR` are ABSENT**. Two SCF-on floor variants hash to the **same** `_cfg_fp` and share a parquet cache filename. `force_rebuild=True` (which the driver already passes) bypasses the cache *read*, so sequential single-board runs are still *correct* (each rebuilds fresh) — but the *write* path reuses the same `cache_key`, so the fix is to extend `_cfg_dict` with `"scf_fl": getattr(_ecfg, "SCF_FLOOR", None)` and `"scf_dd": getattr(_ecfg, "SCF_DIVERSITY_DIVISOR", None)` (matching the existing `getattr(..., None)` idiom). This makes each floor's cache key distinct regardless of run order/concurrency.
- **Env-force-after-dotenv ordering** (`run_scf_off_staging.py:55-65`; memory `gotcha_dotenv_override_order`): load `.env.local` first, then overwrite `os.environ[...]`, so a stray value can't win and `GlickoConfig` reads the env-backed default only at construction. The sweep sets `SCF_ENABLED="true"` (for ON candidates) + `SCF_FLOOR` + `SCF_DIVERSITY_DIVISOR` in this same window, **re-forced per candidate** before any `GlickoConfig()` / `compute_all_cohorts` call.
- **The backtest harness is untracked AND not engine-self-contained.** `experiments/glicko_backtest/` is plain untracked (not gitignored) and exists ONLY in the main checkout. It is NOT engine-isolated: `backtest.py` prepends the repo root to `sys.path` and `glicko_engine_exp.py` imports `src.etl.glicko_config`, so a run executes against the **host checkout's `src/`**. The main checkout's `src/` is the DIRTY `fix/modular11-...` feature branch → running the backtest there makes criterion 4 non-reproducible. Fix (Step 8): **copy `experiments/glicko_backtest/` + its `data/` into the worktree** (clean origin/main `src/` plus the behavior-preserving env-seam) and run it THERE; or verify the main checkout's engine files match `origin/main` before trusting any result. It still reads no prod DB (parquet data) and uses explicit kwargs (not the env seam), so floor sweeps remain VARIANTS-dict-only.
- **Two work locations, two mechanisms:** the board sweep (env seam + driver + cache fingerprint + scoring) runs in the **worktree** `C:/pitchrank-scf-off`; the prediction backtest runs in the **main checkout** `C:/PitchRank`. They are independent — the env seam is for the driver, the backtest uses `ExpGlickoConfig(SCF_FLOOR=...)` kwargs.
- **Run environment:** `C:/Python313/python.exe` (the venv is dead — memory `env_broken_venv_use_python313`). Each board is a full ~35-min two-pass run; 5 boards ≈ 3 hours mostly-sequential.

**Proposed Alignment**

Mirror the `SCF_ENABLED` env seam for `SCF_FLOOR`/`SCF_DIVERSITY_DIVISOR` (no engine-logic edit); generalize the staging driver to one-candidate-per-invocation with a parameterized scratch table and per-candidate floor/divisor forcing; extend the cache fingerprint so floors don't share a cache key; add a `--baseline-table` arg to the stability compare mode so movement is measured against the same-snapshot baseline (not stale prod); add backtest `VARIANTS` entries (kwargs only) in the main checkout. Score each board with the already-present `--rankings-table` / `--compare-table` plus a documented per-board "losing-in-top-decile" SQL check, and each floor with the hotspot backtest. Synthesize a scorecard recommending the lowest passing floor.

## Implementation Steps

1. **Confirm the isolated workspace (no new worktree).**
   - The board-sweep work extends the harness already committed on `scf-off-staging` (`85e2c6a18`) in the existing worktree `C:/pitchrank-scf-off`. Verify it is the right baseline before editing: `git -C ../pitchrank-scf-off status -sb` should show branch `scf-off-staging` at/after `85e2c6a18`. **Expected, ignorable noise** (do NOT treat as a dirty baseline): modified `*.pyc` bytecode regenerated by prior runs (never stash them — memory `feedback_git_stash`), untracked `data/` cache parquets + `*.log` files, and `[ahead 1, behind 1]` vs `origin/main` (the branch predates one unrelated main commit — harmless for this self-contained sweep). The real gate: no unexpected modified **source** files (`.py`/`.sql`/`.md`) beyond the ones this plan edits.
   - The backtest (`experiments/glicko_backtest/`, untracked, main-checkout-only) is NOT engine-self-contained — it runs against the host checkout's `src/` (Step 8). For a reproducible criterion-4, copy that dir (+ its `data/`) into the worktree and run it there against clean origin/main `src/`; do NOT run it from the dirty main checkout. Do NOT edit the main checkout's `src/` engine files.

2. **Env-back `SCF_FLOOR` and `SCF_DIVERSITY_DIVISOR` (worktree `src/etl/glicko_config.py`).**
   - Grep-confirm the current `SCF_FLOOR` / `SCF_DIVERSITY_DIVISOR` field lines (survey: ~101-102). Replace the plain defaults with the env-backed `field(default_factory=...)` form, mirroring `SCF_ENABLED` (~87-89):
     - `SCF_DIVERSITY_DIVISOR: float = field(default_factory=lambda: float(os.getenv("SCF_DIVERSITY_DIVISOR", "4.0")))`
     - `SCF_FLOOR: float = field(default_factory=lambda: float(os.getenv("SCF_FLOOR", "0.4")))`
   - **Preserve** every other field and the `@dataclass`. `import os` already exists. Defaults resolve to `4.0`/`0.4` when unset → prod behavior byte-identical.
   - Mirror `tests/unit/test_glicko_config_scf_env.py` with a parametrized test asserting unset→4.0/0.4 and `os.getenv` overrides parse to float (e.g. `SCF_FLOOR=0.6`→0.6).

3. **Extend the cache fingerprint (worktree `src/rankings/calculator.py`).**
   - In `_cfg_dict` (~2115-2143, grep-confirm), add two keys alongside the existing `scf*` entries: `"scf_fl": getattr(_ecfg, "SCF_FLOOR", None)` and `"scf_dd": getattr(_ecfg, "SCF_DIVERSITY_DIVISOR", None)`. This is additive and behavior-preserving except that it changes the cache key (a one-time rebuild on first run) — required so floor variants get distinct `rankings_<hash>_teams.parquet` filenames.

4. **Generalize the driver into a per-candidate board producer (worktree `scripts/run_scf_off_staging.py`).**
   - Add args: `--scf-floor <float>`, `--scf-divisor <float>` (default 4.0), `--scf-mode {on,off}` (default keep `off` for backward compat), `--table <name>` (validate with the existing `[a-z_][a-z0-9_]*` whitelist), and — for the same-snapshot guarantee — **`--games-snapshot <parquet>` + `--today <YYYY-MM-DD>`**. When `--games-snapshot` is given, load it with `pd.read_parquet` and call `compute_all_cohorts(games_df=<loaded>, fetch_from_supabase=False, today=pd.Timestamp(args.today), ...)` so every board consumes byte-identical input; without it, retain the current `fetch_from_supabase=True` single-board behavior. (`compute_all_cohorts` already accepts `games_df` + `fetch_from_supabase=False` + an explicit `today` — no engine change needed for this seam.)
   - In the post-`load_dotenv` force window (~55-65), set per candidate: `os.environ["SCF_ENABLED"] = "true" if mode=="on" else "false"`, and when mode is `on` also `os.environ["SCF_FLOOR"]`, `os.environ["SCF_DIVERSITY_DIVISOR"]` — BEFORE any `GlickoConfig()`/`compute_all_cohorts`. Generalize `_assert_scf_off` into an effective-config assert that logs `GlickoConfig().SCF_ENABLED / SCF_FLOOR / SCF_DIVERSITY_DIVISOR` and asserts they match the requested candidate; abort loudly otherwise.
   - Parameterize `SCRATCH_TABLE` (the module constant ~line 68) so each invocation loads its own table. Keep the zero-prod-write flags + `force_rebuild=True`; reuse `_load_scratch_table` and `_verify_board_columns` unchanged. Generalize `--teardown` to honor the same `--table` arg (drop one named table per invocation); Step 10 runs it once per scratch table.
   - One invocation = one board (resumable; inspect each before the next). The "sweep" is 5 invocations (Step 6).

5. **Add `--baseline-table` to the stability compare mode (worktree `scripts/ranking_stability_check.py`).**
   - The baseline is hardcoded as `rankings_full` in **four** places — enumerate them so the edit is mechanical (grep-confirm; line numbers drift): (a) `compare_movement` (inline `FROM rankings_full`); (b) `compare_top_movers` (inline `FROM rankings_full`); (c) `compare_stage_shift` — which passes the string **literal** `"rankings_full"` into `_stage_shift(cur, "rankings_full", ...)`, and `_stage_shift` interpolates it raw into `FROM {table_sql}` with NO `sql.Identifier` guard, so the pre-quoted baseline identifier must be passed in here (this is the non-obvious site); (d) `compare_topn_composition` (inline `FROM rankings_full`). Add a `--baseline-table` arg (default `rankings_full`), validate it with the same `[a-z_][a-z0-9_]*` whitelist and quote via `sql.Identifier(...).as_string(conn)` exactly like `cand_ident`, then replace all four occurrences with the quoted baseline so the candidate is compared to the **same-snapshot SCF-on baseline** (`rankings_full_scf_on_base`), not stale prod. Preserve default behavior (no arg → `rankings_full`) and the snapshot mode.

6. **Fetch ONCE, then build the 5 boards (worktree, `C:/Python313/python.exe`, sequential ~3 h, zero-prod-write).**
   - Capture pre-run prod-safety baselines first: `max(last_calculated)` from `rankings_full`, `max(snapshot_date)` from `ranking_history`, `count(*)` from `rankings_full`.
   - **Fetch-once (the same-snapshot guarantee):** run a single `fetch_games_for_rankings` with `today` pinned to today's date and the same `MergeResolver`, and dump the resulting `games_df` to `data/staging/sweep_games_snapshot.parquet`. Every board build below passes `--games-snapshot data/staging/sweep_games_snapshot.parquet --today <that date>` so all 5 share byte-identical inputs. (Add a `--fetch-snapshot` mode to the driver, or a tiny one-shot fetch, to produce this parquet.)
   - Baseline: `--scf-mode on --scf-floor 0.4 --scf-divisor 4.0 --table rankings_full_scf_on_base --games-snapshot <parquet> --today <date>` (SCF-on, prod dials).
   - Floors: `--scf-mode on --scf-floor {0.55,0.60,0.65,0.70} --scf-divisor 4.0 --table rankings_full_scf_floor055|060|065|070 --games-snapshot <parquet> --today <date>`.
   - Each writes a distinct scratch table; confirm row counts ≈ active-team count and the column gate passes per board.

7. **Score every board on the published board (worktree).**
   - Guardrail per board: `diagnose_bubble_teams.py --rankings-table <table>` → bubble total + per-cohort counts + attribution. Criteria 1 & 2 = compare each floor's total / u17F to `rankings_full_scf_on_base`'s.
   - Movement (clean, confound-free): `ranking_stability_check.py --compare-table <floor_table> --baseline-table rankings_full_scf_on_base` → biggest movers with sos_norm/win%. **Descriptive only — NOT a pass/fail gate** (criterion 3, losing-in-top-decile, is the defensibility gate that captures the board-shock concern). Use it to sanity-check the human read.
   - Criterion 3 (losing-in-top-decile), documented per-board SQL (psycopg2/`DATABASE_URL`, read-only). The staging-session sanity query was never committed, so use this skeleton against each board `<table>` (and the baseline):
     ```sql
     WITH cohort AS (
       SELECT team_id, age_group, gender, win_percentage, rank_in_cohort_final,
              count(*) OVER (PARTITION BY age_group, gender) AS cohort_n
       FROM <table>
       WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL
     )
     SELECT c.age_group, c.gender, count(*) AS losing_in_top_decile,
            array_agg(t.team_name ORDER BY c.rank_in_cohort_final) AS teams
     FROM cohort c LEFT JOIN teams t ON t.team_id_master = c.team_id
     WHERE c.win_percentage < 45
       AND c.rank_in_cohort_final <= ceil(0.10 * c.cohort_n)
     GROUP BY c.age_group, c.gender
     ORDER BY losing_in_top_decile DESC;
     ```
     The `teams` join supplies names for the scorecard — the scratch table is `LIKE rankings_full` and has no `team_name` (memory `gotcha_rankings_full_no_team_name`). A floor passes criterion 3 when the cross-cohort total is 0, or ≤ the same-snapshot baseline's count.

8. **Score every floor on prediction — against a CLEAN engine.**
   - **Reproducibility (P1):** `backtest.py` prepends the repo root to `sys.path` and `glicko_engine_exp.py` imports `src.etl.glicko_config`, so the run uses the host checkout's `src/`. Run it against clean origin/main `src/`: **copy the untracked `experiments/glicko_backtest/` (incl. its `data/` parquets) into the worktree `C:/pitchrank-scf-off`** and run it there, NOT from the dirty main checkout. The worktree's behavior-preserving env-seam edits don't affect the backtest (it passes explicit kwargs, not env).
   - Add `VARIANTS` entries: `scf_floor_055/060/065/070` = `({"SCF_FLOOR": x, "SCF_DIVERSITY_DIVISOR": 4.0}, {})`, scored against `baseline_prod`. No `ExpGlickoConfig`/engine edit (inherited fields).
   - Run the hotspot cohorts (mirrors the `scf_bubble_investigation` 8/8 method): `python experiments/glicko_backtest/backtest.py --cohorts 17:female,16:male --variants baseline_prod,scf_floor_055,scf_floor_060,scf_floor_065,scf_floor_070`. Apply the criterion-4 numeric gate (≥6/8 cells, pooled accuracy ≥ +1.5 pts, pooled log-loss not worse), reporting each floor vs `baseline_prod` and the +3.74 reference.

9. **Synthesize the tune-down scorecard (`.turbo/scf-floor-tune-down-scorecard.md`).**
   - Anchor every criterion-1/2 comparison to the **fresh** same-snapshot baseline `rankings_full_scf_on_base` (today's games), NOT the stale 2026-06-16 prod numbers (27 total / u17F=7 / u16M=5 came from a different game set). Recompute the baseline's per-cohort totals on this snapshot first, then compare each floor against those.
   - Per-floor table: bubble total (vs `rankings_full_scf_on_base`), u17F, u16M, losing-in-top-decile count, prediction Δ (accuracy/log-loss vs the `baseline_prod` backtest variant + vs the +3.74 full-off reference), and a 4-criteria pass/fail.
   - Recommendation: the **lowest** floor passing all 4, labeled **PROVISIONAL** — it clears one frozen board snapshot, so the separate ship PR must re-validate it (fresh board guardrail + full unit suite) before promoting the prod default. If none passes, conclude → escalate (next lever: `SCF_DIVERSITY_DIVISOR`, or a publication guard / SOS-credit cap), and say so explicitly.

10. **Teardown & prod-safety confirmation.**
    - After scoring is captured, drop every scratch table by running `--teardown --table <name>` once per table (`rankings_full_scf_on_base`, `rankings_full_scf_floor055/060/065/070`); optionally delete the distinct-hash `data/cache` parquets the runs created.
    - Confirm zero prod mutation: `max(last_calculated)` / `max(snapshot_date)` / `rankings_full` count unchanged from Step 6's pre-run capture; only the (now-dropped) scratch tables ever existed; `SCF_FLOOR`/`SCF_DIVERSITY_DIVISOR`/`SCF_ENABLED` never set in any prod environment (in-process only).

### Out of scope (deferred)

- Shipping the winning floor to prod — a separate guarded PR: flip the prod default (or set the env) on a clean branch off `origin/main`, run the FULL unit suite (~10 min, memory `feedback_full_suite_before_push`), code review, guarded prod run. This plan ends at the scorecard + recommendation.
- Sweeping `SCF_DIVERSITY_DIVISOR` or a publication guard / SOS-credit cap — only if no floor passes (escalation path).
- A permanent injection seam / config-experiment framework — only if floor sweeps become recurring.

## Verification

- **Config seam:** the new `test_glicko_config_scf_env.py` cases pass; `GlickoConfig().SCF_FLOOR` is `0.4` unset and `0.6` under `SCF_FLOOR=0.6`; same for the divisor. `ruff check` clean; the existing engine unit tests (`tests/unit/test_glicko_engine.py`, `test_league_bubble_scf.py`, `test_glicko_sos_role.py`) still pass (behavior-preserving when env unset).
- **Cache disambiguation:** two floor runs produce two distinct `data/cache/rankings_<hash>_teams.parquet` filenames (hash differs because `_cfg_dict` now includes the floor).
- **Boards produced:** each of the 5 scratch tables has ≈ active-team count rows and passes the column gate; the driver log shows the asserted effective `SCF_ENABLED/SCF_FLOOR/SCF_DIVERSITY_DIVISOR` per candidate.
- **Prod-safety (must pass before trusting output):** `max(last_calculated)`, `max(snapshot_date)`, and `rankings_full` count are unchanged after the full sweep vs the Step 6 pre-run capture; no prod (SCF-on default) `data/cache` parquet mtimes change.
- **Criteria computed:** for each floor the scorecard reports all 4 criteria with numbers; the recommendation names the lowest passing floor (or escalates).
- **Edge cases:** a floor that fixes the board but kills prediction (criterion 4 fail) is correctly rejected; a floor where a losing team sits in a cohort top decile (criterion 3 fail) is rejected even if the bubble count dropped; cohorts with zero bubbles score cleanly; `--baseline-table`/`--table` reject non-whitelisted identifiers.

## Context Files

- `scripts/run_scf_off_staging.py` — the driver to generalize (env force window, `_load_scratch_table`, `_verify_board_columns`, `SCRATCH_TABLE`, zero-write flags, `--teardown`). Worktree HEAD.
- `src/etl/glicko_config.py` — `SCF_ENABLED` env-seam template (~87-89) + the `SCF_FLOOR`/`SCF_DIVERSITY_DIVISOR` plain defaults (~101-102) to convert.
- `src/etl/glicko_engine.py` — the `scf = max(SCF_FLOOR, min(.../SCF_DIVERSITY_DIVISOR, 1.0))` consumption (~975-982); confirms no engine-logic edit is needed and shows the zero-bridge ramp side effect.
- `src/rankings/calculator.py` — `_cfg_dict` cache fingerprint (~2115-2143) to extend with `scf_fl`/`scf_dd`.
- `scripts/diagnose_bubble_teams.py` — `--rankings-table` + the bubble definition/baseline numbers (~298-307 and the module docstring).
- `scripts/ranking_stability_check.py` — `--compare-table` + the `compare_*` functions to thread `--baseline-table` through (~346-355 and the compare-mode block).
- `experiments/glicko_backtest/backtest.py` — `VARIANTS` dict (~57-78) + `run_variant` (~181-192). **Main checkout only.**
- `experiments/glicko_backtest/glicko_engine_exp.py` — `ExpGlickoConfig` (~30-37) confirming inherited floor fields; the byte-identical floor logic (~1035-1042). **Main checkout only.**
- `.turbo/scf-off-staging-scorecard.md` + memory `scf_bubble_investigation_2026_06` — the full-off result, the baselines to beat, and the failure mode criterion 3 guards against.
- Memory `gotcha_dotenv_override_order` — force env overrides AFTER `load_dotenv(override=True)`.
- Memory `rankings_offline_run_gotchas`, `env_broken_venv_use_python313` — offline-run + Python-interpreter gotchas.
