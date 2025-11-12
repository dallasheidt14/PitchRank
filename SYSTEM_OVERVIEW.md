# PitchRank: Comprehensive Process & Flow Overview

## 🎯 System Purpose

PitchRank is a youth soccer team ranking system that:
- Processes game data from multiple providers (GotSport, TGS, US Club Soccer)
- Matches teams across different data sources using intelligent fuzzy matching
- Calculates team rankings using a sophisticated v53e algorithm with optional ML enhancement
- Maintains data integrity through validation, deduplication, and immutability

---

## 📊 Complete Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION PHASE                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  1. Master Team Import               │
        │  (import_teams_enhanced.py)          │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  • Read CSV with team metadata       │
        │  • Validate team data                │
        │  • Create teams in database          │
        │  • Create direct ID mappings          │
        │    (match_method='direct_id')        │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  2. Game History Import              │
        │  (import_games_enhanced.py)           │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  Enhanced ETL Pipeline               │
        │  (enhanced_pipeline.py)                │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                             │
        ▼                                             ▼
┌───────────────┐                          ┌───────────────┐
│ VALIDATION    │                          │ DEDUPLICATION │
│               │                          │               │
│ • Required    │                          │ • Perspective │
│   fields      │                          │   duplicates  │
│ • Date format │                          │ • game_uid    │
│ • Scores      │                          │   matching    │
│ • Data types  │                          │ • Immutability│
└───────────────┘                          └───────────────┘
        │                                             │
        └─────────────────────┬─────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  TEAM MATCHING                       │
        │  (game_matcher.py)                    │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                             │
        ▼                                             ▼
┌───────────────┐                          ┌───────────────┐
│ Strategy 1:   │                          │ Strategy 2:   │
│ Direct ID     │                          │ Alias Map     │
│ Match         │                          │ Lookup        │
│               │                          │               │
│ • Check cache │                          │ • Historical  │
│   (if loaded) │                          │   mappings    │
│ • Check       │                          │ • Any approved│
│   team_alias_ │                          │   alias entry │
│   map         │                          │               │
│ • Fastest     │                          │ • Fast        │
│ • 100% conf   │                          │ • 90-100% conf│
└───────────────┘                          └───────────────┘
        │                                             │
        └─────────────────────┬─────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  Strategy 3: Fuzzy Matching          │
        │                                       │
        │  • Team name similarity (65%)         │
        │  • Club name similarity (25%)         │
        │  • Age group match (5%)                │
        │  • Location match (5%)                │
        │                                       │
        │  Thresholds:                          │
        │  • ≥0.90: Auto-approve               │
        │  • 0.75-0.90: Review queue            │
        │  • <0.75: Reject                      │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  GAME INSERTION                      │
        │                                       │
        │  • Batch insert (2000 games/batch)    │
        │  • Retry logic (5 attempts)          │
        │  • SSL error handling                 │
        │  • Adaptive batch sizing              │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  METRICS TRACKING                     │
        │  (build_logs table)                   │
        │                                       │
        │  • Games processed/accepted            │
        │  • Matches created                    │
        │  • Errors logged                      │
        │  • Processing time                    │
        └─────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    RANKINGS CALCULATION PHASE                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  Fetch Games from Database            │
        │  (data_adapter.py)                    │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  Convert to v53e Format               │
        │                                       │
        │  • Supabase → v53e                   │
        │  • Perspective-based (2 rows/game)    │
        │  • Age group conversion (u10 → 10)    │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  v53e Rankings Engine                │
        │  (v53e.py)                           │
        │                                       │
        │  Layer 1: Window filter (365 days)   │
        │  Layer 2: Outlier guard + goal cap   │
        │  Layer 3: Recency weighting          │
        │  Layer 4: Defense ridge              │
        │  Layer 5: Adaptive K                 │
        │  Layer 6: Performance layer          │
        │  Layer 7: Bayesian shrinkage         │
        │  Layer 8: Strength of Schedule       │
        │  Layer 10: Core PowerScore           │
        │  Layer 11: Provisional + ranking     │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  ML Layer (Optional)                 │
        │  (layer13_predictive_adjustment.py)   │
        │                                       │
        │  • XGBoost/RandomForest prediction    │
        │  • Residual calculation               │
        │  • Recency-weighted residuals        │
        │  • Normalize within cohorts           │
        │  • Blend: powerscore_ml =            │
        │    powerscore_adj + α * ml_norm      │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  Convert Back to Supabase Format      │
        │                                       │
        │  • v53e → current_rankings            │
        │  • Map PowerScore columns              │
        │  • Calculate national_rank             │
        └─────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  Save to current_rankings Table      │
        └─────────────────────────────────────┘
