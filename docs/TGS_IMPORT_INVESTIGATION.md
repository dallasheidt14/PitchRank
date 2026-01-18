# TGS Events Import Investigation

## Overview

This document explains how TGS (Total Global Sports) events scraped data flows from raw CSV files to the database through the import pipeline.

## Import Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. SCRAPING (scripts/scrape_tgs_event.py)                      │
│    - Scrapes TGS events via AthleteOne API                     │
│    - Outputs CSV to data/raw/tgs/                              │
│    - Creates dual records (home + away perspectives)           │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. IMPORT SCRIPT (scripts/import_games_enhanced.py)            │
│    - Reads CSV file                                             │
│    - Streams in batches (default: 1000 games/batch)            │
│    - Supports concurrent processing (default: 4 batches)         │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. ETL PIPELINE (src/etl/enhanced_pipeline.py)                 │
│    - EnhancedETLPipeline orchestrates the import              │
│    - Uses TGSGameMatcher for team matching                     │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. VALIDATION & TRANSFORMATION                                 │
│    - Validates game data                                        │
│    - Deduplicates perspective-based duplicates                 │
│    - Transforms to neutral home/away format                    │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. TEAM MATCHING (src/models/tgs_matcher.py)                  │
│    - Direct ID match → Alias map → Fuzzy match                 │
│    - Creates new teams if no match found                       │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. DATABASE INSERTION                                          │
│    - Bulk inserts games in batches                             │
│    - Updates team scrape dates                                 │
│    - Logs metrics to build_logs                                │
└─────────────────────────────────────────────────────────────────┘
```

## Detailed Process Steps

### Step 1: Scraping (scripts/scrape_tgs_event.py)

**Purpose:** Extract game data from TGS events via AthleteOne API

**Key Features:**
- Direct API access (no browser automation)
- Event range support (e.g., events 3900-4000)
- Creates dual records: each game appears twice (home + away perspectives)
- Outputs canonical CSV schema with required columns

**Output Format:**
```csv
provider,scrape_run_id,event_id,event_name,schedule_id,age_year,age_group,gender,
team_id,team_id_source,team_name,club_name,opponent_id,opponent_id_source,
opponent_name,opponent_club_name,state,state_code,game_date,game_time,
home_away,goals_for,goals_against,result,venue,source_url,scraped_at
```

**Example Record:**
- `provider`: "tgs"
- `team_id`: Official TGS team ID from API (e.g., "12345")
- `home_away`: "H" or "A"
- `goals_for`: Score from team's perspective
- `goals_against`: Score from opponent's perspective

### Step 2: Import Script Entry Point

**Command:**
```bash
python scripts/import_games_enhanced.py data/raw/tgs/tgs_events_*.csv tgs
```

**Key Capabilities:**
- **Streaming mode**: Auto-enabled for files >50MB
- **Batch processing**: Default 1000 games/batch
- **Concurrency**: Default 4 concurrent batches
- **Progress tracking**: Checkpoints every 10k games
- **Error handling**: Retry logic with exponential backoff

**File Reading:**
- CSV files are read using `stream_games_csv()` or `load_games_csv()`
- Maps CSV columns to game data format
- Converts numeric fields (team IDs, scores) to proper types

### Step 3: ETL Pipeline Initialization

**Class:** `EnhancedETLPipeline` (src/etl/enhanced_pipeline.py)

**TGS-Specific Setup:**
```python
# Line 152-156: TGS-specific matcher initialization
elif provider_code.lower() == 'tgs':
    from src.models.tgs_matcher import TGSGameMatcher
    logger.info("Using TGSGameMatcher (with enhanced fuzzy matching)")
    self.matcher = TGSGameMatcher(supabase, provider_id=self.provider_id, 
                                   alias_cache=self.alias_cache)
