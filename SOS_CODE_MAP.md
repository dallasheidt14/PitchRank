# Comprehensive SOS (Strength of Schedule) Code Location Map

## Overview
The PitchRank system implements a sophisticated **3-pass iterative SOS calculation** as part of the v53E ranking engine. SOS represents the average strength of opponents a team has faced, weighted by game importance and recency.

---

## 1. CONFIGURATION & PARAMETERS

### Main Configuration
**File:** `/home/user/PitchRank/src/etl/v53e.py` (Lines 14-76)
- **V53EConfig dataclass** defines all SOS parameters:
  - `UNRANKED_SOS_BASE = 0.35` (Line 54) - Default strength for unranked opponents
  - `SOS_REPEAT_CAP = 4` (Line 55) - Max times same opponent counted
  - `SOS_ITERATIONS = 3` (Line 56) - Number of transitivity iterations
  - `SOS_TRANSITIVITY_LAMBDA = 0.20` (Line 57) - Weight: 80% direct, 20% transitive
  - `OFF_WEIGHT = 0.25` (Line 60) - Offense component weight
  - `DEF_WEIGHT = 0.25` (Line 61) - Defense component weight
  - `SOS_WEIGHT = 0.50` (Line 62) - **SOS has 50% weight in PowerScore**

### Environment Configuration
**File:** `/home/user/PitchRank/config/settings.py` (Lines 116-125)
- Environment variable overrides for all SOS parameters
- Default values: `UNRANKED_SOS_BASE=0.35`, `SOS_REPEAT_CAP=4`, `SOS_ITERATIONS=3`, `SOS_TRANSITIVITY_LAMBDA=0.20`, `SOS_WEIGHT=0.50`

---

## 2. SOS CALCULATION ENGINE

### Core SOS Calculation Logic
**File:** `/home/user/PitchRank/src/etl/v53e.py` (Lines 468-530)

#### **Layer 8: Direct SOS Calculation (Lines 468-490)**
```
Line 471: g["w_sos"] = g["w_game"] * g["k_adapt"]  # Weighted strength
Line 473-475: Repeat cap logic - limit each opponent to top 4 games by weight
Line 477: g_sos["opp_strength"] = map opponent team IDs to abs_strength values
Line 486-490: Calculate weighted average of opponent strengths (sos_direct)
```

#### **Iterative Transitivity (Lines 500-524)**
The SOS is refined through 2 additional iterations (total 3 passes):
```
Iteration 1 (Line 490): sos = sos_direct (direct opponent strength)
Iteration 2-3 (Lines 501-524): Blend direct with transitivity
  - Formula: sos = (1 - lambda) * sos_direct + lambda * sos_trans
  - Lambda = 0.20 (so 80% direct, 20% transitive)
  - Clipped to [0.0, 1.0] range (Line 514)
```

### SOS Normalization (Layer 9)
**File:** `/home/user/PitchRank/src/etl/v53e.py` (Line 529)
```python
team = _normalize_by_cohort(team, "sos", "sos_norm", cfg.NORM_MODE)
```
- Normalizes raw SOS within each (age_group, gender) cohort
- Uses percentile ranking or z-score transformation
- Output: `sos_norm` (0.0 to 1.0) - normalized within cohort

### PowerScore Calculation (Layer 10)
**File:** `/home/user/PitchRank/src/etl/v53e.py` (Lines 571-576)
```python
team["powerscore_core"] = (
    cfg.OFF_WEIGHT * team["off_norm"]           # 25%
    + cfg.DEF_WEIGHT * team["def_norm"]         # 25%
    + cfg.SOS_WEIGHT * team["sos_norm"]         # 50% ← SOS has highest weight!
    + team["perf_centered"] * cfg.PERFORMANCE_K
)
```
**SOS is a critical component - 50% of the PowerScore formula**

---

## 3. DATA STORAGE

### Rankings Table Structure
**File:** `/home/user/PitchRank/supabase/migrations/20250120130000_create_rankings_full.sql` (Lines 35-38)
```sql
CREATE TABLE rankings_full (
    -- Raw SOS value (0.0-1.0, iteratively refined)
    sos FLOAT,
    
    -- Normalized SOS (percentile/z-score within cohort)
    sos_norm FLOAT,
    
    -- Alias for backward compatibility
    strength_of_schedule FLOAT
);
```

