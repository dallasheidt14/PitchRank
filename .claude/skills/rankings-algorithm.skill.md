---
name: rankings-algorithm
description: PitchRank Glicko-2 ranking algorithm knowledge - two-pass convergence, ML Layer 13, normalization, PowerScore bounds
---

# Rankings Algorithm Skill for PitchRank

You are working on PitchRank's ranking system. This skill explains the Glicko-2 engine and ML pipeline.

## Ranking Pipeline

```
┌─────────────────┐
│  Fetch Games    │  365-day lookback window
│  (from Supabase)│  data_adapter.py → v53e format (two rows per game)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Resolve Merges  │  Apply team_merge_map
│                 │  Deprecated → Canonical
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PASS 1         │  Glicko-2 convergence per (age, gender) cohort
│  glicko_engine  │  No cross-age knowledge; unknown opponents → 0.35
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Build Global   │  global_strength_map = {team_id: mu}
│  Strength Map   │  from Pass 1 converged ratings
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PASS 2         │  Warm-start from Pass 1 (mu, sigma, volatility)
│  glicko_engine  │  Cross-age opponents scaled via age anchors
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ML Layer 13    │  XGBoost residual adjustment
│                 │  Asymmetric SOS-gated blending (α = 0.08)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Normalize      │  sigmoid(z-score) → [0.0, 1.0]
│  PowerScore     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Save to DB     │  rankings_full + current_rankings + game residuals
└─────────────────┘
```

## Orchestrator: calculator.py

`compute_rankings_with_ml()` drives the full pipeline:

1. `fetch_games_for_rankings()` — Supabase → v53e format
2. Cache check (MD5 of game IDs + lookback + merge version)
3. **Pass 1**: `compute_rankings_v2()` per cohort, `global_strength_map=None`
4. Build `global_strength_map` from Pass 1 results
5. **Pass 2**: `compute_rankings_v2()` per cohort, warm-started
6. `apply_predictive_adjustment()` — ML Layer 13
7. `_persist_game_residuals()` — batch RPC to Supabase
8. `calculate_rank_changes()` — 7d/30d deltas vs historical snapshots
9. `save_ranking_snapshot()` — for future rank change calculations

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
  - Symmetric trim: discard bottom 25% and top 15% of opponents
  - Cross-age scaling via anchors (Pass 2 only)

- **SCF** (Schedule Connectivity Factor): regional bubble dampening
  - Measures opponent state diversity; low diversity → dampen SOS toward 0.5
  - `scf_value = unique_states / SCF_DIVERSITY_DIVISOR` (capped at 1.0)
  - Quality override: opponents avg power > 65th pct AND win_rate > 55% → SCF min 0.85
  - Isolation penalty: <3 bridge games → SOS capped at 0.60

### Normalization: `sigmoid_zscore_normalize()`

```python
z = (value - mean) / std
normalized = 1 / (1 + exp(-z))  # Maps to (0, 1), mean → 0.5
```

All normalizations are per-cohort (age, gender). Preserves natural gaps unlike percentile.

### Age Anchors (Cross-Age Scaling)

Gender-specific anchors scale cross-age opponents in Pass 2:
- Male: U10=0.783 → U19=1.0
- Female: U10=0.792 → U19=1.0

### Glicko-2 Configuration (`GlickoConfig`)

| Parameter | Value | Role |
|-----------|-------|------|
| `INITIAL_MU` | 1500.0 | Starting rating |
| `INITIAL_SIGMA` | 350.0 | Starting rating deviation |
| `INITIAL_VOLATILITY` | 0.06 | Starting volatility |
| `TAU` | 0.5 | Volatility system constant |
| `GLICKO2_SCALE` | 173.7178 | Scale conversion factor |
| `MAX_GAMES` | 30 | Recent games for OFF/DEF |
| `WINDOW_DAYS` | 365 | Historical window |
| `INACTIVE_DAYS` | 180 | Inactive threshold |
| `RECENCY_LAMBDA` | 1.0 | Exponential decay rate |
| `GOAL_DIFF_CAP` | 6 | Max GD per game |
| `CONVERGENCE_THRESHOLD` | 1.0 | Mean |delta_mu| to stop |

## ML Layer 13 (layer13_predictive_adjustment.py)

### What It Does

Trains XGBoost on per-game residuals, aggregates per-team with recency decay, and blends into PowerScore via an asymmetric SOS-gated authority system.

### Pipeline

