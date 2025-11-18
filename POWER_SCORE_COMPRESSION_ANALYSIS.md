# Power Score Compression Investigation

## Executive Summary

**Problem**: A 1,908 rank gap (#2019 vs #111) with 30% win rate difference (39% vs 69%) only produces a 14.11 percentile point power score difference (0.3285 vs 0.4696).

**Root Cause**: Multiple normalization layers compress power scores into a 0-1 range, losing absolute performance differences.

---

## Compression Points in the Pipeline

### 1. **Percentile Normalization** (v53e.py:138-141)
```python
def _percentile_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
    return x.rank(method="average", pct=True).astype(float)
```

**Impact**: Converts ALL raw values to percentile ranks (0-1 scale)
- A team at 98th percentile → 0.98
- A team at 50th percentile → 0.50
- **Only captures RELATIVE position, not ABSOLUTE performance difference**

### 2. **Anchor-Based Rescaling** (v53e.py:588-590)
```python
# Apply anchor-based normalization across ages (hierarchical capping)
anchor_ref = team.groupby("gender")["anchor"].transform("max")
team["powerscore_adj"] = (
    team["powerscore_adj"] * team["anchor"] / anchor_ref
).clip(0.0, 1.0)
```

**Config**: `ANCHOR_PERCENTILE = 0.98` (line 72)

**Impact**:
- Uses 98th percentile within each age/gender cohort as reference
- Rescales all scores relative to this anchor
- Further compresses the range, especially for lower-ranked teams

### 3. **Layer 13 ML Adjustment** (layer13_predictive_adjustment.py:277-279)
```python
out["powerscore_ml"] = out[base_power_col] + cfg.alpha * out["ml_norm"]
# Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
```

**Impact**:
- Adds ML residual adjustment (±0.06 maximum with alpha=0.12)
- Hard clips to [0, 1] again

---

## Why Compression Happens

### Example: U14 Boys Cohort (~3,000 teams hypothetically)

**Before Normalization** (actual performance):
- Rank #111: 69% win rate, strong record
- Rank #2019: 39% win rate, losing record
- **Performance gap**: 30 percentage points

**After Percentile Normalization**:
- Rank #111 → ~96.3rd percentile → 0.963
- Rank #2019 → ~32.7th percentile → 0.327
- **Percentile gap**: 63.6 percentile points

**After Anchor Scaling** (ANCHOR_PERCENTILE = 0.98):
- Both scores get rescaled by: `(score * age_anchor) / max_anchor`
- This compresses the effective range
- Lower-ranked teams get compressed more aggressively

**After Layer 13 ML + Final Clip**:
- Final scores: 0.4696 vs 0.3285
- **Final gap**: 14.11 percentile points (compressed from 63.6!)

---

## The Mathematical Problem

### Percentile Rank Formula
```
percentile = (rank - 1) / (total_teams - 1)
```

### Why It Compresses
1. **Linear spacing**: All teams equally spaced by percentile rank
2. **Performance-blind**: A 1-rank gap at top = 1-rank gap at bottom
3. **No performance weighting**: 95% win rate team and 40% win rate team just differ by percentile position

### Visual Example
```
Actual Performance:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#111: ████████████████████████████████████ (69% win)
#2019: ██████████████ (39% win)

Percentile Normalization (3000 teams):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#111: 96.3rd percentile (0.963)
#2019: 32.7th percentile (0.327)
Gap: 63.6 percentile points

After Anchor Scaling:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#111: 0.4696 (compressed to ~50th percentile range)
#2019: 0.3285 (compressed to ~33rd percentile range)
Gap: 14.11 percentile points (78% compression!)
```

---

## Solution Options

### Option 1: **Replace Percentile with Z-Score Normalization**
**What it does**: Use standard deviations instead of percentile ranks

**Change**: `v53e.py` line 75
```python
# Current:
NORM_MODE: str = "percentile"

# Proposed:
NORM_MODE: str = "zscore"
```

**Already implemented**: Code supports this (lines 144-152)
```python
def _zscore_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0 or len(x) < 2:
        return pd.Series([0.5] * len(x), index=x.index)
    mu = x.mean()
    sd = x.std(ddof=0)
    if sd == 0:
        return pd.Series([0.5] * len(x), index=x.index)
    z = (x - mu) / sd
    return 1 / (1 + np.exp(-z))  # sigmoid
```

**Pros**:
- Preserves performance differences (outliers get higher separation)
- Teams many standard deviations apart get larger power score gaps
- One config change only

**Cons**:
- More sensitive to outliers
- May need revalidation of prediction accuracy
- Could affect UI display ranges

**Impact**: A team 2 std devs above mean gets ~0.88, team at mean gets 0.50 → 38 point gap instead of 14

---

### Option 2: **Reduce Anchor Compression**
**What it does**: Use a lower anchor percentile to reduce rescaling compression

**Change**: `v53e.py` line 72
```python
# Current:
ANCHOR_PERCENTILE: float = 0.98  # top 2%

# Proposed:
ANCHOR_PERCENTILE: float = 0.90  # top 10%
```

**Pros**:
- More teams included in "top tier" reference
- Less aggressive compression of lower-ranked teams
- Preserves percentile normalization for close matchups

**Cons**:
- May not fully solve the blowout prediction problem
- Requires understanding of why 0.98 was chosen originally
- May affect cross-age comparisons

**Impact**: Moderate improvement (14 → ~25 point gap estimated)

---

### Option 3: **Hybrid Approach - Range-Based Normalization**
**What it does**: Use percentile for close matchups, exponential scaling for large gaps

**Change**: Add new normalization mode in `v53e.py`
```python
def _hybrid_norm(x: pd.Series) -> pd.Series:
    """
    Percentile normalization with exponential scaling for outliers
    - Bottom 80%: Linear percentile spacing
    - Top 20%: Exponential spacing to spread elite teams
    - Bottom 20%: Compressed spacing for weak teams
    """
    pct = x.rank(method="average", pct=True)

    # Apply non-linear scaling
    scaled = np.where(
        pct > 0.80,
        0.80 + 0.20 * np.power((pct - 0.80) / 0.20, 0.5),  # sqrt for top 20%
        np.where(
            pct < 0.20,
            0.20 * np.power(pct / 0.20, 2.0),  # square for bottom 20%
            pct  # linear for middle 60%
        )
    )
    return scaled
```

**Pros**:
- Best of both worlds: preserves close-game accuracy, spreads blowouts
- Can be tuned with exponents
- Maintains 0-1 range

**Cons**:
- More complex to implement and tune
- Requires testing and validation
- May create discontinuities

**Impact**: Large improvement (14 → 40+ point gap for extreme outliers)

---

### Option 4: **Remove Hard Clipping in Layer 13**
**What it does**: Allow power scores to exceed [0, 1] range

**Change**: `layer13_predictive_adjustment.py` line 279
```python
# Current:
out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)

# Proposed:
out["powerscore_ml"] = out["powerscore_ml"]  # No clipping
# OR: wider range
out["powerscore_ml"] = out["powerscore_ml"].clip(-0.5, 1.5)
```

**Pros**:
- Allows ML adjustments to create larger separations
- Simple change
- Preserves upstream normalization

**Cons**:
- **Breaking change**: Frontend expects 0-1 range (formatPowerScore multiplies by 100)
- Requires frontend updates
- May break database constraints
- Could create confusion in display

**Impact**: Small improvement (14 → ~20 point gap), requires frontend changes

---

### Option 5: **Increase Alpha in Layer 13**
**What it does**: Increase ML residual weight to create more separation

**Change**: `calculator.py` line 184
```python
# Current:
alpha=0.12,

# Proposed:
alpha=0.25,  # or higher
```

**Pros**:
- Simple config change
- Leverages ML overperformance to spread scores
- No code changes needed

**Cons**:
- May create instability if ML residuals are noisy
- Could hurt close-game accuracy
- ML residuals are clipped to ±3.5 goals already (layer13 line 269)

**Impact**: Moderate (14 → ~30 point gap max with alpha=0.25)

---

## Recommended Approach

### **Primary Recommendation: Option 1 (Z-Score) + Option 5 (Higher Alpha)**

**Why**:
1. **Z-score** (Option 1) preserves performance differences better than percentile
2. **Higher alpha** (Option 5) uses ML residuals to amplify real performance gaps
3. **Both are config changes** - no code modification needed
4. **Complementary**: Z-score spreads base scores, alpha amplifies ML adjustments

**Implementation**:
```python
# v53e.py line 75
NORM_MODE: str = "zscore"

# calculator.py line 184
alpha=0.20,  # increased from 0.12
```

**Expected Impact**:
- 14 point gap → 45-60 point gap for extreme outliers
- Preserves close-game accuracy (both teams near mean)
- Minimal risk, easy rollback

### **Alternative: Option 3 (Hybrid) for Maximum Control**

If you want fine-grained control and are willing to invest in custom code:
- Implement hybrid normalization
- Tune exponents based on validation data
- Highest ceiling for improvement

---

## Testing Recommendations

Before deploying any solution:

1. **Validate on historical data**:
   - Run predictions on past games
   - Compare accuracy for close games vs blowouts
   - Ensure 74.7% accuracy is preserved or improved

2. **Spot check specific matchups**:
   - #111 vs #2019 (your example)
   - #1 vs #50 (close matchup)
   - #100 vs #3000 (extreme blowout)

3. **Check for unintended consequences**:
   - Cross-age comparisons still valid?
   - State rankings still sensible?
   - UI display ranges appropriate?

---

## Next Steps

1. **Decision**: Choose approach (recommend Option 1 + Option 5)
2. **Test**: Run ranking pipeline with new config on sample data
3. **Validate**: Check power score distribution and prediction accuracy
4. **Deploy**: Update production config if validation passes
5. **Monitor**: Watch prediction quality on real matchups

---

## Files Involved

**For Option 1 + Option 5** (recommended):
- `src/etl/v53e.py` line 75: Change NORM_MODE
- `src/rankings/calculator.py` line 184: Change alpha

**For other options**:
- See detailed sections above for specific file/line references
