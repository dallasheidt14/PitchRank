# Weekly Event Scraping Workflow

## Overview

The weekly event scraping workflow is designed to efficiently scrape games from new GotSport events without having to check all 80k teams in your database.

## Workflow Steps

1. **Discover new events** from the last 7 days (or custom range)
2. **Extract teams** from those events
3. **Scrape games** from those teams in the last 30 days (or custom range)

## Usage

### Basic Usage (Last 7 Days, Last 30 Days of Games)

```bash
python scripts/scrape_new_gotsport_events.py
```

### Custom Date Ranges

```bash
# Last 14 days of events, scrape last 60 days of games
python scripts/scrape_new_gotsport_events.py --days-back 14 --lookback-days 60
```

### Custom Output Files

```bash
python scripts/scrape_new_gotsport_events.py \
  --output data/raw/weekly_events.jsonl \
  --scraped-events data/raw/events_tracked.json
```

## Important Notes

### Event ID Mapping Issue

**Problem**: The EventIDs found on `home.gotsoccer.com/events.aspx` (e.g., `97871`) may not directly map to `system.gotsport.com/org_event/events/{id}` format (e.g., `42498`).

**Solution**: The script tries each discovered EventID. If it doesn't work (no teams found), it gracefully skips that event and continues.

**Workaround**: For known working events, use `scripts/scrape_known_events.py` with a manual list:

```bash
# Scrape specific known event IDs
python scripts/scrape_known_events.py --event-ids 40550,42498,40551
```

Or create a JSON file:

```json
{
  "event_ids": ["40550", "42498", "40551"]
}
```

```bash
python scripts/scrape_known_events.py --events-file events.json
```

## Output

### Games File (JSONL)

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
  ...
}
```

### Summary File (JSON)

Contains metadata about the scraping session:

```json
{
  "scrape_date": "2025-11-29T21:00:00",
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

### Scraped Events Tracking

The script maintains a file (`data/raw/scraped_events.json` by default) that tracks which events have already been scraped, preventing duplicate work:

```json
{
  "scraped_event_ids": ["40550", "42498"],
  "last_updated": "2025-11-29T21:00:00"
}
```

## Integration with Weekly Update

You can integrate this into your existing `scripts/weekly/update.py` workflow:

```python
# In scripts/weekly/update.py
import subprocess

# Step 1: Scrape new events
subprocess.run([
    'python', 'scripts/scrape_new_events.py',
    '--days-back', '7',
    '--lookback-days', '30',
    '--output', 'data/raw/new_events.jsonl'
])

# Step 2: Import games (existing import logic)
# ...

# Step 3: Recalculate rankings (existing logic)
# ...
```

## Troubleshooting

### No Teams Found

If you see "No teams found" for an event:
- The EventID from the search page may not match the `system.gotsport.com` format
- Try manually verifying the event URL: `https://system.gotsport.com/org_event/events/{event_id}`
- If it works manually, add it to your known events list

### Zero Games

If events have teams but 0 games:
- The tournament may not have happened yet
- Games may not be entered into GotSport yet
- Many team IDs may be invalid (404s) - this is normal

### Rate Limiting

The script includes rate limiting (2 seconds between events). If you encounter rate limiting:
- Increase the delay in the script
- Run during off-peak hours
- Use `scrape_known_events.py` for smaller batches

## Best Practices

1. **Run weekly**: Set up a cron job or scheduled task to run every Monday
2. **Monitor output**: Check the summary file to see which events succeeded
3. **Maintain known events**: Keep a list of working event IDs for major tournaments
4. **Combine approaches**: Use event scraping for new tournaments, team-based scraping as fallback

