# Implementation Plan: Opponent-Adjusted Offense/Defense

## Goal

Fix the double-counting problem by adjusting offense and defense metrics for opponent strength BEFORE including them in the power score formula.

---

## The Problem (Recap)

Currently:
```python
# Games against weak opponents give you HIGH offense (easy to score)
# Games against strong opponents give you LOW offense (hard to score)
# Then we add a separate SOS penalty/bonus

# This double-counts schedule strength:
# 1. Once through offense/defense (implicit)
# 2. Once through SOS (explicit)
```

**Result:** Teams playing weak schedules get inflated offense/defense that more than offsets their SOS penalty.

---

## The Solution

**Adjust offense/defense for opponent strength at the per-game level:**

```python
# For each game:
off_adjusted = goals_scored × (opponent_strength / baseline_strength)
def_adjusted = goals_allowed × (baseline_strength / opponent_strength)

# Then aggregate:
team_offense = weighted_average(off_adjusted)
team_defense = weighted_average(def_adjusted)
```

**This ensures:**
- Scoring against STRONG opponents → more credit (multiplier > 1)
- Scoring against WEAK opponents → less credit (multiplier < 1)
- Allowing goals vs STRONG opponents → less penalty (multiplier < 1)
- Allowing goals vs WEAK opponents → more penalty (multiplier > 1)

---

## Implementation Strategy

### Challenge: Circular Dependency

We have a chicken-and-egg problem:
1. We need opponent strength to adjust offense/defense
2. Opponent strength comes from `power_presos` = OFF + DEF + SOS×0.5
3. But we're trying to calculate OFF and DEF!

### Solution: Iterative Approach

**Phase 1: Initial pass (unadjusted)**
1. Calculate offense/defense WITHOUT adjustment (current system)
2. Calculate `power_presos` from unadjusted OFF/DEF
3. Create `strength_map` from `power_presos`

**Phase 2: Adjustment pass**
4. Go back to games, adjust offense/defense using opponent strength from Phase 1
5. Re-aggregate adjusted offense/defense
6. Re-shrink with Bayesian shrinkage
7. Re-normalize within cohort
8. Recalculate `power_presos` with adjusted OFF/DEF
9. Update `strength_map`

**Phase 3: Continue normal flow**
10. Calculate adaptive_k using updated strength_map
11. Calculate SOS
12. Calculate performance
13. Calculate final power score

---

## Code Changes Required

### Location: `/home/user/PitchRank/src/etl/v53e.py`

#### 1. Add configuration parameters (lines 30-50)

```python
@dataclass
class V53EConfig:
    # ... existing params ...

    # Opponent-adjusted offense/defense
    OPPONENT_ADJUST_ENABLED: bool = True
    OPPONENT_ADJUST_BASELINE: float = 0.5  # Baseline strength for adjustment
    OPPONENT_ADJUST_CLIP_MIN: float = 0.3  # Min multiplier (avoid extreme adjustments)
    OPPONENT_ADJUST_CLIP_MAX: float = 2.0  # Max multiplier
```

#### 2. Create adjustment function (after line 165)

```python
def _adjust_for_opponent_strength(
    games: pd.DataFrame,
    strength_map: Dict[str, float],
    cfg: V53EConfig
) -> pd.DataFrame:
    """
    Adjust goals for/against based on opponent strength.

    For offense: More credit for scoring against strong opponents
    For defense: Less penalty for allowing goals to strong opponents

    Args:
        games: DataFrame with columns [gf, ga, opp_id]
        strength_map: Dict mapping team_id to strength (0-1)
        cfg: Configuration

    Returns:
        DataFrame with additional columns [gf_adjusted, ga_adjusted]
    """
    g = games.copy()

    # Get opponent strength for each game
    g["opp_strength"] = g["opp_id"].map(
        lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE)
    )

    # Calculate adjustment multipliers
    # Offense: score more against strong = more credit
    g["off_multiplier"] = (g["opp_strength"] / cfg.OPPONENT_ADJUST_BASELINE).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN,
        cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Defense: allow goals to strong = less penalty
    g["def_multiplier"] = (cfg.OPPONENT_ADJUST_BASELINE / g["opp_strength"]).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN,
        cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Apply adjustments
    g["gf_adjusted"] = g["gf"] * g["off_multiplier"]
    g["ga_adjusted"] = g["ga"] * g["def_multiplier"]

    return g
```

