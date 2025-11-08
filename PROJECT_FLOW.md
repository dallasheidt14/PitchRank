# PitchRank Project Flow

Complete workflow documentation for the PitchRank youth soccer rankings system.

## 📊 Overview

PitchRank processes game data from multiple providers (GotSport, TGS, US Club Soccer) to calculate team rankings and strength of schedule metrics. The system uses a sophisticated v53e rankings engine with an optional ML predictive adjustment layer (Layer 13) for enhanced accuracy.

## 🔄 Complete Data Flow

### Phase 1: Data Collection & Import ✅ COMPLETE

#### 1.1 Master Team List Import ✅ DONE

**Script:** `scripts/import_teams_enhanced.py`

**Purpose:** Import master team list from CSV files with team metadata

**Process:**
1. Read CSV file with team information (team_name, club_name, age_group, gender, state, etc.)
2. Validate team data (required fields, valid age groups, gender codes)
3. Create team records in `teams` table
4. Create direct ID mappings in `team_alias_map` with `match_method='direct_id'`
5. Batch insert teams (default: 500 per batch)

**Example:**
```bash
python scripts/import_teams_enhanced.py data/master/all_teams_master.csv gotsport
```

**Output:**
- Teams created in `teams` table
- Direct ID mappings in `team_alias_map` table
- Team validation errors in `quarantine_teams` (if any)

**Status:** ✅ Complete - Master teams imported

---

#### 1.2 Game History Import 🔄 **CURRENT STEP**

**Script:** `scripts/import_games_enhanced.py`

**Purpose:** Import game history with validation, matching, and deduplication

**Your Current File:**
```
C:\PitchRank\data\master\all_games_master.csv
```

**File Stats:**
- Size: ~435 MB
- Total games: 1,291,252
- Valid games: 1,225,075 (94.9%)
- Invalid games: 66,177 (5.1%) - mostly missing scores (future/cancelled games)

**Recommended Import Process:**

**Step 1: Validate Your Data** ✅ DONE
```bash
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport --validate-only
```
**Result:** 94.9% valid rate - excellent!

**Step 2: Test with Small Sample** ✅ DONE
```bash
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport --dry-run --limit 1000
```
**Result:** 844 games accepted, 151 quarantined (as expected)

**Step 3: Full Import (Optimized)**
```bash
# Optimized import settings (5-7x faster)
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport \
  --stream \
  --batch-size 5000 \
  --concurrency 12 \
  --skip-validation \
  --checkpoint
```

**Expected Results:**
- ~1,018,000 valid games imported
- ~182,000 invalid games quarantined (missing scores)
- Processing time: ~12-24 hours with optimizations (was 5 days)
- Memory usage: <1GB (streaming mode)
- **Duplicate Protection**: Automatically skips already-imported games (safe to restart)

**Import Process Steps:**

1. **File Loading (Auto-Optimized)**
   - Your file: 435 MB → Auto-enables streaming
   - CSV format: Streamed line-by-line
   - Batch size: 2000 games per batch

2. **Validation**
   - Validates game data (required fields, date format, scores, etc.)
   - Transforms perspective-based games (each game appears twice) to neutral format
   - Deduplicates perspective-based duplicates
   - Invalid games → `quarantine_games` table

3. **Duplicate Detection**
   - Check for existing games using `game_uid` (deterministic UUID)
   - Skip games already in database (immutability)
   - Track duplicates found and skipped

4. **Team Matching**
   - For each game, match home and away teams:
     - **Direct ID Match** (fastest): Check `team_alias_map` for `match_method='direct_id'`
     - **Fuzzy Match** (if no direct match):
       - Query master teams by age_group and gender
       - Calculate weighted similarity score:
         - Team name: 65% weight
         - Club name: 25% weight ✨ NEW
         - Age group: 5% weight
         - Location: 5% weight
       - Apply normalization (remove punctuation, expand abbreviations, etc.)
       - Match thresholds:
         - ≥0.90: Auto-approve → create alias
         - 0.75-0.90: Manual review → `team_match_review_queue`
         - <0.75: Reject → no alias created

5. **Game Insertion**
   - Batch insert valid games (2000 per batch)
   - Create team aliases for matches
   - Track metrics (games processed, accepted, quarantined, duplicates, matches)

6. **Metrics Tracking**
   - Store detailed metrics in `build_logs` table
   - Track processing time, memory usage, error counts
   - Log progress checkpoints (every 10 batches)

