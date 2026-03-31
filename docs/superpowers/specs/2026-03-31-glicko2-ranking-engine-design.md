# PitchRank v2: Glicko-2 Ranking Engine

## Goal

Replace the v53e 10-layer normalization pipeline with a Glicko-2 core engine that produces a single unified rating per team. Offense, defense, and schedule strength become derived display metrics — not inputs to the ranking. This eliminates the entire class of normalization inflation problems that plague v53e.

## Architecture

```
Games from Supabase (30 games per team, 365-day window)
        |
[Pass 1: Per-Cohort Glicko-2]
  - Each (age, gender) cohort rated independently
  - Iterative convergence (3-5 passes over game set)
  - Log-margin scoring: result = 0.5 + 0.5 * log(1+GD) / log(1+MAX_GD)
  - Output: mu, sigma, volatility per team
        |
[Cross-Age Strength Map] (all cohorts combined)
        |
[Pass 2: Cross-Age Refinement]
  - Re-run each cohort with opponent ratings from other age pools
  - Scale by age anchor ratio (U10=0.40 ... U18/U19=1.00)
        |
[Derive Off/Def/SOS]
  - Offense: avg(actual_gf - expected_gf), weighted by recency + opponent rating
  - Defense: avg(expected_ga - actual_ga), same weighting
  - SOS: average opponent Glicko-2 rating (absolute scale)
        |
[ML Layer 13 Correction]
  - XGBoost on game residuals (actual margin - expected margin)
  - final_rating = glicko_rating + alpha * ml_adjustment (alpha=0.08)
        |
[Output Mapping]
  - Convert to rankings_full schema (same columns, same types)
  - Glicko rating -> powerscore_adj via sigmoid z-score within cohort
  - Off/def/sos -> *_norm via sigmoid z-score within cohort (display only)
        |
[Persist to Supabase]
  - rankings_full table (same schema, frontend unchanged)
  - rating_impacts table (new: per-game rating deltas)
  - games.ml_overperformance (same as current)
```

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Core algorithm | Glicko-2 | Handles uncertainty natively (replaces provisional multiplier), well-documented, standard for game ratings |
| Goal margin | Log margin: `log(1 + GD)` | Diminishing returns, FiveThirtyEight-proven for soccer |
| Game window | Last 30 games within 365 days | Balances recency with data sufficiency |
| Inactivity cutoff | No games in 180 days = Inactive/Unranked | Prevents stale rankings |
| Cross-age handling | Separate pools per cohort, cross-age scaling via age anchors, two-pass | Accurate age-specific rankings with fair cross-age comparisons |
| Off/def derivation | Split from game margins, scaled by opponent rating | Opponent strength baked in, not bolted on |
| ML integration | Correction layer on top of Glicko-2 output (alpha=0.08) | Same proven pattern, catches what Elo misses |
| Transition strategy | Big bang — new engine replaces v53e in one release | v53e.py untouched as rollback, manual spot-checking for validation |
| Normalization | Sigmoid z-score only, no percentile, no rescaling | Lesson learned from v53e — percentile + rescaling inflates moderate values |

## Core Rating Engine

### Glicko-2 Parameters

Each team starts with:
- `mu = 1500` (rating)
- `sigma = 350` (uncertainty — high for new teams)
- `volatility = 0.06` (consistency measure)

### Game Outcome Scoring

For each game, compute a continuous outcome incorporating goal margin:

```
For a win:   result = 0.5 + 0.5 * log(1 + goal_diff) / log(1 + MAX_GD)
For a loss:  result = 0.5 - 0.5 * log(1 + goal_diff) / log(1 + MAX_GD)
For a draw:  result = 0.5
```

Where `MAX_GD` is a cap on goal differential (e.g., 6) to prevent blowouts from dominating. This maps outcomes to a continuous scale where:
- 1-0 win ≈ 0.64
- 3-0 win ≈ 0.81
- 5-0 win ≈ 0.89
- 0-0 draw = 0.50

### Convergence

Since we process historical games in batch (not sequentially like chess), the engine iterates over the full game set 3-5 times until ratings stabilize (max delta < 0.1 per team per iteration). Each iteration uses the updated ratings from the previous pass.

### Cross-Age Scaling

When a U14 team plays a U15 opponent:
1. Look up the U15 opponent's Glicko-2 rating from their own cohort (Pass 2)
2. Scale by age anchor ratio: `scaled_rating = opp_mu * (opp_anchor / team_anchor)`
3. Use scaled_rating as the opponent strength for the Glicko-2 update

Age anchors (same as current v53e):
- U10: 0.40, U11: 0.50, U12: 0.60, U13: 0.70, U14: 0.80, U15: 0.85, U16: 0.90, U17: 0.95, U18: 1.00, U19: 1.00

Two-pass architecture:
- **Pass 1:** Each cohort computed independently, collect all mu values
- **Pass 2:** Re-run each cohort with global rating map for accurate cross-age lookups

### 180-Day Inactivity Rule

Teams with no games in the last 180 days:
- Status set to "Inactive"
- Excluded from rankings (no national_rank, state_rank)
- Rating preserved (sigma widens over time per Glicko-2 volatility model)
- If they play again, they re-enter with their old mu but widened sigma

## Offense/Defense Derivation

After Glicko-2 produces unified ratings, derive offense and defense from game-level data:

### Per-Game Expected Goals

Using the rating difference between team and opponent, compute expected goals for and against based on the league average goals per game within the cohort.

### Offense Rating

```
off_residual_per_game = actual_gf - expected_gf
offense_raw = weighted_avg(off_residuals, weights=recency * opp_rating_weight)
```

Positive = team scores more than expected given opponent quality.

### Defense Rating

