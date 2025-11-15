# SOS Normalization Analysis

## Current Normalization Method: PERCENTILE

**Location**: `src/etl/v53e.py` line 138-141, 564

**How it works**:
```python
def _percentile_norm(x: pd.Series) -> pd.Series:
    return x.rank(method="average", pct=True).astype(float)
```

**Applied to SOS** at line 564:
```python
team = _normalize_by_cohort(team, "sos", "sos_norm", cfg.NORM_MODE)
# Where NORM_MODE = "percentile"
```

This converts raw SOS values to percentile ranks **within each age/gender cohort**.

---

## Why This Causes Identical Values

### Example Scenario

**U12 Boys teams (100 teams total)**:
- 60 teams have raw SOS = 0.50 (played similar opponents)
- 20 teams have raw SOS = 0.45
- 20 teams have raw SOS = 0.55

**After percentile normalization**:

```python
x.rank(method="average", pct=True)
```

- All 60 teams with SOS=0.50 get the **same normalized value**
- The `method="average"` assigns tied values the average of their ranks
- Example: If they occupy ranks 21-80, they all get rank (21+80)/2 = 50.5
- Converted to percentile: 50.5/100 = 0.505

**Result**: 60% of teams have **identical normalized SOS** = 0.505

---

## The Root Problem

**Percentile ranking preserves ties!**

If many teams have similar raw SOS values (which is natural when they play in the same league/region), they will ALL get identical normalized SOS values.

This is especially problematic because:
1. **League structure** creates natural clustering (teams in same division play similar opponents)
2. **Limited opponent diversity** in regional leagues (everyone plays everyone)
3. **Percentile normalization doesn't "spread out" these clusters**

---

## Alternative Normalization Methods

### Option 1: **Min-Max Scaling** (Linear)

```python
def _minmax_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
    min_val = x.min()
    max_val = x.max()
    if max_val == min_val:
        return pd.Series([0.5] * len(x), index=x.index)
    return (x - min_val) / (max_val - min_val)
```

**How it works**:
- Scales values linearly between 0 and 1
- Preserves the exact proportional differences between values

**Example**:
- Raw SOS: [0.45, 0.50, 0.50, 0.50, 0.55]
- Normalized: [0.0, 0.5, 0.5, 0.5, 1.0]

**Pros**:
- ✅ Simple and interpretable
- ✅ Preserves exact relationships between values
- ✅ No rank ties (only value ties)

**Cons**:
- ❌ Still preserves identical values (0.50 → 0.5)
- ❌ Sensitive to outliers (one extreme value affects all others)
- ❌ Different cohorts have different scales

---

### Option 2: **Add Small Random Noise** (Tie-Breaking)

```python
def _percentile_with_jitter(x: pd.Series, noise_scale: float = 0.0001) -> pd.Series:
    if len(x) == 0:
        return x
    # Add tiny random noise to break ties
    np.random.seed(42)  # For reproducibility
    jittered = x + np.random.uniform(-noise_scale, noise_scale, len(x))
    return jittered.rank(method="min", pct=True).astype(float)
```

**How it works**:
- Adds tiny random noise (±0.0001) to break exact ties
- Then applies percentile ranking
- Noise is small enough not to change real differences

**Example**:
- Raw SOS: [0.50, 0.50, 0.50]
- After jitter: [0.50001, 0.49999, 0.50002]
- Normalized: [0.67, 0.33, 1.0] (different values!)

**Pros**:
- ✅ Breaks ties while preserving overall ranking
- ✅ Small noise doesn't affect real differences
- ✅ Each team gets unique value

**Cons**:
- ❌ Introduces randomness (may be controversial)
- ❌ Teams with truly identical SOS get different rankings
- ❌ Not deterministic (unless seeded)

---

### Option 3: **Robust Scaling** (Median/IQR)

```python
def _robust_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
    q25 = x.quantile(0.25)
    q75 = x.quantile(0.75)
    median = x.median()
    iqr = q75 - q25

    if iqr == 0:
        return pd.Series([0.5] * len(x), index=x.index)

    # Scale by IQR, center on median
    normalized = (x - median) / iqr
    # Squash to [0, 1] using sigmoid
    return 1 / (1 + np.exp(-normalized))
```

**How it works**:
- Centers on median instead of mean
- Scales by IQR (interquartile range) instead of std dev
- Less sensitive to outliers than z-score

**Example**:
- Raw SOS: [0.30, 0.50, 0.50, 0.50, 0.70]
- Median: 0.50, IQR: 0.20
- Normalized: [0.27, 0.50, 0.50, 0.50, 0.73]

**Pros**:
- ✅ Robust to outliers
- ✅ Preserves center of distribution
- ✅ Works well with skewed data

**Cons**:
- ❌ Still preserves identical values
- ❌ More complex to understand
- ❌ Doesn't solve the tie problem

---

### Option 4: **Gaussian Rank Normalization** (Force Normal Distribution)

```python
def _gaussian_rank_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
    from scipy.stats import rankdata, norm

    # Get ranks
    ranks = rankdata(x, method='average')
    # Convert to uniform [0, 1]
    uniform = ranks / (len(x) + 1)
    # Transform to normal distribution
    normalized = norm.ppf(uniform)
    # Squash back to [0, 1] for consistency
    return 1 / (1 + np.exp(-normalized))
```

**How it works**:
- Ranks values, converts to uniform distribution
- Transforms to Gaussian (normal) distribution
- Forces data into bell curve shape

**Example**:
- Forces even distribution across 0-1 range
- Breaks up clusters by spreading them out

