# TGS Event Scraper Documentation

## Overview

The TGS (Total Global Sports) Event Scraper is a production-ready API-based scraper that extracts game history data from Total Global Sports tournament events via the AthleteOne API. It outputs raw CSV data to `data/raw/tgs/` for downstream ETL processing.

## Features

- **Direct API access**: Uses AthleteOne API endpoints directly (no browser automation)
- **Fast execution**: 50-100x faster than browser-based scraping
- **Configurable**: All parameters via CLI arguments or environment variables (CLI overrides ENV)
- **Event range support**: Scrape ranges of events automatically
- **Canonical schema**: Outputs data in the standard format expected by the ETL pipeline
- **Replay-safe**: Each scrape run has a unique `scrape_run_id` for tracking
- **Parallel-safe**: Unique identifiers prevent conflicts in parallel execution
- **Dual records**: Creates both home and away perspective records for each game

## Installation

No special installation required beyond standard Python dependencies:

```bash
pip install requests
```

The `requests` library is already included in `requirements.txt`.

## Usage

### Default (Event Range 3900-4000)

```bash
python scripts/scrape_tgs_event.py
```

### Custom Event Range (CLI)

```bash
python scripts/scrape_tgs_event.py --start-event 3900 --end-event 4000
```

### Custom Event Range (ENV)

```bash
TGS_START_EVENT=4067 TGS_END_EVENT=4100 python scripts/scrape_tgs_event.py
```

### CLI Override ENV

```bash
# ENV sets default, CLI overrides
TGS_START_EVENT=3900 TGS_END_EVENT=4000 python scripts/scrape_tgs_event.py --start-event 4067 --end-event 4100
```

### Custom Output Directory

```bash
python scripts/scrape_tgs_event.py --start-event 3900 --end-event 4000 --output-dir data/raw/tgs/custom
```

### Dry Run (Validate Without Writing)

```bash
python scripts/scrape_tgs_event.py --start-event 3900 --end-event 4000 --dry-run
```

## Configuration

### CLI Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--start-event` | int | 3900 | Start event ID (or from `TGS_START_EVENT`) |
| `--end-event` | int | 4000 | End event ID (or from `TGS_END_EVENT`) |
| `--output-dir` | str | `data/raw/tgs` | Output directory for CSV files |
| `--dry-run` | flag | false | Validate and process but don't write output file |

**Precedence**: CLI arguments override environment variables, which override hardcoded defaults.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TGS_START_EVENT` | 3900 | Start event ID (fallback if not in CLI) |
| `TGS_END_EVENT` | 4000 | End event ID (fallback if not in CLI) |
| `TGS_OUTPUT_DIR` | `data/raw/tgs` | Output directory path (fallback if not in CLI) |

## Output Format

### CSV Schema

The scraper outputs CSV files with the following columns (in order):

1. **scrape_run_id**: Unique identifier for this scrape run (format: `{timestamp}_{uuid}`)
2. **event_id**: Event ID
3. **schedule_id**: Schedule/division ID (from API)
4. **age_year**: Birth year extracted from division name (e.g., 2012 from "B2012")
5. **gender**: B (Boys) or G (Girls), extracted from division name
6. **team_name**: Name of the team being scraped
7. **opponent_name**: Name of the opponent team
8. **game_date**: Date string (from API)
9. **game_time**: Time string (from API)
10. **home_away**: H (Home) or A (Away)
11. **goals_for**: Integer or null
12. **goals_against**: Integer or null
13. **result**: W (Win), L (Loss), D (Draw), or U (Unknown)
14. **venue**: Field/venue name
15. **source_url**: Full URL to the event page
16. **scraped_at**: ISO timestamp (UTC) when record was scraped

### File Naming

Output files are named: `tgs_events_{start_event}_{end_event}_{timestamp}.csv`

- Example: `tgs_events_3900_4000_2025-12-10T14-30-00.csv`

## How It Works

1. **Event Navigation**: Calls `https://api.athleteone.com/api/Event/get-public-event-nav-settings-by-eventID/{event_id}` to get event structure
2. **Division Discovery**: Filters divisions that have schedules (`hasSchedules: true`)
3. **Game Retrieval**: For each division, tries multiple API endpoints until one succeeds:
   - `/Game/get-games-by-divisionID/{division_id}`
   - `/Schedule/get-schedule-by-divisionID/{division_id}`
   - `/Event/get-division-games/{division_id}`
