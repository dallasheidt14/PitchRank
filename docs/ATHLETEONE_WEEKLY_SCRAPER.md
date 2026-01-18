# Weekly AthleteOne Event Scraper

## Overview

The `scripts/scrape_athleteone_weekly.py` script is designed to run weekly to check for new games from AthleteOne/TGS events in the last 7 days. This keeps your game database up-to-date incrementally.

## How It Works

1. **Loads Known Events**: Reads from `data/raw/athleteone_november_events.json` (or custom file)
2. **Filters by Date**: Only scrapes games from the last N days (default: 7 days)
3. **Tracks Progress**: Saves which events have been scraped to avoid duplicates
4. **Saves Results**: Outputs games to JSONL file for import

## Setup

### 1. Discover Events

First, discover events that have games you want to track:

```bash
# Discover November events (or any month)
python scripts/discover_athleteone_november_events.py
```

This creates `data/raw/athleteone_november_events.json` with event parameters.

### 2. Run Weekly Scraper

```bash
# Basic usage (last 7 days)
python scripts/scrape_athleteone_weekly.py

# Custom date range (last 14 days)
python scripts/scrape_athleteone_weekly.py --days-back 14

# Use saved HTML files (for testing or when API blocks requests)
python scripts/scrape_athleteone_weekly.py --use-saved-html --html-cache-dir data/raw
```

## Options

- `--days-back N`: How many days back to scrape games (default: 7)
- `--events-file PATH`: Custom path to events JSON file
- `--scraped-events-file PATH`: Custom path to track scraped events
- `--output PATH`: Custom output file path
- `--use-saved-html`: Use cached HTML files instead of API calls
- `--html-cache-dir PATH`: Directory containing cached HTML files

## Output

Games are saved to: `data/raw/athleteone_weekly_YYYYMMDD_HHMMSS.jsonl`

Format: One JSON object per line (JSONL format)

## Production Usage

### Option 1: Browser Automation (Recommended)

For production, you'll need to use browser automation to fetch HTML since the API blocks direct requests:

1. Use browser automation tools to fetch HTML for each event
2. Save HTML files to cache directory
3. Run scraper with `--use-saved-html`

### Option 2: Scheduled HTML Fetching

1. Set up a scheduled job to fetch HTML files using browser automation
2. Save files to `data/raw/athleteone_cache/`
3. Run weekly scraper with `--use-saved-html --html-cache-dir data/raw/athleteone_cache`

### Option 3: Manual HTML Caching

1. Manually fetch HTML files from ECNL site using browser DevTools
2. Save to cache directory with naming: `athleteone_{event_id}_{flight_id}.html`
3. Run scraper with `--use-saved-html`

## Workflow

### Initial Setup (One-Time)

```bash
# 1. Discover events
python scripts/discover_athleteone_november_events.py

# 2. Test scraper with saved HTML
python scripts/scrape_athleteone_weekly.py --use-saved-html --html-cache-dir data/raw
```

### Weekly Run (Ongoing)

```bash
# Run weekly to get new games from last 7 days
python scripts/scrape_athleteone_weekly.py --days-back 7

# Import games to database
python scripts/import_games.py data/raw/athleteone_weekly_*.jsonl
```

## Event Discovery

To add more events, either:

1. **Manual Discovery**: Use browser DevTools on ECNL site to find event parameters
2. **Automated Discovery**: Enhance `discover_athleteone_november_events.py` with browser automation

Event format in JSON:
```json
{
  "org_id": "12",
  "org_season_id": "70",
  "event_id": "3890",
  "flight_id": "32381",
  "name": "ECNL Boys Texas 2025-26 - B2010",
  "november_dates": ["Nov 01, 2025", "Nov 02, 2025", ...]
}
```

## Troubleshooting

### API 403 Errors

The AthleteOne API blocks direct requests. Solutions:
- Use `--use-saved-html` with cached HTML files
- Implement browser automation to fetch HTML
- Use browser DevTools to manually fetch and cache HTML

### No Games Found

- Check that events file exists and has valid events
- Verify date range includes game dates
- Check that HTML files contain games (if using cached HTML)

### Date Filtering

Games are filtered by `game_date` field. Games without dates are included (may be scheduled).

## Future Enhancements

- [ ] Browser automation integration for automatic HTML fetching
- [ ] Auto-import to database (`--auto-import` flag)
- [ ] Event discovery automation
- [ ] Support for multiple organizations/seasons
- [ ] Email notifications for new games