#### 3. Insert adjustment after initial strength_map (after line 456)

```python
    # Line 456: strength_map = dict(zip(team["team_id"], team["abs_strength"]))

    # NEW: Apply opponent-adjusted offense/defense if enabled
    if cfg.OPPONENT_ADJUST_ENABLED:
        logger.info("🔄 Applying opponent-adjusted offense/defense...")

        # Adjust games for opponent strength
        g_adjusted = _adjust_for_opponent_strength(g, strength_map, cfg)

        # Re-aggregate with adjusted values
        g_adjusted["gf_weighted_adj"] = g_adjusted["gf_adjusted"] * g_adjusted["w_game"]
        g_adjusted["ga_weighted_adj"] = g_adjusted["ga_adjusted"] * g_adjusted["w_game"]

        team_adj = g_adjusted.groupby(["team_id", "age", "gender"], as_index=False).agg({
            "gf_weighted_adj": "sum",
            "ga_weighted_adj": "sum",
            "w_game": "sum",
        })

        # Calculate adjusted weighted averages
        w_sum = team_adj["w_game"]
        team_adj["off_raw"] = np.where(
            w_sum > 0,
            team_adj["gf_weighted_adj"] / w_sum,
            0.0
        ).astype(float)
        team_adj["sad_raw"] = np.where(
            w_sum > 0,
            team_adj["ga_weighted_adj"] / w_sum,
            0.0
        ).astype(float)

        # Merge back to team DataFrame
        team = team.drop(columns=["off_raw", "sad_raw"])
        team = team.merge(
            team_adj[["team_id", "age", "gender", "off_raw", "sad_raw"]],
            on=["team_id", "age", "gender"],
            how="left"
        )

        # Re-apply defense ridge
        team["def_raw"] = 1.0 / (team["sad_raw"] + cfg.RIDGE_GA)

        # Re-apply Bayesian shrinkage
        def shrink_grp(df: pd.DataFrame) -> pd.DataFrame:
            mu_off = df["off_raw"].mean()
            mu_sad = df["sad_raw"].mean()
            out = df.copy()
            out["off_shrunk"] = (out["off_raw"] * out["gp"] + mu_off * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
            out["sad_shrunk"] = (out["sad_raw"] * out["gp"] + mu_sad * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
            out["def_shrunk"] = 1.0 / (out["sad_shrunk"] + cfg.RIDGE_GA)
            return out

        team = team.groupby(["age", "gender"], group_keys=False).apply(shrink_grp, include_groups=False)

        # Re-apply outlier clipping
        def clip_team_level(df: pd.DataFrame) -> pd.DataFrame:
            out = df.copy()
            for col in ["off_shrunk", "def_shrunk"]:
                s = out[col]
                if len(s) >= 3 and s.std(ddof=0) > 0:
                    mu, sd = s.mean(), s.std(ddof=0)
                    out[col] = s.clip(mu - cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd,
                                      mu + cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd)
            return out

        team = team.groupby(["age", "gender"], group_keys=False).apply(clip_team_level, include_groups=False)

        # Re-normalize
        team = _normalize_by_cohort(team, "off_shrunk", "off_norm", cfg.NORM_MODE)
        team = _normalize_by_cohort(team, "def_shrunk", "def_norm", cfg.NORM_MODE)

        # Recalculate power_presos with adjusted OFF/DEF
        team["power_presos"] = (
            cfg.OFF_WEIGHT * team["off_norm"]
            + cfg.DEF_WEIGHT * team["def_norm"]
            + cfg.SOS_WEIGHT * team["sos_presos"]
        )

        # Update strength_map with adjusted power
        team["abs_strength"] = (team["power_presos"] / team["anchor"]).clip(0.0, 1.5)
        strength_map = dict(zip(team["team_id"], team["abs_strength"]))
        power_map = dict(zip(team["team_id"], team["power_presos"]))

        logger.info("✅ Opponent-adjusted offense/defense applied successfully")

    # Continue with Layer 5: Adaptive K (now uses updated strength_map)
```

