# ECNL Scraping Investigation

## Overview

Investigation of scraping ECNL (Elite Club National League) game data from https://theecnl.com/sports/2023/8/8/ECNLG_0808235238.aspx

## Key Findings

### 1. Platform Architecture

The ECNL website uses **AthleteOne/TGS (Total Global Sports)** API, which is the same platform already integrated in the codebase:

- **Base URL**: `https://api.athleteone.com`
- **Platform**: Sidearm Sports (hosting) + AthleteOne/TGS (data backend)
- **Existing Infrastructure**: The codebase already has AthleteOne scrapers implemented

### 2. API Endpoints Discovered

From network analysis, the following API endpoints are used:

1. **Get Event List by Season**
   ```
   GET /api/Script/get-event-list-by-season-id/{orgSeasonID}/{eventID}
   ```
   - Example: `https://api.athleteone.com/api/Script/get-event-list-by-season-id/69/0`
   - Returns list of conferences/events for a season

2. **Get Division List by Event**
   ```
   GET /api/Script/get-division-list-by-event-id/{orgID}/{eventID}/{scheduleID}/{flightID}
   ```
   - Example: `https://api.athleteone.com/api/Script/get-division-list-by-event-id/9/3925/0/0`
   - Returns age groups/flights for a conference

3. **Get Conference Schedules** (Main endpoint for game data)
   ```
   GET /api/Script/get-conference-schedules/{orgID}/{orgSeasonID}/{eventID}/{flightID}/0
   ```
   - Example: `https://api.athleteone.com/api/Script/get-conference-schedules/9/69/3925/0/0`
   - Returns HTML table with game schedule data

### 3. ECNL-Specific Parameters

From testing the website interface:

- **Organization ID (org_id)**: `9` (ECNL organization)
- **Organization Season ID (org_season_id)**: `69` (2025-26 season)
- **Event IDs**: Vary by conference (e.g., `3925` for "ECNL Girls Mid-Atlantic 2025-26")
- **Flight IDs**: Vary by age group (e.g., `0` for G2010)

**Conferences Available:**
- ECNL Girls Mid-Atlantic 2025-26
- ECNL Girls Midwest 2025-26
- ECNL Girls New England 2025-26
- ECNL Girls North Atlantic 2025-26
- ECNL Girls Northern Cal 2025-26
- ECNL Girls Northwest 2025-26
- ECNL Girls Ohio Valley 2025-26
- ECNL Girls Southeast 2025-26
- ECNL Girls Southwest 2025-26
- ECNL Girls Texas 2025-26

**Age Groups Available:**
- G2013
- G2012
- G2011
- G2010
- G2009
- G2008/2007

### 4. Existing Codebase Integration

The codebase already has:

1. **AthleteOne Client** (`src/providers/athleteone_client.py`)
   - Handles API requests
   - Supports `get_conference_schedule_html()` method
   - Already configured with proper headers and retry logic

2. **AthleteOne HTML Parser** (`src/providers/athleteone_html_parser.py`)
   - Parses HTML tables from conference schedules
   - Extracts game data (teams, scores, dates, venues)
   - Returns `ParsedAthleteOneGame` objects

3. **AthleteOne Scraper** (`src/scrapers/athleteone_scraper.py`)
   - Converts parsed games to `GameData` format
   - Handles team ID generation
   - Creates both home and away perspectives

4. **AthleteOne Event Scraper** (`src/scrapers/athleteone_event.py`)
   - Scrapes entire events/conferences
   - Extracts teams from events

### 5. Data Flow

The ECNL website works as follows:

1. User selects **Conference** → triggers API call to get event ID
2. User selects **Age Group** → triggers API call to get flight ID
3. Page loads schedule HTML via `get-conference-schedules` endpoint
4. HTML is rendered in a table format
5. Games are displayed with: GM#, Game Info, Team & Venue, Details

## Recommendations

### Option 1: Use Existing AthleteOne Infrastructure (Recommended)

**Pros:**
- Reuses existing, tested code
- Minimal new code required
- Consistent with other AthleteOne integrations

**Implementation:**
1. Create a discovery script to map ECNL conferences to event/flight IDs
2. Use existing `AthleteOneScraper.scrape_conference_games()` method
3. Create ECNL-specific wrapper that:
   - Discovers all conferences and age groups
   - Maps them to org_id=9, org_season_id=69
   - Iterates through all event/flight combinations
   - Scrapes games using existing infrastructure

