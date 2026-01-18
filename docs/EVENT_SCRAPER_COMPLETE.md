# GotSport Event Scraper - Complete Documentation

## Overview

The GotSport Event Scraper system allows you to extract teams and games from GotSport events/tournaments. This is designed to help audit team groupings and bracket placements using PitchRank's comparison and prediction features.

## Scripts Created

### 1. `src/scrapers/gotsport_event.py`
**Purpose**: Core scraper class for extracting teams and games from GotSport events

**Key Features**:
- Extracts teams from event pages using `jsonTeamRegs` JavaScript data
- Organizes teams by their actual brackets (e.g., "SUPER PRO - U9B", "SUPER ELITE - U12G")
- Scrapes games for all teams in an event
- Filters games by event name

**Main Methods**:
- `extract_event_teams_by_bracket(event_id)`: Returns teams organized by bracket
- `list_event_teams(event_id)`: Lists teams with bracket information
- `scrape_event_games(event_id, event_name, since_date)`: Scrapes all games from event
- `scrape_event_by_url(event_url, ...)`: Alternative method using full URL

### 2. `scripts/list_event_teams.py`
**Purpose**: Command-line tool to list all teams in an event, organized by bracket

**Usage**:
```bash
# By event ID
python scripts/list_event_teams.py --event-id 40550

# By URL
python scripts/list_event_teams.py --event-url "https://system.gotsport.com/org_event/events/40550"
```

**Output**: 
- Displays teams in formatted tables, grouped by bracket
- Shows Team ID, Team Name, Age Group, and Gender
- Summary with total brackets and teams

**Use Case**: Quick visual inspection of event structure and team distribution

### 3. `scripts/scrape_event.py`
**Purpose**: Scrape all games from teams participating in an event

**Usage**:
```bash
# Basic usage
python scripts/scrape_event.py --event-id 40550

# With event name filter (recommended)
python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"

# Only recent games
python scripts/scrape_event.py --event-id 40550 --since-date 2025-11-01

# Custom output file
python scripts/scrape_event.py --event-id 40550 --output data/raw/desert_super_cup.jsonl
```

**Output**: JSONL file with game data compatible with your existing import pipeline

**Use Case**: Collect all games from an event for analysis or import

## Data Structures

### EventTeam
```python
@dataclass
class EventTeam:
    team_id: str              # GotSport team ID
    team_name: str            # Full team name
    bracket_name: str         # Actual bracket name (e.g., "SUPER PRO - U9B")
    age_group: Optional[str]  # Age group (e.g., "U9", "U10")
    gender: Optional[str]     # Gender code ("M" or "F")
    division: Optional[str]   # Division/bracket name
```

### Output Format

**Teams by Bracket** (from `list_event_teams.py`):
```json
{
  "SUPER PRO - U9B": [
    {
      "team_id": "3641103",
      "team_name": "Angeles F.C 2017",
      "bracket_name": "SUPER PRO - U9B",
      "age_group": "U9",
      "gender": "M",
      "division": "SUPER PRO - U9B"
    },
    ...
  ],
  "SUPER ELITE - U12G": [
    ...
  ]
}
```

**Games** (from `scrape_event.py`):
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

## Use Cases

### 1. Bracket Auditing
Use `list_event_teams.py` to see how teams are currently grouped in an event, then use PitchRank's comparison features to verify if teams are appropriately placed.

**Workflow**:
1. List teams: `python scripts/list_event_teams.py --event-id 40550`
2. Export to JSON for analysis
3. Use PitchRank compare feature to check if teams in same bracket have similar power scores
4. Identify misplacements

### 2. Game Collection
Scrape all games from an event to:
- Analyze tournament performance
- Update rankings with tournament results
- Track team performance across events

**Workflow**:
1. Scrape games: `python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"`
2. Import games: `python scripts/import_games_enhanced.py data/raw/scraped_event_*.jsonl gotsport`
3. Recalculate rankings: `python scripts/calculate_rankings.py`

### 3. Team Comparison & Prediction
Use the scraped team data with PitchRank's comparison and prediction features:

**Workflow**:
1. Get teams by bracket
2. For each bracket, compare teams using PitchRank's compare feature
3. Use match prediction to see expected outcomes
4. Identify teams that might be in wrong bracket based on power scores

## Integration with PitchRank Features

### Compare Feature
The `ComparePanel` component in your frontend allows comparing two teams. You can:
- Compare teams within the same bracket to verify appropriate grouping
- Compare teams across brackets to identify potential misplacements
- View percentile rankings to see relative strength

### Match Prediction
The `useMatchPrediction` hook provides:
- Predicted scores for matchups
- Win probability
- Explanations for predictions

Use this to:
- Predict outcomes within brackets
- Identify teams that might dominate or struggle in their bracket
- Suggest bracket adjustments

## Configuration

Environment variables (same as team scraper):
- `GOTSPORT_DELAY_MIN`: Min delay between requests (default: 1.5s)
- `GOTSPORT_DELAY_MAX`: Max delay between requests (default: 2.5s)
- `GOTSPORT_MAX_RETRIES`: Max retry attempts (default: 3)
- `GOTSPORT_TIMEOUT`: Request timeout (default: 30s)

## Examples

### Example 1: Audit Desert Super Cup Brackets
```bash
# 1. List all teams by bracket
python scripts/list_event_teams.py --event-id 40550 > desert_super_cup_teams.txt

# 2. Export to JSON for programmatic analysis
python -c "
from supabase import create_client
from src.scrapers.gotsport_event import GotSportEventScraper
import json
import os

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
scraper = GotSportEventScraper(supabase, 'gotsport')
brackets = scraper.list_event_teams(event_id='40550')

# Convert to JSON format
output = {}
for bracket_name, teams in brackets.items():
    output[bracket_name] = [
        {
            'team_id': t.team_id,
            'team_name': t.team_name,
            'bracket_name': t.bracket_name,
            'age_group': t.age_group,
            'gender': t.gender
        }
        for t in teams
    ]

with open('desert_super_cup_brackets.json', 'w') as f:
    json.dump(output, f, indent=2)
"

# 3. Use the JSON with your frontend to compare teams
```

### Example 2: Scrape and Import Event Games
```bash
# Scrape games
python scripts/scrape_event.py \
  --event-id 40550 \
  --event-name "Desert Super Cup" \
  --output data/raw/desert_super_cup_2025.jsonl

# Import to database
python scripts/import_games_enhanced.py \
  data/raw/desert_super_cup_2025.jsonl \
  gotsport \
  --stream \
  --batch-size 2000

# Recalculate rankings with new games
python scripts/calculate_rankings.py
```

### Example 3: Compare Teams in a Bracket
```python
# Get teams in a specific bracket
from supabase import create_client
from src.scrapers.gotsport_event import GotSportEventScraper
import os

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)
scraper = GotSportEventScraper(supabase, 'gotsport')
brackets = scraper.list_event_teams(event_id='40550')

# Get teams in "SUPER PRO - U9B" bracket
u9b_teams = brackets.get('SUPER PRO - U9B', [])

# Now use these team IDs with your compare/prediction features
for team in u9b_teams:
    print(f"Team: {team.team_name} (ID: {team.team_id})")
    # Use team.team_id with your compare feature
```

## Limitations & Notes

1. **Bracket Extraction**: The scraper extracts bracket names from HTML headers. If GotSport changes their page structure, extraction may need updates.

2. **Team Matching**: Team IDs from events are GotSport provider IDs. You'll need to match them to your `team_id_master` UUIDs in the database.

3. **Event Filtering**: When scraping games, provide the event name to filter games correctly. Without it, you'll get all games from event teams (may include other events).

4. **Rate Limiting**: Respects GotSport's rate limits with configurable delays.

## Future Enhancements

Potential improvements:
- Export teams to JSON/CSV with bracket information
- Integration with frontend to display event brackets
- Automatic bracket suggestion based on power scores
- Batch comparison of all teams in a bracket
- Visualization of bracket strength distribution

