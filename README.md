# PitchRank ⚽

A comprehensive ranking system for youth soccer teams with cross-age and cross-state support.

## 🎯 Features

- **National Rankings**: Rankings by age group (U10-U18) and gender
- **State-Level Rankings**: See how teams rank within their state
- **Cross-Age Support**: Unified power scoring system handles cross-age games fairly
- **Smart Matching**: Automated team matching using provider IDs and fuzzy logic
- **Weekly Updates**: Automated ranking calculations with new game data
- **Multi-Provider Support**: Ready for GotSport, TGS, US Club Soccer
- **Scalable Architecture**: Built to handle millions of games

## 🚀 Quick Start

1. **Clone and setup**:

   ```bash
   git clone https://github.com/dallasheidt14/PitchRank.git
   cd PitchRank
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure**:

   ```bash
   cp .env.example .env
   # Edit .env with your Supabase credentials
   ```

3. **Database setup**:

   ```bash
   # Apply migrations
   supabase db push
   # Or manually run: supabase/migrations/20240101000000_initial_schema.sql
   ```

4. **Test**:

   ```bash
   python test_connection.py
   ```

## 📁 Architecture

### Project Structure

```
PitchRank/
├── config/          # Configuration settings
├── src/
│   ├── api/         # API endpoints (future)
│   ├── base/        # Base classes for providers and validators
│   ├── etl/         # ETL pipeline framework
│   ├── models/      # Data models and matching logic
│   ├── rankings/    # Ranking algorithms
│   ├── scrapers/    # Data provider scrapers
│   └── utils/       # Utility functions and validators
├── scripts/         # Import and maintenance scripts
├── supabase/        # Database migrations
├── tests/           # Test suite
└── data/           # Data storage (raw, processed, samples)
```

### Core Components

- **Game Matcher** (`src/models/game_matcher.py`): Fuzzy matching system for team identification
- **ETL Pipeline** (`src/etl/pipeline.py`): Framework for data extraction, transformation, and loading
- **Validators** (`src/utils/validators.py`): Data validation for games and teams
- **Base Providers** (`src/base/__init__.py`): Abstract base classes for data providers

### Database Schema

The system uses PostgreSQL (via Supabase) with:

- **Partitioned Games Table**: Partitioned by year for performance
- **Team Alias Map**: Maps provider team IDs to master teams
- **Ranking Snapshots**: Historical ranking data
- **Build Logs**: Complete ETL tracking
- **Views**: Pre-built queries for common operations

Key tables:
- `teams`: Master team list with `team_id_master` (UUID)
- `games`: Game history with `game_uid` (deterministic UUID) and immutability flags
- `team_alias_map`: Provider to master team mappings with confidence scores
- `current_rankings`: Current power scores and rankings by age group and gender
- `build_logs`: ETL tracking with detailed `metrics` JSONB column
- `providers`: Data provider registry
- `user_corrections`: User-submitted corrections and additions
- `game_corrections`: Game corrections table for immutable games
- `team_match_review_queue`: Pending team matches needing manual review
- `quarantine_games`: Invalid games saved for review
- `quarantine_teams`: Invalid teams saved for review

## ✨ Enhanced Features

### Data Import Pipeline

- **Bulk Operations**: Efficient bulk inserts with configurable batch sizes (default: 1000 games)
- **Validation**: Comprehensive data validation before import with detailed error messages
- **Duplicate Prevention**: Game immutability with deterministic game UIDs prevents duplicate imports
- **Metrics Tracking**: Detailed import metrics stored in `build_logs.metrics` JSONB column
- **Team Matching**: Three-tier fuzzy matching system:
  - **Auto-approve** (≥0.90): Automatically link teams
  - **Manual review** (0.75-0.90): Queue for human review
  - **Reject** (<0.75): Don't create alias

### Performance Optimizations

- Database indexes on all critical query columns
- Chunked processing for large datasets
- Efficient duplicate detection using game_uid
- Batch insert operations with configurable batch sizes

### Data Quality

- Enforced thresholds for team matching (0.90 auto-approve, 0.75 minimum)
- Comprehensive validation of all game and team data
- Quarantine system for invalid data (saved to `quarantine_games` and `quarantine_teams`)
- Manual review queue for ambiguous team matches
- Game immutability with corrections table for data integrity

## 📊 Usage

### Pre-Import Checklist

Before importing data, verify your database is ready:

```bash
python scripts/pre_import_checklist.py
```

This checks for:
- Required tables and columns
- Indexes and triggers
- Database permissions

### Import Process

#### 1. Validate Your Data First

```bash
python scripts/import_games_enhanced.py data/games.json gotsport --validate-only
```

This validates all games without importing, showing:
- Total games processed
- Valid vs invalid games
- Validation errors for invalid games

#### 2. Run Dry Run Import

```bash
python scripts/import_games_enhanced.py data/games.json gotsport --dry-run
```

This simulates the import without committing changes, showing:
- Games that would be accepted
- Duplicates that would be skipped
- Team matches that would be created
- Games that would be quarantined

#### 3. Execute Import

```bash
python scripts/import_games_enhanced.py data/games.json gotsport --batch-size 2000
```

Options:
- `--batch-size`: Number of games to process per batch (default: 1000)
- `--dry-run`: Simulate import without committing
- `--validate-only`: Only validate, don't import

#### 4. Review Metrics

Check `build_logs` table for detailed metrics including:

```sql
SELECT 
    build_id,
    stage,
    metrics->>'games_processed' as games_processed,
    metrics->>'games_accepted' as games_accepted,
    metrics->>'games_quarantined' as games_quarantined,
    metrics->>'duplicates_found' as duplicates,
    metrics->>'fuzzy_matches_auto' as auto_matched,
    metrics->>'fuzzy_matches_manual' as review_queue,
    metrics->>'processing_time_seconds' as processing_time
