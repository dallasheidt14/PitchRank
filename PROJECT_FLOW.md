# PitchRank Project Flow

Complete workflow documentation for the PitchRank youth soccer rankings system.

## 📊 Overview

PitchRank processes game data from multiple providers (GotSport, TGS, US Club Soccer) to calculate team rankings and strength of schedule metrics. Rankings come from a two-pass Glicko-2 engine plus an XGBoost residual layer (ML Layer 13). The older v53e engine is still in the tree but is legacy; nothing in the Glicko path calls it.

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

**Example** (the input is a provider export with a `team_id` column; the GotSport one is not tracked in git):
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
# Stable import settings (proven reliable)
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport \
  --stream \
  --batch-size 2000 \
  --concurrency 4 \
  --checkpoint
```

**Expected Results:**
- ~1,018,000 valid games imported
- ~182,000 invalid games quarantined (missing scores)
- Processing time: ~15-20 hours (stable, reliable settings)
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
         - Team name: 35% weight
         - Club name: 35% weight
         - Age group: 10% weight
         - Location: 10% weight
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
- ✅ **Concurrency**: 4 parallel batches (stable, reliable)
- ✅ **Batch Size**: 2000 games per batch (proven stable)
- ✅ **Validation**: Enabled for data quality (ensures valid games)
- ✅ **Duplicate Checking**: Optimized batch size (2000 UIDs per query)
- ✅ **Retry Logic**: Automatic retry with exponential backoff for network/SSL errors
- ✅ **Error Handling**: Continues on batch failures, reports partial success
- ✅ **Safe Restart**: Automatically skips already-imported games (no duplicates)
- ✅ **Provider ID Matching**: Checks teams table first, then alias map, then fuzzy matching

**Output:**
- Games inserted into `games` table
- Team aliases created in `team_alias_map`
- Pending matches in `team_match_review_queue` (for manual review)
- Invalid games in `quarantine_games`
- Build logs in `build_logs` table

**Status:** 🔄 **IN PROGRESS** - Import running (~15-20 hours with stable settings)

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

### Phase 3: Ranking Calculation

#### 3.1 Calculate Team Rankings

**Script:** `scripts/calculate_rankings.py`

**Purpose:** Calculate team rankings using the Glicko-2 engine plus ML Layer 13

**Process:**

**What production runs** (`calculate-rankings.yml`, Mondays 12:30 UTC):
```bash
python scripts/calculate_rankings.py --ml --force-rebuild --engine glicko
```

**Default run** — `--engine` defaults to `glicko`, so this is the same engine:
```bash
python scripts/calculate_rankings.py --lookback-days 365
```

**With filters:**
```bash
python scripts/calculate_rankings.py \
  --provider gotsport \
  --age-group u10 \
  --gender Male \
  --lookback-days 365
