---
name: rankings-algorithm
description: PitchRank Glicko-2 ranking algorithm knowledge - two-pass convergence, ML Layer 13, normalization, PowerScore bounds
---

# Rankings Algorithm Skill for PitchRank

You are working on PitchRank's ranking system. This skill explains the Glicko-2 engine and ML pipeline.

## Ranking Pipeline

`compute_all_cohorts()` (`src/rankings/calculator.py`) is the two-pass orchestrator;
`compute_rankings_with_ml()` handles one cohort. Canonical stage order:

1. `fetch_games_for_rankings()` — Supabase → engine format (two rows per game); merge
   resolution via `team_merge_map`
2. Cache check (MD5 of game IDs + lookback + merge version + engine); the cache only
   ever serves Pass 1 — Pass 2 always rebuilds
3. **Pass 1**: `compute_rankings_v2()` per (age, gender) cohort, `global_strength_map=None`
   — an opponent outside the cohort is rated 1500 / RD 350. ML runs but its residuals
   are not persisted
4. Build `global_strength_map = {team_id: mu}` from Pass 1 (after SCF dampening)
5. **Pass 2**: `compute_rankings_v2()` per cohort, warm-started; cross-age opponents come
   from the global map + anchor offset, at RD 350 so g(φ) discounts them. Per cohort,
   post-convergence: OFF/DEF → SOS → SCF → sigmoid(z-score) → `powerscore_core`
   → × provisional_mult → `powerscore_adj`, then ML Layer 13 → `powerscore_ml`
6. `_persist_game_residuals()` + `_persist_game_explainability()` — batch RPCs to
   Supabase (called inside `compute_rankings_with_ml` per cohort; skipped for Pass 1
   and when their `persist_game_*` flags are False, e.g. --dry-run)
7. **Pass 3**: national/state SOS columns (`sos_norm_national/state`, `sos_rank_*`) —
   display only, never feeds PowerScore
8. Same-age evidence gates: SOS/evidence-gated ML delta → raw shrink → play-up bonus
   → publish penalty → publication cap band → `power_score_true`
9. `power_score_final = power_score_true × AGE_TO_ANCHOR[age]`; `rank_in_cohort_final`
   by `power_score_true` DESC (Active only)
10. `calculate_rank_changes()` (7d/30d), clip PowerScore columns to [0, 1],
    `save_ranking_snapshot()` → `ranking_history`, then save to `rankings_full` +
    `current_rankings`

## Glicko-2 Engine (glicko_engine.py)

### Core: `compute_rankings_v2()`

Full Glicko-2 convergence pipeline for a single (age, gender) cohort.
Returns `{"teams": DataFrame, "games_used": DataFrame, "game_explainability": DataFrame}`.

### Convergence: `run_glicko2_cohort()`

- Iterates until mean |delta_mu| < `CONVERGENCE_THRESHOLD` (1.0) or max 30 iterations
- Exponential recency decay: `weight = exp(-RECENCY_LAMBDA * days_ago / 365)`
- Caches game-by-game breakdowns for explainability

### Rating Update: `glicko2_update()`

Full Glickman paper implementation:
- Converts 1500-centered scale to Glicko-2 internal via `GLICKO2_SCALE = 173.7178`
- Steps: variance estimation → improvement (delta) → volatility update (Illinois algorithm) → rating update
- `glicko2_g(phi)`: reduces impact of high-uncertainty opponents: `g(phi) = 1/sqrt(1 + 3*phi²/π²)`

### Game Outcome Scoring

```python
# Log-margin scoring (not binary win/loss)
outcome = 0.5 ± 0.5 * log(1 + capped_gd) / log(1 + MAX_GD)
```

### Derived Components

- **Offense/Defense** (`derive_offense_defense()`): residuals from expected goals
  - `off_raw = actual_gf - expected_gf`
  - `def_raw = expected_ga - actual_ga`

- **SOS** (`compute_sos()`): avg opponent mu with:
  - Repeat opponent cap (max 4 games per opponent)
  - Asymmetric trim: discard the bottom 25% and top 15% of opponents (`SOS_TRIM_BOTTOM_PCT` / `SOS_TRIM_TOP_PCT`)
  - Cross-age scaling via anchors (Pass 2 only)