```

---

## 🔍 Detailed Process Logic

### Phase 1: Team Import (`import_teams_enhanced.py`)

**Purpose:** Establish master team list with direct ID mappings

**Process:**
1. **CSV Reading**
   - Reads CSV file with team metadata
   - Maps columns: `team_id`, `team_name`, `age_group`, `gender`, `club_name`, `state_code`

2. **Validation** (`EnhancedDataValidator`)
   - Required fields: `team_name`, `age_group`, `gender`
   - Age group format: `u10`, `u11`, etc.
   - Gender: `Male`, `Female`, `M`, `F`
   - Invalid teams → `quarantine_teams` table

3. **Team Creation**
   - Generate UUID for `team_id_master`
   - Insert into `teams` table with:
     - `provider_id` (UUID from providers table)
     - `provider_team_id` (from CSV)
     - Team metadata

4. **Direct ID Mapping**
   - Create entry in `team_alias_map`:
     - `match_method='direct_id'`
     - `match_confidence=1.0`
     - `review_status='approved'`
   - This enables fast matching during game import

**Output:**
- Teams in `teams` table
- Direct ID mappings in `team_alias_map`
- Invalid teams in `quarantine_teams`

---

### Phase 2: Game Import (`import_games_enhanced.py` → `enhanced_pipeline.py`)

**Purpose:** Import game history with validation, matching, and deduplication

#### Step 1: File Loading

**CSV Format (Perspective-Based):**
- Each game appears twice (once from each team's perspective)
- Format: `team_id`, `opponent_id`, `home_away`, `goals_for`, `goals_against`

**Streaming Mode:**
- Files >100MB automatically use streaming
- Processes line-by-line without loading entire file
- Batch size: 2000 games per batch

#### Step 2: Validation (`_validate_games`)

**Validation Rules:**
- Required fields: `game_date`, `team_id`, `opponent_id`, `goals_for`, `goals_against`
- Date format: `YYYY-MM-DD`
- Scores: Non-negative integers
- Invalid games → `quarantine_games` table

**Perspective Deduplication:**
```python
# Create game key (order-independent)
game_key = f"{provider}:{date}:{sorted_teams[0]}:{sorted_teams[1]}"

# First occurrence → transform to neutral format
# Second occurrence → skip (duplicate)
```

**Transformation:**
- Source: `team_id`, `opponent_id`, `home_away`, `goals_for`, `goals_against`
- Target: `home_team_id`, `away_team_id`, `home_score`, `away_score`

**Game UID Generation:**
```python
game_uid = f"{provider}:{date}:{sorted_team1}:{sorted_team2}"
# Deterministic, no scores included
```

#### Step 3: Duplicate Detection (`_check_duplicates`)

**Logic:**
- Query database for existing `game_uid` values
- Batch size: 2000 UIDs per query
- Skip games already in database (immutability)

**Why Immutability?**
- Prevents duplicate imports
- Safe to restart import (skips existing games)
- Data integrity guarantee

#### Step 4: Team Matching (`game_matcher.py`)

**Matching Strategy (Priority Order):**

**1. Direct ID Match** (Fastest - O(1))
```python
# Check alias cache first (if preloaded)
# Then check team_alias_map (canonical source)
team_alias_map WHERE provider_id = X 
  AND provider_team_id = Y 
  AND match_method = 'direct_id'
  AND review_status = 'approved'
# Returns: team_id_master with 100% confidence
# Note: Does NOT check teams table - team_alias_map is canonical
```

**2. Alias Map Lookup** (Fast - O(1))
```python
# Check any approved alias map entry (fallback)
team_alias_map WHERE provider_id = X 
  AND provider_team_id = Y 
  AND review_status = 'approved'