```

**Legacy engine** — reachable only by asking for it by name:
```bash
python scripts/calculate_rankings.py --engine v53e
```

> **`--ml` does not control the ML layer.** `Layer13Config.__post_init__` overwrites
> `enabled` from `ML_CONFIG` whatever the caller passed, so the flag only changes the
> banner the script prints. Turn Layer 13 off with `ML_LAYER_ENABLED=false`.

**Rankings Engine (Glicko-2):** two passes over each (age, gender) cohort.

- **Pass 1** — Glicko-2 convergence per cohort, with no cross-age knowledge.
- **Global strength map** — `{team_id: mu}` built from Pass 1.
- **Pass 2** — re-run each cohort warm-started from Pass 1; cross-age opponents are
  rated from the global map plus an anchor offset.
- **Post-convergence, per cohort** — OFF/DEF, then SOS (repeat cap + trim), then SCF
  dampening, then `sigmoid(z-score)` to `powerscore_core`, then the provisional
  multiplier to `powerscore_adj`.
- **Pass 3** — national and state SOS columns. Display only; never feeds PowerScore.

Parameters live in `src/etl/glicko_config.py` (`GlickoConfig`) and
`src/rankings/constants.py`. The `rankings-algorithm` skill documents them.

**ML Layer (Layer 13):**
- XGBoost predicts goal margins; residuals (actual − predicted) are recency-weighted
- Residuals are normalized within cohorts (age, gender)
- Blends into PowerScore: `powerscore_ml = powerscore_adj + alpha * ml_norm`
- Effective alpha: **0.08**, from `ML_CONFIG` in `config/settings.py` (env `ML_ALPHA`)
- Uses a 30-day time-split; never trains on the recent data it predicts

**Data Flow:**
1. Fetch games from Supabase (via `data_adapter.py`), 365-day window + 28-day grace taper
2. Resolve merges — deprecated team IDs map to canonical via `MergeResolver`
3. Convert Supabase format → engine format:
   - `game_date` → `date`
   - `home_team_master_id` → `team_id` (perspective-based)
   - `age_group` ('u10') → `age` ('10')
   - Each game appears twice (home/away perspectives)
4. Run the two Glicko-2 passes via `compute_all_cohorts()` in `src/rankings/calculator.py`
5. Apply ML Layer 13, then the same-age evidence gates → `power_score_true`
6. Multiply by `AGE_TO_ANCHOR[age]` → `power_score_final`
7. Convert back to Supabase format and save

**Output:**
- `rankings_full` — the primary output table. Score chain is
  `powerscore_core` → `powerscore_adj` → `powerscore_ml` → `power_score_true` →
  `power_score_final`, plus `rank_in_cohort_final` (the published rank).
  `national_rank` and `state_rank` are always NULL here; the views compute display ranks.
- `current_rankings` — legacy table, still written for backward compatibility.
- `ranking_history` — snapshot for 7d/30d rank-change tracking.

There is no `powerscore` column, and `sos` is on the raw 1500-centred scale — the
0.45 / 0.60 gates read `sos_norm`. Every PowerScore column is clamped to [0.0, 1.0].

---

#### 3.2 State Rankings

**Where:** the database, not a script.

State rankings are not derived by a post-processing step and no column is updated.
`state_rankings_view` ranks within each `(state, age, gender)` partition directly:

```sql
ROW_NUMBER() OVER (
    PARTITION BY rv.state, rv.age, rv.gender
    ORDER BY rv.power_score_final DESC, rv.team_id_master ASC
) AS rank_in_state_final
```

Only `Active` teams get a rank. Rows with status `Not Enough Ranked Games` appear
in the cohort with a NULL rank, and **every other status is excluded outright** — the
view and the RPCs both close with
`WHERE ... status IN ('Active', 'Not Enough Ranked Games')`. The view's own
`COMMENT` says "Non-active teams visible with NULL state rank", which overstates it
the same way; the outer `WHERE`, not the CTE, is what decides visibility.

The frontend does not read the view directly — it calls the `get_state_rankings` and
`get_state_rankings_count` RPCs, which filter before the `ROW_NUMBER()` and so avoid the
timeout the view hits on a full scan. `/rankings/[region]/[ageGroup]/[gender]` is served
this way.

This is why `state_rank` is always NULL in `rankings_full`, per the Output section above:
the display rank is computed at read time, not stored.

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

# Skip the ML layer
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

**Script:** `scripts/analyze_validation_errors.py`

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

**Glicko-2 parameters** live in `src/etl/glicko_config.py` (`GlickoConfig`) — initial mu /
sigma / volatility, `TAU`, the 365-day window and its 28-day grace, `MAX_GAMES`, goal-diff cap,
and the balanced-selection knobs. Age anchors, gate thresholds, and league tier multipliers live
in `src/rankings/constants.py`.

`RANKING_CONFIG` below is the **legacy v53e** parameter set. Each entry names the `V53EConfig`
field it mirrors. It does not configure the Glicko-2 engine:

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
    # ... remaining entries mirror V53EConfig fields
}
```

### ML Layer Configuration

```python
ML_CONFIG = {
    'enabled': True,                   # env ML_LAYER_ENABLED; this is the real on/off switch
    'alpha': 0.08,                     # env ML_ALPHA; tuned via weight simulator
    'recency_decay_lambda': 0.06,      # env ML_RECENCY_DECAY_LAMBDA
    'min_team_games_for_residual': 12, # aligned with Glicko's publication floor
    'residual_clip_goals': 3.5,        # outlier guardrail
    'norm_mode': 'percentile',         # env ML_NORM_MODE
    # XGBoost parameters
}
```

