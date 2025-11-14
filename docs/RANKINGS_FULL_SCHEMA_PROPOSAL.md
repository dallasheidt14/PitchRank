# Rankings Full Schema Proposal

## Overview

This document outlines all fields produced by the v53E ranking engine and Layer 13 ML adjustment that are **not currently stored** in the `current_rankings` table. This serves as a reference for implementing a comprehensive `rankings_full` table in the future.

## Current State

The `current_rankings` table currently stores only a subset of ranking data:
- `team_id`, `national_rank`, `national_power_score`, `global_power_score`
- `games_played`, `wins`, `losses`, `draws`, `win_percentage`
- `strength_of_schedule`, `state_rank`
- `last_game_date`, `last_calculated`

## Missing Fields from v53E Engine

### Team Identity & Status
- `age` - Age group as numeric string (e.g., "10", "11") - derived from `age_group`
- `status` - Team status: "Active", "Inactive", or "Not Enough Ranked Games"
- `last_game` - Timestamp of last game (currently only `last_game_date` stored)

### Offense/Defense Metrics
- `off_raw` - Raw offensive strength (goals for per game, weighted)
- `sad_raw` - Raw defensive weakness (goals against per game, weighted)
- `off_shrunk` - Bayesian-shrunk offensive strength (within cohort)
- `sad_shrunk` - Bayesian-shrunk defensive weakness (within cohort)
- `def_shrunk` - Defensive strength (inverse of SAD with ridge regularization)
- `off_norm` - Normalized offensive strength (percentile or z-score within cohort)
- `def_norm` - Normalized defensive strength (percentile or z-score within cohort)

### Strength of Schedule Variants
- `sos` - Raw SOS value (direct opponent strength, iteratively refined)
- `sos_norm` - Normalized SOS (percentile or z-score within cohort)
- Note: Currently only `strength_of_schedule` is stored (likely maps to `sos`)

### Power Score Layers
- `power_presos` - Power score before SOS (OFF + DEF only)
- `anchor` - Cross-age anchor value for normalization
- `abs_strength` - Absolute strength (power_presos / anchor, clipped to [0, 1.5])
- `powerscore_core` - Core power score (OFF + DEF + SOS, before provisional)
- `provisional_mult` - Provisional multiplier (0.85 if < 5 games, 0.95 if < 15 games, 1.0 otherwise)
- `powerscore_adj` - Adjusted power score (core * provisional_mult * anchor scaling)
- Note: Currently only `national_power_score` is stored (likely maps to `powerscore_adj` or `powerscore_ml`)

### Performance Metrics
- `perf_raw` - Raw performance delta (actual vs expected goal margin, recency-weighted)
- `perf_centered` - Centered performance metric (~[-0.5, +0.5] within cohort)

### Ranking Fields
- `rank_in_cohort` - Rank within age_group + gender cohort (using powerscore_adj)
- Note: Currently only `national_rank` is stored (may differ if using ML-adjusted scores)

## Missing Fields from Layer 13 (ML Adjustment)

### ML Residuals
- `ml_overperf` - Raw ML residual per team (goal units, recency-weighted)
  - Range: clipped to [-residual_clip_goals, +residual_clip_goals] (default: ±3.5)
- `ml_norm` - Cohort-normalized ML residual (~[-0.5, +0.5])
  - Normalized within (age, gender) cohort using percentile or z-score

### ML-Adjusted Power Scores
- `powerscore_ml` - Final ML-adjusted power score
  - Formula: `powerscore_adj + alpha * ml_norm` (default alpha: 0.12)
  - Clipped to [0.0, 1.0]
- `rank_in_cohort_ml` - Rank within cohort using ML-adjusted score

### ML Model Metadata (Potential Future Fields)
- `ml_confidence` - Model confidence score (not currently computed)
- `ml_residual` - Alternative name for ml_overperf (not currently used)
- `ml_normalized_delta` - Alternative name for ml_norm (not currently used)

## Missing Fields from Calculator (Rank Change Tracking)

- `rank_change_7d` - Rank change over 7 days (computed but not stored)
- `rank_change_30d` - Rank change over 30 days (computed but not stored)

## Proposed rankings_full Table Schema