### Current Rankings Table
**File:** `/home/user/PitchRank/supabase/migrations/20240101000000_initial_schema.sql`
- Also stores `strength_of_schedule` field (maps to raw SOS)

---

## 4. DATA ADAPTER & CONVERSION

### v53e Output to Database Format
**File:** `/home/user/PitchRank/src/rankings/data_adapter.py` (Lines 533-544)

**Function:** `v53e_to_rankings_full_format()`
```python
# Lines 534-535: Map SOS values
if 'sos' in rankings_df.columns:
    rankings_df['sos'] = rankings_df['sos'].astype(float)
    rankings_df['strength_of_schedule'] = rankings_df['sos']  # Alias

# Lines 541-544: Map normalized SOS
if 'sos_norm' in rankings_df.columns:
    rankings_df['sos_norm'] = rankings_df['sos_norm'].astype(float)
else:
    rankings_df['sos_norm'] = None
```

**Function:** `v53e_to_supabase_format()`
- Converts v53e output to current_rankings format (Lines 359-408)

---

## 5. RANKINGS CALCULATION & STORAGE

### Main Rankings Calculator
**File:** `/home/user/PitchRank/scripts/calculate_rankings.py`

#### Save to Database (Lines 44-300)
**Function:** `save_rankings_to_supabase()`
- Line 136-138: Maps SOS from teams_df to rankings
  ```python
  if 'sos' in teams_df.columns:
      sos_map = dict(zip(teams_df['team_id'].astype(str), teams_df['sos']))
      rankings_df['sos'] = rankings_df['team_id'].astype(str).map(sos_map)
  ```
- Lines 169-173: Saves SOS to strength_of_schedule field
  ```python
  if 'sos' in row and pd.notna(row.get('sos')):
      record['strength_of_schedule'] = float(row['sos'])
  ```

### Rankings Converter
**File:** `/home/user/PitchRank/src/rankings/calculator.py`
- Calls `compute_rankings()` from v53e which produces `sos` and `sos_norm` columns

---

## 6. DATABASE VIEWS

### Rankings View with SOS
**File:** `/home/user/PitchRank/supabase/migrations/20250120150000_add_sos_norm_to_views.sql`

#### Main Rankings View (Lines 16-81)
```sql
-- Line 50-52: Expose both SOS values
COALESCE(rf.strength_of_schedule, rf.sos, cr.strength_of_schedule) as strength_of_schedule,
COALESCE(rf.sos, cr.strength_of_schedule) as sos,  -- Raw SOS
rf.sos_norm as sos_norm,  -- Normalized SOS

-- Line 70-73: SOS ranking (using RANK() to handle ties)
RANK() OVER (
    PARTITION BY age_group, gender
    ORDER BY strength_of_schedule DESC NULLS LAST
) as national_sos_rank
```

#### State Rankings View (Lines 86-139)
```sql
-- Line 113-115: Pass through SOS values
rv.strength_of_schedule,
rv.sos,     -- Raw SOS
rv.sos_norm,  -- Normalized SOS

-- Line 130-133: State-level SOS ranking
RANK() OVER (
    PARTITION BY age_group, gender, state_code
    ORDER BY strength_of_schedule DESC NULLS LAST
) as state_sos_rank
```

---

## 7. FRONTEND DISPLAY & USAGE

### Type Definitions
**File:** `/home/user/PitchRank/frontend/types/RankingRow.ts` (Lines 7-51)
```typescript
export interface RankingRow {
  sos_norm: number;  // Line 16: Normalized SOS in display
  // ... deprecation warnings for old field names
}
```

**File:** `/home/user/PitchRank/frontend/lib/types.ts` (Lines 110)
```typescript
sos_norm: number | null;  // normalized 0–1 SOS index
```

### SOS Formatting Function
**File:** `/home/user/PitchRank/frontend/lib/utils.ts` (Lines 25-31)
```typescript
export function formatSOSIndex(sosNorm?: number | null): string {
  if (sosNorm == null) return "—";
  return (sosNorm * 100).toFixed(1);  // Convert to 0-100 scale for display
}
```

