# GotSport Event Scraper

## Overview

The `GotSportEventScraper` is a new scraper that allows you to scrape games from specific GotSport events/tournaments. Unlike the team-based scraper, this scraper:

1. Extracts all team IDs from an event page
2. Scrapes games for those teams using the existing team scraper
3. Filters games to include only those from the specified event

## Usage

### List Teams by Bracket

To see all teams in an event organized by bracket/group:

```bash
# List teams by event ID
python scripts/list_event_teams.py --event-id 40550

# List teams by URL
python scripts/list_event_teams.py --event-url "https://system.gotsport.com/org_event/events/40550"
```

This will display teams organized by their brackets (e.g., "SUPER PRO - U9B", "SUPER ELITE - U12G", etc.)

### Scrape Games from Event

The easiest way to use the event scraper is via the `scrape_event.py` script:

```bash
# Scrape by event ID
python scripts/scrape_event.py --event-id 40550

# Scrape by URL
python scripts/scrape_event.py --event-url "https://system.gotsport.com/org_event/events/40550"

# Scrape with event name filter (helps filter games to only those from this event)
python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"

# Scrape only games after a specific date
python scripts/scrape_event.py --event-id 40550 --since-date 2025-11-01

# Specify output file
python scripts/scrape_event.py --event-id 40550 --output data/raw/desert_super_cup.jsonl
```

### Python API

#### List Teams by Bracket

```python
from supabase import create_client
from src.scrapers.gotsport_event import GotSportEventScraper

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

scraper = GotSportEventScraper(supabase, 'gotsport')

# Get teams organized by bracket
brackets = scraper.list_event_teams(event_id="40550")

# brackets is a dict: { "SUPER PRO - U9B": [EventTeam(...), ...], ... }
for bracket_name, teams in brackets.items():
    print(f"{bracket_name}: {len(teams)} teams")
    for team in teams:
        print(f"  - {team.team_name} (ID: {team.team_id})")
```

#### Scrape Games

You can also use the scraper programmatically:

```python
from supabase import create_client
from src.scrapers.gotsport_event import GotSportEventScraper
from datetime import datetime

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Initialize scraper
scraper = GotSportEventScraper(supabase, 'gotsport')

# Scrape by event ID
games = scraper.scrape_event_games(
    event_id="40550",
    event_name="Desert Super Cup",  # Optional: helps filter games
    since_date=datetime(2025, 11, 1)  # Optional: only games after this date
)

# Or scrape by URL
games = scraper.scrape_event_by_url(
    event_url="https://system.gotsport.com/org_event/events/40550",
    event_name="Desert Super Cup"
)
```

## How It Works

1. **Team Extraction**: The scraper fetches the event page HTML and extracts team IDs using multiple methods:
   - Team links in HTML (`/teams/{id}` or `/team/{id}`)
   - Data attributes (`data-team-id`)
   - JSON data in script tags
   - Other patterns

2. **Game Scraping**: For each team found, it uses the existing `GotSportScraper.scrape_team_games()` method to get games.

3. **Filtering**: If an `event_name` is provided, games are filtered to only include those where the event name appears in the competition or event_name fields.

## Output

The scraper outputs games in the same JSONL format as the team scraper:

```json
{
  "provider": "gotsport",
  "team_id": "123456",
  "opponent_id": "789012",
  "game_date": "2025-11-28",
  "home_away": "H",
  "goals_for": 3,
  "goals_against": 1,
  "result": "W",
  "competition": "2025 Desert Super Cup",
  "venue": "Phoenix Soccer Complex",
  ...
}
```

## Limitations

- **Team Extraction**: The scraper relies on HTML parsing to find team IDs. If GotSport changes their page structure, the extraction may need updates.
- **Event Filtering**: Without an `event_name`, the scraper returns all games from teams in the event, which may include games from other events/competitions.
- **Rate Limiting**: Uses the same rate limiting as the team scraper (configurable via `GOTSPORT_DELAY_MIN` and `GOTSPORT_DELAY_MAX`).

## Configuration

Uses the same environment variables as the team scraper:
- `GOTSPORT_DELAY_MIN`: Min delay between requests (default: 1.5s)
- `GOTSPORT_DELAY_MAX`: Max delay between requests (default: 2.5s)
- `GOTSPORT_MAX_RETRIES`: Max retry attempts (default: 3)
- `GOTSPORT_TIMEOUT`: Request timeout (default: 30s)

## Examples

### Example 1: List Teams in Desert Super Cup 2025

```bash
# See all teams organized by bracket
python scripts/list_event_teams.py --event-id 40550
```

This will show output like:
```
SUPER PRO - U9B (8 teams)
  Team ID    Team Name                    Age Group  Gender
  ────────── ──────────────────────────── ───────── ────────
  123456     Team Name 1                   U9        M
  789012     Team Name 2                   U9        M
  ...

SUPER ELITE - U12G (12 teams)
  ...
```

### Example 2: Scrape Desert Super Cup 2025

```bash
python scripts/scrape_event.py \
  --event-id 40550 \
  --event-name "Desert Super Cup" \
  --output data/raw/desert_super_cup_2025.jsonl
```

### Example 3: Scrape Recent Games from an Event

```bash
python scripts/scrape_event.py \
  --event-url "https://system.gotsport.com/org_event/events/40550" \
  --since-date 2025-11-01 \
  --output data/raw/recent_event_games.jsonl
```

## Integration with Existing Pipeline

The output from the event scraper is compatible with the existing import pipeline:

```bash
# After scraping
python scripts/import_games_enhanced.py data/raw/scraped_event_40550_*.jsonl gotsport
```

## Notes

- This scraper is **separate** from the existing `GotSportScraper` - it doesn't modify any existing functionality
- The event scraper reuses the team scraper's game fetching logic, ensuring consistency
- Team extraction may need refinement based on actual GotSport event page structures

