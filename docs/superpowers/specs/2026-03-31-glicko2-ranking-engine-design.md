# PitchRank v2: Glicko-2 Ranking Engine

## Goal

Replace the v53e 10-layer normalization pipeline with a Glicko-2 core engine that produces a single unified rating per team. Offense, defense, and schedule strength become derived display metrics — not inputs to the ranking. This eliminates the multi-layer normalization inflation cascade in v53e. Regional bubble inflation requires separate handling (see SCF section).

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

Where `MAX_GD = 6` (matching v53e's GOAL_DIFF_CAP) to prevent blowouts from dominating.

**Outlier guard:** Before computing goal differential, clip individual game GF/GA to cohort mean +/- 2.5 standard deviations (matching v53e's OUTLIER_GUARD_ZSCORE). This prevents data entry errors (e.g., 15-0 forfeits coded as scores) from distorting ratings.

This maps outcomes to a continuous scale where:
- 1-0 win ≈ 0.64
- 3-0 win ≈ 0.81
- 5-0 win ≈ 0.89
- 0-0 draw = 0.50

### Convergence

Since we process historical games in batch (not sequentially like chess), the engine iterates over the full game set until ratings stabilize. Each iteration uses the updated ratings from the previous pass.

**Convergence criteria:**
- Stop when max |delta_mu| < 1.0 across all teams (on the 1500-scale, 1.0 is negligible)
- Safety valve: max 10 iterations with a warning log if not converged
- Expected convergence: 3-5 iterations for typical cohorts, empirically validated on production data before go-live

**Recency weighting:** Each game's contribution to the Glicko-2 mu/sigma update is weighted by exponential decay: `weight = exp(-lambda * days_ago / 365)` where lambda matches v53e's effective decay. Recent games have ~5x the impact of games from 11 months ago. Without this, a team dominant 10 months ago but losing recently would still appear elite.

**Disconnected components:** Teams that never play each other (even transitively) converge independently. Their rating scales may not be directly comparable. The SCF bubble detection (see below) identifies and dampens isolated clusters.

### Cross-Age Scaling

When a U14 team plays a U15 opponent:
1. Look up the U15 opponent's Glicko-2 rating from their own cohort (Pass 2)
2. Apply **additive** age adjustment: `scaled_mu = opp_mu + (opp_anchor - team_anchor) * ANCHOR_SCALE_FACTOR`
3. Use scaled_mu as the opponent strength for the Glicko-2 update

**Why additive, not multiplicative:** Glicko-2 mu is on an interval scale (1500 = average). Multiplying mu by a ratio (as v53e does with 0-1 normalized strengths) produces nonsensical results — a U14 team rated 1500 (average) seen by a U19 team would become 1500 * 0.93 = 1395 ("well below average"), when the intended meaning is "slightly younger age group, same relative strength." Additive scaling preserves the "average in their cohort" meaning.

**ANCHOR_SCALE_FACTOR:** Converts anchor difference to Glicko-2 rating points. Calibrated so that the full U10→U19 anchor spread maps to a meaningful rating gap (e.g., ANCHOR_SCALE_FACTOR = 400 means the U10/U19 gap ≈ 80 rating points).

**Age anchors (calibrated from empirical cross-age data):**

Male:

| Age | Anchor | Source |
|-----|--------|--------|
| U10 | 0.783 | Empirical: top-team rating 78.3% of U19 |
| U11 | 0.793 | |
| U12 | 0.824 | |
| U13 | 0.878 | |
| U14 | 0.928 | |
| U15 | 0.935 | |
| U16 | 0.962 | |
| U17 | 0.965 | |
| U18 | 0.985 | Interpolated |
| U19 | 1.000 | Reference |

Female:

| Age | Anchor | Source |
|-----|--------|--------|
| U10 | 0.792 | Empirical: top-team rating 79.2% of U19 |
| U11 | 0.828 | |
| U12 | 0.885 | |
| U13 | 0.914 | |
| U14 | 0.957 | |
| U15 | 0.962 | |
| U16 | 0.984 | |
| U17 | 0.996 | |
| U18 | 0.998 | Interpolated |
| U19 | 1.000 | Reference |

**Key insight from calibration:** Age gaps are much tighter than v53e's old anchors assumed. U14-U19 is within ~7% for both genders. The real separation is U10-U13. Previous anchors (U10=0.40, U14=0.70) were over-penalizing younger age groups by nearly 2x.

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

Use the Glicko-2 expected score function to predict goals:

```
E(team, opp) = 1 / (1 + 10^((opp_mu - team_mu) / 400))
expected_gf = cohort_avg_gpg * E(team, opp)
expected_ga = cohort_avg_gpg * E(opp, team)
```

Where `cohort_avg_gpg` is the average goals per game within the (age, gender) cohort (typically 2-3 for youth soccer). This converts a win probability into an expected goal count.

### Offense Rating

```
off_residual_per_game = actual_gf - expected_gf
offense_raw = weighted_avg(off_residuals, weights=recency_weight * opp_rating_weight)
```

Positive = team scores more than expected given opponent quality. Recency weight uses the same exponential decay as the core engine.

### Defense Rating

```
def_residual_per_game = expected_ga - actual_ga
defense_raw = weighted_avg(def_residuals, weights=recency_weight * opp_rating_weight)
```

Positive = team concedes less than expected given opponent quality.

### Key Property

A team scoring 3 goals against a 1600-rated opponent gets more offensive credit than scoring 3 against a 1200-rated opponent. Opponent strength is inherent in the expected goals calculation — `E(team, 1600_opp)` produces lower expected_gf than `E(team, 1200_opp)`, so the same actual goals yield a larger positive residual.

### Display Normalization

Convert offense_raw and defense_raw to 0-1 scale within cohort using sigmoid z-score (no percentile, no min-max rescaling). These are display-only metrics — they do not feed back into the ranking.

## Schedule Strength

```
sos_raw = mean(opponent_glicko_rating for each game played)
```

No normalization needed for the computation — opponent ratings are already on an absolute scale (1500 = cohort average). A team with SOS of 1620 played harder opponents than a team with SOS of 1480, period.

For display in the frontend, convert to 0-1 via sigmoid z-score within cohort (same as off/def — display only, not a ranking input).

## Schedule Strength Details

### SOS Repeat Cap and Trimming

Port from v53e to prevent schedule gaming:
- **Repeat cap:** Cap repeat opponents at 4 games (SOS_REPEAT_CAP=4). A team playing the same weak opponent 8 times only counts 4 toward SOS.
- **Symmetric trim:** Trim bottom 25% and top 15% of opponents by rating before computing mean SOS. Prevents outlier opponents from distorting the average.

With Glicko-2 ratings on an absolute scale, trimming is simpler than v53e's percentile-based approach — just sort opponents by mu and trim.

## SCF: Regional Bubble Detection

Regional bubble inflation is a graph topology problem that Glicko-2 does not solve. Three teams in Idaho playing only each other will inflate each other's ratings through circular wins.

**Port the SCF (Schedule Connectivity Factor) logic from v53e:**
- Detect connected components in the game graph
- Compute bridge games (cross-component games that connect isolated clusters)
- Dampen ratings for teams in isolated components with few bridge games
- Track `unique_opp_states` to detect regional bubbles

**Output columns:** `scf`, `bridge_games`, `is_isolated`, `unique_opp_states`, `quality_boosted` — same as v53e, computed on Glicko-2 ratings instead of base_strength_map.

**PageRank dampening:** Apply the same PageRank-style dampening to Glicko-2 SOS values for teams in small components. This reduces the SOS credit for playing within a closed cluster.

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

### Feature Compatibility

The current Layer 13 uses v53e features (team_power, opp_power, power_diff, age_gap, cross_gender). To preserve learned relationships, map Glicko-2 mu to 0-1 power score first (via sigmoid z-score), then use the same feature names. This avoids a cold-start problem where the ML model needs to relearn from scratch.

Alpha = 0.08 was tuned for v53e residuals. Re-tune on Glicko-2 residuals after the first production run — the residual scale may differ.

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

The new engine maps to the exact same `rankings_full` columns. Every column is accounted for:

### Core ranking columns (computed by new engine)

| Column | Source in New Engine |
|--------|---------------------|
| powerscore_adj | Glicko-2 mu → sigmoid z-score within cohort → 0-1 |
| off_norm | Derived offense → sigmoid z-score within cohort → 0-1 |
| def_norm | Derived defense → sigmoid z-score within cohort → 0-1 |
| sos_norm | Avg opponent rating → sigmoid z-score within cohort → 0-1 |
| sos | Average opponent Glicko-2 mu (absolute scale) |
| national_rank | Rank by Glicko-2 mu within cohort |
| state_rank | Rank by Glicko-2 mu within cohort + state |
| global_rank | Rank by Glicko-2 mu across all cohorts |
| games_played | Count of games in 30-game window |
| wins/losses/draws | From game results |
| win_percentage | wins / games_played |
| goals_for / goals_against | Sum from game results |
| provisional_mult | Derived from sigma (see formula below) |
| powerscore_ml | powerscore_adj + alpha * ml_norm |
| status | Active if game in last 180 days, else Inactive |
| power_score_final | = powerscore_ml (or powerscore_adj if ML disabled) |
| sample_flag | "LOW_SAMPLE" if gp < 6, else "OK" |
| last_game | Most recent game date |
| last_calculated | Timestamp of ranking run |

### Raw/intermediate columns (computed for diagnostics and display)

| Column | Source |
|--------|--------|
| off_raw | offense_raw (pre-normalization residual) |
| sad_raw | defense_raw as goals-against average (for backward compat) |
| off_shrunk | = off_raw (no separate shrinkage — Glicko-2 sigma handles uncertainty) |
| def_shrunk | = defense_raw |
| sad_shrunk | = sad_raw |
| abs_strength | Glicko-2 mu normalized to 0-1 (used by two-pass cross-age) |
| power_presos | powerscore_adj before ML correction |
| anchor | Bayesian anchor (0.5 — cohort midpoint) |
| powerscore_core | = powerscore_adj (no separate core vs adj in Glicko-2) |

### SCF/bubble columns (ported from v53e)

| Column | Source |
|--------|--------|
| scf | Schedule Connectivity Factor from bubble detection |
| bridge_games | Count of cross-component games |
| is_isolated | Boolean: team in small disconnected component |
| unique_opp_states | Count of unique states among opponents |
| quality_boosted | Boolean: quality override applied |

### SOS detail columns

| Column | Source |
|--------|--------|
| sos_raw | = sos (average opponent Glicko-2 mu) |
| sos_norm_national | sos_norm (same — already national scope) |
| sos_norm_state | SOS sigmoid z-score within state subset |
| sos_rank_national | Rank by sos within cohort |
| sos_rank_state | Rank by sos within cohort + state |
| strength_of_schedule | = sos (alias) |

### ML columns

| Column | Source |
|--------|--------|
| ml_overperf | ML adjustment value per team |
| ml_norm | ML adjustment normalized within cohort |
| powerscore_ml | powerscore_adj + alpha * ml_norm |
| rank_in_cohort_ml | Rank by powerscore_ml |
| perf_raw | Game residuals (actual - expected margin) |
| perf_centered | perf_raw centered within cohort |

### Computed downstream (not by engine)

| Column | Source |
|--------|--------|
| rank_change_7d | Computed by comparing to ranking_history |
| rank_change_30d | Same |
| rank_change_state_7d | Same |
| rank_change_state_30d | Same |
| national_power_score | = power_score_final (alias) |
| global_power_score | = power_score_final (alias) |
| power_score_true | = power_score_final (alias) |
| games_last_180_days | Count from game dates |

### Provisional Multiplier Formula

Derived from Glicko-2 sigma (uncertainty):

```
provisional_mult = clip(1.0 - (sigma / INITIAL_SIGMA)^2, 0.0, 1.0)
```

Where INITIAL_SIGMA = 350. Examples:
- New team (sigma=350): mult = 0.00 (fully dampened)
- 3 games (sigma~250): mult ≈ 0.49
- 6 games (sigma~180): mult ≈ 0.74
- 15 games (sigma~100): mult ≈ 0.92
- 30 games (sigma~60): mult ≈ 0.97

This naturally replaces v53e's hard-coded GP thresholds with a continuous function driven by actual rating confidence.

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

## Performance

v53e processes ~500K game rows in a ~2hr window. The Glicko-2 engine adds convergence iterations (3-5x) and a second pass (2x), for roughly 6-10x more row-passes.

**Mitigations:**
- Vectorize Glicko-2 updates with numpy (batch all teams simultaneously, not per-team loops)
- Pass 2 may need only 1-2 refinement iterations (not full convergence) since cross-age games are a small fraction
- Per-cohort processing is embarrassingly parallel — can use multiprocessing if needed
- Benchmark on production data before go-live; if >4hr, reduce convergence iterations with empirical justification

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
