# GotSport Event Scraper - Complete Summary

## What Was Created

I've created a complete system for scraping and analyzing GotSport events/tournaments, specifically designed to help you audit bracket placements using PitchRank's comparison and prediction features.

## Files Created

### 1. Core Scraper (`src/scrapers/gotsport_event.py`)
**Purpose**: Main scraper class that extracts teams and games from GotSport events

**Key Methods**:
- `extract_event_teams_by_bracket(event_id)`: Gets teams organized by bracket
- `list_event_teams(event_id)`: Returns teams with bracket information
- `scrape_event_games(event_id, event_name, since_date)`: Scrapes all games from event

### 2. List Teams Script (`scripts/list_event_teams.py`)
**Purpose**: Command-line tool to view and export teams by bracket

**Features**:
- Displays teams in formatted tables grouped by bracket
- **Automatically exports to JSON** (`data/raw/event_{event_id}_teams.json`)
- Shows Team ID, Name, Age Group, Gender for each team
- Summary statistics

**Usage**:
```bash
python scripts/list_event_teams.py --event-id 40550
```

**Output**:
- Console: Formatted tables showing teams by bracket
- JSON File: `data/raw/event_40550_teams.json` with all teams organized by bracket

### 3. Scrape Games Script (`scripts/scrape_event.py`)
**Purpose**: Scrape all games from teams participating in an event

**Usage**:
```bash
python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"
```

**Output**: JSONL file compatible with your existing import pipeline

## JSON Output Format

The JSON export from `list_event_teams.py` is structured like this:

```json
{
  "U10B": [
    {
      "team_id": "3519647",
      "team_name": "16G GSA",
      "bracket_name": "U10B",
      "age_group": "U10",
      "gender": "M",
      "division": "U10B"
    },
    ...
  ],
  "U10G": [
    {
      "team_id": "3595450",
      "team_name": "17G GSA",
      "bracket_name": "U10G",
      "age_group": "U10",
      "gender": "F",
      "division": "U10G"
    },
    ...
  ]
}
```

**Key Points**:
- Teams are **grouped by bracket** (age group + gender)
- Each team has: `team_id`, `team_name`, `bracket_name`, `age_group`, `gender`
- Ready to use with your compare and prediction features

## How to Use for Bracket Auditing

### Step 1: Export Teams to JSON
```bash
python scripts/list_event_teams.py --event-id 40550
```
This creates: `data/raw/event_40550_teams.json`

### Step 2: Load in Your Application
```javascript
// Frontend example
import teamsByBracket from './data/raw/event_40550_teams.json';

// For each bracket
Object.entries(teamsByBracket).forEach(([bracketName, teams]) => {
  // Get team IDs
  const teamIds = teams.map(t => t.team_id);
  
  // Use with your ComparePanel component
  // Compare teams within bracket to check if they're appropriately grouped
});
```

### Step 3: Use PitchRank Features

**Compare Teams**:
- Use `ComparePanel` to compare teams within the same bracket
- Check if teams have similar power scores (they should if bracket is appropriate)
- Identify outliers that might be in wrong bracket

**Predict Match Outcomes**:
- Use `useMatchPrediction` hook to predict outcomes between teams
- If predictions show extreme mismatches (e.g., 5-0 predicted), teams might be misplaced
- Compare all teams in a bracket to see strength distribution

**Example Workflow**:
1. Load JSON with teams by bracket
2. For each bracket:
   - Get power scores for all teams in bracket
   - Calculate bracket strength statistics (mean, std dev, range)
   - Compare teams using your compare feature
   - Predict matchups using your prediction feature
   - Flag teams that are outliers (too strong/weak for bracket)

### Step 4: Generate Audit Report

You can create a script to:
- Load teams from JSON
- Query your database for power scores
- Calculate bracket strength metrics
- Identify teams that might be misplaced
- Suggest bracket adjustments

## Integration with Your Site

### Frontend Integration
1. **API Endpoint**: Create endpoint to serve event teams JSON
2. **Bracket Viewer**: Display teams grouped by bracket
3. **Compare Integration**: Allow comparing teams within/across brackets
4. **Prediction Integration**: Show predicted outcomes for bracket matchups

### Backend Integration
1. **Team Matching**: Match GotSport team IDs to your `team_id_master` UUIDs
2. **Power Score Lookup**: Get current rankings for event teams
3. **Bracket Analysis**: Calculate metrics (strength, competitiveness, etc.)
4. **Audit Reports**: Generate reports with suggestions

## Example: Complete Workflow

```bash
# 1. List teams and export to JSON
python scripts/list_event_teams.py --event-id 40550
# Output: data/raw/event_40550_teams.json

# 2. (Optional) Scrape games from event
python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"
# Output: data/raw/scraped_event_40550_*.jsonl

# 3. (Optional) Import games
python scripts/import_games_enhanced.py data/raw/scraped_event_*.jsonl gotsport

# 4. (Optional) Recalculate rankings
python scripts/calculate_rankings.py

# 5. Use JSON with your frontend/backend to:
#    - Display teams by bracket
#    - Compare teams using ComparePanel
#    - Predict outcomes using match prediction
#    - Audit bracket placements
```

## Data Structure Details

### EventTeam Class
```python
@dataclass
class EventTeam:
    team_id: str              # GotSport team ID (e.g., "3519647")
    team_name: str            # Full team name
    bracket_name: str         # Bracket identifier (e.g., "U10B")
    age_group: Optional[str]  # Age group (e.g., "U10")
    gender: Optional[str]     # Gender code ("M" or "F")
    division: Optional[str]   # Division/bracket name
```

### JSON Structure
- **Top Level**: Object with bracket names as keys
- **Each Bracket**: Array of team objects
- **Team Object**: Contains all EventTeam fields as JSON

## Next Steps for Enhancement

1. **Add Power Scores to JSON**: Enhance export to include current power scores
2. **Bracket Analysis Script**: Create script to analyze bracket strength
3. **Frontend Component**: Build UI component to display event brackets
4. **Audit Dashboard**: Create dashboard for bracket auditing
5. **Automated Suggestions**: Use ML to suggest optimal bracket placements

## Documentation Files

- `docs/EVENT_SCRAPER_COMPLETE.md` - Full detailed documentation
- `docs/EVENT_SCRAPER_QUICK_REFERENCE.md` - Quick reference guide
- `docs/EVENT_SCRAPER_SUMMARY.md` - This file (overview)

## Key Benefits

1. **Automated Extraction**: No manual copying of team lists
2. **Structured Data**: JSON format ready for programmatic use
3. **Bracket Organization**: Teams already grouped by bracket
4. **Integration Ready**: Works with your existing compare/prediction features
5. **Audit Support**: Perfect for verifying bracket appropriateness

## Questions or Issues?

- Check `docs/EVENT_SCRAPER_COMPLETE.md` for detailed documentation
- Review `docs/EVENT_SCRAPER_QUICK_REFERENCE.md` for quick examples
- The JSON output is designed to work directly with your PitchRank features

