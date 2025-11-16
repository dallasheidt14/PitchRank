# SOS (Strength of Schedule) Fields Explanation

This document explains all SOS-related fields in the rankings system, how they're calculated, and what they represent.

## Overview

The v53E ranking engine calculates **two different SOS values**:
1. **`sos`** - Raw SOS value (0.0 to 1.0)
2. **`sos_norm`** - Normalized SOS value (percentile/z-score within cohort)

Additionally, there's:
3. **`strength_of_schedule`** - Alias field for backward compatibility
4. **`national_sos_rank`** / **`state_sos_rank`** - Rankings based on SOS values

---

## 1. `sos` - Raw Strength of Schedule

### What It Is
The **raw SOS value** represents the average strength of opponents a team has faced, weighted by game importance and recency.

### How It's Calculated (v53E Layer 8)

The calculation happens in multiple steps:

#### Step 1: Direct Opponent Strength
```python
# For each game, get the opponent's absolute strength
opp_strength = opponent.abs_strength  # From power_presos/anchor calculation

# Weight each game by:
# - w_game (recency weight)
# - k_adapt (adaptive K based on strength gap)
w_sos = w_game * k_adapt

# Calculate weighted average of opponent strengths
sos_direct = weighted_average(opp_strength, weights=w_sos)
```

#### Step 2: Repeat Cap (Limit Opponent Appearances)
- Only count the **top 4 games** against each unique opponent (by weight)
- This prevents teams from inflating SOS by playing weak teams many times
- Config: `SOS_REPEAT_CAP = 4`

#### Step 3: Iterative Transitivity (3 iterations)
The SOS is refined through transitivity - if Team A plays Team B, and Team B has high SOS, that should boost Team A's SOS:

```python
# Iteration 1: Direct opponent strength
sos = sos_direct

# Iterations 2-3: Add transitivity component
for iteration in range(2, 4):
    opp_sos = opponent.sos  # Use opponent's SOS from previous iteration
    sos_trans = weighted_average(opp_sos, weights=w_sos)
    
    # Blend direct and transitive (80% direct, 20% transitive)
    sos = (1 - SOS_TRANSITIVITY_LAMBDA) * sos_direct + SOS_TRANSITIVITY_LAMBDA * sos_trans
    sos = sos.clip(0.0, 1.0)  # Ensure in valid range
```

**Configuration:**
- `SOS_ITERATIONS = 3` (total iterations)
- `SOS_TRANSITIVITY_LAMBDA = 0.20` (20% weight on transitivity)
- `UNRANKED_SOS_BASE = 0.35` (default for unranked opponents)

### Value Range
- **0.0 to 1.0** (clipped)
- **1.0** = Played only the strongest opponents
- **0.0** = Played only the weakest opponents
- **0.35** = Default for unranked opponents

### Example
If a team plays:
- 10 games against teams with abs_strength = 0.9 (strong)
- 5 games against teams with abs_strength = 0.3 (weak)

Their raw SOS would be weighted toward 0.9, giving them a high `sos` value (close to 1.0).

---

## 2. `sos_norm` - Normalized Strength of Schedule

### What It Is
The **normalized SOS** converts the raw `sos` value into a percentile or z-score **within the same age group and gender cohort**.

### How It's Calculated (v53E Layer 9)

```python
# For each (age_group, gender) cohort:
# 1. Get all teams' raw sos values
# 2. Normalize using percentile or z-score method

if NORM_MODE == "percentile":
    # Percentile ranking: 0.0 = worst, 1.0 = best
    sos_norm = percentile_rank(sos, within_cohort)
    # Example: If team has 90th percentile SOS, sos_norm = 0.90

elif NORM_MODE == "zscore":
    # Z-score normalization, then sigmoid to [0, 1]
    z = (sos - mean(sos)) / std(sos)
    sos_norm = 1 / (1 + exp(-z))  # Sigmoid transform
```

**Configuration:**
- `NORM_MODE = "percentile"` (default) or `"zscore"`

### Why Normalize?

**Problem with raw `sos`:**
- In u12 Male, the strongest teams might have `sos = 0.95`
- In u17 Female, the strongest teams might have `sos = 0.88`
- Raw values aren't comparable across cohorts

**Solution with `sos_norm`:**
- In u12 Male, top teams have `sos_norm = 0.99` (99th percentile)
- In u17 Female, top teams have `sos_norm = 0.99` (99th percentile)
- Now values are comparable - both represent "top 1% SOS in their cohort"

### Value Range
- **0.0 to 1.0** (percentile) or sigmoid-transformed z-score
- **1.0** = Highest SOS in the cohort
- **0.0** = Lowest SOS in the cohort
- **0.5** = Median SOS in the cohort

### Example
If in u12 Male:
- Team A: `sos = 0.95`, `sos_norm = 0.99` (top 1%)
- Team B: `sos = 0.88`, `sos_norm = 0.75` (75th percentile)
- Team C: `sos = 0.50`, `sos_norm = 0.25` (25th percentile)

Even though Team B has `sos = 0.88` (which seems high), their `sos_norm = 0.75` shows they're only in the 75th percentile for their cohort.

---

## 3. `strength_of_schedule` - Backward Compatibility Alias

### What It Is
An **alias field** that maps to `sos` for backward compatibility with the old `current_rankings` table.

