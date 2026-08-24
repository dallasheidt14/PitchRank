---
status: done
---

# Plan: SCF_DIVERSITY_DIVISOR sweep (change WHICH teams dampen, not how hard)

## Context

The completed `SCF_FLOOR` tune-down sweep (`.turbo/plans/scf-floor-tune-down-sweep.md` [done]; scorecard `.turbo/scf-floor-tune-down-scorecard.md`; memory `scf_bubble_investigation_2026_06`) proved that **`SCF_FLOOR` cannot decouple bubble-suppression from prediction loss.** Floors 0.60–0.70 fixed the published board (bubble 25→23, both hotspots improve, losing-in-top-decile drops, gentle movement) but recovered only +0.30 to +0.48 pts of prediction vs the +1.5-pt gate and the +3.74 full-off reference — because the prediction gain and the indefensible-board damage are **co-located in the aggressive-dampening tail (floor→1.0)**. Raising the floor lifts everyone's dampening floor uniformly, so it moves both together and can't trade one for the other. No floor passed all four criteria → escalate.

`SCF_DIVERSITY_DIVISOR` is the next lever, and it is structurally different. It sets the **connectivity threshold** rather than the dampening depth: `scf_raw = min(weighted_unique_states / SCF_DIVERSITY_DIVISOR, 1.0)` (`src/etl/glicko_engine.py:975`), then `scf = max(SCF_FLOOR, scf_raw)`. Prod `=4.0` means a team needs 4 weighted unique states to earn full credit (no raw-term dampening); below that it dampens (bounded by the floor). Changing the divisor changes **which** teams fall under the dampening threshold — a *lower* divisor (e.g. 3.0) lets more teams reach full credit (looser, closer to SCF-off, prediction-recovering, but re-bubbling), a *higher* divisor (e.g. 6.0/8.0) pulls more teams under the threshold (stricter isolation detection, more bubble suppression). The hypothesis worth testing: a divisor value that catches the genuinely-isolated bubble teams **without** over-dampening the well-connected teams that drive prediction — the decoupling the floor couldn't deliver.

This sweep holds `SCF_FLOOR` at prod `0.4` and SCF **on**, and sweeps `SCF_DIVERSITY_DIVISOR ∈ {3.0, 5.0, 6.0, 8.0}` (spanning both sides of prod 4.0). It reuses the harness shipped in `scf-off-staging` HEAD `4a66c34dd` **verbatim** — the env seam, the per-candidate driver, the cache fingerprint, and `--baseline-table` are all already in place, so this plan needs **no config-seam / driver / cache code changes**. The deliverable is a scorecard naming the divisor that decouples (or concluding none does → escalate to an SOS-credit cap). Shipping any winner to prod is a separate guarded PR, out of scope here.

### Locked decisions (do not re-open)

- **Dials:** `SCF_DIVERSITY_DIVISOR ∈ {3.0, 5.0, 6.0, 8.0}`, `SCF_FLOOR=0.4` (prod), SCF on for all candidates. Baseline = prod (`divisor 4.0, floor 0.4`).
- **One fixed snapshot — fetch ONCE, reuse for all 5 boards** (the same-snapshot guarantee, identical to the floor sweep). Fetch the games dataset once via the driver's `--fetch-snapshot` (pin `today`), persist to a snapshot parquet, and build the SCF-on baseline AND all 4 divisor candidates from that **identical** dataset via `--games-snapshot <parquet> --today <date>` (which routes to `compute_all_cohorts(games_df=<snapshot>, fetch_from_supabase=False, today=<fixed>)`). Without the single prefetch the same-snapshot promise is not delivered.
- **Winner rule:** recommend the divisor that passes all 4 criteria AND best **decouples** — i.e. suppresses the board bubble while *retaining* prediction (the win the floor could not produce). If two pass, prefer the one with the larger prediction retention. If none passes, conclude → escalate to an engine-native SOS-credit cap.
- **Both scorers:** every candidate scored on the published board AND with the prediction backtest.

### Pass criteria (a divisor must satisfy all four — unchanged from the floor sweep, anchored to the same-snapshot baseline)

