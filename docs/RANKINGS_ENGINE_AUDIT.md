# Rankings Engine Audit — Gaps & Inaccuracy Vectors

**Date**: 2026-02-11
**Scope**: Full review of v53e engine, calculator, ML layer, data adapter, config, and tests
**Files Reviewed**:
- `src/etl/v53e.py` (1,541 lines — core algorithm)
- `src/rankings/calculator.py` (923 lines — orchestration + anchor scaling)
- `src/rankings/layer13_predictive_adjustment.py` (647 lines — ML layer)
- `src/rankings/data_adapter.py` (885 lines — Supabase ↔ v53e)
- `config/settings.py` (280 lines — central config)
- `tests/unit/test_sos_validation.py`, `test_regional_bubble_detection.py`

---

## CRITICAL — Directly Causing Inaccuracies

### 1. `NORM_MODE` Config Mismatch (settings.py vs v53e.py)

**Location**: `config/settings.py:160` vs `src/etl/v53e.py:102`

`settings.py` defaults `norm_mode` to `"percentile"`, but `V53EConfig` hardcodes `NORM_MODE = "zscore"`. The v53e engine uses its own dataclass — not `RANKING_CONFIG` from settings. The settings.py value is dead config.

**Impact**: Operators who set `NORM_MODE=percentile` via env vars expect it to change behavior. It doesn't.

**Fix**: Either wire `RANKING_CONFIG['norm_mode']` into `V53EConfig` construction, or remove the dead setting.

### 2. `_recency_weights` Ignores All Config Parameters

**Location**: `src/etl/v53e.py:211-240`

The function signature accepts `k`, `recent_share`, `tail_start`, `tail_end`, `w_start`, `w_end` but ignores all of them, using a hardcoded `decay_rate = 0.05`. Config exposes `RECENT_K=15`, `RECENT_SHARE=0.65`, `DAMPEN_TAIL_*` as tunable — none do anything.

**Impact**: False tunability. No way to adjust recency weighting despite config suggesting otherwise.

**Fix**: Either use the config params or remove them from `V53EConfig` and `settings.py`.

### 3. Wins/Losses/Draws Never Computed

**Location**: `src/etl/v53e.py:1532-1538`

W/L/D are set to `None` despite having full `gf`/`ga` data for every game. `win_percentage` is always null.

**Impact**: Frontend displays empty W/L/D records. Users cannot see basic team records.

**Fix**: Add W/L/D aggregation in the team-level computation:
```python
wins = (g["gf"] > g["ga"]).sum()
losses = (g["gf"] < g["ga"]).sum()
draws = (g["gf"] == g["ga"]).sum()
```

---

## HIGH — Significant Accuracy Concerns

### 4. No Forfeit/Walkover/Bye Handling

**Location**: Entire codebase (confirmed via grep — zero references)

Forfeit wins (typically recorded as 1-0) are treated as competitive results. Inflates winner's OFF, deflates loser's DEF, and the forfeited opponent counts as full-strength for SOS.

**Fix**: Add a `is_forfeit` column to games table and either exclude forfeits from rankings or weight them at 0.

### 5. No Home/Away Advantage Adjustment

**Location**: `src/etl/v53e.py` — venue data scraped but unused

The `home_team_master_id` field exists but is only used for ML residual extraction. No GF/GA adjustment for home advantage.

**Fix**: Apply a small adjustment factor (e.g., ±0.15 goals) based on home/away status, or at minimum flag neutral-site games.

### 6. Opponent Adjustment Is Single-Pass

**Location**: `src/etl/v53e.py:750-843`

Uses strength estimates from pre-adjustment OFF/DEF to adjust OFF/DEF. A second pass with updated strengths would yield different results.

**Fix**: Run 2-3 iterations of the opponent adjustment, checking for convergence.

### 7. Performance Threshold Too Harsh for Young Ages

**Location**: `src/etl/v53e.py:1210-1213`

`PERFORMANCE_THRESHOLD = 2.0` goals means any game where actual margin differs from expected by <2 goals gets zero performance credit. For U10-U12 where typical margins are 1-2 goals, this silences the performance signal.