```sql
CREATE TABLE rankings_full (
    team_id UUID REFERENCES teams(team_id_master) PRIMARY KEY,
    
    -- Team identity (from teams table, denormalized for performance)
    age_group TEXT NOT NULL,
    gender TEXT NOT NULL,
    state_code TEXT,
    
    -- Status & tracking
    status TEXT, -- 'Active', 'Inactive', 'Not Enough Ranked Games'
    last_game TIMESTAMPTZ,
    last_calculated TIMESTAMPTZ DEFAULT NOW(),
    
    -- Game statistics
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    goals_for INTEGER DEFAULT 0,
    goals_against INTEGER DEFAULT 0,
    win_percentage FLOAT,
    
    -- Offense/Defense metrics
    off_raw FLOAT,
    sad_raw FLOAT,
    off_shrunk FLOAT,
    sad_shrunk FLOAT,
    def_shrunk FLOAT,
    off_norm FLOAT,
    def_norm FLOAT,
    
    -- Strength of Schedule
    sos FLOAT, -- Raw SOS
    sos_norm FLOAT, -- Normalized SOS
    strength_of_schedule FLOAT, -- Alias for sos (backward compatibility)
    
    -- Power Score layers
    power_presos FLOAT, -- Before SOS
    anchor FLOAT, -- Cross-age anchor
    abs_strength FLOAT, -- Absolute strength
    powerscore_core FLOAT, -- Core (OFF + DEF + SOS)
    provisional_mult FLOAT, -- Provisional multiplier
    powerscore_adj FLOAT, -- Adjusted (after provisional + anchor)
    
    -- Performance metrics
    perf_raw FLOAT,
    perf_centered FLOAT,
    
    -- ML Layer fields
    ml_overperf FLOAT, -- Raw ML residual
    ml_norm FLOAT, -- Normalized ML residual
    powerscore_ml FLOAT, -- ML-adjusted power score
    rank_in_cohort_ml INTEGER, -- Rank using ML score
    
    -- Ranking fields
    rank_in_cohort INTEGER, -- Rank using powerscore_adj
    national_rank INTEGER, -- Rank using power_score_final (computed in view)
    state_rank INTEGER, -- State-specific rank (computed in view)
    global_rank INTEGER, -- Global rank across all ages (computed in view)
    
    -- Rank change tracking
    rank_change_7d INTEGER,
    rank_change_30d INTEGER,
    
    -- Final power scores (for views)
    national_power_score FLOAT NOT NULL, -- Maps to powerscore_ml or powerscore_adj
    global_power_score FLOAT, -- Cross-age normalized (if computed)
    power_score_final FLOAT -- COALESCE(global_power_score, national_power_score)
);

-- Indexes for performance
CREATE INDEX idx_rankings_full_age_gender ON rankings_full(age_group, gender);
CREATE INDEX idx_rankings_full_state ON rankings_full(state_code) WHERE state_code IS NOT NULL;
CREATE INDEX idx_rankings_full_power_score ON rankings_full(power_score_final DESC);
CREATE INDEX idx_rankings_full_ml_score ON rankings_full(powerscore_ml DESC) WHERE powerscore_ml IS NOT NULL;
```

## Migration Strategy

### Phase 1: Create rankings_full Table ✅ COMPLETE
1. ✅ Create the `rankings_full` table with all fields - Migration: `20250120130000_create_rankings_full.sql`
2. ✅ Add indexes for performance
3. ✅ Set up RLS policies if needed (deferred to view-level RLS)

### Phase 2: Update Data Adapter ✅ COMPLETE
1. ✅ Added `v53e_to_rankings_full_format()` function in `src/rankings/data_adapter.py` to map all fields
2. ✅ Updated `save_rankings_to_supabase()` in `scripts/calculate_rankings.py` to use `rankings_full`
3. ✅ Ensured backward compatibility with `current_rankings` (saves to both tables by default)

### Phase 3: Update Views ✅ COMPLETE
1. ✅ Modified `rankings_view` to read from `rankings_full` with fallback to `current_rankings` - Migration: `20250120140000_update_views_for_rankings_full.sql`
2. ✅ Modified `state_rankings_view` accordingly
3. ✅ Ensured all computed fields (ranks, power_score_final) are calculated correctly with ML > global > adj > national fallback

### Phase 4: Data Migration ✅ READY
1. ✅ Created `scripts/backfill_rankings_full.py` to backfill `rankings_full` from existing `current_rankings` (with NULLs for missing fields)
2. ⏳ Run next rankings calculation to populate all fields (use `python scripts/calculate_rankings.py --ml`)
3. ⏳ Verify data integrity (manual step)

## Benefits of rankings_full Table

1. **Complete Data Preservation**: All v53E + Layer 13 outputs are stored
2. **Analytics**: Enable deep analysis of ranking components (OFF, DEF, SOS, ML adjustments)
3. **Debugging**: Easier to diagnose ranking issues with full field visibility
4. **Future Features**: Enable features like "why did my rank change?" with rank_change tracking
5. **Transparency**: Show users breakdown of their power score components

## Notes

- The `current_rankings` table can remain for backward compatibility
- Views can be updated to read from `rankings_full` with fallback to `current_rankings`
- The `power_score_final` field should use: `COALESCE(powerscore_ml, global_power_score, powerscore_adj)`
- All rank fields should be computed dynamically in views for accuracy

