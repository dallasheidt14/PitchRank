# Iterative SOS Algorithm Analysis: Accuracy Issues

## You're Right - This is the Real Problem!

Normalization tie-breaking is just a band-aid. The real question is: **Why do so many teams have identical raw SOS values in the first place?**

---

## Current Iterative Algorithm

**Location**: `src/etl/v53e.py` lines 538-559

### How It Works (Simplified)

```python
# Step 1: Direct SOS (average opponent strength)
sos = avg(opponent_strengths)  # e.g., 0.50

# Step 2-4: Iterate 3 times with transitivity
for iteration in range(3):
    # Add 15% of "how strong did my opponents' opponents play"
    sos = 85% × direct_sos + 15% × avg(opponent_sos_values)
```

### Configuration
- **Iterations**: 3 (line 56)
- **Transitivity weight**: 15% (line 57)
- **Default for missing opponents**: 0.35 (UNRANKED_SOS_BASE)

---

## Critical Issues I Found

### Issue 1: **Missing Opponents in Iterations** ⚠️

**Line 547**:
```python
g_sos["opp_sos"] = g_sos["opp_id"].map(lambda o: opp_sos_map.get(o, cfg.UNRANKED_SOS_BASE))
```

**The Problem**:
- In each iteration, we look up opponent's SOS from `opp_sos_map`
- `opp_sos_map` only contains teams in `sos_curr` (line 546)
- `sos_curr` only contains teams that appear as `team_id` in filtered games
- **Missing opponents default to 0.35 in EVERY iteration!**

**Impact**:
- If Team A plays Team B, and B was filtered out:
  - Iteration 1: B's strength = 0.35 (from strength_map)
  - Iteration 2: B's SOS = 0.35 (default, not calculated!)
  - Iteration 3: B's SOS = 0.35 (still defaulting!)
- Transitivity doesn't work for filtered opponents!

**Example**:
```
Team A plays Team B (filtered out)
Team B plays strong teams X, Y, Z

WITHOUT fix:
- A's direct SOS = 0.35 (B defaults)
- Iteration 1: B's SOS = 0.35 (not calculated)
- A's transitive SOS = 85% × 0.35 + 15% × 0.35 = 0.35
- No improvement from transitivity!

WITH fix (estimating B's strength):
- A's direct SOS = 0.55 (B estimated from performance)
- Iteration 1: B's SOS = ??? (still defaults to 0.35!)
- A's transitive SOS = 85% × 0.55 + 15% × 0.35 = 0.52
- Slight improvement, but B's SOS still not accurate!
```

**My current fix (lines 459-509) only helps with initial strength, NOT with iterative SOS!**

---

### Issue 2: **Insufficient Iterations** ⚠️

**Current**: 3 iterations with 15% transitivity weight