**Performance Optimizations:**
- ✅ **Streaming**: Processes 435 MB file without loading into memory
- ✅ **Concurrency**: 12 parallel batches (optimized from 4)
- ✅ **Batch Size**: 5000 games per batch (optimized from 2000)
- ✅ **Skip Validation**: Enabled for faster imports (if data already validated)
- ✅ **Duplicate Checking**: Optimized batch size (2000 UIDs per query)
- ✅ **Retry Logic**: Automatic retry with exponential backoff + jitter
- ✅ **Error Handling**: Continues on batch failures, reports partial success
- ✅ **Safe Restart**: Automatically skips already-imported games (no duplicates)

**Output:**
- Games inserted into `games` table
- Team aliases created in `team_alias_map`
- Pending matches in `team_match_review_queue` (for manual review)
- Invalid games in `quarantine_games`
- Build logs in `build_logs` table

**Status:** 🔄 **IN PROGRESS** - Optimized import running (~12-24 hours)

---

### Phase 2: Team Matching Review ⏳ PENDING

#### 2.1 Review Pending Matches

**Script:** `scripts/review_matches.py`

**Purpose:** Review and approve/reject fuzzy matches in review queue

**Process:**
1. Display pending matches from `team_match_review_queue`
2. Show match details (provider team, master team, confidence score)
3. Allow user to approve or reject matches
4. Update `team_alias_map` with approved matches
5. Remove reviewed matches from queue

**Example:**
```bash
python scripts/review_matches.py
```

**Output:**
- Approved matches → `team_alias_map` with `match_method='fuzzy_review'`
- Rejected matches → removed from queue
- Updated match statistics

**Status:** ⏳ Pending - Run after game import completes

---

### Phase 3: Ranking Calculation ✨ NEW

#### 3.1 Calculate Team Rankings

**Script:** `scripts/calculate_rankings.py`

**Purpose:** Calculate team rankings using v53e engine with optional ML enhancement

**Process:**

**Option A: v53e Only (Deterministic)**
```bash
python scripts/calculate_rankings.py --lookback-days 365
```

**Option B: v53e + ML Layer (Enhanced)**
```bash
python scripts/calculate_rankings.py --ml --lookback-days 365
```

**Option C: With Filters**
```bash
python scripts/calculate_rankings.py --ml \
  --provider gotsport \
  --age-group u10 \
  --gender Male \
  --lookback-days 365
```

**Rankings Engine (v53e):**
- **Layer 1**: Window filter (365-day rolling window)
- **Layer 2**: Outlier guard + goal diff cap
- **Layer 3**: Recency weighting (recent games weighted more)
- **Layer 4**: Defense ridge regression
- **Layer 5**: Adaptive K (strength-based weighting)
- **Layer 6**: Performance layer (goal margin analysis)
- **Layer 7**: Bayesian shrinkage
- **Layer 8**: Strength of Schedule (iterative transitivity)
- **Layer 10**: Core PowerScore (OFF + DEF + SOS weights)
- **Layer 11**: Provisional multiplier + ranking

**ML Layer (Layer 13) - Optional:**
- Uses XGBoost or RandomForest to predict goal margins
- Calculates residuals (actual - predicted) with recency weighting
- Normalizes residuals within cohorts (age, gender)
- Blends into PowerScore: `powerscore_ml = powerscore_adj + alpha * ml_norm`
- Default alpha: 0.12 (12% ML adjustment)

**Data Flow:**
1. Fetch games from Supabase (via `data_adapter.py`)
2. Convert Supabase format → v53e format:
   - `game_date` → `date`
   - `home_team_master_id` → `team_id` (perspective-based)
   - `age_group` ('u10') → `age` ('10')
   - Each game appears twice (home/away perspectives)
3. Run v53e `compute_rankings()` function
4. Apply ML predictive adjustment (if `--ml` flag)
5. Convert back to Supabase format
6. Save to `current_rankings` table

**Output:**
- Rankings in `current_rankings` table:
  - `team_id` (UUID)
  - `national_power_score` (float)
  - `national_rank` (integer)
  - `games_played`, `wins`, `losses`, `draws`
  - `win_percentage`, `strength_of_schedule`

**Status:** ✨ Ready - Run after game import completes

---

#### 3.2 Calculate State Rankings

**Script:** (To be implemented)

**Purpose:** Derive state-level rankings from national rankings