**Fix**: Scale threshold by age group (e.g., 1.0 for U10-U12, 1.5 for U13-U15, 2.0 for U16+).

---

## MEDIUM — Accuracy Degraders

### 8. Power-SOS Co-Calculation Loop Erases SCF + PageRank — FIXED

**Location**: `src/etl/v53e.py:1281-1383`
**Status**: **FIXED** — `SOS_POWER_ITERATIONS` set to 0

The loop used `abs_strength` (identical to `base_strength_map`) to recompute the same raw SOS as the initial pass — but WITHOUT PageRank dampening, SCF, or isolation cap. The 80/20 blend (`SOS_POWER_DAMPING=0.80`) exponentially washed away the protected values: after 5 iterations, only `0.20^5 = 0.03%` of the SCF-corrected SOS remained. Since SCF is team-specific (unlike PageRank which is affine), this actively flipped rank order for isolated bubble teams.

**Fix applied**: `SOS_POWER_ITERATIONS: int = 0` — skips the loop entirely, preserving all anti-inflation mechanisms from the initial SOS pass.

### 9. Small Cohort SOS Percentile Normalization Creates Noise

**Location**: `src/etl/v53e.py:1135-1149`

Percentile normalization within (age, gender) forces uniform distribution. Cohort of 5 teams → SOS values [0.0, 0.25, 0.5, 0.75, 1.0] regardless of actual differences.

**Fix**: Apply minimum cohort size for percentile normalization. Below threshold, use z-score normalization or raw values with shrinkage.

### 10. `UNRANKED_SOS_BASE = 0.35` Penalizes Teams Playing Newcomers

**Location**: `src/etl/v53e.py:55`

Unknown opponents default to 0.35 strength (below midpoint). Teams with many new/uncovered opponents get systematically lower SOS.

**Fix**: Use 0.50 (neutral) as default, or compute a more informed prior from the opponent's age/gender cohort.

### 11. No Score Sanity Bounds

**Location**: `src/rankings/data_adapter.py`, `src/etl/v53e.py`

No upper limit on scores. A data entry error of 100-0 would partially survive the z-score outlier guard but still distort raw OFF/DEF.

**Fix**: Add a maximum score threshold (e.g., 20 goals) in the data adapter. Flag and quarantine games exceeding it.

### 12. Cross-Age OFF/DEF Unadjusted

**Location**: `src/etl/v53e.py` (opponent adjustment only handles same-age)

When U14 plays U16, the GF/GA values are taken at face value for OFF/DEF. Only SOS accounts for age difference.

**Fix**: Apply age-gap multiplier to GF/GA similar to opponent strength adjustment.

---

## LOW — Minor Issues

### 13. Stepped Provisional Multiplier (Cliff Effects)

**Location**: `src/etl/v53e.py:271-276`

Discrete steps at 5 and 15 games create ranking jumps.

**Fix**: Use smooth function: `min(1.0, gp / 15)` or sigmoid.

### 14. Thin Test Coverage on Core Logic

**Location**: `tests/`

No tests for: recency weighting, Bayesian shrinkage, opponent adjustment, performance layer, PowerScore formula, cross-age SOS, provisional multiplier.

**Fix**: Add unit tests for each layer with known-answer tests.

### 15. Context Multiplier String Matching

**Location**: `src/etl/v53e.py:609-617`

Checks `"1"`, `"true"`, `"yes"` but not `"True"`, `"t"`, `"Y"`.

**Fix**: Normalize to boolean before comparison.

---

## Priority Recommendations

1. **Quick wins** (fix today): #3 (W/L/D), #2 (remove dead params or wire them), #1 (align config)
2. **Next sprint**: #7 (age-scaled perf threshold), #9 (small cohort handling), #10 (neutral default), #8 (remove no-op iterations)
3. **Medium-term**: #4 (forfeit handling), #5 (home/away), #6 (iterative opponent adjust), #14 (tests)
4. **Nice-to-have**: #11 (score bounds), #12 (cross-age goals), #13 (smooth provisional), #15 (string matching)
