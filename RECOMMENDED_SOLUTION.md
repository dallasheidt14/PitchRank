# Recommended Solution: Secondary Metric Tie-Breaking

## Summary

**Problem**: Teams with identical SOS values all get the same normalized SOS score.

**Solution**: Use a secondary metric (like win percentage or offensive power) to break ties meaningfully.

**Result**: Teams with identical SOS but different performance get different normalized scores.

---

## How It Works

Instead of just ranking by SOS:
```
SOS = 0.50 → Rank 10.5 (tie)
SOS = 0.50 → Rank 10.5 (tie)
SOS = 0.50 → Rank 10.5 (tie)
```

We combine SOS with a tiny fraction of a secondary metric:
```
Combined = SOS + (win_pct × 0.00001)

Team A: SOS=0.50, Win%=0.60 → Combined=0.500006 → Rank 11
Team B: SOS=0.50, Win%=0.45 → Combined=0.5000045 → Rank 10
Team C: SOS=0.50, Win%=0.55 → Combined=0.5000055 → Rank 10.5
```

The secondary metric is scaled so tiny (× 0.00001) that it:
- ✅ Only affects ties (teams with identical SOS)
- ✅ Doesn't affect teams with different SOS
- ✅ Creates meaningful tie-breaking order

---

## Implementation Options

### Option A: Use Win Percentage (BEST)

**Pros**:
- Most meaningful: Better teams get better ranks
- Easy to explain to users
- Already reflects overall team quality

**How to calculate**:
```python
# Add win percentage calculation
team['wins'] = team['team_id'].map(
    lambda tid: len(g[(g['team_id'] == tid) & (g['gf'] > g['ga'])])
)
team['win_pct'] = team['wins'] / team['gp']
```

**Use for tie-breaking**:
```python
team = _normalize_with_tiebreak(team, "sos", "win_pct", "sos_norm", cfg.NORM_MODE)
```

---

### Option B: Use Offensive Power (off_norm)

**Pros**:
- Already calculated in the system
- No new code needed
- Rewards strong offensive teams

**Cons**:
- Less direct than win percentage
- May favor high-scoring teams unfairly

**Use for tie-breaking**:
```python
team = _normalize_with_tiebreak(team, "sos", "off_norm", "sos_norm", cfg.NORM_MODE)
```

---

### Option C: Use Goal Differential

**Pros**:
- Balanced (considers offense and defense)
- Common in sports rankings

**How to calculate**:
```python
team['total_gd'] = team['team_id'].map(
    lambda tid: g[g['team_id'] == tid]['gd'].sum()
)
team['avg_gd'] = team['total_gd'] / team['gp']
```

**Use for tie-breaking**:
```python
team = _normalize_with_tiebreak(team, "sos", "avg_gd", "sos_norm", cfg.NORM_MODE)
```

---

### Option D: Use Composite (Win% + Goal Diff)

**Pros**:
- Most comprehensive
- Harder to have exact ties

**How to calculate**:
```python
# Combine multiple metrics
team['tiebreak_score'] = (
    team['win_pct'] * 0.7 +
    team['avg_gd'] / 10.0 * 0.3  # Normalize GD to ~0-1 range
)
```

**Use for tie-breaking**:
```python
team = _normalize_with_tiebreak(team, "sos", "tiebreak_score", "sos_norm", cfg.NORM_MODE)
```

---

## Code Changes Required

### Step 1: Add new normalization function

**File**: `src/etl/v53e.py`

**Location**: After `_normalize_by_cohort` (around line 164)