**Files to Create:**
- `scripts/discover_ecnl_conferences.py` - Map conferences to event/flight IDs
- `src/scrapers/ecnl_scraper.py` - ECNL-specific wrapper (optional, can use AthleteOne directly)

### Option 2: Create ECNL-Specific Scraper

**Pros:**
- More explicit ECNL integration
- Can add ECNL-specific metadata

**Implementation:**
1. Create `ECNLScraper` that extends or wraps `AthleteOneScraper`
2. Hardcode ECNL org_id=9, org_season_id=69
3. Implement conference/age group discovery
4. Register as new provider in `config/settings.py`

### Option 3: Enhance Existing AthleteOne Event Scraper

**Pros:**
- Minimal changes to existing code
- ECNL becomes just another AthleteOne event source

**Implementation:**
1. Add ECNL event discovery to `scripts/discover_athleteone_november_events.py`
2. Use existing `scripts/scrape_athleteone_weekly.py`
3. Store ECNL events in same format as other AthleteOne events

## Implementation Plan (Recommended: Option 1)

### Phase 1: Discovery

1. **Create Conference Discovery Script**
   ```python
   # scripts/discover_ecnl_conferences.py
   # - Load ECNL schedule page
   # - Extract all conference options
   # - For each conference, extract event ID
   # - For each age group, extract flight ID
   # - Save to data/raw/ecnl_conferences.json
   ```

2. **Test API Access**
   - Verify API endpoints are accessible
   - Test with sample conference/age group
   - Verify HTML parsing works with ECNL format

### Phase 2: Integration

1. **Create ECNL Scraper Wrapper**
   ```python
   # src/scrapers/ecnl_scraper.py
   # - Load discovered conferences
   # - Iterate through all conference/age group combinations
   # - Use AthleteOneScraper.scrape_conference_games()
   # - Add ECNL-specific metadata
   ```

2. **Register Provider** (if creating new provider)
   - Add to `config/settings.py`
   - Add database entry for 'ecnl' provider

### Phase 3: Testing

1. **Test with Single Conference**
   - Scrape one conference/age group
   - Verify game data quality
   - Check team name extraction

2. **Test Full Scrape**
   - Scrape all conferences
   - Verify no duplicates
   - Check data completeness

### Phase 4: Production

1. **Create Scheduled Job**
   - Weekly scraper for incremental updates
   - Or integrate into existing AthleteOne weekly scraper

2. **Data Import**
   - Use existing import pipeline
   - Map to teams database
   - Handle team matching

## Technical Details

### API Response Format

The `get-conference-schedules` endpoint returns HTML, not JSON. The HTML contains:
- Table with game rows
- Each row has: Game number, Date/Time, Home Team, Away Team, Score, Venue
- Structure matches existing `athleteone_html_parser.py` expectations

### Team ID Strategy

ECNL doesn't provide team IDs in the API response. Options:
1. Use existing hash-based ID generation from `AthleteOneScraper._generate_team_id()`
2. Match team names to existing teams in database
3. Create ECNL-specific team ID format: `ecnl:{conference}:{age_group}:{team_name_hash}`

### Data Quality Considerations

1. **Team Name Normalization**
   - ECNL team names may need normalization
   - Handle club name variations
   - Match to existing teams where possible

2. **Score Parsing**
   - Verify score format in HTML
   - Handle incomplete games
   - Parse result (W/L/D)

3. **Date/Time Parsing**
   - ECNL may use different date formats
   - Handle timezone issues
   - Parse game times correctly

## Next Steps

1. **Immediate**: Create discovery script to map all ECNL conferences to event/flight IDs
2. **Short-term**: Test scraping with one conference using existing AthleteOne infrastructure
3. **Medium-term**: Create ECNL-specific scraper wrapper or enhance existing AthleteOne scraper
4. **Long-term**: Integrate into production scraping pipeline

## Files to Review

- `src/providers/athleteone_client.py` - API client
- `src/providers/athleteone_html_parser.py` - HTML parser
- `src/scrapers/athleteone_scraper.py` - Main scraper
- `src/scrapers/athleteone_event.py` - Event-level scraper
- `scripts/discover_athleteone_november_events.py` - Discovery pattern
- `scripts/scrape_athleteone_weekly.py` - Weekly scraper pattern

## Notes

- The ECNL website is a Sidearm Sports site, but data comes from AthleteOne/TGS API
- Existing AthleteOne infrastructure should work with minimal modifications
- May need to handle ECNL-specific team naming conventions
- Consider rate limiting when scraping all conferences/age groups












