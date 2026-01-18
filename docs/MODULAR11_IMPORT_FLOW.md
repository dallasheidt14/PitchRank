# Modular11 Game Import Flow

Complete file and script reference for importing Modular11 games into PitchRank.

## 📋 Overview

The Modular11 import process involves:
1. **Scraping** games from Modular11 API → CSV
2. **Importing** CSV → Database with team matching
3. **Team Matching** using aliases and fuzzy matching
4. **Validation** and error handling

---

## 🔄 Complete File Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. SCRAPING PHASE                                               │
└─────────────────────────────────────────────────────────────────┘

scrapers/modular11_scraper/
├── modular11_scraper/
│   ├── spiders/
│   │   └── modular11_schedule.py      ← Scrapes Modular11 API
│   ├── items.py                        ← Defines Modular11GameItem schema
│   ├── pipelines.py                    ← Normalizes & writes CSV
│   └── settings.py                    ← Scrapy configuration
└── output/
    └── modular11_u16.csv               ← OUTPUT: CSV file ready for import

Command:
  cd scrapers/modular11_scraper
  scrapy crawl modular11_schedule -a age_min=16 -a age_max=16 -a days_back=365


┌─────────────────────────────────────────────────────────────────┐
│ 2. IMPORT PHASE                                                 │
└─────────────────────────────────────────────────────────────────┘

scripts/
└── import_games_enhanced.py            ← Main import script entry point

Command:
  python scripts/import_games_enhanced.py \
    scrapers/modular11_scraper/output/modular11_u16.csv \
    modular11


┌─────────────────────────────────────────────────────────────────┐
│ 3. ETL PIPELINE (import_games_enhanced.py → enhanced_pipeline) │
└─────────────────────────────────────────────────────────────────┘

src/etl/
└── enhanced_pipeline.py               ← Core ETL logic
    ├── EnhancedETLPipeline class
    │   ├── __init__()                  ← Loads alias cache, creates matcher
    │   ├── import_games()              ← Main import orchestrator
    │   ├── _validate_games()           ← Validates game data
    │   ├── _transform_game_perspective() ← Converts to home/away format
    │   ├── _check_duplicates()         ← Prevents duplicate imports
    │   └── _bulk_insert_games()        ← Batch inserts to database
    └── ImportMetrics dataclass


┌─────────────────────────────────────────────────────────────────┐
│ 4. TEAM MATCHING (enhanced_pipeline → game_matcher)            │
└─────────────────────────────────────────────────────────────────┘

src/models/
└── game_matcher.py                     ← Team matching logic
    ├── GameHistoryMatcher class
    │   ├── match_game_history()         ← Main matching orchestrator
    │   ├── _match_team()                ← 3-tier matching strategy
    │   │   ├── Strategy 1: _match_by_provider_id()  ← Direct ID match
    │   │   │   └── _validate_team_age_group()       ← NEW: Age validation
    │   │   ├── Strategy 2: _match_by_alias()        ← Alias map lookup
    │   │   └── Strategy 3: _fuzzy_match_team()      ← Fuzzy matching
    │   ├── _calculate_match_score()     ← Weighted similarity scoring
    │   ├── _create_alias()              ← Creates team_alias_map entries
    │   └── _create_review_queue_entry() ← Adds to review queue
    └── generate_game_uid()              ← Creates deterministic game UIDs


┌─────────────────────────────────────────────────────────────────┐
│ 5. VALIDATION                                                    │
└─────────────────────────────────────────────────────────────────┘

src/utils/
└── enhanced_validators.py              ← Data validation
    └── EnhancedDataValidator class
        └── validate_game()             ← Validates game schema & data


┌─────────────────────────────────────────────────────────────────┐
│ 6. DATABASE TABLES                                               │
└─────────────────────────────────────────────────────────────────┘

