# Event Scraper - Quick Reference Guide

## Summary of Scripts Created

### 1. **Core Scraper**: `src/scrapers/gotsport_event.py`
- **Purpose**: Extract teams and games from GotSport events
- **Key Features**:
  - Extracts teams from `jsonTeamRegs` JavaScript data
  - Organizes teams by brackets (age group + gender)
  - Scrapes games for all teams in an event
  - Filters games by event name

### 2. **List Teams Script**: `scripts/list_event_teams.py`
- **Purpose**: Display teams organized by bracket
- **Usage**: `python scripts/list_event_teams.py --event-id 40550`
- **Output**: 
  - Console display with formatted tables
  - **JSON export** to `data/raw/event_{event_id}_teams.json`
- **Use Case**: Quick inspection and JSON export for bracket auditing

### 3. **Scrape Games Script**: `scripts/scrape_event.py`
- **Purpose**: Scrape all games from event teams
- **Usage**: `python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"`
- **Output**: JSONL file with game data
- **Use Case**: Collect tournament games for analysis/import

## JSON Output Format

The `list_event_teams.py` script exports teams in this format:

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
  "U11B": [
    ...
  ]
}
```

## Using for Bracket Auditing

### Step 1: Export Teams
```bash
python scripts/list_event_teams.py --event-id 40550
```
This creates: `data/raw/event_40550_teams.json`

### Step 2: Load JSON in Your Application
```javascript
// In your frontend or analysis script
const teamsByBracket = require('./data/raw/event_40550_teams.json');

// For each bracket
Object.entries(teamsByBracket).forEach(([bracketName, teams]) => {
  console.log(`Bracket: ${bracketName} (${teams.length} teams)`);
  
  // Get team IDs for comparison
  const teamIds = teams.map(t => t.team_id);
  
  // Use with PitchRank compare feature
  // Compare teams within bracket to verify appropriate grouping
});
```

### Step 3: Compare Teams Using PitchRank Features

**Using Compare Feature**:
- Load team IDs from JSON
- For each bracket, compare teams using `ComparePanel` component
- Check if teams in same bracket have similar power scores
- Identify outliers that might be in wrong bracket

**Using Match Prediction**:
- Use `useMatchPrediction` hook to predict outcomes
- If predictions show extreme mismatches, teams might be misplaced
- Compare predicted scores across bracket to identify strength disparities

### Step 4: Generate Audit Report

```python
# Example: Analyze bracket strength distribution
import json

with open('data/raw/event_40550_teams.json') as f:
    brackets = json.load(f)

# For each bracket, you can:
# 1. Get team power scores from your database
# 2. Calculate bracket strength statistics
# 3. Identify teams that are outliers
# 4. Suggest bracket adjustments
```

## Integration Points

### Frontend Integration
1. **Load Event Teams**: Create API endpoint to load event teams JSON
2. **Bracket Display**: Show teams grouped by bracket
3. **Compare Feature**: Allow comparing teams within/across brackets
4. **Prediction Feature**: Show predicted outcomes for bracket matchups

### Backend Integration
1. **Team Matching**: Match GotSport team IDs to `team_id_master` UUIDs
2. **Power Score Lookup**: Get current power scores for event teams
3. **Bracket Analysis**: Calculate bracket strength metrics
4. **Audit Reports**: Generate reports showing bracket appropriateness

## Example Workflow

```bash
# 1. List teams and export to JSON
python scripts/list_event_teams.py --event-id 40550

# 2. Scrape games from event (optional)
python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"

# 3. Import games (if scraped)
python scripts/import_games_enhanced.py data/raw/scraped_event_*.jsonl gotsport

# 4. Recalculate rankings
python scripts/calculate_rankings.py

# 5. Use JSON with your frontend to:
#    - Display teams by bracket
#    - Compare teams within brackets
#    - Predict match outcomes
#    - Audit bracket placements
```

## Files Created

1. `src/scrapers/gotsport_event.py` - Core scraper class
2. `scripts/list_event_teams.py` - List teams by bracket
3. `scripts/scrape_event.py` - Scrape games from event
4. `docs/EVENT_SCRAPER_COMPLETE.md` - Full documentation
5. `docs/EVENT_SCRAPER_QUICK_REFERENCE.md` - This file

## Next Steps for Your Use Case

1. **Enhance JSON Export**: Add power scores and rankings to JSON output
2. **Create Bracket Analysis Tool**: Script to analyze bracket strength
3. **Frontend Integration**: Add event bracket viewer to your site
4. **Audit Dashboard**: Create UI to compare teams and suggest bracket changes
5. **Automated Suggestions**: Use ML predictions to suggest optimal bracket placements

