# PitchRank Project Flow

Complete workflow documentation for the PitchRank youth soccer rankings system.

## 📊 Overview

PitchRank processes game data from multiple providers (GotSport, TGS, US Club Soccer) to calculate team rankings and strength of schedule metrics. The system handles millions of games with efficient streaming, parallel processing, and intelligent team matching.

## 🔄 Complete Data Flow

### Phase 1: Data Collection & Import

#### 1.1 Master Team List Import

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
python scripts/import_teams_enhanced.py data/master_teams.csv gotsport
```

**Output:**
- Teams created in `teams` table
- Direct ID mappings in `team_alias_map` table
- Team validation errors in `quarantine_teams` (if any)

#### 1.2 Game History Import

**Script:** `scripts/import_games_enhanced.py`

**Purpose:** Import game history with validation, matching, and deduplication

**Process:**

1. **File Loading (Auto-Optimized)**
   - Small files (<50MB): Load all into memory
   - Large files (>50MB): Auto-enable streaming
   - JSONL/NDJSON: Always streamed line-by-line
   - Standard JSON: Loaded all at once (or streamed if >500MB)

2. **Pre-Validation (Optional)**
   ```bash
   python scripts/import_games_enhanced.py data/games.json gotsport --validate-only
   ```
   - Validates all games without importing
   - Shows validation summary and errors
   - Useful for checking data quality before import

3. **Dry Run (Optional)**
   ```bash
   python scripts/import_games_enhanced.py data/games.json gotsport --dry-run
   ```
   - Simulates import without committing
   - Shows what would be imported, matched, quarantined
   - Useful for testing before actual import

4. **Actual Import**
   ```bash
   # Standard import
   python scripts/import_games_enhanced.py data/games.json gotsport
   
   # Large file with optimizations
   python scripts/import_games_enhanced.py data/games.jsonl gotsport \
     --stream \
     --batch-size 2000 \
     --concurrency 4 \
     --checkpoint \
     --skip-validation  # If pre-validated
   ```

**Import Process Steps:**

1. **Validation** (unless `--skip-validation`)
   - Validate game data (required fields, date format, scores, etc.)
   - Transform perspective-based games (each game appears twice) to neutral format
   - Deduplicate perspective-based duplicates
   - Invalid games → `quarantine_games` table

2. **Duplicate Detection**
   - Check for existing games using `game_uid` (deterministic UUID)
   - Skip games already in database (immutability)
   - Track duplicates found and skipped

3. **Team Matching**
   - For each game, match home and away teams:
     - **Direct ID Match** (fastest): Check `team_alias_map` for `match_method='direct_id'`
     - **Fuzzy Match** (if no direct match):
       - Query master teams by age_group and gender
       - Calculate weighted similarity score:
         - Team name: 65% weight
         - Club name: 25% weight (new!)
         - Age group: 5% weight
         - Location: 5% weight
       - Apply normalization (remove punctuation, expand abbreviations, etc.)
       - Match thresholds:
         - ≥0.90: Auto-approve → create alias
         - 0.75-0.90: Manual review → `team_match_review_queue`
         - <0.75: Reject → no alias created

4. **Game Insertion**
   - Batch insert valid games (default: 2000 per batch)
   - Create team aliases for matches
   - Track metrics (games processed, accepted, quarantined, duplicates, matches)

5. **Metrics Tracking**
   - Store detailed metrics in `build_logs` table
   - Track processing time, memory usage, error counts
   - Log progress checkpoints (if `--checkpoint` enabled)

**Performance Optimizations:**

- **Streaming**: For large files, processes in batches without loading entire file
- **Concurrency**: Processes multiple batches in parallel (default: 4 concurrent)
- **Batch Size**: Configurable batch size (default: 2000, can increase to 5000)
- **Retry Logic**: Automatic retry with exponential backoff (1.0s, 2.5s) + jitter
- **Error Handling**: Continues on batch failures, reports partial success

**Output:**
- Games inserted into `games` table
- Team aliases created in `team_alias_map`
- Pending matches in `team_match_review_queue` (for manual review)
- Invalid games in `quarantine_games`
- Build logs in `build_logs` table

### Phase 2: Team Matching Review

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

### Phase 3: Ranking Calculation

#### 3.1 Calculate Team Rankings

**Script:** (To be implemented)

**Purpose:** Calculate team rankings based on game results

**Process:**
1. Query games from last 365 days (rolling window)
2. Calculate power scores for each team:
   - Win/loss record
   - Strength of schedule (opponent quality)
   - Goal differential
   - Recent form (weight recent games more)
3. Rank teams by age group and gender
4. Store rankings in `current_rankings` table

**Algorithm:**
- Power Score = Base Score + Win Bonus + SOS Bonus + Goal Differential
- Base Score by age group (U10=1000, U11=1100, ..., U18=1800)
- Win Bonus = Opponent Power Score * 0.1
- SOS Bonus = Average Opponent Power Score * 0.05
- Goal Differential = (Goals For - Goals Against) * 2

**Output:**
- Rankings in `current_rankings` table
- Power scores by age group and gender
- Historical ranking snapshots (optional)

#### 3.2 Calculate State Rankings

**Script:** (To be implemented)

**Purpose:** Derive state-level rankings from national rankings

**Process:**
1. Query `current_rankings` filtered by state
2. Re-rank teams within each state
3. Store state rankings (can be derived from national rankings)

**Output:**
- State rankings view/table
- Teams ranked within their state

### Phase 4: Data Maintenance

#### 4.1 Weekly Updates

**Process:**
1. **Scrape New Games**: Run provider scrapers to get new games
2. **Import Games**: Import new games using `import_games_enhanced.py`
3. **Review Matches**: Review any new fuzzy matches
4. **Recalculate Rankings**: Update rankings with new games
5. **Update State Rankings**: Recalculate state rankings

#### 4.2 Data Validation

**Script:** `scripts/pre_import_checklist.py`

**Purpose:** Verify database is ready for imports

**Checks:**
- Required tables exist
- Indexes are present
- Triggers are enabled
- Permissions are correct

**Example:**
```bash
python scripts/pre_import_checklist.py
```

#### 4.3 Review Quarantined Data

**Process:**
1. Query `quarantine_games` and `quarantine_teams` tables
2. Review invalid data
3. Fix issues and re-import
4. Clean up quarantined records

## 📁 Data Structures

### Key Tables

1. **`teams`**: Master team list
   - `team_id_master` (UUID, primary key)
   - `team_name`, `club_name`, `age_group`, `gender`, `state_code`
   - `provider_id`, `provider_team_id` (for provider-specific teams)

2. **`games`**: Game history
   - `game_uid` (deterministic UUID, primary key)
   - `home_team_id_master`, `away_team_id_master`
   - `home_score`, `away_score`, `game_date`
   - `provider_id`, `is_immutable` (prevents duplicate imports)

3. **`team_alias_map`**: Team matching mappings
   - Maps provider team IDs to master team IDs
   - `match_method`: `direct_id`, `fuzzy_auto`, `fuzzy_review`
   - `match_confidence`: 0.0-1.0

4. **`current_rankings`**: Current team rankings
   - `team_id_master`, `power_score`, `rank`, `age_group`, `gender`
   - `state_rank` (optional)

5. **`team_match_review_queue`**: Pending matches for review
   - Provider team, master team, confidence score
   - Status: `pending`, `approved`, `rejected`

6. **`quarantine_games`** / **`quarantine_teams`**: Invalid data
   - Stores games/teams that failed validation
   - For manual review and correction

7. **`build_logs`**: ETL tracking
   - `build_id`, `stage`, `metrics` (JSONB)
   - `started_at`, `completed_at`, `status`

## 🔧 Configuration

### Matching Configuration (`config/settings.py`)

```python
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.75,        # Minimum score to consider match
    'auto_approve_threshold': 0.9,  # Auto-approve matches above this
    'review_threshold': 0.75,      # Queue for review above this
    'max_age_diff': 2,              # Max age group difference
    'weights': {
        'team': 0.65,               # Team name similarity weight
        'club': 0.25,               # Club name similarity weight
        'age': 0.05,                # Age group match weight
        'location': 0.05             # Location match weight
    },
    'club_boost_identical': 0.05,   # Boost for identical clubs
    'club_min_similarity': 0.8     # Minimum club similarity
}
```

### Import Configuration

**Default Batch Size:** 2000 (increased from 1000)

**Default Concurrency:** 4 (can be adjusted based on database load)

**Streaming Threshold:** 50MB (auto-enables streaming)

## 🚀 Performance Tips

### For Large Files (100K+ games)

1. **Use JSONL format** (one JSON object per line)
   - Enables true streaming
   - Reduces memory usage

2. **Enable streaming and concurrency**
   ```bash
   python scripts/import_games_enhanced.py data/games.jsonl gotsport \
     --stream \
     --batch-size 2000 \
     --concurrency 4
   ```

3. **Use checkpointing for long runs**
   ```bash
   --checkpoint  # Logs progress every 10 batches
   ```

4. **Pre-validate then skip validation**
   ```bash
   # Step 1: Validate
   python scripts/import_games_enhanced.py data/games.jsonl gotsport --validate-only
   
   # Step 2: Import without validation
   python scripts/import_games_enhanced.py data/games.jsonl gotsport \
     --skip-validation \
     --stream \
     --concurrency 4
   ```

### For Small Files (<10K games)

- Standard import is fine
- No need for streaming or concurrency
- Default batch size (2000) is sufficient

## 📊 Example Workflow

### Complete Import Workflow

```bash
# 1. Pre-import checklist
python scripts/pre_import_checklist.py