1. **Build features**: team_power, opp_power, power_diff, age_gap, cross_gender
2. **Time-based split**: 30-day holdout (leakage protection)
3. **Fit XGBoost** (fallback RandomForest): predict goal_margin
4. **Compute residuals**: `residual = actual_margin - predicted_margin` (clipped ±3.5)
5. **Aggregate per-team**: weighted avg with exponential recency decay (λ=0.06), min 6 games
6. **Normalize**: percentile rank per cohort → `ml_norm ∈ [-0.5, +0.5]`
7. **Asymmetric gate** via SOS thresholds:
   - SOS < 0.45 → no ML authority (except 50% floor for downrating)
   - SOS > 0.60 → full ML authority
   - Between → linear interpolation
8. **Blend**: `powerscore_ml = powerscore_adj + 0.08 * ml_norm`
9. **Clamp** to [0, 1]

### Why Asymmetric

Negative ML adjustments (downrating) get minimum 50% authority even below the SOS threshold. Prevents overrated teams in weak schedules from escaping correction.

### Layer 13 Configuration

| Parameter | Value | Role |
|-----------|-------|------|
| `alpha` | 0.08 | PowerScore blend weight |
| `recency_decay_lambda` | 0.06 | Per-game recency decay |
| `min_team_games_for_residual` | 6 | Min games for ML adjustment |
| `residual_clip_goals` | 3.5 | Outlier guardrail |
| `norm_mode` | "percentile" | Normalization method |
| `min_training_rows` | 30 | ML leakage protection |
| `SOS_ML_THRESHOLD_LOW` | 0.45 | Below: no ML authority |
| `SOS_ML_THRESHOLD_HIGH` | 0.60 | Above: full ML authority |
| `NEGATIVE_ML_FLOOR` | 0.50 | Min authority for downrating |

### XGBoost Hyperparameters

`n_estimators=220, max_depth=5, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9, reg_lambda=1.0`

## League Tier System

Tier multipliers applied to opponent strength in SOS calculation (U13+ only):

| Tier | Multiplier | Leagues |
|------|-----------|---------|
| Tier 1 (elite) | 1.00 | ECNL, MLS NEXT HD, GA |
| Tier 2 (regional) | 0.85 | ECNL RL, MLS NEXT AD, DPL |
| Tier 3 (local) | 0.70 | NPL, EA, NL, ASPIRE |
| Unaffiliated | 1.00 | Default |

## v53e Engine (Legacy Alternative)

`src/etl/v53e.py` — 11-layer deterministic engine, switchable via `use_glicko=False`.
Still available for comparison/validation. Uses win/draw/loss base scoring, 3-pass iterative SOS,
hybrid normalization (70% percentile + 30% sigmoid z-score), and Bayesian shrinkage (τ=8.0).
Blend weights: 20% offense + 20% defense + 60% SOS.

## PowerScore Requirements

### MUST be in [0.0, 1.0]

```python
assert 0.0 <= power_score <= 1.0, f"Invalid PowerScore: {power_score}"
power_score = max(0.0, min(1.0, power_score))  # Clamp to bounds
```

### Higher = Better

- 0.95+ = Elite national team
- 0.80-0.95 = Top tier
- 0.50-0.80 = Competitive
- 0.20-0.50 = Developing
- <0.20 = Limited data or new team

## Calculation Arguments

```bash
python scripts/calculate_rankings.py \
    --ml                    # Enable ML layer
    --glicko               # Use Glicko-2 engine (default)
    --no-glicko            # Use v53e engine
    --lookback-days 365     # Game window
    --dry-run              # Don't save to DB
    --force-rebuild        # Ignore cache
    --age-group u14        # Filter age group
    --gender Male          # Filter gender
```

## Output Tables

### `rankings_full` (Primary)

```sql
team_id                 UUID
national_power_score    FLOAT (0.0-1.0)  -- derived from power_score_true
national_rank           INT
state_rank              INT
age_group               TEXT
gender                  TEXT
state_code              TEXT
games_played            INT
wins, losses, draws     INT
goals_for, goals_against INT
strength_of_schedule    FLOAT
powerscore_adj          FLOAT  -- pre-ML PowerScore
powerscore_ml           FLOAT  -- post-ML PowerScore
last_calculated         TIMESTAMPTZ
```

Note: `mu`, `SCF` columns are NOT in `rankings_full`. Use `powerscore_adj` for the base Glicko-2 score.

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