**Process:**
1. Query `current_rankings` filtered by state
2. Re-rank teams within each state
3. Update `state_rank` column in `current_rankings` table

**Status:** ⏳ Pending - Future enhancement

---

### Phase 4: Weekly Automation ✅ COMPLETE

#### 4.1 Weekly Update Pipeline

**Script:** `scripts/weekly/update.py`

**Purpose:** Automated weekly pipeline for scraping, importing, and recalculating rankings

**Process:**
1. **Scrape New Games**: Scrape games from GotSport API (only new games since last scrape)
2. **Import Games**: Import scraped games to database
3. **Recalculate Rankings**: Update rankings with new games

**Full Weekly Update:**
```bash
python scripts/weekly/update.py --provider gotsport
```

**Options:**
```bash
# Skip scraping (use existing file)
python scripts/weekly/update.py --skip-scrape --games-file data/raw/scraped_games.jsonl

# Import only
python scripts/weekly/update.py --skip-scrape --skip-rankings --games-file data/new_games.jsonl

# Rankings only
python scripts/weekly/update.py --skip-scrape --skip-import

# v53e only (no ML)
python scripts/weekly/update.py --no-ml
```

**Scheduling (Windows Task Scheduler):**
- Run every Monday at 2 AM
- See `scripts/weekly/README.md` for setup instructions

**Status:** ✅ Complete - Ready for weekly automation

---

#### 4.2 Game Scraping

**Script:** `scripts/scrape_games.py`

**Purpose:** Scrape new games from GotSport API

**Process:**
1. Get teams that need scraping (not scraped in last 7 days)
2. For each team, fetch games since last scrape date
3. Save scraped games to JSONL file
4. Log scrape activity to `team_scrape_log`

**Example:**
```bash
# Scrape all teams
python scripts/scrape_games.py --provider gotsport

# Scrape with output file
python scripts/scrape_games.py --provider gotsport --output data/raw/scraped_games.jsonl

# Test with limited teams
python scripts/scrape_games.py --provider gotsport --limit-teams 10
```

**GotSport Scraper (`src/scrapers/gotsport.py`):**
- Uses GotSport API: `https://system.gotsport.com/api/v1/teams/{team_id}/matches?past=true`
- Supports ZenRows proxy (via `ZENROWS_API_KEY` env var)
- Incremental scraping: Only fetches games since last scrape date
- Rate limiting: Configurable delays (default 1.5-2.5s)
- Club name extraction: Fetches club names from team details API

**Configuration:**
- `ZENROWS_API_KEY`: Optional proxy API key
- `GOTSPORT_DELAY_MIN`: Min delay between requests (default: 1.5s)
- `GOTSPORT_DELAY_MAX`: Max delay between requests (default: 2.5s)
- `GOTSPORT_MAX_RETRIES`: Max retry attempts (default: 3)

**Output:**
- JSONL file with scraped games
- `team_scrape_log` entries updated
- `teams.last_scraped_at` updated

**Status:** ✅ Complete - GotSport scraper implemented

---

#### 4.3 Data Validation & Review

**Script:** `scripts/analyze_validation_errors.py` ✨ NEW

**Purpose:** Analyze validation errors to understand data quality issues

**Example:**
```bash
python scripts/analyze_validation_errors.py data/master/all_games_master.csv --limit 1000
```

**Output:**
- Error type breakdown
- Error frequency statistics
- Example games with errors

**Status:** ✅ Available

---

#### 4.3 Review Quarantined Data

**Process:**
1. Query `quarantine_games` and `quarantine_teams` tables
2. Review invalid data
3. Fix issues and re-import
4. Clean up quarantined records

**Status:** ⏳ Pending - Run after import

---

## 📁 Data Structures

### Key Tables

1. **`teams`**: Master team list ✅
   - `team_id_master` (UUID, primary key)
   - `team_name`, `club_name`, `age_group`, `gender`, `state_code`
   - `provider_id`, `provider_team_id` (for provider-specific teams)

2. **`games`**: Game history 🔄 **IMPORTING**
   - `game_uid` (deterministic UUID, primary key)
   - `home_team_master_id`, `away_team_master_id`
   - `home_score`, `away_score`, `game_date`
   - `provider_id`, `is_immutable` (prevents duplicate imports)

3. **`team_alias_map`**: Team matching mappings ✅
   - Maps provider team IDs to master team IDs
   - `match_method`: `direct_id`, `fuzzy_auto`, `fuzzy_review`
   - `match_confidence`: 0.0-1.0