```python
def _normalize_by_cohort_with_tiebreak(
    df: pd.DataFrame,
    value_col: str,
    tiebreak_col: str,
    out_col: str,
    mode: str,
    tiebreak_weight: float = 0.00001
) -> pd.DataFrame:
    """
    Normalize values within cohorts with secondary tie-breaking

    Args:
        df: DataFrame with teams
        value_col: Primary column to normalize (e.g., "sos")
        tiebreak_col: Secondary column for tie-breaking (e.g., "win_pct")
        out_col: Output column name (e.g., "sos_norm")
        mode: "percentile" or "zscore"
        tiebreak_weight: How much weight to give tie-breaker (default 0.00001)

    Returns:
        DataFrame with normalized values
    """
    parts = []
    for (age, gender), grp in df.groupby(["age", "gender"], dropna=False):
        # Combine primary value with tiny fraction of tie-breaker
        combined = grp[value_col] + grp[tiebreak_col] * tiebreak_weight

        # Normalize the combined values
        if mode == "zscore":
            normalized = _zscore_norm(combined)
        else:
            normalized = _percentile_norm(combined)

        sub = grp.copy()
        sub[out_col] = normalized
        parts.append(sub)

    return pd.concat(parts, axis=0)
```

---

### Step 2: Calculate win percentage (if using Option A)

**File**: `src/etl/v53e.py`

**Location**: After team aggregation (around line 290)

```python
# Calculate win percentage for tie-breaking
def count_wins(team_id):
    team_games = g[g['team_id'] == team_id]
    wins = len(team_games[team_games['gf'] > team_games['ga']])
    return wins

team['wins'] = team['team_id'].apply(count_wins)
team['win_pct'] = team['wins'] / team['gp']
# Handle teams with 0 games
team['win_pct'] = team['win_pct'].fillna(0.0)
```

---

### Step 3: Use new function for SOS normalization

**File**: `src/etl/v53e.py`

**Location**: Line 564 (current SOS normalization)

**BEFORE**:
```python
team = _normalize_by_cohort(team, "sos", "sos_norm", cfg.NORM_MODE)
```

**AFTER** (Option A - Win%):
```python
team = _normalize_by_cohort_with_tiebreak(
    team,
    value_col="sos",
    tiebreak_col="win_pct",
    out_col="sos_norm",
    mode=cfg.NORM_MODE
)
```

**AFTER** (Option B - Offensive Power):
```python
team = _normalize_by_cohort_with_tiebreak(
    team,
    value_col="sos",
    tiebreak_col="off_norm",
    out_col="sos_norm",
    mode=cfg.NORM_MODE
)
```

---

### Step 4: Add configuration parameter (optional)

**File**: `src/etl/v53e.py`

**Location**: In `V53EConfig` class (around line 23)

```python
@dataclass
class V53EConfig:
    # ... existing config ...

    # SOS tie-breaking
    SOS_TIEBREAK_METRIC: str = "win_pct"  # or "off_norm", "avg_gd", etc.
    SOS_TIEBREAK_WEIGHT: float = 0.00001  # Weight for tie-breaker
```

---

## Testing

Before deploying, test with:

```python
python demo_normalization_methods.py
```

This shows you exactly how many teams will get unique values with each method.

---

## Expected Results

**Before** (Current):
- 100 teams in U12 Boys
- 40 teams have SOS = 0.50 → All get normalized SOS = 0.574
- Users see "40 teams with identical SOS scores"

**After** (With win% tie-breaking):
- Same 100 teams
- 40 teams have raw SOS = 0.50
- But each has different win% → Each gets unique normalized SOS
- Normalized values: 0.560, 0.562, 0.565, ... 0.588
- Users see "No teams with identical SOS scores"

---

## My Recommendation

**Use Option A (Win Percentage)**

1. Add win% calculation after line 290
2. Add `_normalize_by_cohort_with_tiebreak()` function after line 164
3. Replace line 564 to use new function with win% tie-breaking

This gives you:
- ✅ Meaningful tie-breaking (better teams rank higher)
- ✅ No identical SOS values
- ✅ Deterministic (reproducible)
- ✅ Easy to explain to users

**Want me to implement this?** Just give me the go-ahead and I'll make the changes!