### How It's Set
```sql
-- In rankings_full table:
strength_of_schedule = sos  -- Direct copy

-- In views:
strength_of_schedule = COALESCE(rf.strength_of_schedule, rf.sos, cr.strength_of_schedule)
```

### Why It Exists
- The original `current_rankings` table had a `strength_of_schedule` field
- It stored the raw SOS value
- We keep this alias so existing queries don't break
- **It's the same as `sos`** - just a different name

---

## 4. `national_sos_rank` / `state_sos_rank` - SOS Rankings

### What It Is
The **rank** of a team based on their SOS value within their cohort.

### How It's Calculated (In Views)

```sql
-- National SOS Rank
RANK() OVER (
    PARTITION BY age_group, gender
    ORDER BY strength_of_schedule DESC NULLS LAST
) as national_sos_rank

-- State SOS Rank
RANK() OVER (
    PARTITION BY age_group, gender, state_code
    ORDER BY strength_of_schedule DESC NULLS LAST
) as state_sos_rank
```

### Ranking Logic

**Current Implementation (FIXED):**
- Uses `RANK()` which handles ties properly
- Teams with the same SOS value get the same rank
- Next rank skips (e.g., if 3 teams tie for rank 1, next team is rank 4)

**Previous Implementation (BROKEN):**
- Used `ROW_NUMBER()` which doesn't handle ties
- Teams with same SOS got arbitrary sequential ranks (1, 2, 3, 4...)
- This caused the issue you saw: teams with `sos = 1.0` getting ranks like 4, 1197, 236

### Example

**Scenario:** 5 teams in u12 Male, all with `sos = 1.0`:

| Team | sos | national_sos_rank (RANK) | national_sos_rank (ROW_NUMBER - WRONG) |
|------|-----|--------------------------|----------------------------------------|
| A    | 1.0 | 1                        | 1                                       |
| B    | 1.0 | 1                        | 2                                       |
| C    | 1.0 | 1                        | 3                                       |
| D    | 1.0 | 1                        | 4                                       |
| E    | 1.0 | 1                        | 5                                       |
| F    | 0.9 | 6                        | 6                                       |

With `RANK()`: All 5 teams tied for rank 1 (correct)
With `ROW_NUMBER()`: Teams get ranks 1-5 arbitrarily (wrong)

---

## Field Relationships

```
Raw Data (v53e output)
  ↓
sos (0.0-1.0, raw opponent strength)
  ↓
sos_norm (0.0-1.0, normalized within cohort)
  ↓
strength_of_schedule (alias for sos, backward compatibility)
  ↓
national_sos_rank (RANK() based on strength_of_schedule)
```

## Which Field Should You Use?

### For Displaying SOS to Users
- **Use `strength_of_schedule`** or **`sos`** - Shows the raw value (0.0-1.0)
- More intuitive: "0.95 SOS" is easier to understand than "0.88 normalized"

### For Comparing Across Cohorts
- **Use `sos_norm`** - Normalized values are comparable
- Example: "This team has 90th percentile SOS" works across all age groups

### For Ranking Teams by SOS
- **Use `national_sos_rank`** or **`state_sos_rank`** - Already calculated ranks
- Shows "This team has the 5th toughest schedule in u12 Male"

### For Power Score Calculation
- **v53E uses `sos_norm`** in the power score formula:
  ```
  powerscore_core = (OFF_WEIGHT * off_norm) + 
                    (DEF_WEIGHT * def_norm) + 
                    (SOS_WEIGHT * sos_norm)
  ```
- This ensures SOS contribution is comparable across cohorts

---

## The Problem You Found

### Issue
Teams with `sos = 1.0` were getting wildly different `national_sos_rank` values (4, 1197, 236, etc.)

### Root Cause
The view was using `ROW_NUMBER()` instead of `RANK()`:
- `ROW_NUMBER()` assigns sequential numbers even when values are equal
- When many teams have `sos = 1.0`, they should all get rank 1, but `ROW_NUMBER()` gave them 1, 2, 3, 4...
- The arbitrary ordering within the window function caused the scattered ranks

### Why Many Teams Have `sos = 1.0`
This is actually **normal** - many top teams play only other top teams, so they all hit the maximum SOS value of 1.0. The normalization (`sos_norm`) then differentiates them.

### Fix
Changed from `ROW_NUMBER()` to `RANK()`:
- Teams with same SOS now get the same rank
- Next rank properly skips (if 3 teams tie for rank 1, next is rank 4)

---

## Summary Table

| Field | Type | Range | Purpose | Used In |
|-------|------|-------|---------|---------|
| `sos` | Raw value | 0.0-1.0 | Direct opponent strength (iterative) | Power score calculation (via sos_norm) |
| `sos_norm` | Normalized | 0.0-1.0 | Percentile/z-score within cohort | Power score calculation |
| `strength_of_schedule` | Alias | 0.0-1.0 | Backward compatibility (same as sos) | Display, ranking |
| `national_sos_rank` | Rank | 1+ | Rank by SOS within cohort | Display, sorting |
| `state_sos_rank` | Rank | 1+ | Rank by SOS within state cohort | Display, sorting |

---

## References

- **v53E Layer 8**: SOS calculation (`src/etl/v53e.py` lines 468-512)
- **v53E Layer 9**: Normalization (`src/etl/v53e.py` line 512)
- **View Definition**: `supabase/migrations/20250120140000_update_views_for_rankings_full.sql`
- **Schema**: `supabase/migrations/20250120130000_create_rankings_full.sql`