- **SCF** (Schedule Connectivity Factor): regional bubble dampening
  - Measures opponent state diversity; low diversity dampens raw SOS toward 1500 (and mu, since `SCF_PUBLISH_ONLY=False`)
  - `scf_value = quality-weighted unique_states / SCF_DIVERSITY_DIVISOR` (capped at 1.0); floor 0.4 at ≥3 bridge games, ramping to 0.1 with none
  - League-family diversity is added for U13+ (`SCF_LEAGUE_FLOOR` 0.5)
  - Bridge games and states are quality-weighted (`SCF_QUALITY_WEIGHT_ENABLED`; cross-age bridges × 0.6), so three low-quality interstate games can still count as fewer than three
  - Isolation penalty: weighted bridge games < 3, weighted states < 2, or (lower-tier league family) unique leagues below `SCF_MIN_UNIQUE_LEAGUES` → SOS capped at `1500 + ISOLATION_SOS_CAP(0.60)·(cohort max − 1500)` (the 0.60 is a coefficient on the raw 1500-centred scale, not a `sos_norm` threshold)
  - `UNKNOWN` filtering is opponent-side only: an opponent with no `state_code` contributes no state and no bridge. A **team** with no `state_code` (stored as `UNKNOWN`) fails the same-state test against every known opponent state, so all of its games count as bridges and its SCF is *inflated*, not dampened — one more reason `state_code` is load-bearing (see CLAUDE.md "Adding a new scraper")
  - Withholding state data cannot disable SCF: stateless teams become `UNKNOWN` and SCF still runs (it is skipped only when the metadata fetch returns nothing at all)

### Normalization: `sigmoid_zscore_normalize()`

```python
z = (value - mean) / std
normalized = 1 / (1 + exp(-z))  # Maps to (0, 1), mean → 0.5
```

All normalizations are per-cohort (age, gender). Preserves natural gaps unlike percentile.

### Age Anchors — two tables

- `GlickoConfig.MALE_ANCHORS` / `FEMALE_ANCHORS` (gendered): the Pass-2 cross-age
  opponent offset. Male U10=0.783 → U19=1.0; Female U10=0.792 → U19=1.0
- `AGE_TO_ANCHOR` (`src/rankings/constants.py`): the M/F average (U10 0.788 → U19 1.000),
  applied once at the end as `power_score_final = power_score_true × AGE_TO_ANCHOR[age]`

### Glicko-2 Configuration (`GlickoConfig`)

| Parameter | Value | Role |
|-----------|-------|------|
| `INITIAL_MU` | 1500.0 | Starting rating |
| `INITIAL_SIGMA` | 350.0 | Starting rating deviation |
| `INITIAL_VOLATILITY` | 0.06 | Starting volatility |
| `TAU` | 0.5 | Volatility system constant |
| `GLICKO2_SCALE` | 173.7178 | Scale conversion factor (module constant in `glicko_engine.py`, not a config field) |
| `MAX_GAMES` | 30 | Recent games for OFF/DEF |
| `WINDOW_DAYS` | 365 | Historical window |
| `INACTIVE_DAYS` | 180 | Inactive threshold |
| `RECENCY_LAMBDA` | 1.0 | Exponential decay rate |
| `MAX_GD` | 6 | Max goal difference per game |
| `CONVERGENCE_THRESHOLD` | 1.0 | Mean |delta_mu| to stop (max 30 Jacobi iterations) |
| `WINDOW_GRACE_DAYS` | 28 | Linear taper applied to games 366–393 days old, on top of the exponential |

### Other engine parameters (single home — CLAUDE.md and the agent point here)