1. **Bubble count materially improves** — `diagnose_bubble_teams.py` total on the candidate board is below the same-snapshot SCF-on baseline's total, with no hotspot (u16M, u17F) regressing.
2. **u17/Female does not regress** — candidate u17F bubble count ≤ the same-snapshot baseline's u17F count.
3. **No new losing-in-top-decile** — `score_losing_top_decile.py` cross-cohort total (Active, `win_percentage < 45`, `rank_in_cohort_final ≤ ceil(0.10 × cohort_active_count)`) is 0 OR ≤ the same-snapshot baseline's count.
4. **Prediction stays meaningfully better than prod (numeric gate).** On the u17F+u16M holdout backtest (8 cells = 2 cohorts × 4 cutoffs), vs the `baseline_prod` variant the divisor must: (a) win accuracy in **≥6/8 cells**, (b) post a **pooled accuracy delta ≥ +1.5 pts**, and (c) have **pooled log-loss no worse** than baseline. Report each divisor's magnitude vs both `baseline_prod` and the +3.74 full-off reference. (Same thresholds as the floor sweep so the two are directly comparable; the ship PR may revisit them.)

## Pattern Survey

**Analogous Features**

- `.turbo/plans/scf-floor-tune-down-sweep.md` (status done) — the direct template; identical 5-board / one-snapshot / dual-scorer / scorecard structure. This sweep is a near-verbatim clone swapping the swept dial (`SCF_FLOOR ∈ {.55,.60,.65,.70}` at divisor 4.0 → `SCF_DIVERSITY_DIVISOR ∈ {3.0,5.0,6.0,8.0}` at floor 0.4).
- `.turbo/scf-floor-tune-down-scorecard.md` — the output template; its recommendation (line ~81) names *this* divisor sweep as the next lever. This sweep IS that escalation.
- `C:/pitchrank-scf-off/data/staging/run_sweep_builds.sh` and `run_scoring.sh` (**untracked** worktree helpers) — sequential 5-board builder off one shared snapshot + per-board scorer. Clone them swapping `--scf-floor F --scf-divisor 4.0` → `--scf-floor 0.4 --scf-divisor Y` and renaming the board tables. (These are throwaway `data/staging/` helpers; recreate if absent.)
- `experiments/glicko_backtest/backtest.py:57-78` (**main-checkout only**) — the `VARIANTS` dict; `"abl_no_scf": ({"SCF_ENABLED": False}, {})` is the dial-exposure pattern. NOTE: the floor sweep's `scf_floor_*` entries are NOT here (they lived in a since-deleted worktree copy) — this sweep adds fresh `scf_dd_*` entries.

**Reusable Utilities (all confirmed present on `scf-off-staging` HEAD `4a66c34dd` — NO edits needed)**