```

**Key Components:**
- Preloads alias cache for fast lookups
- Gets provider UUID from `providers` table
- Initializes TGS-specific matcher with enhanced fuzzy matching

### Step 4: Validation & Deduplication

**Process:** `_validate_games()` method

**Key Operations:**

1. **Skip games with no scores:**
   ```python
   # Both goals_for and goals_against are None/empty
   if is_empty_score(goals_for) and is_empty_score(goals_against):
       skipped_empty_scores += 1
       continue
   ```

2. **Deduplicate perspective-based duplicates:**
   ```python
   # Create game key (order-independent)
   sorted_teams = sorted([team1_id, team2_id])
   game_key = f"{provider_code}:{game_date}:{sorted_teams[0]}:{sorted_teams[1]}"
   
   # First occurrence → transform and store
   # Second occurrence → skip (duplicate)
   ```

3. **Transform to neutral format:**
   ```python
   # Source: team_id, opponent_id, home_away, goals_for, goals_against
   # Target: home_team_id, away_team_id, home_score, away_score
   
   if home_away == 'H':
       home_team_id = team_id
       away_team_id = opponent_id
       home_score = goals_for
       away_score = goals_against
   else:
       home_team_id = opponent_id
       away_team_id = team_id
       home_score = goals_against
       away_score = goals_for
   ```

4. **Generate game_uid:**
   ```python
   game_uid = GameHistoryMatcher.generate_game_uid(
       provider=provider_code,
       game_date=game_date_normalized,
       team1_id=sorted_teams[0],
       team2_id=sorted_teams[1]
   )
   ```

**Result:** ~50% of records are skipped as perspective duplicates

### Step 5: Duplicate Detection

**Process:** `_check_duplicates()` and `_check_duplicates_by_composite_key()`

**Two-Level Check:**

1. **Game UID Check:**
   ```python
   # Query existing game_uid values
   existing_uids = await self._check_duplicates(valid_games)
   new_games = [g for g in valid_games if g.get('game_uid') not in existing_uids]
   ```

2. **Composite Key Check (after team matching):**
   ```python
   # Database constraint: (provider_id, home_provider_id, away_provider_id, 
   #                       game_date, COALESCE(home_score, -1), COALESCE(away_score, -1))
   existing_composite_keys = await self._check_duplicates_by_composite_key(game_records)
   ```

**Why Both?**
- Game UID check: Fast pre-filter (before team matching)
- Composite key check: Catches duplicates with different game_uid formats

### Step 6: Team Matching (TGS-Specific)

**Matcher:** `TGSGameMatcher` (src/models/tgs_matcher.py)

**Matching Strategy (Priority Order):**

#### 1. Direct ID Match (Fastest)
```python
# Check alias cache (preloaded)
if team_id in self.alias_cache:
    return alias_cache[team_id]['team_id_master']

# Query team_alias_map
team_alias_map WHERE provider_id = 'tgs'
  AND provider_team_id = '12345'
  AND match_method = 'direct_id'
  AND review_status = 'approved'
```

#### 2. Alias Map Lookup
```python
# Any approved alias entry
team_alias_map WHERE provider_id = 'tgs'
  AND provider_team_id = '12345'
  AND review_status = 'approved'
```

#### 3. Fuzzy Matching (TGS-Enhanced)
```python
# Query teams by age_group + gender
teams WHERE age_group = 'u12' AND gender = 'Male'

# For each candidate:
score = _calculate_match_score(provider_team, candidate)

# TGS-specific enhancements:
# - Lower threshold: 0.75 (vs 0.85 standard)
# - Club name boost: +0.25 if clubs match + age tokens match
# - Enhanced normalization: Strips ECNL, RL suffixes
# - Age token extraction: "14b", "u12", "B2012" patterns
```

**Fuzzy Matching Thresholds:**
- **Auto-approve**: ≥0.91 (creates alias, auto-approved)
- **Review queue**: 0.70-0.91 (creates alias, pending review)
- **Reject**: <0.70 (no match)

**TGS-Specific Normalization:**
```python
# Strips TGS-specific suffixes:
# - "ECNL G12", "RL Southwest", "Academy"
# - Age groups: "G12", "B13", "U14"
# - Coach names: "- Orozco", "- Smith"