4. **`current_rankings`**: Current team rankings ⏳ **PENDING**
   - `team_id_master`, `national_power_score`, `national_rank`
   - `age_group`, `gender` (derived from teams table)
   - `state_rank` (optional, future)
   - `games_played`, `wins`, `losses`, `draws`
   - `win_percentage`, `strength_of_schedule`

5. **`team_match_review_queue`**: Pending matches for review ⏳ **PENDING**
   - Provider team, master team, confidence score
   - Status: `pending`, `approved`, `rejected`

6. **`quarantine_games`** / **`quarantine_teams`**: Invalid data
   - Stores games/teams that failed validation
   - For manual review and correction

7. **`build_logs`**: ETL tracking
   - `build_id`, `stage`, `metrics` (JSONB)
   - `started_at`, `completed_at`, `status`

---

## 🔧 Configuration

### Ranking Configuration (`config/settings.py`)

**v53e Engine Parameters:**
```python
RANKING_CONFIG = {
    'window_days': 365,              # Rolling window
    'max_games': 30,                 # Max games per team
    'recent_k': 15,                  # Recent games count
    'recent_share': 0.65,            # Weight for recent games
    'off_weight': 0.25,              # Offense weight
    'def_weight': 0.25,              # Defense weight
    'sos_weight': 0.50,              # Strength of Schedule weight
    'min_games_for_ranking': 5,      # Minimum games required
    # ... all v53e parameters aligned
}
```

### ML Layer Configuration

```python
ML_CONFIG = {
    'enabled': True,                  # Enable ML layer
    'alpha': 0.12,                    # Blend weight (5-20% recommended)
    'recency_decay_lambda': 0.06,    # Recency decay rate
    'min_team_games_for_residual': 6, # Min games for ML adjustment
    'residual_clip_goals': 3.5,       # Outlier guardrail
    'norm_mode': 'percentile',        # Normalization mode
    # XGBoost/RandomForest parameters
}
```

### Matching Configuration

```python
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.75,          # Minimum score to consider
    'auto_approve_threshold': 0.9,   # Auto-approve matches
    'review_threshold': 0.75,        # Queue for review
    'weights': {
        'team': 0.65,                 # Team name similarity
        'club': 0.25,                 # Club name similarity ✨ NEW
        'age': 0.05,                  # Age group match
        'location': 0.05              # Location match
    },
    'club_boost_identical': 0.05,     # Boost for identical clubs
}
```

### Data Adapter Configuration

```python
DATA_ADAPTER_CONFIG = {
    'games_table': 'games',
    'teams_table': 'teams',
    'column_mappings': {
        'game_date': 'date',
        'home_team_master_id': 'team_id',
        'away_team_master_id': 'opp_id',
        'home_score': 'gf',
        'away_score': 'ga',
        'age_group': 'age',  # 'u10' → '10'
        'gender': 'gender',
    },
    'perspective_based': True,  # Each game appears twice
}
```

---

## 🚀 Current Status & Next Steps

### ✅ Completed

1. **Master Team List Import** ✅
   - Teams imported to `teams` table
   - Direct ID mappings created

2. **Game Import Script** ✅
   - CSV support added
   - Streaming for large files
   - Concurrency support
   - Validation error analysis

3. **Rankings Engine** ✅
   - v53e engine integrated
   - ML layer (Layer 13) integrated
   - Data adapter for Supabase alignment
   - Rankings calculation script

### 🔄 Current Step: Game History Import

**Your Status:**
- ✅ Master teams imported
- ✅ Game file ready: `data/master/all_games_master.csv`
- ✅ Validation completed (94.9% valid)
- ✅ Sample test completed (1000 games)
- 🔄 **Ready for full import**

**Next Action:**
```bash
# Run full import (will take 15-20 hours)
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport \
  --stream \
  --batch-size 2000 \
  --concurrency 4 \
  --checkpoint
```

**What to Expect:**
- Processing time: ~15-20 hours
- Memory usage: <1GB (streaming)
- Progress checkpoints: Every 10 batches
- Final metrics: Games imported, matches created, errors

### ⏳ After Import Completes

1. **Review Team Matches** (if any pending)
   ```bash
   python scripts/review_matches.py
   ```

2. **Calculate Rankings**
   ```bash
   # v53e only
   python scripts/calculate_rankings.py
   
   # With ML enhancement
   python scripts/calculate_rankings.py --ml
   ```