# Returns: team_id_master with stored confidence
```

**3. Fuzzy Matching** (Slower - O(n))
```python
# Query master teams by age_group + gender
teams WHERE age_group = X AND gender = Y

# For each candidate:
score = weighted_similarity(provider_team, candidate)

# Weighted scoring:
# - Team name: 65%
# - Club name: 25%
# - Age group: 5%
# - Location: 5%
```

**Fuzzy Matching Details:**

**Normalization:**
- Lowercase, remove punctuation
- Expand abbreviations: `FC` → `Football Club`, `SC` → `Soccer Club`
- Remove common suffixes

**Similarity Calculation:**
- Uses `SequenceMatcher` (difflib)
- Normalizes both strings before comparison
- Returns 0.0-1.0 similarity score

**Match Thresholds:**
- **≥0.90**: Auto-approve → Create alias with `match_method='fuzzy_auto'`
- **0.75-0.90**: Manual review → Insert into `team_match_review_queue` (NOT alias map)
- **<0.75**: Reject → No alias created, no review queue entry

**Match Status:**
- `matched`: Both teams matched (`home_team_master_id` AND `away_team_master_id`)
- `partial`: One team matched (only `home_team_master_id` OR `away_team_master_id`)
- `failed`: Neither team matched

#### Step 5: Game Insertion (`_bulk_insert_games`)

**Batch Processing:**
- Batch size: 2000 games (configurable)
- Insert using Supabase batch API
- `returning='minimal'` for performance

**Retry Logic:**
- **5 retries** for SSL/network errors (increased from 3)
- Exponential backoff with jitter
- Adaptive batch sizing:
  - Reduce batch size on repeated SSL errors
  - Gradually restore after successful inserts

**Error Handling:**
- **Duplicate key violations**: Skip (already in DB)
- **SSL errors**: Retry with backoff
- **NOT NULL violations**: Log and skip batch
- **Other errors**: Retry with backoff

**Adaptive Batch Sizing:**
```python
if ssl_error_count >= 3:
    batch_size = max(500, int(batch_size * 0.7))
    # Gradually restore after success
```

#### Step 6: Metrics Tracking (`_log_build_metrics`)

**Metrics Stored:**
- `games_processed`: Total games processed
- `games_accepted`: Successfully inserted
- `games_quarantined`: Invalid games
- `duplicates_found`: Already in database
- `duplicates_skipped`: Perspective duplicates
- `matched_games_count`: Both teams matched
- `partial_games_count`: One team matched
- `failed_games_count`: Neither team matched
- `teams_matched`: Total team matches
- `fuzzy_matches_auto`: Auto-approved fuzzy matches
- `fuzzy_matches_manual`: Pending review
- `processing_time_seconds`: Total time
- `errors`: Error list (max 100)

**Logging Frequency:**
- Every 50 batches (configurable)
- First batch always logged
- Reduces database write overhead

---

### Phase 3: Rankings Calculation (`calculate_rankings.py`)

#### Step 1: Data Fetching (`fetch_games_for_rankings`)

**Query:**
```sql
SELECT id, game_uid, game_date, home_team_master_id, away_team_master_id,
       home_score, away_score, provider_id
