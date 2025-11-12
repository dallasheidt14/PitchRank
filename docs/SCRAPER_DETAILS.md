# GotSport Scraper - Detailed Documentation

## Overview
The GotSport scraper fetches game history data from GotSport's public API and converts it into a standardized format for import into your database.

## API Endpoints Used

### 1. Team Matches API
**Endpoint:** `https://system.gotsport.com/api/v1/teams/{team_id}/matches`
**Method:** GET
**Parameters:** `past=true` (gets past matches only)

**What it returns:**
- List of match objects containing game history for the team
- Up to 30 most recent matches (sorted by date, newest first)

### 2. Team Details API
**Endpoint:** `https://system.gotsport.com/api/v1/team_ranking_data/team_details`
**Method:** GET
**Parameters:** `team_id={team_id}`

**What it returns:**
- Team details including club name
- Used to enrich game data with club information

## Data Collected Per Game

For each game/match, the scraper extracts:

### Core Game Data
- **Team ID** (`team_id`): GotSport team ID (e.g., "126693")
- **Opponent ID** (`opponent_id`): GotSport opponent team ID
- **Team Name** (`team_name`): Full name of the team (from your database)
- **Opponent Name** (`opponent_name`): Full name of the opponent team
- **Game Date** (`game_date`): Date of the game (YYYY-MM-DD format)
- **Home/Away** (`home_away`): "H" for home, "A" for away
- **Goals For** (`goals_for`): Goals scored by the team
- **Goals Against** (`goals_against`): Goals scored by opponent
- **Result** (`result`): "W" (Win), "L" (Loss), "D" (Draw), "U" (Unknown)

### Competition & Venue Data
- **Competition** (`competition`): Competition name (e.g., "U12 Boys League")
- **Division Name** (`division_name`): Division/age group
- **Event Name** (`event_name`): Tournament/event name
- **Venue** (`venue`): Venue/location name

### Metadata
- **Source URL** (`source_url`): Link to GotSport game history page
- **Scraped At** (`scraped_at`): Timestamp when data was scraped
- **Club Name** (`club_name`): Club name for the team
- **Opponent Club Name** (`opponent_club_name`): Club name for opponent

## How It Works

### Step-by-Step Process

1. **Get Teams to Scrape**
   - Queries database for teams with NULL `last_scraped_at` (or teams not scraped in last 7 days)
   - Filters by provider (gotsport)

2. **For Each Team:**
   
   a. **Fetch Club Name**
      - Calls team details API to get club name
      - Caches club name to avoid repeated API calls
   
   b. **Fetch Matches**
      - Calls matches API: `GET /api/v1/teams/{team_id}/matches?past=true`
      - Gets list of past matches
      - Limits to 30 most recent matches
   
   c. **Parse Each Match**
      - Determines if team is home or away
      - Extracts scores (goals_for/goals_against)
      - Parses game date
      - Filters by `since_date` (only games after specified date)
      - Extracts opponent info (name, ID, club)
      - Extracts competition/venue info
      - Determines result (W/L/D)
   
   d. **Convert to Standard Format**
      - Converts API response to `GameData` object
      - Then converts to dictionary format for import
   
   e. **Log Scrape**
      - Updates `teams.last_scraped_at` timestamp
      - Logs to `team_scrape_log` table

3. **Save to File**
   - All scraped games saved to JSONL file
   - Format: `data/raw/scraped_games_YYYYMMDD_HHMMSS.jsonl`
   - One JSON object per line

4. **Auto-Import** (if `--auto-import` flag used)
   - Automatically runs import script
   - Imports games to database using enhanced pipeline

## API Response Structure

### Matches API Response Example:
```json
[
  {
    "match_date": "2025-11-10T14:00:00Z",
    "homeTeam": {
      "team_id": 126693,
      "full_name": "FC United U12 Boys",
      "club": {
        "name": "FC United"
      }
    },
    "awayTeam": {
      "team_id": 128456,
      "full_name": "Soccer Stars U12",
      "club": {
        "name": "Soccer Stars Club"
      }
    },
    "home_score": 3,
    "away_score": 1,
    "venue": {
      "name": "Field 5"
    },
    "competition_name": "U12 Boys League",
    "division_name": "Division A",
    "event_name": "Fall 2025 Season"
  }
]
```

### Team Details API Response Example:
```json
{
  "club_name": "FC United",
  "team_id": 126693,
  "full_name": "FC United U12 Boys"
}
```

## Data Flow

```
GotSport API
    ↓
[Scraper fetches matches]
    ↓
[Parse & filter by date]
    ↓
[Extract game data]
    ↓
[Convert to GameData objects]
    ↓
[Convert to dictionaries]
    ↓
[Save to JSONL file]
    ↓
[Auto-import to database] (if enabled)
    ↓
[Import pipeline validates & matches teams]
    ↓
[Insert into games table]
```

## Rate Limiting & Retries

- **Delay between requests:** 1.5-2.5 seconds (random)
- **Max retries:** 3 attempts per team
- **Timeout:** 30 seconds per request
- **Retry delay:** 2 seconds between retries

## Incremental Scraping

- **First-time scrape:** Uses October 17, 2025 as baseline (or custom `--since-date`)
- **Incremental scrape:** Uses `last_scraped_at` from database
- **Date filtering:** Only scrapes games after the `since_date`
- **Efficiency:** Avoids re-scraping old games

## Error Handling

- **404 errors:** Team not found - skipped gracefully
- **Network errors:** Retries up to 3 times
- **Parse errors:** Logs warning, continues with next match
- **Missing data:** Uses defaults (empty strings, "U" for unknown result)

## Output Format

Each line in the JSONL file contains:
```json
{
  "provider": "gotsport",
  "team_id": "126693",
  "team_id_source": "126693",
  "opponent_id": "128456",
  "opponent_id_source": "128456",
  "team_name": "FC United U12 Boys",
  "opponent_name": "Soccer Stars U12",
  "game_date": "2025-11-10",
  "home_away": "H",
  "goals_for": 3,
  "goals_against": 1,
  "result": "W",
  "competition": "U12 Boys League",
  "venue": "Field 5",
  "source_url": "https://rankings.gotsport.com/teams/126693/game-history",
  "scraped_at": "2025-11-11T12:00:00",
  "club_name": "FC United",
  "opponent_club_name": "Soccer Stars Club"
}
```

## Current Run Details

**What's happening now:**
- Scraping teams with NULL `last_scraped_at`
- Using `since_date` = October 17, 2025
- Will automatically import after scraping completes
- Saving to: `data/raw/scraped_games_YYYYMMDD_HHMMSS.jsonl`