FROM build_logs
ORDER BY started_at DESC
LIMIT 10;
```

#### 5. Handle Team Matches

Review pending matches in the review queue:

```sql
SELECT * FROM pending_match_reviews ORDER BY confidence_score DESC;
```

Or use the review script:

```bash
python scripts/review_matches.py
```

### Import Process - Using Direct Team ID Matching

#### 1. Import Master Teams (Creates Direct ID Mappings)

```bash
# This creates both teams AND their ID mappings with match_method='direct_id'
python scripts/import_teams_enhanced.py data/master_teams.csv gotsport

# Verify the mappings were created
python scripts/verify_team_mappings.py gotsport

# With dry-run
python scripts/import_teams_enhanced.py data/master_teams.csv gotsport --dry-run
```

#### 2. Import Games (Will Use Direct ID Matches)

```bash
# Games will automatically match using team IDs (fast!)
python scripts/import_games_enhanced.py data/games.json gotsport
```

The system will:
1. **First**: Check for direct ID matches (match_method='direct_id') - this is fastest!
2. **Then**: Only use fuzzy matching if no direct ID match exists

#### 3. Check Match Statistics

```sql
-- See how many teams were matched by each method
SELECT match_method, COUNT(*) as count, AVG(match_confidence) as avg_confidence
FROM team_alias_map 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
GROUP BY match_method
ORDER BY count DESC;

-- Or use the view
SELECT * FROM match_type_statistics WHERE provider_name = 'GotSport';
```

```bash
# Or use the verification script
python scripts/verify_team_mappings.py gotsport
```

#### 4. Find Unmapped Teams

```sql
-- Find teams in games without mappings
SELECT DISTINCT team_id, COUNT(*) as game_count
FROM (
    SELECT home_provider_id as team_id FROM games 
    WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    UNION ALL
    SELECT away_provider_id as team_id FROM games 
    WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
) t
WHERE NOT EXISTS (
    SELECT 1 FROM team_alias_map tam 
    JOIN providers p ON tam.provider_id = p.id
    WHERE p.code = 'gotsport'
    AND tam.provider_team_id = t.team_id
)
GROUP BY team_id
ORDER BY game_count DESC
LIMIT 20;
```

### Import Game History (Legacy)

```bash
python scripts/import_game_history_enhanced.py data/raw/games.json
```

### Create Sample Data

```bash
python scripts/create_sample_data.py 20 15
# Creates 20 teams with 15 games each
```

### Review Team Aliases

```bash
python scripts/review_aliases.py
```

## 🔧 Configuration

Configuration is managed in `config/settings.py`:

- **Providers**: GotSport, TGS, US Club Soccer
- **Age Groups**: U10-U18 with anchor scores
- **Ranking Config**: Window days, max games, weights
- **Matching Config**: Fuzzy thresholds, auto-approve settings
- **ETL Config**: Batch sizes, retry settings

Environment variables (`.env`):
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_KEY`: Supabase anon key
- `SUPABASE_SERVICE_ROLE_KEY`: Service role key (for admin operations)
- `RANKING_WINDOW_DAYS`: Days to look back for rankings (default: 365)
- `MAX_GAMES_PER_TEAM`: Maximum games to consider (default: 30)

## 🧪 Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=src --cov-report=html
```

## 📝 Development

### Adding a New Provider

1. Create scraper in `src/scrapers/` extending `BaseScraper`
2. Add provider config to `config/settings.py`
3. Insert provider record in database
4. Test with sample data

### Weekly Updates

The system uses continuous rankings that update weekly:

1. **Weekly Scraping**: Run scraper to get teams needing updates (using `get_teams_to_scrape()`)
2. **Game Import**: Import new games from last 7 days only
3. **Ranking Calculation**: Update national rankings by age group and gender
4. **State Rankings**: Derive state rankings from national using `calculate_state_rankings()`
5. **Cross-Age SOS**: Calculate global power scores for cross-age strength of schedule

No season management needed - rankings are continuous based on a 365-day rolling window.

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

[Add license information]

---

Built with ❤️ for youth soccer by [Dallas Heidt](mailto:dallasheidt14@gmail.com)