- `scripts/run_scf_off_staging.py` — fully generalized driver; every needed arg present: `--scf-mode`, `--scf-floor`, `--scf-divisor` (default 4.0), `--table`, `--games-snapshot`, `--today`, `--fetch-snapshot`, `--teardown`. `--scf-divisor` is already a first-class swept dial. Functions `_force_scf_env`, `_assert_effective_config`, `_fetch_snapshot`, `_build_board`, `_load_scratch_table`, `_run_teardown`, `_verify_board_columns` all in place.
- `src/etl/glicko_config.py:101` — `SCF_DIVERSITY_DIVISOR` is already `field(default_factory=lambda: float(os.getenv("SCF_DIVERSITY_DIVISOR", "4.0")))`. Env seam shipped.
- `src/etl/glicko_engine.py:975` — `scf_raw = min(weighted_unique_states / cfg.SCF_DIVERSITY_DIVISOR, 1.0)` reads off `cfg`; env-backed default propagates with zero engine edits.
- `src/rankings/calculator.py:2124` — `_cfg_dict` already has `"scf_dd": getattr(_ecfg, "SCF_DIVERSITY_DIVISOR", None)`, so divisor variants get distinct cache keys / parquet filenames automatically. (For the floor sweep this was an incomplete gap to fix; here it is already satisfied.)
- `scripts/diagnose_bubble_teams.py` — `--rankings-table` (regex-guarded + `sql.Identifier`). `scripts/ranking_stability_check.py` — `--baseline-table` threaded through all four `compare_*` functions. `data/staging/score_losing_top_decile.py` — committed-this-session criterion-3 scorer (untracked; recreate from the floor scorecard's SQL if the worktree lost it).
- `experiments/glicko_backtest/glicko_engine_exp.py:31` — `ExpGlickoConfig(GlickoConfig)` does NOT redefine `SCF_DIVERSITY_DIVISOR`, so `ExpGlickoConfig(SCF_DIVERSITY_DIVISOR=6.0)` is already valid (no fork field). Its divisor consumption (~1035) is byte-identical to prod `glicko_engine.py:975`.

**Convention Anchors**

- **Env-force-after-dotenv ordering** (`run_scf_off_staging.py`): `.env.local` loads with `override=True`, then `_force_scf_env(...)` runs in `main()` AFTER dotenv and BEFORE any `GlickoConfig()` / `compute_all_cohorts`; `_assert_effective_config` re-constructs `GlickoConfig()` and aborts on mismatch (memory `gotcha_dotenv_override_order`). The driver sets `SCF_FLOOR=0.4` + `SCF_DIVERSITY_DIVISOR=Y` per candidate.
- **Cache fingerprint is load-bearing and ALREADY complete** for this sweep — `scf_dd` is present, so two SCF-on divisor variants hash distinctly even though `force_rebuild=True` bypasses the read.
- **Backtest needs a CLEAN engine** (load-bearing for criterion-4 reproducibility): `experiments/glicko_backtest/` is untracked and main-checkout-only, and the main checkout sits on the **dirty `fix/modular11-events-division-mapping` branch** (not origin/main). `backtest.py` prepends the repo root to `sys.path` and `glicko_engine_exp` imports `src.etl.glicko_config`, so running from the main checkout uses the wrong engine. **Copy `experiments/glicko_backtest/` (+ its `data/` parquets) into the worktree `C:/pitchrank-scf-off` (clean origin/main `src/` + the behavior-preserving env seam) and run the backtest THERE.** The env-seam edits don't affect it (it passes explicit `ExpGlickoConfig(SCF_DIVERSITY_DIVISOR=…)` kwargs, not env).
- **Run environment**: `C:/Python313/python` (the venv is dead — memory `env_broken_venv_use_python313`). Each board is a full ~1 h two-pass run; 5 boards ≈ 3 h mostly-sequential.
- **Zero-prod-write**: driver keeps `force_rebuild=True` + `save_snapshot/persist_game_residuals/persist_game_explainability/calculate_rank_changes_enabled` all False; scratch tables `LIKE rankings_full`; all scorers are SELECT-only.

**Proposed Alignment**

Run the existing harness with the divisor as the swept dial (floor held at 0.4); add `scf_dd_*` `VARIANTS` entries (kwargs only) to a clean-worktree copy of `backtest.py`; clone the two `data/staging/` orchestrator scripts swapping the dial; fetch one shared snapshot; build the SCF-on baseline + 4 divisor boards; score each with the bubble guardrail, the losing-in-top-decile scorer, and the board-vs-same-snapshot-baseline stability compare; backtest the hotspot cohorts; synthesize a scorecard recommending the decoupling divisor (or escalating to an SOS-credit cap).

## Implementation Steps

1. **Confirm the isolated workspace (no new worktree).**
   - Work in the existing worktree `C:/pitchrank-scf-off`. Verify `git -C ../pitchrank-scf-off status -sb` shows branch `scf-off-staging` at/after `4a66c34dd` (the harness commit, now on `origin/scf-off-staging`). **Expected, ignorable noise**: modified `*.pyc` bytecode (never stash — memory `feedback_git_stash`), untracked `data/cache/` parquets, `data/staging/` helpers + logs. The real gate: no unexpected modified **source** files (`.py`/`.sql`) beyond none (this plan changes no tracked source).
   - Confirm the reusable `data/staging/` helpers still exist: `score_losing_top_decile.py`, and the prior `run_sweep_builds.sh`/`run_scoring.sh` (to clone). If any was cleaned up, recreate it (the criterion-3 SQL is in `.turbo/scf-floor-tune-down-scorecard.md`).

2. **Stage the backtest harness against a CLEAN engine (the only "code" step — VARIANTS only).**
   - Copy the untracked `experiments/glicko_backtest/` (incl. its `data/` parquets) from `C:/PitchRank` into the worktree `C:/pitchrank-scf-off/experiments/glicko_backtest/` (a dir junction for `data/` avoids duplicating ~420 MB). The main checkout is on a dirty branch, so the copy runs against the worktree's clean origin/main `src/`.
   - In the worktree copy of `experiments/glicko_backtest/backtest.py`, add to the `VARIANTS` dict (mirroring `abl_no_scf`):
     - `"scf_dd_030": ({"SCF_DIVERSITY_DIVISOR": 3.0}, {})`
     - `"scf_dd_050": ({"SCF_DIVERSITY_DIVISOR": 5.0}, {})`
     - `"scf_dd_060": ({"SCF_DIVERSITY_DIVISOR": 6.0}, {})`
     - `"scf_dd_080": ({"SCF_DIVERSITY_DIVISOR": 8.0}, {})`
   - No `ExpGlickoConfig`/engine edit (the field is inherited). `SCF_FLOOR` is left at its inherited prod default 0.4 for every variant (including `baseline_prod`), so only the divisor differs.

3. **Capture pre-run prod-safety baselines.**
   - Record `max(last_calculated)` from `rankings_full`, `max(snapshot_date)` from `ranking_history`, `count(*)` from `rankings_full` (psycopg2 / `DATABASE_URL`, read-only) to a file for the post-run comparison.

4. **Fetch ONCE — the shared games snapshot.**
   - `python scripts/run_scf_off_staging.py --fetch-snapshot --games-snapshot data/staging/divisor_sweep_games_snapshot.parquet --today <today>` (pin `today` to the run date). Confirm the parquet is written with a sane perspective count (~1.8M, matching the floor sweep's snapshot).

5. **Build the 5 boards (worktree, `C:/Python313/python`, sequential ~3 h, zero-prod-write).**
   - Baseline: `--scf-mode on --scf-floor 0.4 --scf-divisor 4.0 --table rankings_full_scf_on_base --games-snapshot <parquet> --today <date>`.
   - Divisors: `--scf-mode on --scf-floor 0.4 --scf-divisor {3.0,5.0,6.0,8.0} --table rankings_full_scf_div030|050|060|080 --games-snapshot <parquet> --today <date>`.
   - Each writes a distinct scratch table; confirm row count ≈ active-team count and that the driver log shows the asserted effective `SCF_ENABLED=True / SCF_FLOOR=0.4 / SCF_DIVERSITY_DIVISOR=<Y>` per candidate. Resumable (one invocation = one board); a cloned `run_sweep_builds.sh` runs them in sequence.

6. **Score every board on the published board (worktree).**
   - Guardrail per board: `diagnose_bubble_teams.py --rankings-table <table>` → bubble total + per-cohort (esp. u17F, u16M). Criteria 1 & 2 = compare each divisor's total / u17F to `rankings_full_scf_on_base`.
   - Criterion 3 per board: `python data/staging/score_losing_top_decile.py --table <table>` → cross-cohort losing-in-top-decile total; compare to the baseline's.
   - Movement (descriptive, NOT a gate): `ranking_stability_check.py --compare-table <div_table> --baseline-table rankings_full_scf_on_base` → biggest movers with sos_norm/win%; sanity-check that high risers are not sub-.500 teams.

7. **Score every divisor on prediction — against the clean engine.**
   - From the worktree copy: `python experiments/glicko_backtest/backtest.py --cohorts 17:female,16:male --variants baseline_prod,scf_dd_030,scf_dd_050,scf_dd_060,scf_dd_080 --out scf_divisor_sweep_metrics.csv`.
   - Apply the criterion-4 numeric gate (≥6/8 cells, pooled accuracy ≥ +1.5 pts, pooled log-loss not worse), reporting each divisor vs `baseline_prod` and the +3.74 reference. Compute per-cell wins + pooled (n_decisive-weighted) accuracy/log-loss from the metrics CSV.

8. **Synthesize the scorecard (`.turbo/scf-divisor-tune-up-scorecard.md`).**
   - Anchor every criterion-1/2/3 comparison to the **fresh** same-snapshot baseline `rankings_full_scf_on_base` (recompute its bubble/u17F/u16M/losing-decile totals on this snapshot first), NOT the floor-sweep's numbers (different snapshot).
   - Per-divisor table: bubble total (vs baseline), u17F, u16M, losing-in-top-decile, prediction Δ (accuracy/log-loss vs `baseline_prod` + vs the +3.74 reference), 4-criteria pass/fail, and a **decoupling read** (did it suppress the board AND keep prediction?).
   - Recommendation: the divisor that passes all 4 and best decouples, labeled **PROVISIONAL** (clears one frozen snapshot; the ship PR must re-validate). If none passes, conclude → escalate to an engine-native SOS-credit cap (cap the SOS reward a low-diversity schedule can earn), and say so explicitly — and note whether the divisor at least moved the prediction/board trade-off differently from the floor (informs whether the next lever is the cap or a structural SCF reshape).

9. **Teardown & prod-safety confirmation.**
   - Drop every scratch table via `--teardown --table <name>` (`rankings_full_scf_on_base`, `rankings_full_scf_div030/050/060/080`); optionally delete the distinct-hash `data/cache` parquets + the worktree backtest copy.
   - Confirm zero prod mutation: `max(last_calculated)` / `max(snapshot_date)` / `rankings_full` count unchanged from Step 3's capture; `SCF_DIVERSITY_DIVISOR`/`SCF_FLOOR`/`SCF_ENABLED` never set in any prod environment (in-process only).

### Out of scope (deferred)

- Shipping a winning divisor to prod — a separate guarded PR off `origin/main`: flip the prod default (or set the env) on a clean branch, run the FULL unit suite (memory `feedback_full_suite_before_push`), code review, guarded prod run.
- The engine-native SOS-credit cap — only if no divisor passes (the next escalation lever after this sweep).
- Sweeping `SCF_FLOOR` and `SCF_DIVERSITY_DIVISOR` jointly (2-D) — only if the 1-D divisor sweep is suggestive but inconclusive.

## Verification

- **Boards produced:** each of the 5 scratch tables has ≈ active-team count rows and passes the column gate; the driver log shows the asserted effective `SCF_ENABLED=True / SCF_FLOOR=0.4 / SCF_DIVERSITY_DIVISOR=<Y>` per candidate (the assert aborts on mismatch).
- **Cache disambiguation:** the 5 boards write distinct `data/cache/rankings_<hash>_teams.parquet` filenames (hash differs because `_cfg_dict` includes `scf_dd`) — spot-check that no two divisor boards share a cache hash.
- **Clean-engine backtest:** `python -c "import inspect, experiments.glicko_backtest.glicko_engine_exp as ge; from src.etl.glicko_config import GlickoConfig; print(inspect.getfile(ge), inspect.getfile(GlickoConfig))"` (run from the worktree) resolves both to `C:/pitchrank-scf-off/...` (NOT the dirty main checkout).
- **Prod-safety (must pass before trusting output):** `max(last_calculated)`, `max(snapshot_date)`, and `rankings_full` count unchanged after the full sweep vs the Step 3 pre-run capture; no prod (SCF-on default) `data/cache` parquet mtimes change.
- **Criteria computed:** for each divisor the scorecard reports all 4 criteria with numbers + a decoupling read; the recommendation names the passing/decoupling divisor (or escalates).
- **Edge cases:** a divisor that fixes the board but fails the +1.5-pt prediction gate is correctly rejected (the floor-sweep failure mode); a divisor that recovers prediction but re-bubbles (looser, e.g. 3.0) is rejected on criterion 1; cohorts with zero bubbles score cleanly; the same-snapshot baseline (divisor 4.0) reproduces the floor sweep's baseline numbers within snapshot noise.

## Context Files

- `.turbo/plans/scf-floor-tune-down-sweep.md` + `.turbo/scf-floor-tune-down-scorecard.md` — the direct template plan and output format; the criteria, the same-snapshot machinery, and the failure mode this sweep tries to beat.
- `scripts/run_scf_off_staging.py` (worktree) — the driver to run unchanged: `--scf-divisor`/`--scf-mode`/`--table`/`--games-snapshot`/`--today`/`--fetch-snapshot`, the env-force window, `_assert_effective_config`, zero-write flags, `--teardown`.
- `src/etl/glicko_engine.py` (~975) — `scf_raw = min(weighted_unique_states / SCF_DIVERSITY_DIVISOR, 1.0)`; confirms the divisor is the connectivity threshold and that no engine edit is needed.
- `src/etl/glicko_config.py` (~101) — the env-backed `SCF_DIVERSITY_DIVISOR` default (prod 4.0 when unset).
- `src/rankings/calculator.py` (~2124) — `_cfg_dict` with the `scf_dd` cache key (already present).
- `scripts/diagnose_bubble_teams.py` (`--rankings-table`), `scripts/ranking_stability_check.py` (`--compare-table` + `--baseline-table`), `data/staging/score_losing_top_decile.py` — the three board scorers.
- `experiments/glicko_backtest/backtest.py` (`VARIANTS` ~57-78) + `glicko_engine_exp.py` (`ExpGlickoConfig` ~31, inherits the divisor) — where the `scf_dd_*` entries go; main-checkout copy → run from a clean worktree copy.
- Memories `scf_bubble_investigation_2026_06` (the lever lineage + the floor-sweep verdict), `rankings_offline_run_gotchas` (fetch-once + clean-engine patterns), `gotcha_dotenv_override_order`, `env_broken_venv_use_python313`.