# Example: "RSL-AZ 14b North ECNL G12" → "rsl az 14b north"
```

**Club Name Matching:**
```python
# Significant boost when club names match:
if club_match and age_token_overlap:
    boost = 0.25  # Enough to push borderline matches over threshold
elif club_match:
    boost = 0.18  # Still significant boost
```

#### 4. Create New Team (If No Match)
```python
# TGS creates new teams when no match found (like Modular11)
if not matched:
    new_team_id = self._create_new_tgs_team(
        team_name=team_name,
        club_name=club_name,
        age_group=age_group,
        gender=gender,
        provider_id=provider_id,
        provider_team_id=provider_team_id  # Official TGS ID
    )
    
    # Create alias mapping
    self._create_alias(
        provider_id=provider_id,
        provider_team_id=provider_team_id,
        team_id_master=new_team_id,
        match_method='import',
        review_status='approved'
    )
```

**Key Difference from Standard Matcher:**
- Standard matcher: Returns `matched: False` if no match found
- TGS matcher: Creates new team automatically (ensures all games can be imported)

### Step 7: Score Validation

**Process:** `_has_valid_scores()` method

**Requirement:**
```python
# Both scores must be valid numeric values
# Handles: None, 'None', 'null', empty strings
if home_score is None or away_score is None:
    return False  # Skip game

# Must be convertible to float (numeric)
try:
    float(home_score)
    float(away_score)
    return True
except ValueError:
    return False  # Skip game
```

**Games with invalid scores are skipped** (not quarantined, just skipped)

### Step 8: Database Insertion

**Process:** `_bulk_insert_games()` method

**Batch Insertion:**
```python
# Insert in batches (default: 1000 games)
for chunk in self._chunks(insert_records, current_batch_size):
    result = self.supabase.table('games').insert(chunk, returning='minimal').execute()
    inserted += len(chunk)
```

**Error Handling:**
- **Duplicate key violations**: Fall back to individual inserts
- **Rate limits (429)**: Reduce batch size, wait 60-120s
- **SSL/Network errors**: Retry with exponential backoff
- **Adaptive batch sizing**: Reduces batch size on repeated errors

**Record Structure:**
```python
{
    'game_uid': 'tgs:2025-12-06:12345:67890',
    'home_team_master_id': 'uuid-here',
    'away_team_master_id': 'uuid-here',
    'home_provider_id': '12345',  # TGS team ID
    'away_provider_id': '67890',  # TGS team ID
    'home_score': 2,
    'away_score': 1,
    'game_date': '2025-12-06',
    'provider_id': provider_uuid,
    'is_immutable': True
}
```

### Step 9: Post-Import Updates

**Update Team Scrape Dates:**
```python
# Update last_scraped_at for teams based on imported games
await self._update_team_scrape_dates(valid_game_records)
```

**Log Metrics:**
```python
# Log to build_logs table
await self._log_build_metrics()
```

**Metrics Tracked:**
- Games processed, accepted, quarantined
- Duplicates found, skipped
- Teams matched, created
- Fuzzy matches (auto, manual, rejected)
- Processing time, errors

## Key Differences: TGS vs Other Providers

### 1. Dual Records (Perspective-Based)
- **TGS**: Each game scraped twice (home + away perspectives)
- **Other providers**: May have single record per game
- **Impact**: ~50% of records are deduplicated during validation

### 2. Official Team IDs
- **TGS**: Uses official provider team IDs from API (`hometeamID`, `awayteamID`)
- **Other providers**: May use generated IDs
- **Impact**: Better matching to existing teams from other providers

### 3. Enhanced Fuzzy Matching
- **TGS**: Lower threshold (0.75), club name boost, age token extraction
- **Other providers**: Standard threshold (0.85)
- **Impact**: More aggressive matching, fewer new teams created

### 4. Automatic Team Creation
- **TGS**: Creates new teams if no match found (like Modular11)
- **Other providers**: May fail if no match found
- **Impact**: All games can be imported, even for new teams

### 5. TGS-Specific Normalization
- **TGS**: Strips ECNL, RL suffixes, handles "Club Name - Team Name" format
- **Other providers**: Standard normalization
- **Impact**: Better matching for TGS naming patterns

## Workflow Integration

**GitHub Actions Workflow:** `.github/workflows/tgs-event-scrape-import.yml`

**Steps:**
1. Scrape TGS events (scripts/scrape_tgs_event.py)
2. Find scraped CSV file
3. Import games (scripts/import_games_enhanced.py)
4. Upload artifacts and logs

**Example:**
```yaml
- name: Scrape TGS Events
  run: |
    python scripts/scrape_tgs_event.py --start-event 3900 --end-event 4000

