# Opponent-Adjusted Offense/Defense: Implementation Summary

## What Was Implemented

A fix for the **double-counting problem** where teams playing weak schedules get inflated offense/defense scores that more than offset their SOS penalty.

---

## The Problem (Before)

```python
# Current system:
offense = raw_goals_scored  # Implicitly affected by schedule strength
defense = raw_goals_allowed  # Implicitly affected by schedule strength
sos = opponent_strength  # Explicitly measures schedule strength

power_score = 0.25×offense + 0.25×defense + 0.50×sos
```

**Double-counting:** Schedule strength affects the score twice:
1. **Implicitly** through offense/defense (easy to score vs weak opponents)
2. **Explicitly** through SOS

**Result:** Teams with weak schedules rank too high because their inflated offense/defense (+0.0718) more than offsets their SOS penalty (-0.0524).

---

## The Solution (After)

```python
# New system with opponent adjustment:
for each game:
    off_adjusted = goals_scored × (opponent_strength / baseline_strength)
    def_adjusted = goals_allowed × (baseline_strength / opponent_strength)

offense = average(off_adjusted)  # Now opponent-neutral!
defense = average(def_adjusted)  # Now opponent-neutral!
sos = opponent_strength  # Still explicit

power_score = 0.25×offense + 0.25×defense + 0.50×sos
```

**No more double-counting:** Schedule strength only affects the score once (through SOS).

---

## How It Works

### Step 1: Initial Pass (Unadjusted)
1. Calculate offense/defense WITHOUT adjustment (current system)
2. Calculate `power_presos` from unadjusted OFF/DEF
3. Create `strength_map` (opponent quality measure)

### Step 2: Adjustment Pass
4. Go back to games, adjust offense/defense using opponent strength
   - **Offense multiplier** = `opponent_strength / 0.5`
     - Strong opponent (0.8): multiplier = 1.6 (60% more credit)
     - Weak opponent (0.3): multiplier = 0.6 (40% less credit)
   - **Defense multiplier** = `0.5 / opponent_strength`
     - Strong opponent (0.8): multiplier = 0.625 (37.5% less penalty)
     - Weak opponent (0.3): multiplier = 1.67 (67% more penalty)
5. Re-aggregate adjusted goals
6. Re-shrink, re-normalize, recalculate power
7. Update strength_map

### Step 3: Continue Normal Flow
8. Calculate adaptive_k using updated strength_map
9. Calculate SOS
10. Calculate performance
11. Calculate final power score

---

## Configuration

### Enable/Disable the Feature

**Default: ENABLED**

To disable (not recommended):

```bash
# Environment variable
export OPPONENT_ADJUST_ENABLED=false

# Or in code
cfg = V53EConfig()
cfg.OPPONENT_ADJUST_ENABLED = False
```

### Tune the Adjustment

```python
# In v53e.py V53EConfig:
OPPONENT_ADJUST_BASELINE = 0.5  # Reference strength (don't change)
OPPONENT_ADJUST_CLIP_MIN = 0.4  # Min multiplier (prevent extreme penalties)
OPPONENT_ADJUST_CLIP_MAX = 1.6  # Max multiplier (prevent extreme rewards)
```

**Conservative bounds (0.4 - 1.6)** prevent extreme adjustments:
- At most 60% more credit for scoring vs elite opponents
- At most 60% less credit for scoring vs weak opponents

---

## Expected Impact

### PRFC Scottsdale vs Dynamos SC Test Case

**Before (unadjusted):**
```
PRFC:    OFF=0.863 (inflated), SOS=0.745 → Power=0.8194
Dynamos: OFF=0.590 (deflated), SOS=0.850 → Power=0.8000
Gap: +0.0194 (PRFC ahead) ← WRONG
```

**After (adjusted):**
```
PRFC:    OFF≈0.70-0.75 (corrected down), SOS=0.745 → Power≈0.78
Dynamos: OFF≈0.70-0.72 (corrected up), SOS=0.850 → Power≈0.80
Gap: -0.02 (Dynamos ahead) ← CORRECT
```

### Broader Impact

**Teams that will rank HIGHER:**
✓ Teams playing tough schedules who compete well
✓ Teams whose offense/defense was deflated by strong opponents
✓ Example: Dynamos SC (SOS 0.850, currently undervalued)

**Teams that will rank LOWER:**
✗ Teams playing weak schedules who dominate
✗ Teams whose offense/defense was inflated by weak opponents
✗ Example: PRFC Scottsdale (SOS 0.745, currently overvalued)

**Net effect:** Rankings will more accurately reflect true team quality rather than schedule selection.

---

## How to Test

### Option 1: Quick Test (Specific Teams)

```bash
# Run rankings calculation with the new system
python scripts/calculate_rankings.py

# Query results for PRFC and Dynamos
# Should see Dynamos rank higher now
```

### Option 2: Full Comparison

```bash
# 1. Save current rankings
python scripts/calculate_rankings.py --output current_rankings.csv

# 2. Disable opponent adjustment
export OPPONENT_ADJUST_ENABLED=false
python scripts/calculate_rankings.py --output unadjusted_rankings.csv

# 3. Re-enable and compare
export OPPONENT_ADJUST_ENABLED=true
python scripts/calculate_rankings.py --output adjusted_rankings.csv

# 4. Analyze differences
python -c "
import pandas as pd
current = pd.read_csv('current_rankings.csv')
adjusted = pd.read_csv('adjusted_rankings.csv')
unadjusted = pd.read_csv('unadjusted_rankings.csv')

# Compare rank changes
merged = current.merge(adjusted, on='team_id', suffixes=('_before', '_after'))
merged['rank_change'] = merged['rank_before'] - merged['rank_after']
print(merged.sort_values('rank_change', ascending=False).head(20))
"
```