```
def_residual_per_game = expected_ga - actual_ga
defense_raw = weighted_avg(def_residuals, weights=recency * opp_rating_weight)
```

Positive = team concedes less than expected given opponent quality.

### Key Property

A team scoring 3 goals against a 1600-rated opponent gets more offensive credit than scoring 3 against a 1200-rated opponent. Opponent strength is inherent in the expected goals calculation.

### Display Normalization

Convert offense_raw and defense_raw to 0-1 scale within cohort using sigmoid z-score (no percentile, no min-max rescaling). These are display-only metrics — they do not feed back into the ranking.

## Schedule Strength

```
sos_raw = mean(opponent_glicko_rating for each game played)
```

No normalization needed for the computation — opponent ratings are already on an absolute scale (1500 = cohort average). A team with SOS of 1620 played harder opponents than a team with SOS of 1480, period.

For display in the frontend, convert to 0-1 via sigmoid z-score within cohort (same as off/def — display only, not a ranking input).

## ML Layer Integration

### Same Pattern as Current Layer 13

After the core engine produces Glicko-2 ratings:

```
final_rating = glicko_rating + alpha * ml_adjustment
```

Default alpha = 0.08 (configurable).

### What ML Catches

- Teams on rapid trajectory (coaching change, roster additions) — Glicko-2 updates incrementally but ML detects the acceleration
- Systematic biases in specific leagues or regions
- Performance patterns in high-stakes games vs regular season

### Input Features to XGBoost

- Game residuals: `actual_margin - expected_margin` (from Glicko-2 predictions)
- Recency-weighted residual trend (increasing or decreasing?)
- Opponent rating variance (performs differently against strong vs weak?)
- Win streak / form indicators

### Retraining

ML model retrains every ranking run using latest game residuals. No manual intervention needed.

## Game-Level Explainability

### Rating Impact Tracking

The engine stores per-game rating impact:

| Field | Description |
|-------|-------------|
| game_id | UUID of the game |
| team_id | UUID of the team |
| opponent_rating | Opponent's Glicko-2 mu at time of game |
| result | W/L/D with score (e.g., "W 3-1") |
| rating_before | Team's mu before this game |
| rating_after | Team's mu after this game |
| rating_delta | Change in mu from this game |

### Storage

New `rating_impacts` table in Supabase, or appended as columns to the existing games table. This powers future explainability features: "Your 3-1 win over Team X (rated 1580) earned +18 points."

No frontend changes required at launch — this is the data layer for future UI work.

## Output Contract

The new engine maps to the exact same `rankings_full` columns:

| Column | Source in New Engine |
|--------|---------------------|
| powerscore_adj | Glicko-2 mu → sigmoid z-score within cohort → 0-1 |
| off_norm | Derived offense → sigmoid z-score within cohort → 0-1 |
| def_norm | Derived defense → sigmoid z-score within cohort → 0-1 |
| sos_norm | Avg opponent rating → sigmoid z-score within cohort → 0-1 |
| sos | Average opponent Glicko-2 mu (absolute scale) |
| national_rank | Rank by Glicko-2 mu within cohort |
| state_rank | Rank by Glicko-2 mu within cohort + state |
| games_played | Count of games in 30-game window |
| wins/losses/draws | From game results |
| provisional_mult | Derived from sigma: high uncertainty → lower mult |
| powerscore_ml | powerscore_adj + alpha * ml_norm |
| status | Active if game in last 180 days, else Inactive |
| power_score_final | = powerscore_ml (or powerscore_adj if ML disabled) |

### Wiring Change

In `calculate_rankings.py`, one import swap:

```python
# Old:
# from src.etl.v53e import compute_rankings
# New:
from src.etl.glicko_engine import compute_rankings_v2
```

### Rollback

Change the import back. v53e.py is untouched.

## What Stays Untouched

- Scraping / import pipeline
- Team matching / deduplication
- Game storage (Supabase tables)
- Frontend (reads from rankings_full — same schema)
- Predict / compare features
- Trajectory tracking
- GitHub Actions workflows (except the ranking calculation step)

## What Gets Created

| File | Purpose |
|------|---------|
| `src/etl/glicko_engine.py` | Core Glicko-2 engine + output mapping |
| `tests/unit/test_glicko_engine.py` | Unit tests for rating math, margin scaling, cross-age |
| `tests/integration/test_glicko_full_pipeline.py` | Synthetic league end-to-end test |

## What Gets Modified

| File | Change |
|------|--------|
| `scripts/calculate_rankings.py` | Import swap: v53e → glicko_engine |
| `src/rankings/layer13_predictive_adjustment.py` | Adapt input features to Glicko-2 output (game residuals from new engine) |

## Testing & Validation

### Unit Tests
- Glicko-2 math: known inputs → expected mu/sigma (published test vectors)
- Log margin scaling: verify diminishing returns curve
- Cross-age scaling: U14 vs U15 produces correct adjusted ratings
- Off/def derivation: team scoring above expected → positive offense
- Output contract: all rankings_full columns present and valid

### Integration Test
- Synthetic league: 20 teams, 100 games, known strength ordering
- Verify output ranking matches known ordering
- Verify convergence in 3-5 iterations

### Production Validation (Manual Spot-Check)
- Phoenix (691eb36d): should remain elite — legitimate strong team, 30 GP, diverse opponents
- Flagged U16M (286a5a52): should drop — dominates weak regional league
- Flagged U17M (1c7c8006): should drop — 19-1-2 but against non-elite opponents
- MLS Next U13 AZ (cc14cfb9): should rise — plays nationally competitive schedule
- Verify: teams dominating weak leagues rank lower than teams competitive against strong opponents

### Regression Safety
- v53e.py untouched as instant rollback
- First production run compared against latest v53e output before going fully live