FROM games
WHERE game_date >= (today - lookback_days)
LIMIT 1000000
```

**Team Metadata Fetching:**
- Batch size: 100 team IDs per query (UUIDs are long)
- Fetches: `team_id_master`, `age_group`, `gender`
- Creates lookup maps for fast access

#### Step 2: Format Conversion (`supabase_to_v53e_format`)

**Supabase Format:**
- One row per game
- Columns: `home_team_master_id`, `away_team_master_id`, `home_score`, `away_score`

**v53e Format (Perspective-Based):**
- Two rows per game (home and away perspectives)
- Columns: `game_id`, `date`, `team_id`, `opp_id`, `age`, `gender`, `gf`, `ga`

**Age Group Conversion:**
- `u10` → `10`
- `u11` → `11`
- etc.

#### Step 3: v53e Rankings Engine (`compute_rankings`)

**Layer 1: Window Filter**
- Filter games within `WINDOW_DAYS` (default: 365)
- Remove games older than cutoff date

**Layer 2: Outlier Guard**
- Cap goal difference at `GOAL_DIFF_CAP` (default: 6)
- Remove outliers using z-score (`OUTLIER_GUARD_ZSCORE`: 2.5)
- Limit games per team (`MAX_GAMES_FOR_RANK`: 30)

**Layer 3: Recency Weighting**
- Weight recent games more heavily
- `RECENT_K`: 15 most recent games
- `RECENT_SHARE`: 65% weight for recent games
- Tail dampening for games 26-30 days old

**Layer 4: Defense Ridge**
- Ridge regression for defensive strength
- `RIDGE_GA`: 0.25 regularization parameter

**Layer 5: Adaptive K**
- Adjust K-factor based on team strength
- Stronger teams: higher K (more volatile)
- Weaker teams: lower K (more stable)

**Layer 6: Performance Layer**
- Analyze goal margins vs expected
- Reward overperformance
- Decay rate: 0.08 per game

**Layer 7: Bayesian Shrinkage**
- Shrink toward mean for teams with few games
- `SHRINK_TAU`: 8.0 shrinkage parameter

**Layer 8: Strength of Schedule (SOS)**
- Iterative transitivity calculation
- 3 iterations default
- Accounts for opponent strength

**Layer 10: Core PowerScore**
- Combine offense, defense, and SOS:
  ```
  PowerScore = (OFF_WEIGHT * offense) + 
               (DEF_WEIGHT * defense) + 
               (SOS_WEIGHT * sos)
  ```
- Default weights: 25% offense, 25% defense, 50% SOS

**Layer 11: Provisional & Ranking**
- Teams with <5 games: Provisional multiplier
- Rank teams within cohorts (age, gender)

#### Step 4: ML Layer (Optional) (`apply_predictive_adjustment`)

**Process:**
1. **Feature Engineering**
   - Team PowerScore (from v53e)
   - Opponent PowerScore
   - Home/away indicator
   - Recency weighting

2. **Model Training**
   - XGBoost or RandomForest
   - Predicts goal margin
   - Trained on historical games

3. **Residual Calculation**
   - `residual = actual_margin - predicted_margin`
   - Recency-weighted residuals
   - Clip outliers at ±3.5 goals

4. **Normalization**
   - Normalize residuals within cohorts (age, gender)
   - Mode: `percentile` or `zscore`

5. **Blending**
   ```
   powerscore_ml = powerscore_adj + (alpha * ml_normalized_residual)
   ```
   - Default `alpha`: 0.12 (12% ML adjustment)

#### Step 5: Save Rankings (`save_rankings_to_supabase`)

**Conversion:**
- `powerscore_ml` → `national_power_score`
- `rank_in_cohort_ml` → `national_rank`
- Calculate `win_percentage`

**Upsert Logic:**
- Delete all existing rankings
- Insert new rankings in batches (1000 per batch)

---

## 🗄️ Database Schema Overview

### Core Tables

**`teams`**
- `team_id_master` (UUID, PK)
- `team_name`, `club_name`, `age_group`, `gender`, `state_code`
- `provider_id`, `provider_team_id`

**`games`**
- `game_uid` (TEXT, PK) - Deterministic: `provider:date:team1:team2`
- `home_team_master_id`, `away_team_master_id` (UUIDs)
- `home_provider_id`, `away_provider_id` (TEXT)
- `home_score`, `away_score` (INTEGER)
- `game_date`, `provider_id`
- `is_immutable` (BOOLEAN) - Prevents updates

**`team_alias_map`**
- Maps provider teams to master teams
- `match_method`: `direct_id`, `fuzzy_auto`, `fuzzy_review`
- `match_confidence`: 0.0-1.0
- `review_status`: `pending`, `approved`, `rejected`

**`current_rankings`**
- `team_id` (UUID, PK)
- `national_power_score` (FLOAT)
- `national_rank` (INTEGER)
- `games_played`, `wins`, `losses`, `draws`
- `win_percentage`, `strength_of_schedule`

**`build_logs`**
- `build_id`, `stage`, `provider_id`
- `metrics` (JSONB) - Detailed import metrics
- `started_at`, `completed_at`

**`quarantine_games`** / **`quarantine_teams`**
- Invalid data for review
- `reason_code`, `error_details`

---

## 🔧 Key Configuration

### Matching Configuration (`config/settings.py`)

```python
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.75,        # Minimum to consider
    'auto_approve_threshold': 0.9,  # Auto-approve matches
    'review_threshold': 0.75,      # Queue for review
    'weights': {
        'team': 0.65,               # Team name similarity
        'club': 0.25,                # Club name similarity
        'age': 0.05,                 # Age group match
        'location': 0.05             # Location match
    },
    'club_boost_identical': 0.05    # Boost for identical clubs
}
```

### Ranking Configuration

```python
RANKING_CONFIG = {
    'window_days': 365,             # Rolling window
    'max_games': 30,                # Max games per team
    'recent_k': 15,                 # Recent games count
    'recent_share': 0.65,           # Weight for recent games
    'off_weight': 0.25,             # Offense weight
    'def_weight': 0.25,             # Defense weight
    'sos_weight': 0.50,             # Strength of Schedule weight
    'min_games_for_ranking': 5      # Minimum games required
}
```

### ML Configuration

```python
ML_CONFIG = {
    'enabled': True,
    'alpha': 0.12,                  # Blend weight (5-20% recommended)
    'recency_decay_lambda': 0.06,   # Recency decay rate
    'min_team_games_for_residual': 6, # Min games for ML adjustment
    'residual_clip_goals': 3.5,     # Outlier guardrail
    'norm_mode': 'percentile'       # Normalization mode
}
```

---

## 🚀 Performance Optimizations

### Import Optimizations

1. **Streaming**: Processes large files without loading into memory
2. **Batch Processing**: 2000 games per batch
3. **Concurrency**: 4 parallel batches (configurable)
4. **Duplicate Checking**: Batch queries (2000 UIDs per query)
5. **Retry Logic**: Exponential backoff with jitter
6. **Adaptive Batch Sizing**: Reduces batch size on SSL errors
7. **Metrics Logging**: Every 50 batches (reduces DB writes)
8. **Alias Map Caching**: Preloads all approved aliases at import start for instant lookups (eliminates millions of tiny SELECT queries)

### Rankings Optimizations

1. **Caching**: Cache v53e results by game ID hash
2. **Batch Team Fetching**: 100 team IDs per query
3. **Parallel Cohort Processing**: Process age/gender cohorts concurrently
4. **Data Adapter**: Efficient format conversion

---

## 📈 Current Status

**Database:**
- ✅ 16,649 games imported
- ✅ 14,031 fully matched (84.3%)
- ✅ 2,618 partially matched (15.7%)
- ✅ 0 unmatched (0.0%)

**Rankings:**
- ✅ 543 teams ranked
- ✅ v53e engine working
- ✅ ML layer available (optional)

**Next Steps:**
1. Continue game import (if more data available)
2. Review pending matches (if any)
3. Calculate rankings with ML layer
4. Set up weekly automation

---

## 🔍 Key Design Decisions

### Why Perspective-Based Games?

- **Source Data**: Each game appears twice (once per team)
- **Deduplication**: Sort team IDs to create consistent game key
- **Rankings**: v53e needs perspective-based format (each team's view)

### Why Deterministic Game UIDs?

- **No Scores**: UID doesn't include scores (scores can be corrected)
- **Order-Independent**: Sorted team IDs ensure consistency
- **Immutability**: Same game always has same UID

### Why Three-Tier Matching?

1. **Direct ID**: Fastest (O(1) lookup from `team_alias_map`, or cache hit)
2. **Alias Map**: Fast (O(1) lookup, historical mappings from any method)
3. **Fuzzy**: Slower (O(n) search) but handles name variations
4. **All tiers use `team_alias_map`**: Keeps `teams` table as immutable master records

### Why ML Layer is Optional?

- **v53e**: Deterministic, reproducible rankings
- **ML**: Adds predictive adjustment but requires training data
- **Flexibility**: Can run with or without ML

---

## 📝 Summary

PitchRank is a sophisticated system that:

1. **Imports teams** with direct ID mappings for fast matching
2. **Imports games** with validation, deduplication, and intelligent team matching
3. **Calculates rankings** using a multi-layer v53e algorithm with optional ML enhancement
4. **Maintains data integrity** through immutability, validation, and quarantine systems
5. **Optimizes performance** through streaming, batching, caching, and adaptive error handling

The system is designed to handle millions of games while maintaining accuracy and performance.

