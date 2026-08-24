---
status: shelved
---

<!-- Concluded 2026-06-24: do-not-ship. Single-global-MAX one-sided cap fails the
ground-truth gate at every tested MAX (best 14/23; demotes genuine elites at the
strength needed to drop inflated teams; one-sided shape cannot lift buried elites).
Foundation committed default-off (scf-off-staging 5c4f44a3d). See the SOS-credit-cap
scorecard. Next: fresh design pass for a two-part (record/score separation + lift) mechanism. -->


# Plan: Record-gated SOS-credit cap (engine-native, behind a flag)

## Context

The manual board audit (`.turbo/scf-divisor-8.0-audit.md`) killed the SCF-divisor lever: it works the wrong axis (schedule *diversity*, not SOS *magnitude*). The real, customer-facing problem is **SOS over-weighting** — mediocre-record teams on brutal schedules sit in the top 10 (Strikers FC 53% wins / 0.98 SOS at #4; TSF #5; Cedar Stars #6; San Diego Surf #5, Utah Royals #6 in u17F), while strong-record teams on lower SOS are buried (SOLAR 90% wins #20, 2009 GA 86% wins / 0.50 SOS #25, San Juan #27, De Anza #70). Against the owner's expert ground truth, current prod scores **7/23**.

This plan implements **Option 2** from `.turbo/specs/sos-credit-cap-options.md`: a new, isolated, flag-guarded post-`mu` shaping step that caps each team's **SOS-credit** — the portion of its published score that exceeds what its own record justifies — gated on record so it only pulls down SOS-inflated teams and never touches record-justified ones. Two hard requirements: (1) Strikers-type teams must leave the top 10 (drop toward 35–50); (2) strong-but-lower-SOS teams (SOLAR / 2009 GA / San Juan / De Anza) must hold or rise, never be pushed down. The deliverable is a reversible engine change validated on the same ground truth before any prod ship (ship is a separate guarded PR, out of scope here).

### Why Option 2, not Option 1 (and skip the Option-1 probe)

`SOS_ADJ` (Option 1's hook, `glicko_engine.py:1734-1744`) only rescales `mu` by `±3%` (strong) / `−16%` (weak) of `(mu−1500)`. But the over-ranking lives in the **core `mu`**: Strikers earns a top-5 `mu` from *competitive results vs elite opponents* (a close loss to #1 barely dents `mu`), not from the +3% `SOS_ADJ` reward. So even zeroing/penalizing the `SOS_ADJ` reward can't move #4→35–50 without widening the band into broad collateral movement. **Recommendation: skip the Option-1 probe.** It is confirmed too weak to fix the demonstrated cases and would cost a full rebuild/score round-trip for a near-null result. Go straight to Option 2, which acts on `powerscore_core` (the normalized score that ranks teams) and can move teams by the needed magnitude.

## Pattern Survey

**Analogous Features**

- `src/etl/glicko_engine.py:1734-1756` — the **`SOS_ADJ` block**, the structural template: an isolated post-`mu` shaping conditioned on a normalized signal, clipped to a band, sitting inline in `compute_rankings_v2` between `mu` and `powerscore_core`. Mirror its shape (a `cfg.<FLAG>_ENABLED`-guarded block), but as a *separate* Option-2 stage on `powerscore_core`.
- `src/etl/glicko_engine.py:1320-1324` — `apply_scf_dampening(team_df, scf_data, cfg)`: the precedent for a named, isolated, flag-driven post-convergence shaping function with a `(team_df, …, cfg)` signature. Runs at 1728 on `sos_raw` — **before** the hook, orthogonal to the cap.
- `src/rankings/calculator.py:493,524,572,1685,2916` — the publication-cap / same-age evidence-gate machinery (`_compute_publication_cap_scores`, `_apply_publication_cap_band`, `_validate_publication_caps`, `_publication_cap_rank`). Operates downstream on `power_score_true`/`publication_cap_rank`. **The cap must NOT touch this layer** — it is the "unrelated publish logic" to avoid.

**Reusable Utilities**

- `src/etl/glicko_engine.py` `sigmoid_zscore_normalize(series)` (used at 1731/1732/1733/1756/1770/1855) — maps raw values to a within-cohort [0,1]. **`record_score` must be produced by this same function** so it is on the identical scale as `powerscore_core` and the subtraction `powerscore_core − record_score` is meaningful.
- `src/etl/glicko_engine.py:719-761` `derive_offense_defense(...)` → `off_raw`/`def_raw` (merged at 1693; normalized to `off_norm`/`def_norm` at 1731-1732) — the goal-based record signals available at the hook.
- `scripts/run_scf_off_staging.py:119-136,~376` — staging driver that env-forces config flags and writes a named `rankings_full_*` scratch table (zero prod-write). Extend with `--sos-credit-cap {on,off}` + `--sos-credit-max`.
- `data/staging/audit_ground_truth.py` + `audit_ground_truth.json` — the 23-team u16M/u17F pass/fail scorer (`--table`; drop PASS if `cand_rank ≥ target_min`, elite PASS if `cand_rank ≤ 15`). **Primary gate.**
- `scripts/diagnose_bubble_teams.py:298-307` (`--rankings-table`), `data/staging/score_losing_top_decile.py` — board guardrails.
- `experiments/glicko_backtest/` — prediction backtest; **main-checkout only**, copy into the worktree for a clean-engine run.

**Convention Anchors**

- **Config:** env-backed `field(default_factory=lambda: ...)` — `SCF_ENABLED` (`glicko_config.py:87-89`, bool) and `SCF_FLOOR`/`SCF_DIVERSITY_DIVISOR` (101-102, `float(os.getenv(...))`). New `SOS_CREDIT_CAP_ENABLED` mirrors `SCF_ENABLED` (env bool, **default off** = prod-identical); `SOS_CREDIT_MAX` and the blend/ramp constants mirror `SCF_FLOOR` (env float). The plain `SOS_ADJ_*` group (144-148) is the in-context numeric-constant precedent.
- **Hook placement:** the two `powerscore_core` assignments (1756 SOS-ADJ branch, 1770 else-branch) are parallel — **insert the cap after the if/else converges (after 1770, before `powerscore_adj` at 1774)** so one block covers both branches.
- **Cache fingerprint:** `calculator.py` `_cfg_dict` (~2115-2145) already keys on `scf`/`scf_fl`/`scf_dd`/`sos_adj_*`; add the new flag + `SOS_CREDIT_MAX` so cap variants get distinct cache files (the floor/divisor sweeps relied on this).
- **`wins` at the hook — CONFIRMED:** `run_glicko2_cohort` builds `team_df` with `team_id, mu, sigma, games_played, wins, losses, draws, goals_for, goals_against, last_game` (1586-1614), so at 1756 the cap has `wins, games_played, goals_for/against, off_norm, def_norm, sos_norm` — the full record set. Only the `win_percentage` *column* is later (1804); win% is derived inline. **The cap reads record at the hook; no move needed.**
- **`powerscore_core` downstream — CONFIRMED independent:** nothing recomputes from `powerscore_core`/`power_presos`; `powerscore_adj = powerscore_core * provisional_mult` (1774) flows into ML (reads `powerscore_adj`) and `power_score_true`. Capping `powerscore_core` before 1774 propagates cleanly. (`power_presos` at ~1858 is a persisted snapshot — keep it the *pre-cap* value by snapshotting before the cap, so a pre/post audit is possible.)

**Proposed Alignment**

Add `apply_sos_credit_cap(team_df, cfg)` as an isolated `cfg.SOS_CREDIT_CAP_ENABLED`-guarded transform inserted after the `powerscore_core` if/else converges, reusing `sigmoid_zscore_normalize` for `record_score`. Env-backed config mirroring `SCF_ENABLED`/`SCF_FLOOR`. Validate via the existing staging → ground-truth → bubble → losing-decile → backtest chain. Fully reversible behind one flag; touches no SCF, publication-cap, evidence-gate, or ML logic.

## Implementation Steps

1. **Add config (worktree `src/etl/glicko_config.py`).**
   - Mirror the `SCF_ENABLED` env-backed bool (87-89): `SOS_CREDIT_CAP_ENABLED: bool = field(default_factory=lambda: os.getenv("SOS_CREDIT_CAP_ENABLED","false").strip().lower() in ("1","true","yes"))` — **default off → byte-identical prod.**
   - Mirror the `SCF_FLOOR` env-backed float (101-102) for: `SOS_CREDIT_MAX` (the allowed SOS bonus above record, default e.g. `0.15`), `SOS_CREDIT_RECORD_WIN_WEIGHT` / `SOS_CREDIT_RECORD_GD_WEIGHT` (record-blend weights, default e.g. `0.6`/`0.4`), `SOS_CREDIT_MIN_GAMES_FULL` (games at which the cap is fully applied, default e.g. `12`, reuse `MIN_GAMES_PROVISIONAL`). Keep every other field and the `@dataclass`.

2. **Add the cap function (worktree `src/etl/glicko_engine.py`).** Define `apply_sos_credit_cap(team_df, cfg)` near `apply_scf_dampening` (~1320) and call it once, guarded, after the `powerscore_core` if/else converges (after 1770, before 1774). Mechanism — all within cohort, on the normalized scale:
   - **`record_score`** = `sigmoid_zscore_normalize(record_raw)` where `record_raw` is the team's own results: a blend of win-rate `wins/games_played` and per-game goal differential `(goals_for − goals_against)/games_played` (or reuse `off_raw − def_raw`), weighted by `SOS_CREDIT_RECORD_WIN_WEIGHT`/`SOS_CREDIT_RECORD_GD_WEIGHT`. This is "what the record alone justifies," on the same [0,1] scale as `powerscore_core`.
   - **`SOS_credit`** = `powerscore_core − record_score` (the portion of the published score above record-justified level).
   - **Allowance (scales by record + games):** `allowance = SOS_CREDIT_MAX * record_score * games_ramp`, where `games_ramp = clip(games_played / SOS_CREDIT_MIN_GAMES_FULL, 0, 1)` so low-sample teams keep a wider (less-capped) allowance and aren't whipsawed, and the allowance grows with `record_score` so strong records keep ~full credit while mediocre records get little. (Multiplying by `record_score` makes the ceiling `record_score*(1+SOS_CREDIT_MAX*games_ramp)` — a strong record → high ceiling → uncapped; mediocre → low ceiling → capped.)
   - **Cap:** `capped_core = minimum(powerscore_core, record_score + allowance)`. `min` is continuous (no discontinuity ⇒ no rank cliff). Write back to `team_df["powerscore_core"]`. Snapshot the pre-cap value first (e.g. keep `power_presos` = pre-cap) so a pre/post audit is possible.
   - Guard the whole block with `if cfg.SOS_CREDIT_CAP_ENABLED:`. When off, `powerscore_core` is untouched.
   - **Preserve:** the existing `provisional_mult`/`powerscore_adj` line (1774) and everything downstream — the cap only lowers `powerscore_core` for inflated teams; it never raises any score, and never touches `mu`, `mu_sos`, SCF, evidence gates, caps, or ML.

3. **Extend the cache fingerprint (worktree `src/rankings/calculator.py`).** In `_cfg_dict` (~2115-2145, alongside `scf_fl`/`scf_dd`) add `"sos_cc": getattr(_ecfg,"SOS_CREDIT_CAP_ENABLED",None)` and `"sos_cm": getattr(_ecfg,"SOS_CREDIT_MAX",None)` (matching the `getattr(...,None)` idiom) so cap variants get distinct cache keys.

4. **Extend the staging driver (worktree `scripts/run_scf_off_staging.py`).** Add `--sos-credit-cap {on,off}` (default off) and `--sos-credit-max <float>`; force `os.environ["SOS_CREDIT_CAP_ENABLED"]` + `os.environ["SOS_CREDIT_MAX"]` in the existing env-force window before any `GlickoConfig()`, and extend `_assert_effective_config` to log/assert them. Mirror the existing `--scf-floor`/`--scf-divisor` plumbing exactly.

5. **Mirror a config unit test (worktree `tests/unit/test_glicko_config_scf_env.py` or a sibling).** Parametrized: unset `SOS_CREDIT_CAP_ENABLED` → `False`; `"true"` → `True`; `SOS_CREDIT_MAX` unset → default, override parses to float. Confirms flag-off = prod-identical.

## Verification

- **Behavior-preserving (flag off):** `ruff check` clean; the existing engine unit tests (`tests/unit/test_glicko_engine.py`, `test_league_bubble_scf.py`, `test_glicko_sos_role.py`) and the config-seam tests pass unchanged (cap default off ⇒ byte-identical prod). New flag-parse test passes.
- **Cache disambiguation:** two `SOS_CREDIT_MAX` values produce two distinct `data/cache/rankings_<hash>_teams.parquet` filenames.
- **Build a candidate board (zero prod-write):** `run_scf_off_staging.py --scf-mode on --sos-credit-cap on --sos-credit-max <X> --table rankings_full_sos_cap --games-snapshot <one fixed snapshot> --today <date>`; confirm the asserted effective flags and ≈ active-team row count.
- **PRIMARY GATE — ground truth:** `python data/staging/audit_ground_truth.py --table rankings_full_sos_cap`. Required: **(a) all 7 over-ranked "drop" teams reach their target floor** (Strikers ≥35, TSF/Cedar Stars ≥70, SC Del Sol ≥100; San Diego Surf ≥25, Utah Royals ≥20, Nationals ≥30); **(b) net score materially beats prod's 7/23** (target ≥17/23, with the under-ranked elite — SOLAR, 2009 GA, San Juan, De Anza, Michigan Wolves, Atlanta, Philly Union — rising toward top-15); **(c) NO genuine elite demoted** — Total Futbol stays #1–2, ALBION LA stays top-5, and the already-correct u17F top (ECNL-PA #1, PDA #2, Sting #4) hold.
- **GUARDRAILS (must not regress):** `diagnose_bubble_teams.py --rankings-table rankings_full_sos_cap` bubble total ≤ prod; `score_losing_top_decile.py --table rankings_full_sos_cap` ≤ prod; prediction backtest (copy `experiments/glicko_backtest/` into the worktree, add a `sos_cap` VARIANT) — pooled accuracy not materially worse (≥ −0.5 pt) and pooled log-loss not materially worse vs `baseline_prod`.
- **No rank cliffs:** within each audited cohort, confirm no large cluster of teams pinned to an identical capped score (the score→rank mapping stays strictly ordered; `min`-cap is continuous).
- **Calibrate `SOS_CREDIT_MAX`:** build 3–4 values on ONE shared snapshot (reuse the fetch-once harness), pick the **lowest** `SOS_CREDIT_MAX` (least intervention) that clears the PRIMARY GATE without tripping a guardrail.
- **Edge cases:** low-sample teams (games < `SOS_CREDIT_MIN_GAMES_FULL`) are not whipsawed (games_ramp widens their allowance); a team whose `powerscore_core ≤ record_score` is never reduced (cap one-sided); strong-record + strong-SOS elite (Total Futbol 80%/0.99) is uncapped (record-justified).

### Pass/fail before shipping

**PASS (→ proceed to a separate guarded prod PR):** all 7 drop teams reach target AND net ground-truth ≥17/23 AND no genuine-elite demoted AND bubble guardrail ≤ prod AND losing-in-top-decile ≤ prod AND prediction within −0.5 pt accuracy / log-loss not materially worse AND no rank cliffs — at the lowest `SOS_CREDIT_MAX` that achieves it.
**FAIL (→ stop, reassess mechanism, do not ship):** drop teams stay top-10, OR a genuine elite is demoted, OR any guardrail regresses, OR cliffs appear — at every tested `SOS_CREDIT_MAX`.

## Context Files

- `.turbo/specs/sos-credit-cap-options.md` — the option set; this plan is Option 2.
- `.turbo/scf-divisor-8.0-audit.md` — why the divisor failed + the ground-truth cases this must fix.
- `src/etl/glicko_engine.py` — the hook (`powerscore_core` 1756/1770 → `powerscore_adj` 1774), the `SOS_ADJ` template (1734-1744), `apply_scf_dampening` (1320), `derive_offense_defense` (719-761), `sigmoid_zscore_normalize`, the `team_df` column set (1586-1614), `power_presos` (~1858).
- `src/etl/glicko_config.py` — the env-backed flag/float pattern (87-89, 101-102) + the `SOS_ADJ_*` constants (144-148).
- `src/rankings/calculator.py` — `_cfg_dict` cache fingerprint (~2115-2145) + the publication-cap path to leave untouched.
- `data/staging/audit_ground_truth.json` + `audit_ground_truth.py` — the primary validation gate.
- `scripts/run_scf_off_staging.py`, `scripts/diagnose_bubble_teams.py`, `data/staging/score_losing_top_decile.py` — the staging + guardrail harness to extend/reuse.
- Memories `scf_bubble_investigation_2026_06` (lever lineage), `feedback_algorithm_changes` (diagnostic-first, safeguarded), `feedback_algorithm_scope` (fix the confirmed problem; keep the experiment clean), `rankings_offline_run_gotchas` (fetch-once + clean-engine backtest patterns).