# 2. Import master teams
python scripts/import_teams_enhanced.py data/master_teams.csv gotsport

# 3. Validate game data
python scripts/import_games_enhanced.py data/games.jsonl gotsport --validate-only

# 4. Dry run import
python scripts/import_games_enhanced.py data/games.jsonl gotsport --dry-run

# 5. Actual import (with optimizations)
python scripts/import_games_enhanced.py data/games.jsonl gotsport \
  --stream \
  --batch-size 2000 \
  --concurrency 4 \
  --checkpoint \
  --skip-validation

# 6. Review pending matches
python scripts/review_matches.py

# 7. Verify team mappings
python scripts/verify_team_mappings.py gotsport

# 8. Check build logs
python check_progress.py  # Or query build_logs table
```

## 🔍 Monitoring & Debugging

### Check Import Progress

```bash
# View checkpoint logs
cat logs/import_progress.log

# Or query build_logs
python check_progress.py
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
SELECT * FROM quarantine_games 
ORDER BY created_at DESC
LIMIT 20;

-- Invalid teams
SELECT * FROM quarantine_teams 
ORDER BY created_at DESC
LIMIT 20;
```

## 🎯 Key Features

### Intelligent Team Matching

- **Direct ID Matching**: Fastest method, uses provider team IDs
- **Fuzzy Matching**: Advanced similarity scoring with normalization
- **Club Name Weighting**: Improves accuracy for teams from same club
- **Abbreviation Expansion**: Handles "FC", "SC", "YS", etc.
- **Manual Review Queue**: For ambiguous matches

### Performance Optimizations

- **Streaming**: Processes large files without loading into memory
- **Parallel Processing**: Concurrent batch processing with semaphore control
- **Batch Inserts**: Efficient bulk database operations
- **Retry Logic**: Automatic retry with exponential backoff
- **Progress Tracking**: Checkpoint logging for long imports

### Data Quality

- **Validation**: Comprehensive data validation before import
- **Deduplication**: Prevents duplicate imports (immutability)
- **Quarantine System**: Invalid data stored for review
- **Error Tracking**: Detailed error reporting and metrics

## 📝 Next Steps

1. **Ranking Calculation**: Implement ranking algorithms
2. **State Rankings**: Derive state-level rankings
3. **API Endpoints**: Create REST API for rankings
4. **Frontend**: Build web interface for viewing rankings
5. **Weekly Automation**: Automated weekly updates
6. **Analytics**: Advanced analytics and reporting

---

**Last Updated:** 2024-01-15
**Version:** 2.0.0