### Rankings Display Component
**File:** `/home/user/PitchRank/frontend/components/RankingsTable.tsx`
- Lines 68-69: Filter teams by SOS_norm existence
- Lines 112-114: Sort by sos_norm (normalized within cohort)
- Line 421: Display SOS using `formatSOSIndex(team.sos_norm)`

### Team Header Component
**File:** `/home/user/PitchRank/frontend/components/TeamHeader.tsx`
- Line 13: Import formatSOSIndex
- Line 62: Access sos_norm from team data
- Line 207: Display SOS using formatSOSIndex(teamRanking.sos_norm)

### API Functions
**File:** `/home/user/PitchRank/frontend/lib/api.ts`
- Line 98: Query includes `sos_norm` in rankings fetching
- Line 183: Map `sos_norm` from ranking data
- Line 231: Handle null cases for sos_norm

---

## 8. DOCUMENTATION

### SOS Fields Explanation
**File:** `/home/user/PitchRank/docs/SOS_FIELDS_EXPLANATION.md` (Complete guide - 288 lines)
- Lines 17-78: Explanation of raw `sos` calculation
- Lines 82-132: Explanation of normalized `sos_norm`
- Lines 136-155: Backward compatibility `strength_of_schedule` field
- Lines 158-206: SOS ranking fields (national_sos_rank, state_sos_rank)
- Lines 223-244: Which field to use for different purposes

### Rankings Schema Proposal
**File:** `/home/user/PitchRank/docs/RANKINGS_FULL_SCHEMA_PROPOSAL.md` (Lines 31-40)
- Field specifications for SOS variants
- Integration into power score formula

### SQL Queries Guide
**File:** `/home/user/PitchRank/docs/SQL_QUERIES_FOR_RANKINGS.md` (Lines 24-26, 92-95, etc.)
```sql
strength_of_schedule,  -- Alias for sos (backward compatibility)
sos,                   -- Raw SOS value (0.0-1.0)
sos_norm              -- Normalized SOS (percentile/z-score within cohort)
```

---

## 9. VALIDATION & TESTING

### SOS Validation Tests
**File:** `/home/user/PitchRank/tests/unit/test_sos_validation.py` (All lines)
- **TestSOSConfiguration** (Lines 10-78): Configuration validation
- **TestSOSValueRanges** (Lines 81-171): Output range validation
  - Tests `sos` is in [0.0, 1.0] range (Lines 102-120)
  - Tests `sos_norm` is in [0.0, 1.0] range (Lines 122-140)
  - Tests PowerScore uses `sos_norm`, not raw `sos` (Lines 142-169)
- **TestSOSTransitivity** (Lines 172-193): Transitivity calculation
- **TestSOSDocumentation** (Lines 194-219): Config matches documentation

### Configuration Validator
**File:** `/home/user/PitchRank/scripts/validate_sos_config.py` (All 225 lines)
- Lines 20-92: Validate V53EConfig
- Lines 95-119: Validate settings.py
- Lines 122-147: Validate documentation consistency
- Lines 150-182: Validate transitivity formula

### SOS Check Script
**File:** `/home/user/PitchRank/scripts/check_sos.py` (All 172 lines)
- Line 46: Check if SOS is calculated in rankings
- Line 63-89: Verify SOS columns and statistics
- Line 95-143: Check if SOS stored in database
- Line 148-168: Summary panel

### SOS Impact Verification
**File:** `/home/user/PitchRank/scripts/verify_sos_impact.py` (All 168 lines)
- Line 44-52: Display PowerScore formula weights (25% OFF, 25% DEF, 50% SOS)
- Lines 80-85: Calculate correlation between SOS and PowerScore
- Lines 131-152: Verify PowerScore formula includes SOS correctly

---

## 10. WORKFLOW & INTEGRATION

### Calculate Rankings Workflow
**File:** `/home/user/PitchRank/scripts/calculate_rankings.py`
1. Fetch games from Supabase
2. Call `compute_rankings_v53e_only()` → runs v53e engine including SOS calculation (Layer 8)
3. Convert output using `v53e_to_rankings_full_format()` → maps `sos` and `sos_norm`
4. Save to `rankings_full` table via `save_rankings_to_supabase()`
5. Save to `current_rankings` for backward compatibility