Supabase Tables:
├── games                                ← Game records (immutable)
├── teams                                ← Master team list
├── team_alias_map                       ← Provider → Master team mappings
├── team_match_review_queue              ← Pending team matches for review
├── quarantine_games                     ← Invalid games
├── validation_errors                    ← Validation failures
└── providers                             ← Provider metadata


┌─────────────────────────────────────────────────────────────────┐
│ 7. SUPPORTING SCRIPTS                                             │
└─────────────────────────────────────────────────────────────────┘

scripts/
├── delete_u16_imports.py                ← Delete recent imports (cleanup)
├── match_modular11_teams.py            ← Manual team matching script
├── populate_review_queue.py             ← Backfill review queue
├── show_unmatched_modular11.py         ← List unmatched teams
├── export_teams_for_mapping.py         ← Export teams for manual mapping
└── check_u16_age_mismatches.py         ← Verify age group matches


┌─────────────────────────────────────────────────────────────────┐
│ 8. DASHBOARD (Streamlit)                                          │
└─────────────────────────────────────────────────────────────────┘

dashboard.py                             ← Streamlit web interface
├── "📋 Team Match Review Queue" tab    ← Review pending matches
│   ├── Approve matches
│   ├── Skip matches
│   └── Create new teams
└── "🔎 Unknown Teams Mapper" tab        ← Map unmapped teams

```

---

## 🔍 Key Files Explained

### 1. **Scraper Files**

#### `scrapers/modular11_scraper/modular11_scraper/spiders/modular11_schedule.py`
- **Purpose**: Scrapes Modular11 API for game data
- **Key Methods**:
  - `start_requests()` - Generates API requests for each age group/division
  - `parse()` - Parses HTML response from API
  - `_parse_match_row()` - Extracts game data from HTML rows
  - `_create_perspective_items()` - Creates home/away perspective items
- **Output**: Yields `Modular11GameItem` objects

#### `scrapers/modular11_scraper/modular11_scraper/pipelines.py`
- **Purpose**: Normalizes and validates scraped items, writes CSV
- **Key Methods**:
  - `process_item()` - Normalizes fields, validates, filters by date
  - `_compute_result()` - Calculates W/L/D/U from scores
  - `_write_item()` - Writes to CSV file
- **Output**: `modular11_u16.csv` in `output/` directory

---

### 2. **Import Script**

#### `scripts/import_games_enhanced.py`
- **Purpose**: Main entry point for importing games
- **Key Functions**:
  - `stream_games_csv()` - Streams CSV in batches
  - `load_games_csv()` - Loads entire CSV into memory
  - `main()` - Orchestrates import process
- **Usage**:
  ```bash
  python scripts/import_games_enhanced.py <csv_file> modular11
  ```

---

### 3. **ETL Pipeline**

#### `src/etl/enhanced_pipeline.py`
- **Purpose**: Core ETL logic for game import
- **Key Methods**:
  - `__init__()` - Initializes pipeline, loads alias cache
  - `import_games()` - Main import orchestrator
  - `_validate_games()` - Validates game data using `EnhancedDataValidator`
  - `_transform_game_perspective()` - Converts perspective format to home/away
  - `_check_duplicates()` - Prevents duplicate imports using `game_uid`
  - `_bulk_insert_games()` - Batch inserts games to database

---

### 4. **Team Matching**

#### `src/models/game_matcher.py`
- **Purpose**: Matches provider teams to master teams
- **Matching Strategy** (3-tier):
  
  1. **Direct ID Match** (`_match_by_provider_id`)
     - Checks `team_alias_map` for exact `provider_team_id` match
     - **NEW**: Validates `age_group` to prevent cross-age matches
     - Fastest (O(1) lookup)
  
  2. **Alias Map Lookup** (`_match_by_alias`)
     - Checks historical mappings from previous imports
     - Validates `age_group` and `gender`
  
  3. **Fuzzy Matching** (`_fuzzy_match_team`)
     - Queries `teams` table by `age_group` + `gender`
     - Calculates weighted similarity score
     - Auto-approves if confidence ≥ 90%
     - Queues for review if confidence 75-90%
     - Rejects if confidence < 75%

- **Key Methods**:
  - `match_game_history()` - Main matching orchestrator
  - `_match_team()` - 3-tier matching strategy
  - `_validate_team_age_group()` - **NEW**: Validates age_group match
  - `_fuzzy_match_team()` - Fuzzy matching with club name weighting
  - `_calculate_match_score()` - Weighted similarity (team 65%, club 25%, age 5%, location 5%)
  - `_create_alias()` - Creates `team_alias_map` entry
  - `_create_review_queue_entry()` - Adds to `team_match_review_queue`

---

### 5. **Validation**

#### `src/utils/enhanced_validators.py`
- **Purpose**: Validates game data schema and values
- **Key Methods**:
  - `validate_game()` - Validates game against schema
  - Checks required fields, date format, score validity

---

## 🔄 Data Flow Example

```
1. Scraper runs:
   modular11_schedule.py → pipelines.py → modular11_u16.csv

