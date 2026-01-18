# Weekly Event Scraper - User Guide

## What It's Called

**Script Name**: `scripts/scrape_new_gotsport_events.py`

**Purpose**: Automatically discovers new GotSport events and scrapes games from all teams participating in those events.

## What It Does

The script performs these steps automatically:

1. **Discovers New Events**: Searches GotSport's event search page for tournaments in the last 7 days (configurable)
2. **Resolves Event IDs**: Automatically converts search page EventIDs to the correct `system.gotsport.com` format
3. **Extracts Teams**: Finds all teams participating in each event
4. **Scrapes Games**: **YES - It scrapes games for each team found** (from the last 30 days by default)
5. **Tracks Progress**: Saves which events have been scraped to avoid duplicates

## How to Use It

### Basic Usage (Recommended)

Run this once per week (e.g., every Monday):

```bash
# Scrape only (you'll import manually later)
python scripts/scrape_new_gotsport_events.py

# Scrape AND automatically import games
python scripts/scrape_new_gotsport_events.py --auto-import
```

This will:
- Look for events from the last 7 days
- Scrape games from the last 30 days for all teams in those events
- Save games to: `data/raw/new_events_YYYYMMDD_HHMMSS.jsonl`
- Track scraped events in: `data/raw/scraped_events.json`
- **If `--auto-import` is used**: Automatically import games to your database

### Custom Date Ranges

If you want to look back further or scrape more game history:

```bash
# Last 14 days of events, scrape last 60 days of games
python scripts/scrape_new_gotsport_events.py --days-back 14 --lookback-days 60
```

### Custom Output Location

```bash
python scripts/scrape_new_gotsport_events.py \
  --output data/raw/weekly_events.jsonl \
  --scraped-events data/raw/events_tracked.json
```

## What Happens When You Run It

1. **Discovery Phase**: 
   - Searches GotSport for events in your date range
   - Resolves all EventIDs automatically
   - Shows you a table of new events found

2. **Team Extraction Phase**:
   - For each event, extracts all participating team IDs
   - Shows progress: "Event X: Y teams found"

3. **Game Scraping Phase**:
   - **For each team found, scrapes their games** from the last N days
   - Filters games to only include those from the event (when possible)
   - Shows progress: "Event X: Y teams, Z games"

4. **Output Phase**:
   - Saves all games to a JSONL file
   - Creates a summary JSON file with statistics
   - Updates the scraped events tracking file

## Output Files

### Games File (JSONL)
**Location**: `data/raw/new_events_YYYYMMDD_HHMMSS.jsonl`

Each line is a JSON object with game data:
```json
{
  "provider": "gotsport",
  "team_id": "12345",
  "opponent_id": "67890",
  "team_name": "Team A",
  "opponent_name": "Team B",
  "game_date": "2025-11-28",
  "goals_for": 2,
  "goals_against": 1,
  "competition": "Desert Super Cup",
  ...
}
```

### Summary File (JSON)
**Location**: `data/raw/new_events_YYYYMMDD_HHMMSS_summary.json`

Contains metadata about the scraping session:
```json
{
  "scrape_date": "2025-11-29T22:00:00",
  "days_back": 7,
  "lookback_days": 30,
  "total_events": 5,
  "total_games": 150,
  "events": [
    {
      "event_id": "40550",
      "event_name": "Desert Super Cup",
      "teams_count": 291,
      "games_count": 45,
      "status": "success"
    }
  ]
}
```

### Tracking File
**Location**: `data/raw/scraped_events.json`

Tracks which events have been scraped to prevent duplicates:
```json
{
  "scraped_event_ids": ["40550", "42498", "44447"],
  "last_updated": "2025-11-29T22:00:00"
}
```

## Weekly Workflow

### Recommended Schedule

Run this script **once per week**, ideally on Monday mornings:

```bash
# Every Monday at 9 AM (example cron job)
0 9 * * 1 cd /path/to/PitchRank && python scripts/scrape_new_gotsport_events.py
```

### What Gets Scraped

- **New events only**: Events you've already scraped are skipped (tracked in `scraped_events.json`)
- **All teams in each event**: Every team participating in discovered events
- **Recent games**: Games from the last 30 days (configurable) for each team
- **Event-filtered**: When possible, games are filtered to only include those from the specific event

## Integration with Your Existing Workflow

### Option 1: Automatic Import (Recommended)

Use the `--auto-import` flag to automatically import games after scraping:

```bash
python scripts/scrape_new_gotsport_events.py --auto-import
```

This will:
1. Scrape games from new events
2. Automatically import them to your database
3. You're done! (Just recalculate rankings if needed)

### Option 2: Manual Import

If you prefer to review the games file first:

```bash
# Step 1: Scrape
python scripts/scrape_new_gotsport_events.py

# Step 2: Review the output file, then import
python scripts/import_games_enhanced.py data/raw/new_events_*.jsonl gotsport --stream --batch-size 2000 --concurrency 4 --checkpoint
```

### After Import

1. **Recalculate rankings** using your existing ranking script

2. **Combine with team-based scraping**: Use event scraping for new tournaments, keep team-based scraping as a fallback for teams not in events

## Troubleshooting

### No Teams Found for an Event
- The event may not have teams registered yet
- The event page structure may be different
- Check the event URL manually: `https://system.gotsport.com/org_event/events/{event_id}`

### Zero Games Returned
- The tournament may not have happened yet
- Games may not be entered into GotSport yet
- Many team IDs may be invalid (404s) - this is normal for some events

### Rate Limiting
The script includes automatic rate limiting (2 seconds between events). If you encounter issues:
- The script will automatically retry failed requests
- Increase delays if needed (modify the script)

## Example Output

```
╔══════════════════════════════════════════════════════════╗
║          Weekly Event Scraper                            ║
║          Looking for events in last 7 days               ║
║          Scraping games from last 30 days                 ║
╠══════════════════════════════════════════════════════════╣

Already scraped 0 events

Step 1: Discovering New Events
Searching for events from 2025-11-22 to 2025-11-29...
✅ Found 12 new events (out of 12 total)

Step 2: Scraping Games from Event Teams
Scraping events... 100%
  Desert Super Cup: 291 teams, 45 games
  Hawaii Thanksgiving: 144 teams, 32 games
  ...

✅ Scraped 150 total games from 12 events
```

## Key Points

✅ **Fully Automated**: No manual event ID entry needed  
✅ **Smart Discovery**: Automatically resolves EventIDs  
✅ **Game Scraping**: Yes, it scrapes games for every team found  
✅ **Duplicate Prevention**: Tracks scraped events automatically  
✅ **Efficient**: Only checks teams in new events, not all 80k teams  

## Next Steps

1. **Run it weekly**: Set up a scheduled task to run every Monday
2. **Monitor output**: Check the summary file to see which events succeeded
3. **Import games**: Use your existing import workflow to add games to your database
4. **Review results**: Check the JSONL file to verify games are being found