- GF/GA are clipped at ±2.5σ per cohort before the outcome formula above
- **Game selection**: `MAX_GAMES` is a balanced pick of 20 recent + 7 same-age quality + 3 bridge, then recent backfill
- **Weights**: the recency exponential is multiplied by the `WINDOW_GRACE_DAYS` taper and normalized to sum 1 per team; repeat-opponent multipliers 1.0 / 0.8 / 0.6 / 0.4
- **Cross-age**: `opp_mu + (opp_anchor − team_anchor)·400`; Pass 2 rates cross-age opponents at RD 350 so g(φ) discounts them
- **SOS adjustment**: mu's distance from 1500 scaled down up to 16% when `sos_norm < 0.45`, up at most 3% when `sos_norm > 0.60`
- **Provisional / status**: `provisional_mult = 1 − (RD/350)²`; Inactive after `INACTIVE_DAYS`; "Not Enough Ranked Games" below 12

### Feature flags currently OFF

Do not enable any of these without a dry run and a `diagnose_ranking.py` comparison.

- `SCF_PUBLISH_ONLY`, `TIER_MULT_CENTERED` - publishing them moved scores enough that #885 was rolled back
- `EVIDENCE_GATE_FROZEN_REF` - untested in production
- `SOS_CREDIT_CAP_ENABLED` / `RECORD_RECONCILE_ENABLED` - env-gated experiments, mutually exclusive

## ML Layer 13 (layer13_predictive_adjustment.py)

### What It Does

Trains XGBoost on per-game residuals, aggregates per-team with recency decay, and blends into PowerScore via an asymmetric SOS-gated authority system.

### Pipeline

1. **Build features**: team_power, opp_power, power_diff, age_gap, cross_gender
2. **Time-based split**: 30-day holdout (leakage protection)
3. **Fit XGBoost** (fallback RandomForest): predict goal_margin
4. **Compute residuals**: `residual = actual_margin - predicted_margin` (clipped ±3.5)
5. **Aggregate per-team**: weighted avg with recency decay by game rank (λ=0.06), min 12 games (`min_team_games_for_residual`)
6. **Normalize**: percentile rank per cohort → `ml_norm ∈ [-0.5, +0.5]`
7. **Asymmetric gate**, applied by the calculator *after* `powerscore_ml` is written
   (the gates produce `power_score_true`; `powerscore_ml` itself is ungated):
   - Positive corrections: scaled by `sos_norm` (0 below 0.45, full at 0.60, linear
     between) **and** by `positive_ml_evidence_scale` from the same-age evidence gates —
     `sos_norm > 0.60` alone is not sufficient
   - Negative corrections always apply in full
8. **Blend**: `powerscore_ml = powerscore_adj + 0.08 * ml_norm`
9. **Clamp** to [0, 1]

### Why Asymmetric

Negative ML adjustments (downrating) always apply at full authority regardless of `sos_norm` (`NEGATIVE_ML_FLOOR = 1.0`). A weak schedule never shields a team from being marked overrated; only positive corrections must earn authority through schedule strength.

### Layer 13 Configuration

| Parameter | Value | Role |
|-----------|-------|------|
| `alpha` | 0.08 | PowerScore blend weight |
| `recency_decay_lambda` | 0.06 | Per-game recency decay |
| `min_team_games_for_residual` | 12 | Min games for ML adjustment |
| `residual_clip_goals` | 3.5 | Outlier guardrail |
| `norm_mode` | "percentile" | Normalization method |
| `min_training_rows` | 30 | ML leakage protection |
| `SOS_ML_THRESHOLD_LOW` | 0.45 | Below: no ML authority |
| `SOS_ML_THRESHOLD_HIGH` | 0.60 | Above: full ML authority |
| `NEGATIVE_ML_FLOOR` | 1.0 | Documents the behaviour (the gate hardcodes 1.0 for negative deltas); the constant itself is only read into the cache fingerprint |

### XGBoost Hyperparameters

`n_estimators=220, max_depth=5, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9, reg_lambda=1.0`

## League Tier System

Per-league multipliers (`src/rankings/constants.py`) discount opponent mu both inside the
Glicko-2 convergence loop and in SOS, U13+ only. Male and female tables differ:

| League | Male | Female |
|--------|------|--------|
| MLS NEXT HD | 1.00 | — |
| ECNL | 0.98 | 1.00 |
| MLS NEXT AD | 0.98 | — |
| GA | — | 0.98 |
| ECNL RL | 0.95 | 0.94 |
| DPL, NPL, EA, NL (ASPIRE: F) | 0.93 | 0.93 |
| EA2 | 0.91 | — |
| Unaffiliated | 0.97 | 0.97 |

## v53e Engine (Legacy Alternative)

`src/etl/v53e.py` — 11-layer deterministic engine, reachable only via `--engine v53e`.
Still available for comparison/validation. Uses win/draw/loss base scoring, 3-pass iterative SOS,
hybrid normalization (70% percentile + 30% sigmoid z-score), and Bayesian shrinkage (τ=8.0).
Blend weights: 20% offense + 20% defense + 60% SOS.

## PowerScore Requirements

### MUST be in [0.0, 1.0]

```python
assert 0.0 <= power_score <= 1.0, f"Invalid PowerScore: {power_score}"
power_score = max(0.0, min(1.0, power_score))  # Clamp to bounds
```

### Reading a score

Nothing in code defines named tiers. `powerscore_core` is a within-cohort sigmoid of the
SOS-adjusted, evidence-shrunk mu, so 0.5 corresponds to the mean of that input (not a
percentile), and `power_score_final` then applies the age anchor. Describe a team by rank and
by distance from its cohort mean, never by an absolute band.

## Calculation Arguments

```bash
python scripts/calculate_rankings.py --engine glicko --lookback-days 365 --dry-run
```

| Flag | Effect |
|------|--------|
| `--ml` | No-op under Glicko: ML runs unless env `ML_LAYER_ENABLED=false` |
| `--engine glicko` | Engine: glicko (default) or v53e (legacy) |
| `--lookback-days 365` | Game window |
| `--dry-run` | No database writes |
| `--force-rebuild` | Ignore cache |
| `--age-group u14` | Filter age group |
| `--gender Male` | Filter gender |

## Output Tables

### `rankings_full` (Primary)

```sql
team_id                 UUID
national_power_score    FLOAT (0.0-1.0)  -- derived from power_score_true
national_rank           INT    -- always NULL in rankings_full (current_rankings aliases rank_in_cohort_final)
state_rank              INT    -- always NULL in rankings_full; views compute display ranks
rank_in_cohort          INT    -- engine order by mu
rank_in_cohort_ml       INT    -- order by powerscore_ml
rank_in_cohort_final    INT    -- published rank (Active only)
sos                     FLOAT  -- raw, 1500-centred
sos_norm                FLOAT  -- 0-1; every threshold (0.45 / 0.60) reads this
age_group               TEXT
gender                  TEXT
state_code              TEXT
games_played            INT
wins, losses, draws     INT
goals_for, goals_against INT
strength_of_schedule    FLOAT
powerscore_core         FLOAT  -- sigmoid(z-score) of SOS-adjusted mu
powerscore_adj          FLOAT  -- × provisional_mult (pre-ML)
powerscore_ml           FLOAT  -- post-ML
power_score_true        FLOAT  -- post evidence gates, unanchored
power_score_final       FLOAT  -- × AGE_TO_ANCHOR
last_calculated         TIMESTAMPTZ
```

Note: Glicko `mu` / `sigma` / `volatility` are exported as `glicko_rating` / `glicko_rd` /
`glicko_volatility`; there is no `scf` column. Use `powerscore_adj` for the base Glicko-2 score.

### `current_rankings` (Legacy)

Subset of rankings_full for backward compatibility.

## Common Issues

### "0 teams ranked"
- Check if games exist in lookback window
- Verify Supabase connectivity
- Check filter parameters (age_group format is "u14" not "14")

### PowerScore out of bounds
- Normalization step may have failed
- Check for NaN values in mu/sigma
- Verify convergence completed (check iteration count)

### Rankings stale
- Monday workflow may have failed
- Check GitHub Actions logs
- Verify Supabase write permissions

### Cross-age SOS looks wrong
- Confirm Pass 2 ran with non-empty `global_strength_map`
- Check age anchors for the relevant gender
- Verify the opponent has games in the lookback window