2. Import script runs:
   import_games_enhanced.py
   ├── Reads CSV
   ├── Creates EnhancedETLPipeline
   └── Calls pipeline.import_games()

3. Pipeline processes:
   enhanced_pipeline.py
   ├── _validate_games() → quarantine_games (if invalid)
   ├── _transform_game_perspective() → home/away format
   ├── _check_duplicates() → Skip if game_uid exists
   └── For each game:
       └── match_game_history() → game_matcher.py
           ├── _match_team(home) → Returns home_team_master_id
           └── _match_team(away) → Returns away_team_master_id

4. Team matching:
   game_matcher.py
   ├── Strategy 1: Check team_alias_map by provider_team_id
   │   └── _validate_team_age_group() → Reject if age mismatch
   ├── Strategy 2: Check alias map by name
   └── Strategy 3: Fuzzy match → Create alias or queue for review

5. Database insert:
   _bulk_insert_games()
   └── INSERT INTO games (home_team_master_id, away_team_master_id, ...)
```

---

## 🐛 Recent Bug Fix

### Issue: Age Group Mismatch
- **Problem**: U16 games were matching to U13 teams because `_match_by_provider_id()` didn't validate `age_group`
- **Root Cause**: Modular11 uses same `provider_team_id` (club ID) for all age groups
- **Fix**: Added `_validate_team_age_group()` to check age_group before accepting match
- **File**: `src/models/game_matcher.py` (lines 420-471, 731-784)

---

## 📊 Database Schema

### `team_alias_map`
- Maps `provider_team_id` → `team_id_master`
- Columns: `provider_id`, `provider_team_id`, `team_id_master`, `match_method`, `match_confidence`, `review_status`
- **Note**: Does NOT store `age_group` (age validation happens at match time)

### `team_match_review_queue`
- Stores pending team matches for manual review
- Columns: `provider_id`, `provider_team_id`, `provider_team_name`, `suggested_master_team_id`, `confidence_score`, `status`
- Used by Streamlit dashboard for manual mapping

---

## 🚀 Quick Reference Commands

```bash
# Scrape U16 games
cd scrapers/modular11_scraper
scrapy crawl modular11_schedule -a age_min=16 -a age_max=16 -a days_back=365

# Import games
python scripts/import_games_enhanced.py \
  scrapers/modular11_scraper/output/modular11_u16.csv \
  modular11

# Delete recent imports (cleanup)
python scripts/delete_u16_imports.py --yes

# Check for unmatched teams
python scripts/show_unmatched_modular11.py
```

---

## 📝 Notes

- **Immutable Games**: Once imported, games cannot be updated (must use `game_corrections` table)
- **Perspective Deduplication**: Each game appears twice in CSV (home + away), but only one record in database
- **Game UID**: Deterministic format: `{provider}:{date}:{sorted_team1}:{sorted_team2}` (no scores)
- **Team Matching**: Prioritizes speed (direct ID) → accuracy (fuzzy matching)