### GitHub Workflow
**File:** `/home/user/PitchRank/.github/workflows/calculate-rankings.yml`
- Triggers daily ranking calculations
- Executes `/scripts/calculate_rankings.py`
- Updates both rankings_full and current_rankings tables

---

## 11. KEY FORMULAS

### Raw SOS Calculation (Pass 1 - Direct)
```
sos_direct = weighted_average(opponent_strengths, weights=w_sos)

where:
  - opponent_strengths = abs_strength values of opponents
  - w_sos = w_game * k_adapt (recency × adaptive K)
  - Only top 4 games per opponent counted (SOS_REPEAT_CAP=4)
```

### Iterative Transitivity (Passes 2-3)
```
For each iteration:
  sos_trans = weighted_average(opponent_sos_values, weights=w_sos)
  sos = (1 - λ) * sos_direct + λ * sos_trans
  sos = clip(sos, 0.0, 1.0)

where:
  - λ = SOS_TRANSITIVITY_LAMBDA = 0.20
  - Blends: 80% direct, 20% transitive
```

### Normalized SOS
```
sos_norm = percentile_rank(sos, within_age_gender_cohort)
OR
sos_norm = sigmoid((sos - mean) / std)  # if using z-score mode

Result: 0.0 (softest schedule) to 1.0 (toughest schedule) within cohort
```

### PowerScore Formula
```
powerscore_core = (OFF_WEIGHT * off_norm) + 
                  (DEF_WEIGHT * def_norm) + 
                  (SOS_WEIGHT * sos_norm) +
                  (PERFORMANCE_K * perf_centered)

where:
  - OFF_WEIGHT = 0.25 (25%)
  - DEF_WEIGHT = 0.25 (25%)
  - SOS_WEIGHT = 0.50 (50%)  ← SOS dominates the formula
```

---

## 12. SUMMARY TABLE

| Component | File Location | Line Range | Purpose |
|-----------|--------------|-----------|---------|
| **Configuration** | `src/etl/v53e.py` | 14-76 | Define SOS parameters |
| | `config/settings.py` | 116-125 | Environment overrides |
| **Calculation** | `src/etl/v53e.py` | 468-530 | SOS engine (Layer 8-9) |
| **PowerScore** | `src/etl/v53e.py` | 571-576 | 50% SOS weight formula |
| **Data Convert** | `src/rankings/data_adapter.py` | 533-544 | Map to database format |
| **Storage** | `supabase/migrations/20250120130000` | 35-38 | rankings_full table |
| **Views** | `supabase/migrations/20250120150000` | 16-139 | Rankings views with SOS |
| **Frontend Types** | `frontend/types/RankingRow.ts` | 7-51 | TypeScript interface |
| **Display** | `frontend/lib/utils.ts` | 25-31 | formatSOSIndex() |
| **Components** | `frontend/components/RankingsTable.tsx` | 68-114 | Display & sort |
| **Documentation** | `docs/SOS_FIELDS_EXPLANATION.md` | 1-288 | Complete guide |
| **Tests** | `tests/unit/test_sos_validation.py` | 1-219 | Validation tests |
| **Validation** | `scripts/validate_sos_config.py` | 1-225 | Config validation |
| **Verification** | `scripts/verify_sos_impact.py` | 1-168 | Impact analysis |

---

## Key Takeaways

1. **SOS has 50% weight in PowerScore** - It's the most important ranking component
2. **3-pass iterative calculation** - Direct opponent strength + 2 iterations of transitivity
3. **Transitivity blending** - 80% direct, 20% transitive (λ=0.20)
4. **Repeat cap protection** - Each opponent counted max 4 times
5. **Normalized within cohort** - `sos_norm` is percentile within age/gender
6. **Two SOS fields** - `sos` (raw 0-1) vs `sos_norm` (normalized percentile)
7. **PowerScore formula** - 25% offense + 25% defense + 50% SOS
8. **Backward compatible** - `strength_of_schedule` field aliases `sos`
9. **Full ranking integration** - SOS drives both rankings and power scores
10. **Comprehensive validation** - Multiple scripts verify SOS correctness

