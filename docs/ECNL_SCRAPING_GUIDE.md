# ECNL Scraping Guide

## Overview

This guide explains how to scrape ECNL (Elite Club National League) game data using the provided scripts. The scraping infrastructure uses the existing AthleteOne/TGS API integration.

## Quick Start

### Step 1: Discover Conferences

First, discover all available ECNL conferences and map them to API parameters:

```bash
python scripts/discover_ecnl_conferences.py
```

This creates:
- `data/raw/ecnl_conferences.json` - Full conference details
- `data/raw/ecnl_conferences_simplified.json` - Simplified mapping for scraping

**Note**: If the discovery script doesn't find conferences in the HTML (due to dynamic content), you may need to:
1. Use browser automation (Selenium/Playwright)
2. Manually create the conferences file based on the investigation findings

### Step 2: One-Time 365-Day Scrape

Scrape all games from the last 365 days:

```bash
# Basic usage
python scripts/scrape_ecnl_365days.py

# Auto-import to database
python scripts/scrape_ecnl_365days.py --auto-import

# Custom date range (e.g., last 180 days)
python scripts/scrape_ecnl_365days.py --days-back 180
```

**Output**: `data/raw/ecnl_365days_YYYYMMDD_HHMMSS.jsonl`

### Step 3: Set Up Weekly Scraper

After the initial scrape, set up weekly incremental updates:

```bash
# Basic usage (last 7 days)
python scripts/scrape_ecnl_weekly.py

# Auto-import to database
python scripts/scrape_ecnl_weekly.py --auto-import

# Custom date range (e.g., last 14 days)
python scripts/scrape_ecnl_weekly.py --days-back 14
```

**Output**: `data/raw/ecnl_weekly_YYYYMMDD_HHMMSS.jsonl`

## Scripts

### 1. `discover_ecnl_conferences.py`

**Purpose**: Discover all ECNL conferences and map them to AthleteOne API parameters.

**Usage**:
```bash
python scripts/discover_ecnl_conferences.py
```

**Output**:
- `data/raw/ecnl_conferences.json` - Full conference data
- `data/raw/ecnl_conferences_simplified.json` - Simplified mapping

**Note**: May require browser automation if conferences are loaded dynamically.

### 2. `scrape_ecnl_365days.py`

**Purpose**: One-time scraper for all games in the last 365 days (or custom range).

**Usage**:
```bash
# Basic usage
python scripts/scrape_ecnl_365days.py

# Options
python scripts/scrape_ecnl_365days.py \
  --conferences-file data/raw/ecnl_conferences_simplified.json \
  --output data/raw/ecnl_all_games.jsonl \
  --auto-import \
  --days-back 365
```

**Options**:
- `--conferences-file PATH`: Path to conferences JSON (default: `data/raw/ecnl_conferences_simplified.json`)
- `--output PATH`: Output file path (default: auto-generated)
- `--auto-import`: Automatically import games to database
- `--days-back N`: Number of days to look back (default: 365)

**Features**:
- Scrapes all conferences and age groups
- Filters games by date range
- Removes duplicates (home/away perspectives)
- Saves to JSONL format
- Optional auto-import to database

### 3. `scrape_ecnl_weekly.py`

**Purpose**: Weekly incremental scraper for new games in the last 7 days.

**Usage**:
```bash
# Basic usage (last 7 days)
python scripts/scrape_ecnl_weekly.py

# Options
python scripts/scrape_ecnl_weekly.py \
  --days-back 7 \
  --conferences-file data/raw/ecnl_conferences_simplified.json \
  --scraped-conferences-file data/raw/ecnl_scraped_conferences.json \
  --output data/raw/ecnl_this_week.jsonl \
  --auto-import
```

**Options**:
- `--days-back N`: Days to look back (default: 7)
- `--conferences-file PATH`: Path to conferences JSON
- `--scraped-conferences-file PATH`: Path to track scraped conferences
- `--output PATH`: Output file path (default: auto-generated)
- `--auto-import`: Automatically import games to database

**Features**:
- Only scrapes games from specified date range
- Tracks which conferences have been scraped
- Removes duplicates
- Saves to JSONL format
- Optional auto-import to database

## Workflow

### Initial Setup (One-Time)

1. **Discover Conferences**:
   ```bash
   python scripts/discover_ecnl_conferences.py
   ```

2. **Initial 365-Day Scrape**:
   ```bash
   python scripts/scrape_ecnl_365days.py --auto-import
   ```

### Weekly Maintenance

Run the weekly scraper (e.g., every Monday):

```bash
python scripts/scrape_ecnl_weekly.py --auto-import
```

Or set up a cron job / scheduled task:

```bash
# Linux/Mac cron (every Monday at 2 AM)
0 2 * * 1 cd /path/to/PitchRank && python scripts/scrape_ecnl_weekly.py --auto-import

# Windows Task Scheduler
# Create task to run: python scripts/scrape_ecnl_weekly.py --auto-import
```

## Data Format

### Input: Conferences JSON

```json
[
  {
    "conference": "ECNL Girls Mid-Atlantic 2025-26",
    "age_group": "G2010",
    "org_id": "9",
    "org_season_id": "69",
    "event_id": "3925",
    "flight_id": "0"
  }
]
```

### Output: Games JSONL

Each line is a JSON object:

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
  "source_url": "https://api.athleteone.com/...",
  "scraped_at": "2025-12-08T21:30:00"
}
```

## Troubleshooting

### No Conferences Found

If `discover_ecnl_conferences.py` doesn't find conferences:

1. **Check if page uses dynamic content**: The ECNL page may load conferences via JavaScript
2. **Use browser automation**: Modify the script to use Selenium or Playwright
3. **Manual mapping**: Create the conferences file manually based on the investigation document

### API Blocking Requests

If the AthleteOne API blocks direct requests:

1. **Use browser automation**: Fetch HTML via browser and save to cache
2. **Add delays**: Increase delays between requests
3. **Use proxies**: Configure proxy rotation
4. **Contact ECNL**: Request API access or rate limit information

### No Games Found

If no games are found:

1. **Check date range**: Verify games exist in the specified date range
2. **Check conference IDs**: Verify event_id and flight_id are correct
3. **Check API response**: Save HTML and inspect manually
4. **Verify season**: Ensure org_season_id matches current season

### Duplicate Games

The scripts automatically remove duplicates from home/away perspectives. If you still see duplicates:

1. **Check game_date format**: Ensure dates are consistent
2. **Check team names**: Verify team name normalization
3. **Review deduplication logic**: May need to adjust key generation

## Integration with Existing Pipeline

The ECNL scrapers use the existing AthleteOne infrastructure:

- **Client**: `src/providers/athleteone_client.py`
- **Parser**: `src/providers/athleteone_html_parser.py`
- **Scraper**: `src/scrapers/athleteone_scraper.py`

This means:
- ✅ No new dependencies required
- ✅ Consistent data format with other AthleteOne sources
- ✅ Reuses tested parsing logic
- ✅ Same error handling and retry logic

## Next Steps

1. **Run discovery script** to map all conferences
2. **Run 365-day scraper** to populate initial dataset
3. **Set up weekly scraper** as scheduled task
4. **Monitor for errors** and adjust as needed
5. **Consider team matching** to link ECNL teams to existing teams in database

## Related Documentation

- `docs/ECNL_SCRAPING_INVESTIGATION.md` - Technical investigation details
- `docs/ATHLETEONE_WEEKLY_SCRAPER.md` - Similar weekly scraper pattern
- `src/scrapers/athleteone_scraper.py` - Underlying scraper implementation