**Pros**:
- ✅ Breaks up clusters of similar values
- ✅ Creates more even distribution
- ✅ Reduces impact of value clustering

**Cons**:
- ❌ Complex and harder to explain
- ❌ Distorts true differences
- ❌ May over-separate truly similar teams

---

### Option 5: **Hash-Based Tie Breaking** (Deterministic)

```python
def _percentile_with_hash_tiebreak(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x

    # Create unique tie-breaker based on team_id
    # This requires access to team_id in the normalization function
    df = pd.DataFrame({'value': x, 'index': x.index})

    # Use index as deterministic tie-breaker
    df['tiebreak'] = df['index'].apply(lambda idx: hash(str(idx)) % 10000 / 10000.0)
    df['value_with_tiebreak'] = df['value'] + df['tiebreak'] * 0.00001

    return df['value_with_tiebreak'].rank(method="min", pct=True).astype(float)
```

**How it works**:
- Uses team_id hash as deterministic tie-breaker
- Adds tiny offset based on team_id (always same for same team)
- Breaks ties consistently across rankings

**Pros**:
- ✅ Deterministic (same input = same output)
- ✅ Breaks ties without randomness
- ✅ Stable across multiple ranking runs

**Cons**:
- ❌ Tie-breaking order based on hash (arbitrary)
- ❌ Slightly more complex
- ❌ Teams with identical SOS still ranked differently

---

### Option 6: **Quantile Bucketing** (Discrete Tiers)

```python
def _quantile_bucket_norm(x: pd.Series, n_buckets: int = 20) -> pd.Series:
    if len(x) == 0:
        return x

    # Create buckets based on quantiles
    buckets = pd.qcut(x, q=n_buckets, labels=False, duplicates='drop')
    # Normalize buckets to [0, 1]
    max_bucket = buckets.max()
    if max_bucket == 0:
        return pd.Series([0.5] * len(x), index=x.index)

    return buckets / max_bucket
```

**How it works**:
- Divides teams into N equal-sized buckets (e.g., 20 buckets = 5% per bucket)
- All teams in same bucket get same normalized value
- Explicitly groups similar teams together

**Example** (10 buckets):
- Top 10% get 1.0
- Next 10% get 0.9
- etc.

**Pros**:
- ✅ Explicit tiers (easier to understand)
- ✅ Reduces noise from tiny differences
- ✅ Clear grouping of similar teams

**Cons**:
- ❌ Creates more identical values (by design)
- ❌ Arbitrary bucket boundaries
- ❌ Doesn't solve your problem (makes it worse!)

---

## Recommended Solutions

### **Best Option: Add Tiny Jitter + Use Secondary Metrics**

```python
def _percentile_norm_with_tiebreak(x: pd.Series, secondary: pd.Series = None) -> pd.Series:
    """
    Percentile normalization with optional secondary tie-breaker

    Args:
        x: Primary values (e.g., SOS)
        secondary: Optional secondary metric for tie-breaking (e.g., win percentage)
    """
    if len(x) == 0:
        return x

    # If secondary metric provided, use it for tie-breaking
    if secondary is not None:
        # Combine: primary + tiny fraction of secondary
        combined = x + secondary * 0.00001
        return combined.rank(method="min", pct=True).astype(float)
    else:
        # Use deterministic jitter based on index
        jitter = x.index.map(lambda idx: hash(str(idx)) % 10000 / 10000000.0)
        combined = x + jitter
        return combined.rank(method="min", pct=True).astype(float)
```

**Why this is best**:
- ✅ Preserves overall ranking structure
- ✅ Breaks ties using meaningful secondary metric (win%, offense, etc.)
- ✅ Deterministic and stable
- ✅ Minimal change to current system

---

### **Alternative: Min-Max Scaling (If you want linear)**

```python
def _minmax_norm_with_spread(x: pd.Series, min_spread: float = 0.01) -> pd.Series:
    """
    Min-max normalization with guaranteed minimum spread
    """
    if len(x) == 0:
        return x

    min_val = x.min()
    max_val = x.max()

    if max_val - min_val < min_spread:
        # If range is too small, center at 0.5 and add small spread
        center = (max_val + min_val) / 2
        spread = min_spread / 2
        return 0.5 + (x - center) / spread / 2

    return (x - min_val) / (max_val - min_val)
```

---

## What I Recommend

**Two-step approach**:

1. **Keep percentile normalization** (it's working as designed)

2. **Add tie-breaking using secondary metrics**:
   - Use win percentage as tie-breaker
   - Or use average goal differential
   - Or use offensive power
   - This makes tie-breaking **meaningful** rather than arbitrary

**Implementation**:
```python
# At line 564, instead of:
team = _normalize_by_cohort(team, "sos", "sos_norm", cfg.NORM_MODE)

# Do:
team = _normalize_by_cohort_with_tiebreak(
    team,
    primary_col="sos",
    tiebreak_col="off_norm",  # or "def_norm" or custom win%
    out_col="sos_norm",
    mode=cfg.NORM_MODE
)
```

This way:
- Teams with truly identical SOS + identical offense get same rank (fair)
- Teams with identical SOS but different offense get different ranks (meaningful)
- No random noise or arbitrary tie-breaking

---

## Next Steps

Which approach do you prefer?

1. **Tie-breaking with secondary metrics** (most meaningful)
2. **Min-max scaling** (simpler, linear)
3. **Hash-based deterministic jitter** (breaks all ties)
4. **Something else?**

I can implement any of these - just let me know which makes most sense for your use case!
