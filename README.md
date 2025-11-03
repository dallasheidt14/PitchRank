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
- `teams`: Master team list
- `games`: Game history (partitioned by year)
- `team_alias_map`: Provider to master team mappings
- `current_rankings`: Current power scores and rankings
- `ranking_snapshots`: Historical rankings
- `build_logs`: ETL tracking
- `providers`: Data provider registry
- `user_corrections`: User-submitted corrections and additions

## 📊 Usage

### Import Master Teams

```bash
python scripts/import_master_teams.py data/samples/teams.csv gotsport
```

### Import Game History

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

