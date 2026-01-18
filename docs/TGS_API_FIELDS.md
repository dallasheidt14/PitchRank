# TGS API Available Fields

## Game Data Fields (from `get-schedules-by-flight` endpoint)

### Currently Extracted ✅
- `matchID` → Used internally
- `gameDate` → `game_date` 
- `gameTime` → `game_time`
- `hometeamID` → `team_id` / `opponent_id`
- `awayteamID` → `opponent_id` / `team_id`
- `homeTeam` → `team_name` / `opponent_name`
- `awayTeam` → `opponent_name` / `team_name`
- `homeTeamClub` → `club_name` / `opponent_club_name`
- `awayTeamClub` → `opponent_club_name` / `club_name`
- `hometeamscore` → `goals_for` / `goals_against`
- `awayteamscore` → `goals_against` / `goals_for`
- `venue` → `venue`
- `zip` → Used to extract `state` and `state_code`
- `division` → Used to extract `age_year` and `gender`
- `flight` → Could be used for `division_name`
- `eventID` → `event_id`
- `scheduleID` → `schedule_id`

### Available but NOT Currently Extracted ⚠️
- `gamenumber` - Game number/identifier
- `gameDate1` - Alternative date format
- `complexID` - Venue complex ID
- `complex` - Venue complex name (e.g., "St. Julien Park")
- `venueID` - Venue ID
- `isactive` - Whether game is active
- `divisionID` - Division ID
- `flightID` - Flight ID
- `flightgroupID` - Flight group ID
- `timeslotID` - Time slot ID
- `type` - Game type (e.g., "Crossover")
- `homeClubLogo` - URL to home team club logo
- `awayClubLogo` - URL to away team club logo
- `awayTeamClubID` - Away team club ID
- `homeTeamClubID` - Home team club ID
- `gameTimeText` - Formatted time text (e.g., "09:00 AM")
- `flagText` - Flag text (e.g., "Box Score")
- `publicNote` - Public notes about the game
- `status` - Game status (e.g., "On Time")
- `friendly` - Whether it's a friendly match (0/1)
- `matchDelayedMin` - Minutes delayed
- `hometeamPKscore` - Home team penalty kick score
- `awayteamPKscore` - Away team penalty kick score
- `statusID` - Status ID

### Division/Flight Data Fields (from `get-flight-division-by-flightID` endpoint)
- `divisionID` - Division ID
- `divisionName` - Division name (e.g., "B2008/2007")
- `flightID` - Flight ID
- `flightName` - Flight name (e.g., "ECNL Regional League")
- `eventID` - Event ID
- `hasActiveSchedule` - Whether schedule is active
- `hasTournamentFormatBracket` - Tournament bracket flag
- `divisionGender` - Division gender ("m" or "f")
- `teamCount` - Number of teams in division

## Recommendations

### High Value Fields to Add:
1. **`complex`** - Venue complex name (more descriptive than just `venue`)
2. **`type`** - Game type (e.g., "Crossover", "Regular", "Playoff")
3. **`status`** - Game status (e.g., "On Time", "Delayed", "Cancelled")
4. **`flight`** - Flight name (could be used as `division_name` or `competition`)
5. **`homeTeamClubID` / `awayTeamClubID`** - Club IDs (useful for matching)
6. **`hometeamPKscore` / `awayteamPKscore`** - PK scores (for tournaments)

### Medium Value Fields:
- `gameTimeText` - Formatted time (already have `gameTime` but formatted might be useful)
- `friendly` - Friendly match flag
- `matchDelayedMin` - Delay information
- `publicNote` - Public notes

### Low Value Fields:
- `gamenumber` - Usually null
- `gameDate1` - Alternative format, redundant
- `flagText` - Usually just "Box Score"
- `statusID` - Usually null
- Logo URLs - Not needed for data import

## Current CSV Schema

```python
REQUIRED_COLUMNS = [
    "provider",              # ✅ "tgs"
    "scrape_run_id",         # ✅ Generated
    "event_id",              # ✅ From eventID
    "event_name",            # ✅ From get_event_name()
    "schedule_id",           # ✅ From scheduleID
    "age_year",              # ✅ Extracted from division name
    "gender",                # ✅ Extracted from division name
    "team_id",               # ✅ From hometeamID/awayteamID
    "team_id_source",        # ✅ Same as team_id
    "team_name",             # ✅ From homeTeam/awayTeam
    "club_name",             # ✅ From homeTeamClub/awayTeamClub
    "opponent_id",           # ✅ From awayteamID/hometeamID
    "opponent_id_source",    # ✅ Same as opponent_id
    "opponent_name",         # ✅ From awayTeam/homeTeam
    "opponent_club_name",    # ✅ From awayTeamClub/homeTeamClub
    "state",                 # ✅ Extracted from zip
    "state_code",            # ✅ Extracted from zip
    "game_date",             # ✅ From gameDate
    "game_time",             # ✅ From gameTime
    "home_away",             # ✅ "H" or "A"
    "goals_for",             # ✅ From hometeamscore/awayteamscore
    "goals_against",         # ✅ From awayteamscore/hometeamscore
    "result",                # ✅ Computed from scores
    "venue",                 # ✅ From venue
    "source_url",            # ✅ Generated
    "scraped_at"             # ✅ Timestamp
]
```

## Potential Additions

If we want to add more fields, we could add:
- `competition` - Could use `flight` field
- `division_name` - Could use `flight` field  
- `venue_complex` - From `complex` field
- `game_type` - From `type` field
- `game_status` - From `status` field
- `club_id` - From `homeTeamClubID` / `awayTeamClubID`
- `pk_score_home` - From `hometeamPKscore`
- `pk_score_away` - From `awayteamPKscore`