### Option 3: Validate Specific Case

```python
from src.etl.v53e import compute_rankings, V53EConfig

# Load your games data
games_df = pd.read_parquet('data/games.parquet')

# Test with adjustment
cfg = V53EConfig()
cfg.OPPONENT_ADJUST_ENABLED = True
result = compute_rankings(games_df, cfg=cfg)

# Check PRFC vs Dynamos
teams = result['teams']
prfc = teams[teams['team_id'] == '2e39aab1-27c2-4882-95e9-6e68699a36f4']
dynamos = teams[teams['team_id'] == 'c2f8e0aa-2f96-4c23-b5ae-6782ce392bc9']

print(f"PRFC: OFF={prfc['off_norm'].values[0]:.3f}, PowerScore={prfc['powerscore_core'].values[0]:.6f}")
print(f"Dynamos: OFF={dynamos['off_norm'].values[0]:.3f}, PowerScore={dynamos['powerscore_core'].values[0]:.6f}")
```

---

## Rollout Plan

### Phase 1: Testing (Current)
- ✓ Implementation complete
- ☐ Test with sample data
- ☐ Verify PRFC vs Dynamos flips
- ☐ Check top 100 teams for anomalies

### Phase 2: Staging
- ☐ Deploy to staging environment
- ☐ Run full rankings calculation
- ☐ Compare with production
- ☐ Review biggest movers
- ☐ Validate changes make sense

### Phase 3: Production
- ☐ Deploy to production with feature enabled
- ☐ Monitor for issues
- ☐ Document in release notes
- ☐ Update user-facing documentation

### Phase 4: Tuning (if needed)
- ☐ Analyze results after 1 week
- ☐ Adjust clipping bounds if needed (currently 0.4 - 1.6)
- ☐ Consider adjusting baseline if needed (currently 0.5)

---

## Technical Details

### Code Locations

**Main implementation:**
- `src/etl/v53e.py` lines 59-63: Configuration parameters
- `src/etl/v53e.py` lines 180-229: `_adjust_for_opponent_strength()` function
- `src/etl/v53e.py` lines 517-601: Adjustment logic in main pipeline

**Configuration:**
- `config/settings.py` lines 122-126: Environment variable mappings

**Documentation:**
- `IMPLEMENTATION_PLAN_OPPONENT_ADJUSTED.md`: Detailed implementation plan
- `OPPONENT_ADJUSTED_SUMMARY.md`: This document

### Performance Impact

**Expected:** < 5% increase in computation time
- One additional pass over games DataFrame
- Re-aggregation, re-shrinkage, re-normalization
- All vectorized operations (fast)

**Measured:** TBD (test with full dataset)

---

## Risks & Mitigation

### Risk 1: Breaks existing rankings
**Mitigation:** Feature flag allows easy disable. Run side-by-side comparison before production.

### Risk 2: Over-correction
**Mitigation:** Conservative clipping bounds (0.4 - 1.6) prevent extreme adjustments.

### Risk 3: User confusion
**Mitigation:** Clear documentation, gradual rollout, communicate changes.

### Risk 4: Performance degradation
**Mitigation:** Measure runtime, optimize if needed. Expected impact minimal.

---

## FAQs

### Q: Will this change all rankings?
**A:** Yes, but mostly for teams with very weak or very strong schedules. Teams with average schedules (~0.5 SOS) will see minimal change.

### Q: Can I disable it?
**A:** Yes, set `OPPONENT_ADJUST_ENABLED=false` in environment or code.

### Q: How do I tune the adjustment strength?
**A:** Adjust `OPPONENT_ADJUST_CLIP_MIN` and `OPPONENT_ADJUST_CLIP_MAX`. Lower bounds = more conservative, higher bounds = more aggressive.

### Q: Why not just increase SOS weight instead?
**A:** That's a band-aid that doesn't fix the root cause. This implementation ensures offense/defense are opponent-neutral BEFORE adding SOS.

### Q: What if opponent strength isn't available?
**A:** Falls back to `UNRANKED_SOS_BASE` (0.35) for unranked opponents, same as current SOS calculation.

---

## Success Criteria

- ✓ Implementation complete
- ☐ PRFC vs Dynamos gap flips in Dynamos' favor
- ☐ Teams with strong schedules rank higher (holding performance equal)
- ☐ Teams with weak schedules rank lower (holding performance equal)
- ☐ No breaking changes to existing system
- ☐ Runtime impact < 10%
- ☐ All tests pass

---

## Next Steps

1. **Test with real data** - Run full rankings calculation
2. **Verify PRFC vs Dynamos** - Check that gap flips
3. **Review top movers** - Identify biggest ranking changes
4. **Validate results** - Ensure changes make intuitive sense
5. **Deploy to staging** - Test in staging environment
6. **Production rollout** - Deploy when confident

---

## Support

For questions or issues:
- Review `IMPLEMENTATION_PLAN_OPPONENT_ADJUSTED.md` for detailed design
- Check `src/etl/v53e.py` for implementation details
- Test with `OPPONENT_ADJUST_ENABLED=false` to compare
- Open GitHub issue if problems persist

---

**Status:** Implementation complete, ready for testing
**Feature Flag:** `OPPONENT_ADJUST_ENABLED` (default: True)
**Impact:** Fixes double-counting problem, more accurate rankings