**What this achieves**:
- Iteration 1: Incorporates 1-hop transitivity (opponent's strength)
- Iteration 2: Incorporates 2-hop transitivity (opponent's opponent's strength) at ~2.25% weight
- Iteration 3: Incorporates 3-hop transitivity at ~0.34% weight

**The Math**:
- Direct influence: Always 85%
- 1-hop influence: 15%
- 2-hop influence: 15% × 15% = 2.25%
- 3-hop influence: 15% × 15% × 15% = 0.34%

**Is this enough?**
- Depends on league structure
- In tightly connected leagues (everyone plays everyone): YES
- In regional leagues with divisions: MAYBE NOT
- Teams only influence nearby teams in the graph

---

### Issue 3: **Low Transitivity Weight** ⚠️

**Current**: 15% (lowered from 25% for "stability")

**Comment in code**: "Lowered from 0.25 for stability"

**Question**: Why was it lowered?
- Stability issues suggest oscillation or divergence
- But low weight means less differentiation between teams
- More teams cluster toward similar values

**Impact**:
If all my opponents have SOS between 0.45-0.55:
- My direct SOS = ~0.50
- Transitivity adds: 15% × (0.45 to 0.55) = 0.0675 to 0.0825
- My final SOS = 0.50 ± 0.03
- **Very narrow range!**

---

### Issue 4: **No Convergence Checking** ⚠️

**Current**: Always does exactly 3 iterations

**Better approach**: Iterate until convergence
```python
# Check if SOS values have stabilized
max_change = (new_sos - old_sos).abs().max()
if max_change < 0.001:
    break  # Converged!
```

**Why this matters**:
- 3 iterations might not be enough for complex league structures
- Or might be too many (wasted computation) for simple structures
- No way to know if we've reached accurate values

---

### Issue 5: **Clipping Loses Information** ⚠️

**Line 558**:
```python
merged["sos"] = merged["sos"].clip(0.0, 1.0)
```

**The Problem**:
- If calculated SOS > 1.0, it gets clipped to 1.0
- If calculated SOS < 0.0, it gets clipped to 0.0
- Multiple teams might get clipped to same value!

**When this happens**:
- Team plays very strong opponents (strength > 1.0)
- Calculated SOS = 1.2 → clipped to 1.0
- Another team: SOS = 1.3 → clipped to 1.0
- **Both teams now have identical SOS = 1.0!**

**Is clipping necessary?**
- Depends on whether abs_strength can exceed 1.0
- Line 454: `team["abs_strength"] = (team["power_presos"] / team["anchor"]).clip(0.0, 1.5)`
- Yes! Strength can be up to 1.5!
- So SOS could theoretically be > 1.0

---

## The Core Question: Are Identical SOS Values CORRECT?

### Scenario A: **Mathematically Correct Ties**

If Team A and Team B:
- Play the exact same opponents
- With the same weights
- And those opponents have identical strength/SOS

Then A and B **should** have identical SOS! This is accurate!

### Scenario B: **Artificial Ties from Defaults**

If Team A and Team B:
- Play different opponents
- But those opponents were all filtered out
- And all default to 0.35

Then A and B have identical SOS, but it's **not accurate**!

---

## Root Cause Analysis

I think you're seeing **Scenario B** because:

1. **MAX_GAMES_FOR_RANK=30 filters out many teams**
   - These teams appear as opponents but not as ranked teams
   - They don't get SOS calculated in iterations
   - They all default to 0.35

2. **My fix only partially helps**
   - Estimates initial strength (line 459-509)
   - But doesn't estimate SOS for iterations (line 547)
   - Transitivity still uses defaults!

3. **Low transitivity weight (15%) doesn't spread values enough**
   - Even with different opponents, values cluster
   - 3 iterations with 15% = limited differentiation

4. **Clipping at [0, 1] creates more ties**
   - Teams with strong opponents all clip to 1.0
   - Teams with weak opponents all clip to 0.0

---

## Proposed Fixes (In Order of Impact)

### Fix 1: **Estimate SOS for Missing Opponents in Iterations** (HIGHEST IMPACT)

**Problem**: Line 547 defaults missing opponents to 0.35

**Solution**: Extend my current fix to also estimate SOS during iterations

```python
# In each iteration, if opponent not in opp_sos_map:
# 1. Check if we estimated their strength earlier (in strength_map)
# 2. Use that as proxy for their SOS
# 3. Or calculate their SOS from their games (if available)

for _ in range(max(0, cfg.SOS_ITERATIONS - 1)):
    opp_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))

    # NEW: Add missing opponents with estimated SOS
    missing_opps = set(g_sos["opp_id"].unique()) - set(opp_sos_map.keys())
    for opp in missing_opps:
        # Estimate based on strength (teams with higher strength likely have higher SOS)
        estimated_sos = strength_map.get(opp, cfg.UNRANKED_SOS_BASE)
        opp_sos_map[opp] = estimated_sos

    g_sos["opp_sos"] = g_sos["opp_id"].map(lambda o: opp_sos_map.get(o, cfg.UNRANKED_SOS_BASE))
    # ... rest of iteration
```

---

### Fix 2: **Increase Iterations Until Convergence** (MEDIUM IMPACT)

**Problem**: 3 iterations might not be enough

**Solution**: Iterate until SOS values stabilize

```python
max_iterations = 10
convergence_threshold = 0.001

for iteration in range(max_iterations):
    old_sos = sos_curr.copy()

    # ... do iteration calculation ...

    # Check convergence
    merged_with_old = merged.merge(old_sos, on="team_id", suffixes=("_new", "_old"))
    max_change = (merged_with_old["sos_new"] - merged_with_old["sos_old"]).abs().max()

    if max_change < convergence_threshold:
        logger.info(f"SOS converged after {iteration+1} iterations (max change: {max_change:.6f})")
        break
```

---

### Fix 3: **Increase Transitivity Weight** (LOW-MEDIUM IMPACT)

**Problem**: 15% is very conservative

**Solution**: Try 25-30% for better differentiation

```python
SOS_TRANSITIVITY_LAMBDA: float = 0.25  # Increased from 0.15
```

**Risk**: Might cause instability (need to test)

---

### Fix 4: **Remove or Widen Clipping** (LOW IMPACT)

**Problem**: Clipping to [0, 1] creates artificial ties

**Solution**: Either remove clipping or widen range

```python
# Option A: Widen range
merged["sos"] = merged["sos"].clip(0.0, 1.5)  # Match abs_strength max

# Option B: Remove clipping (let values be natural)
# merged["sos"] = merged["sos"]  # No clipping

# Option C: Soft clipping (sigmoid)
merged["sos"] = 1.5 / (1 + np.exp(-merged["sos"]))  # Maps (-∞, ∞) to (0, 1.5)
```

---

## What I Recommend

**Implement in this order**:

1. ✅ **Keep my current fix** (lines 459-509) for initial strength estimation

2. **NEW: Extend it to iterations** (Fix 1)
   - Estimate SOS for missing opponents in each iteration
   - Use their estimated strength as proxy for SOS
   - This will make the biggest difference

3. **Add convergence checking** (Fix 2)
   - Iterate until SOS stabilizes
   - Log how many iterations it takes
   - This tells us if 3 is enough

4. **Experiment with transitivity weight** (Fix 3)
   - Try 20%, 25%, 30%
   - See if values spread out more
   - Watch for instability

5. **Test with real data**
   - Run rankings, check SOS distribution
   - Count how many teams still have identical values
   - Compare before/after

---

## Want Me to Implement This?

I can create:
1. Extended fix for iterative SOS estimation
2. Convergence-based iteration loop
3. Configurable transitivity weight
4. Test script to compare results

**Should I proceed?** And which fixes do you want me to prioritize?