4. **Data Normalization**: Maps API response to canonical schema:
   - Extracts `age_year` and `gender` from division name (e.g., "B2012" → year=2012, gender="B")
   - Computes `result` from scores (W/L/D/U)
   - Generates both home and away perspective records
5. **Output**: Writes all records to CSV with validation

## Error Handling

- **Unreachable events**: Prints error message and continues to next event
- **Missing divisions**: Skips divisions without schedules
- **Missing games**: Prints warning and continues to next division
- **API failures**: Tries multiple endpoint candidates before giving up
- **Invalid data**: Sets result to "U" (Unknown) if scores cannot be parsed
- **Validation**: Validates all records have required columns before writing

## Integration with ETL Pipeline

The scraper outputs raw data to `data/raw/tgs/` which can then be processed by your ETL pipeline:

1. **Raw Data**: CSV files in `data/raw/tgs/`
2. **ETL Processing**: Use `scripts/import_games_enhanced.py` or similar
3. **Team Matching**: Identity engine matches teams to master team list
4. **Rankings**: Ranking engine processes games for power scores

### Example ETL Flow

```bash
# 1. Scrape data
python scripts/scrape_tgs_event.py --start-event 3900 --end-event 4000

# 2. Import to database (example)
python scripts/import_games_enhanced.py \
  data/raw/tgs/tgs_events_3900_4000_*.csv \
  tgs
```

## Troubleshooting

### No Games Found

If a division shows "No games found", it may be that:
- The division has no scheduled games yet
- The API endpoint structure has changed (the scraper tries multiple endpoints)
- The event/division doesn't exist

### Missing Age/Year or Gender

If `age_year` or `gender` is null in the output, the division name format may be unexpected. The scraper extracts these from division names like "B2012" or "G2013". Check the division name format in the API response.

### API Timeout Errors

If you encounter timeout errors, the API may be slow or temporarily unavailable. The scraper will continue to the next event/division.

## Best Practices

1. **Use dry-run first**: Test with `--dry-run` to validate configuration
2. **Start small**: Test with a small event range before running large scrapes
3. **Monitor output**: Check CSV files to ensure data quality
4. **Track runs**: Use `scrape_run_id` to track and replay specific scrape runs
5. **CLI + ENV**: Use ENV for defaults, CLI for overrides (best of both worlds)

## Examples

### Scrape Default Range

```bash
python scripts/scrape_tgs_event.py
```

### Scrape Specific Event Range

```bash
python scripts/scrape_tgs_event.py --start-event 4067 --end-event 4100
```

### CI/CD Configuration

```yaml
# Example GitHub Actions workflow
env:
  TGS_START_EVENT: 3900
  TGS_END_EVENT: 4000
  TGS_OUTPUT_DIR: data/raw/tgs
run: python scripts/scrape_tgs_event.py
```

### Local Testing with ENV Override

```bash
# Set defaults in .env or shell
export TGS_START_EVENT=3900
export TGS_END_EVENT=4000

# Override for one-off run
python scripts/scrape_tgs_event.py --start-event 4067 --end-event 4100
```

## Migration from Playwright Version

If you were using the previous Playwright-based scraper:

- **No browser needed**: The new version uses direct API calls
- **Faster**: 50-100x faster execution
- **Simpler config**: Event range instead of individual event IDs
- **Same output**: CSV schema is identical, fully compatible with ETL pipeline
- **No Playwright dependency**: Removed from `requirements.txt`

## API Endpoints Used

- **Navigation**: `GET /api/Event/get-public-event-nav-settings-by-eventID/{event_id}`
- **Games** (tried in order):
  - `GET /api/Game/get-games-by-divisionID/{division_id}`
  - `GET /api/Schedule/get-schedule-by-divisionID/{division_id}`
  - `GET /api/Event/get-division-games/{division_id}`
