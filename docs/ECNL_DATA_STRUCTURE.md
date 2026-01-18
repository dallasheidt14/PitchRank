# ECNL Game Data Structure

## Overview

This document describes the data structure for ECNL games after scraping and conversion.

## Data Flow

1. **API Response**: HTML table from AthleteOne API
2. **Parsed Games**: `ParsedAthleteOneGame` objects (from HTML parser)
3. **GameData Objects**: Standardized `GameData` objects (from scraper)
4. **JSONL Output**: Dictionary format for database import

## GameData Structure

Each game is represented as a `GameData` object with the following fields:

```python
GameData(
    provider_id="athleteone",  # Provider code
    team_id="athone:abc12345",  # Generated team ID (hash-based)
    opponent_id="athone:def67890",  # Generated opponent ID
    team_name="FC United",  # Team name from HTML
    opponent_name="Real Madrid",  # Opponent name from HTML
    game_date="2025-01-15",  # Date in YYYY-MM-DD format
    home_away="H",  # "H" for home, "A" for away
    goals_for=2,  # Goals scored by team (int or None)
    goals_against=1,  # Goals scored by opponent (int or None)
    result="W",  # "W" (win), "L" (loss), "D" (draw), or None
    competition="ECNL Girls Mid-Atlantic 2025-26",  # Competition name
    venue="Field 1",  # Venue name
    meta={  # Additional metadata
        "source": "athleteone_conference",
        "match_id": "12345",
        "fetch_url": "https://api.athleteone.com/...",
        "timezone": "local",
        "field": "Field 1"  # Optional field name
    }
)
```

## JSONL Output Format

For database import, games are converted to JSON dictionaries:

```json
{
  "provider": "ecnl",
  "team_id": "athone:abc12345",
  "team_id_source": "athone:abc12345",
  "opponent_id": "athone:def67890",
  "opponent_id_source": "athone:def67890",
  "team_name": "FC United",
  "opponent_name": "Real Madrid",
  "game_date": "2025-01-15",
  "home_away": "H",
  "goals_for": 2,
  "goals_against": 1,
  "result": "W",
  "competition": "ECNL Girls Mid-Atlantic 2025-26",
  "venue": "Field 1",
  "source_url": "https://api.athleteone.com/api/Script/get-conference-schedules/9/69/3925/0/0",
  "scraped_at": "2025-12-08T21:30:00"
}
```

## Key Points

### 1. Duplicate Games

Each game appears **twice** in the raw output:
- Once from the home team's perspective
- Once from the away team's perspective

The scraper scripts automatically deduplicate these before saving.

### 2. Team IDs

ECNL doesn't provide team IDs in the API response, so they are generated using:
- Hash of normalized team name
- Format: `athone:{first_8_chars_of_md5_hash}`

Example:
- Team: "FC United" → ID: `athone:abc12345`

### 3. Date Format

- **GameData.game_date**: String in `YYYY-MM-DD` format
- **Parsed game_datetime**: Python `datetime` object (converted to date string)

### 4. Score Handling

- Scores are integers or `None` if not available
- `None` scores indicate scheduled games (not yet played)
- Result is calculated from scores: `W` (win), `L` (loss), `D` (draw), or `None`

### 5. Competition Name

The competition name comes from the conference name:
- Format: `{Conference Name} - {Age Group}`
- Example: "ECNL Girls Mid-Atlantic 2025-26 - G2010"

## Sample Data

### Example Game (Home Team Perspective)

```json
{
  "provider": "ecnl",
  "team_id": "athone:8f3a2b1c",
  "team_id_source": "athone:8f3a2b1c",
  "opponent_id": "athone:9d4e5f6a",
  "opponent_id_source": "athone:9d4e5f6a",
  "team_name": "FC United 2010",
  "opponent_name": "Real Madrid 2010",
  "game_date": "2025-01-15",
  "home_away": "H",
  "goals_for": 2,
  "goals_against": 1,
  "result": "W",
  "competition": "ECNL Girls Mid-Atlantic 2025-26",
  "venue": "Field 1",
  "source_url": "https://api.athleteone.com/api/Script/get-conference-schedules/9/69/3925/0/0",
  "scraped_at": "2025-12-08T21:30:00.123456"
}
```

### Example Game (Away Team Perspective)

```json
{
  "provider": "ecnl",
  "team_id": "athone:9d4e5f6a",
  "team_id_source": "athone:9d4e5f6a",
  "opponent_id": "athone:8f3a2b1c",
  "opponent_id_source": "athone:8f3a2b1c",
  "team_name": "Real Madrid 2010",
  "opponent_name": "FC United 2010",
  "game_date": "2025-01-15",
  "home_away": "A",
  "goals_for": 1,
  "goals_against": 2,
  "result": "L",
  "competition": "ECNL Girls Mid-Atlantic 2025-26",
  "venue": "Field 1",
  "source_url": "https://api.athleteone.com/api/Script/get-conference-schedules/9/69/3925/0/0",
  "scraped_at": "2025-12-08T21:30:00.123456"
}
```

## Data Quality Notes

1. **Team Name Variations**: Team names may have slight variations (e.g., "FC United" vs "FC United 2010")
2. **Missing Data**: Some fields may be `None` or empty strings if not available in source
3. **Date Parsing**: Dates are parsed from HTML and converted to ISO format
4. **Venue Information**: May include field name, location, or both

## Testing

To test the data structure:

```bash
# Run test scraper
python scripts/scrape_ecnl_365days.py \
  --conferences-file data/raw/ecnl_conferences_simplified.json \
  --output data/raw/ecnl_test.jsonl \
  --days-back 365

# Inspect output
head -n 5 data/raw/ecnl_test.jsonl | python -m json.tool
```

## Related Files

- `src/base/__init__.py` - GameData class definition
- `src/scrapers/athleteone_scraper.py` - Conversion logic
- `src/providers/athleteone_html_parser.py` - HTML parsing
- `scripts/scrape_ecnl_365days.py` - 365-day scraper
- `scripts/scrape_ecnl_weekly.py` - Weekly scraper












