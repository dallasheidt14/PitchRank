# Surf Sports Tournament Scraper

## Overview

The SurfSports scraper extracts game history data from all Surf Sports tournaments hosted on Total Global Sports. It navigates from `surfsports.com` to find tournament links, then scrapes game data from `public.totalglobalsports.com` schedule pages.

## Features

- **Automatic Tournament Discovery**: Finds all tournaments from surfsports.com
- **Schedule Extraction**: Extracts all schedule IDs for each age group/flight
- **Game Data Scraping**: Parses game data from individual schedule pages
- **Filtering**: Supports filtering by gender, age group, and date
- **Dual Perspective**: Creates GameData objects for both home and away teams

## Usage

### Basic Usage

```python
from src.scrapers.surfsports import SurfSportsScraper

# Initialize scraper
scraper = SurfSportsScraper(supabase_client, 'surfsports')

# Scrape all tournaments
all_games = scraper.scrape_tournament_games()

# Scrape specific event
games = scraper.scrape_tournament_games(event_id='4067')

# Scrape only boys games
boys_games = scraper.scrape_tournament_games(gender_filter='B')

# Scrape only B2012 games
b2012_games = scraper.scrape_tournament_games(
    event_id='4067',
    gender_filter='B',
    age_group_filter='2012'
)

# Scrape games after a specific date
recent_games = scraper.scrape_tournament_games(
    since_date=datetime(2025, 12, 1)
)
```

### Parameters

- `event_id` (optional): Specific event ID to scrape (e.g., "4067"). If None, scrapes all tournaments
- `gender_filter` (optional): Filter by gender ("B" for boys, "G" for girls). If None, scrapes all
- `age_group_filter` (optional): Filter by age group (e.g., "2012"). If None, scrapes all
- `since_date` (optional): Only scrape games after this date

## How It Works

1. **Find Tournaments**: Scrapes `surfsports.com` to find links to `totalglobalsports.com` event pages
2. **Extract Schedule IDs**: For each event, finds all schedule IDs from the schedules-standings page
3. **Scrape Schedule Pages**: For each schedule ID, scrapes the schedule page to extract game data
4. **Parse Game Data**: Extracts:
   - Date and time
   - Home and away teams
   - Scores
   - Venue
   - Competition name

## Data Structure

Each game is returned as a `GameData` object with:
- `team_name`: Name of the team
- `opponent_name`: Name of the opponent
- `game_date`: Date of the game (YYYY-MM-DD)
- `home_away`: "H" for home, "A" for away
- `goals_for`: Goals scored by the team
- `goals_against`: Goals scored by opponent
- `result`: "W" (Win), "L" (Loss), "D" (Draw), "U" (Unknown)
- `competition`: Tournament/event name
- `venue`: Venue/location name
- `meta`: Additional metadata including source URL, event ID, schedule ID

## Example: Scraping B2012 Games

```python
from src.scrapers.surfsports import SurfSportsScraper
from datetime import datetime

scraper = SurfSportsScraper(supabase_client, 'surfsports')

# Scrape B2012 games from Surf College Cup Youngers (event 4067)
games = scraper.scrape_tournament_games(
    event_id='4067',
    gender_filter='B',
    age_group_filter='2012'
)

print(f"Found {len(games)} games")
for game in games:
    print(f"{game.team_name} vs {game.opponent_name}: {game.goals_for}-{game.goals_against}")
```

## URL Structure

The scraper works with URLs like:
- Event page: `https://public.totalglobalsports.com/public/event/4067/schedules-standings`
- Schedule page: `https://public.totalglobalsports.com/public/event/4067/schedules/35450`

## Notes

- The scraper creates two `GameData` objects per game (one for each team)
- Team IDs are currently set to team names (may need to be mapped to actual team IDs)
- The scraper includes rate limiting to avoid overwhelming the server
- All games are filtered by date if `since_date` is provided

## Testing

Run the test script:

```bash
python scripts/test_surfsports_scraper.py
```

This will test scraping B2012 games from event 4067.