---

## Expected Impact

### PRFC vs Dynamos Test Case

**Current (unadjusted):**
```
PRFC:    OFF=0.863, DEF=0.925, SOS=0.745 → PowerScore core = 0.8194
Dynamos: OFF=0.590, DEF=0.910, SOS=0.850 → PowerScore core = 0.8000
Gap: +0.0194 (PRFC ahead)
```

**Expected (adjusted):**
```
PRFC:    OFF≈0.75, DEF≈0.88, SOS=0.745 → PowerScore core ≈ 0.78
         (offense adjusted DOWN because weak opponents)

Dynamos: OFF≈0.72, DEF≈0.87, SOS=0.850 → PowerScore core ≈ 0.81
         (offense adjusted UP because strong opponents)

Gap: -0.03 (Dynamos ahead) ✓
```

The adjustment should:
1. Reduce PRFC's inflated offense (0.863 → ~0.75)
2. Increase Dynamos' deflated offense (0.590 → ~0.72)
3. Flip the ranking so Dynamos ranks higher

---

## Testing Plan

1. **Unit test the adjustment function**
   - Test with known opponent strengths
   - Verify multipliers are correct
   - Check clipping works

2. **Integration test with PRFC vs Dynamos**
   - Run v53e with adjustment enabled
   - Verify gap flips in Dynamos' favor
   - Check all other teams aren't broken

3. **Full rankings comparison**
   - Run rankings with/without adjustment
   - Compare top 100 teams
   - Identify biggest movers
   - Validate changes make sense

4. **Performance test**
   - Measure runtime impact
   - Should be minimal (one extra pass over games)

---

## Rollout Strategy

### Phase 1: Development & Testing
- Implement changes in v53e.py
- Add flag to enable/disable: `OPPONENT_ADJUST_ENABLED = True`
- Test thoroughly with sample data

### Phase 2: Staging
- Deploy to staging environment
- Run full rankings calculation
- Compare with production
- Review top movers

### Phase 3: Production
- Deploy to production
- Monitor for issues
- Document changes in release notes

### Phase 4: Tuning (if needed)
- Adjust baseline (currently 0.5)
- Adjust clipping bounds (currently 0.3 - 2.0)
- Tune if adjustments are too aggressive/conservative

---

## Configuration Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `OPPONENT_ADJUST_ENABLED` | `True` | Enable/disable feature |
| `OPPONENT_ADJUST_BASELINE` | `0.5` | Reference strength for adjustment |
| `OPPONENT_ADJUST_CLIP_MIN` | `0.3` | Minimum multiplier (avoid extreme penalties) |
| `OPPONENT_ADJUST_CLIP_MAX` | `2.0` | Maximum multiplier (avoid extreme rewards) |

---

## Risks & Mitigation

### Risk 1: Breaks existing rankings
**Mitigation:** Keep feature flag to disable, run side-by-side comparison

### Risk 2: Over-correction
**Mitigation:** Use conservative clipping (0.3 - 2.0) to limit extreme adjustments

### Risk 3: Performance impact
**Mitigation:** Measure runtime, optimize if needed (should be minimal)

### Risk 4: Unexpected edge cases
**Mitigation:** Thorough testing, gradual rollout

---

## Success Criteria

1. ✓ PRFC vs Dynamos gap flips in Dynamos' favor
2. ✓ Teams with strong schedules rank higher (holding performance equal)
3. ✓ Teams with weak schedules rank lower (holding performance equal)
4. ✓ No breaking changes to existing system
5. ✓ Runtime impact < 10%
6. ✓ All tests pass

---

## Timeline

- Implementation: 1-2 hours
- Testing: 2-3 hours
- Review & refinement: 1-2 hours
- Documentation: 1 hour
- **Total: 5-8 hours**

---

## Next Steps

1. Implement the changes in v53e.py
2. Create test script for PRFC vs Dynamos
3. Run full rankings comparison
4. Review and commit