3. **Verify Rankings**
   ```sql
   SELECT * FROM current_rankings 
   ORDER BY national_power_score DESC 
   LIMIT 20;
   ```

---

## 📊 Example Workflow

### Complete Import Workflow

```bash
# 1. Pre-import checklist
python scripts/pre_import_checklist.py

# 2. Import master teams (if not done)
python scripts/import_teams_enhanced.py data/master/all_teams_master.csv gotsport

# 3. Validate game data
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport --validate-only

# 4. Test with sample
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport --dry-run --limit 1000

# 5. Full import (Optimized)
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport \
  --stream \
  --batch-size 5000 \
  --concurrency 12 \
  --skip-validation \
  --checkpoint

# 6. Review pending matches (after import)
python scripts/review_matches.py

# 7. Calculate rankings
python scripts/calculate_rankings.py --ml

# 8. Check import progress
python scripts/check_import_progress.py

# 9. View rankings details
python scripts/show_rankings_details.py
```

---

## 🔍 Monitoring & Debugging

### Check Import Progress

```bash
# View checkpoint logs
cat logs/import_progress.log

# Or query build_logs
python scripts/check_import_progress.py
```

### Review Metrics

```sql
-- Recent builds
SELECT 
    build_id,
    stage,
    metrics->>'games_processed' as games_processed,
    metrics->>'games_accepted' as games_accepted,
    metrics->>'fuzzy_matches_auto' as auto_matched,
    metrics->>'fuzzy_matches_manual' as review_queue,
    started_at,
    completed_at
FROM build_logs
ORDER BY started_at DESC
LIMIT 10;
```

### Check Pending Matches

```sql
SELECT * FROM pending_match_reviews 
ORDER BY confidence_score DESC
LIMIT 20;
```

### Review Quarantined Data

```sql
-- Invalid games
SELECT reason_code, COUNT(*) 
FROM quarantine_games 
GROUP BY reason_code
ORDER BY COUNT(*) DESC;

-- Sample invalid games
SELECT * FROM quarantine_games 
ORDER BY created_at DESC
LIMIT 20;
```

### Check Rankings

```sql
-- Top teams by PowerScore
SELECT 
    t.team_name,
    t.age_group,
    t.gender,
    r.national_rank,
    r.national_power_score,
    r.games_played
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
ORDER BY r.national_power_score DESC
LIMIT 20;
```

---

## 🎯 Key Features

### Intelligent Team Matching

- **Direct ID Matching**: Fastest method, uses provider team IDs
- **Fuzzy Matching**: Advanced similarity scoring with normalization
- **Club Name Weighting**: ✨ NEW - Improves accuracy for teams from same club
- **Abbreviation Expansion**: Handles "FC", "SC", "YS", etc.
- **Manual Review Queue**: For ambiguous matches

### Performance Optimizations

- **Streaming**: Processes large files without loading into memory
- **Parallel Processing**: Concurrent batch processing with semaphore control
- **Batch Inserts**: Efficient bulk database operations (2000 per batch)
- **Retry Logic**: Automatic retry with exponential backoff + jitter
- **Progress Tracking**: Checkpoint logging for long imports

### Rankings Engine

- **v53e Engine**: 11-layer deterministic ranking system
- **ML Layer (Optional)**: XGBoost/RandomForest predictive adjustment
- **Supabase Integration**: Automatic data fetching and conversion
- **Age Group Support**: U10-U18 with cross-age normalization
- **State Rankings**: (Future) State-level ranking derivation

### Data Quality

- **Validation**: Comprehensive data validation before import
- **Deduplication**: Prevents duplicate imports (immutability)
- **Quarantine System**: Invalid data stored for review
- **Error Tracking**: Detailed error reporting and metrics

---

## 📝 Next Steps

1. **Ranking Calculation**: ✅ Ready - Run after game import
2. **State Rankings**: ⏳ Future - Derive state-level rankings
3. **API Endpoints**: ⏳ Future - Create REST API for rankings
4. **Frontend**: ⏳ Future - Build web interface for viewing rankings
5. **Weekly Automation**: ⏳ Future - Automated weekly updates
6. **Analytics**: ⏳ Future - Advanced analytics and reporting

---

**Last Updated:** 2024-11-06
**Version:** 2.1.0
**Current Step:** Phase 1.2 - Game History Import 🔄