`Layer13Config.__post_init__` reads every one of these out of `ML_CONFIG` and overwrites
whatever the caller passed, so these values win over any `Layer13Config(...)` constructed in
code.

### Matching Configuration

```python
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.75,          # Minimum score to consider
    'auto_approve_threshold': 0.9,   # Auto-approve matches
    'review_threshold': 0.75,        # Queue for review
    'max_age_diff': 2,
    'weights': {
        'team': 0.35,                 # Team name similarity
        'club': 0.35,                 # Club name similarity
        'age': 0.10,                  # Age group match
        'location': 0.10              # Location match
    },
    'club_boost_identical': 0.10,     # Boost for identical clubs
    'club_min_similarity': 0.8,
    'club_variant_match_boost': 0.15,
    'fuzzy_confidence_ceiling': 0.99,
    # ... plus the affinity_* gates; see config/settings.py for the full set
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
   - Glicko-2 engine integrated (v53e retained as legacy)
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
   # Glicko-2 + ML Layer 13 (the default engine)
   python scripts/calculate_rankings.py

   # What the weekly workflow runs
   python scripts/calculate_rankings.py --ml --force-rebuild --engine glicko
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

# 5. Full import (Stable settings)
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport \
  --stream \
  --batch-size 2000 \
  --concurrency 4 \
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

## 🏠 Local Development Setup

### Using Local Supabase (Recommended for Testing)

Local Supabase eliminates SSL/TLS errors and provides faster imports for development/testing.

**Setup:**
```bash
# 1. Ensure Docker Desktop is running
# 2. Start local Supabase
supabase start

# 3. Note the output credentials and create .env.local:
USE_LOCAL_SUPABASE=true
SUPABASE_URL=http://localhost:54321
SUPABASE_KEY=<from_output>
SUPABASE_SERVICE_ROLE_KEY=<from_output>

# 4. (Optional) Pull production schema
supabase link --project-ref pfkrhmprwxtghtpinrot
supabase db pull
supabase db reset  # Apply migrations

# 5. Test import locally
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport \
  --stream \
  --batch-size 2000 \
  --concurrency 4 \
  --dry-run \
  --limit 1000
```

**Benefits:**
- ✅ No SSL/TLS errors (local HTTP)
- ✅ Faster imports (no network latency)
- ✅ Free testing (no API limits)
- ✅ Full database access via Supabase Studio (http://localhost:54323)

**Switching Environments:**
- Local: Use `.env.local` with `USE_LOCAL_SUPABASE=true`
- Production: Use `.env` (production credentials)
- Code automatically detects `USE_LOCAL_SUPABASE` environment variable

**Access Local Supabase Studio:**
- URL: http://localhost:54323
- View tables, run queries, inspect data

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
- **Club Name Weighting**: club name carries the same 35% as team name
- **Abbreviation Expansion**: Handles "FC", "SC", "YS", etc.
- **Manual Review Queue**: For ambiguous matches

### Performance Optimizations

- **Streaming**: Processes large files without loading into memory
- **Parallel Processing**: Concurrent batch processing with semaphore control
- **Batch Inserts**: Efficient bulk database operations (2000 per batch)
- **Retry Logic**: Enhanced SSL error handling with adaptive batch sizing
  - 5 retries for SSL/network errors (increased from 3)
  - Exponential backoff with jitter to avoid retry collisions
  - Automatic batch size reduction on repeated SSL errors
  - Gradual batch size restoration after successful inserts
- **Progress Tracking**: Checkpoint logging for long imports
- **Local Development**: Use local Supabase to avoid SSL errors entirely

### Rankings Engine

- **Glicko-2 Engine**: two-pass rating with cross-age anchoring (v53e is legacy)
- **ML Layer 13**: XGBoost residual adjustment, alpha 0.08
- **Supabase Integration**: Automatic data fetching and conversion
- **Age Group Support**: U10-U19 with cross-age normalization
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