- name: Import Games
  run: |
    python scripts/import_games_enhanced.py "$CSV_FILE" tgs
```

## Performance Characteristics

**Batch Processing:**
- Default batch size: 1000 games
- Concurrent batches: 4
- Streaming mode: Auto-enabled for files >50MB

**Database Operations:**
- Duplicate check: 2000 UIDs per query
- Bulk insert: 1000 games per batch
- Rate limit handling: Adaptive batch sizing

**Typical Performance:**
- ~1000-2000 games/second (depending on team matching complexity)
- Large imports (100k+ games): ~10-30 minutes

## Error Handling

**Retry Logic:**
- Max retries: 5 attempts
- Exponential backoff: 1s, 2s, 4s, 8s, 16s
- Jitter: Random 0-0.5s added to prevent collisions

**Error Types:**
- **Duplicate key violations**: Fall back to individual inserts
- **Rate limits (429)**: Reduce batch size, wait longer
- **SSL/Network errors**: Retry with backoff, reduce batch size
- **Validation errors**: Quarantine games, continue import

**Failed Batches:**
- Tracked in `failed_batches` list
- Logged but don't stop import
- Can be retried manually

## Monitoring & Debugging

**Logs:**
- Console: Progress updates every 10k games
- Database: Metrics logged to `build_logs` table
- File: `logs/import_progress.log` (if checkpoint enabled)

**Debug Mode:**
```bash
python scripts/import_games_enhanced.py file.csv tgs --debug
```

**Metrics Available:**
- Games processed, accepted, quarantined
- Duplicates found, skipped
- Teams matched, created
- Fuzzy matches (auto, manual, rejected)
- Processing time, errors

## Common Issues & Solutions

### Issue: High Duplicate Rate
**Symptom:** Many games marked as duplicates
**Cause:** Re-importing same events
**Solution:** Normal - duplicates are skipped, import continues

### Issue: Many New Teams Created
**Symptom:** High `teams_created` count
**Cause:** Teams don't match existing database teams
**Solution:** Review fuzzy match thresholds, check team name normalization

### Issue: Rate Limit Errors
**Symptom:** 429 errors during import
**Cause:** Too many concurrent requests
**Solution:** Reduce batch size or concurrency, increase delays

### Issue: SSL Errors
**Symptom:** Connection errors during insert
**Cause:** Network instability
**Solution:** Retry logic handles this automatically, reduces batch size

## Related Files

- **Scraper**: `scripts/scrape_tgs_event.py`
- **Import Script**: `scripts/import_games_enhanced.py`
- **ETL Pipeline**: `src/etl/enhanced_pipeline.py`
- **TGS Matcher**: `src/models/tgs_matcher.py`
- **Base Matcher**: `src/models/game_matcher.py`
- **Validators**: `src/utils/enhanced_validators.py`
- **Workflow**: `.github/workflows/tgs-event-scrape-import.yml`
- **Documentation**: `docs/TGS_SCRAPER.md`







