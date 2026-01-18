# SincSports Exploration Findings

## Summary

Initial exploration of SincSports reveals:

### ✅ What We Know

1. **Site Structure**:
   - ASP.NET application (.aspx pages)
   - Uses POST forms for search functionality
   - Has JavaScript/AJAX functionality (detected API calls)
   - robots.txt allows scraping (only blocks images, photos, login pages)

2. **Search Functionality**:
   - Uses POST form to `/sicClubs.aspx?sinc=Y`
   - JavaScript function `SearchClubs()` handles search
   - Form has 39 inputs (likely includes ViewState and filter options)
   - Search filters: State, Age, Alpha (name prefix)

3. **Team URL Patterns**:
   - `/team/team.aspx?id=12345` - Redirects to this pattern
   - `/sicclub.aspx?id=12345` - Club page pattern
   - Team IDs appear to be numeric (based on test pattern)

### ❓ What We Need to Discover

1. **Team ID Format**:
   - Need to find actual team IDs from search results
   - Verify if numeric or alphanumeric
   - Check if IDs are sequential or have specific format

2. **Game Data Access**:
   - Do team pages show game history?
   - Is there a separate games endpoint?
   - What does game/match data look like?

3. **API Endpoints**:
   - Are there AJAX endpoints for data?
   - Can we get JSON responses?
   - What authentication is required?

## Key Discovery: Team Mapping Strategy

**Good News**: The PitchRank system already supports multiple providers!

### How It Works

1. **Master Teams**: One team record per actual team (identified by UUID)
2. **Provider IDs**: Each provider has its own team ID format
3. **Alias Map**: Links provider IDs to master teams
   - GotSport team ID → Master team UUID
   - SincSports team ID → Same master team UUID (if same team)

### Example Flow

```
GotSport Team:
  provider_team_id: "544491"
  team_name: "FC Dallas U12 Boys"
  → team_id_master: "abc-123-uuid"

SincSports Team:
  provider_team_id: "12345"  (different format!)
  team_name: "FC Dallas U12 Boys"  (same team!)
  → Fuzzy match finds existing master team
  → Links to same team_id_master: "abc-123-uuid"
  
Result: Games from both providers contribute to same team's ranking!
```

### Implementation Steps

1. **Add SincSports Provider**:
   ```sql
   INSERT INTO providers (code, name, base_url) 
   VALUES ('sincsports', 'SincSports', 'https://soccer.sincsports.com');
   ```

2. **Scrape SincSports Teams**:
   - Discover teams via search or listing
   - Extract team IDs and metadata
   - Use fuzzy matching to link to existing master teams

3. **Create Alias Mappings**:
   - If fuzzy match finds existing team: Link SincSports ID to that master team
   - If no match: Create new master team and link SincSports ID

4. **Import Games**:
   - Scrape games using SincSports team IDs
   - Import pipeline automatically matches to master teams via alias map
   - Games contribute to rankings alongside GotSport games

## Next Steps

### Immediate Actions

1. **Browser Dev Tools Analysis** (CRITICAL):
   - Open https://soccer.sincsports.com/sicClubs.aspx?sinc=Y
   - Open Network tab
   - Perform a search (select filters, click "Search Teams")
   - Document:
     - All AJAX/API requests
     - Response formats (JSON? HTML?)
     - Request parameters
     - Team URLs in results

2. **Find Real Team Examples**:
   - Perform search to get actual team results
   - Click on a team to see:
     - Full URL structure
     - Team ID format
     - Team detail page structure
     - Game history location (if visible)

3. **Test Team Page Access**:
   - Try accessing a real team page programmatically
   - Check if game history is visible
   - Document data structure

### Development Tasks

1. **Create SincSports Scraper** (`src/scrapers/sincsports.py`):
   - Implement team discovery (search or listing)
   - Implement game scraping from team pages
   - Handle POST form submissions
   - Parse HTML responses

2. **Test Team Matching**:
   - Scrape a few SincSports teams
   - Test fuzzy matching against existing GotSport teams
   - Verify alias map creation
   - Confirm same master team is used

3. **Integration Testing**:
   - Test full scraping workflow
   - Verify games import correctly
   - Check rankings include games from both providers

## Technical Notes

### Form Submission

The search form uses POST with ASP.NET ViewState. We'll need to:
- Extract ViewState from initial page load
- Include ViewState in POST request
- Handle form field names (they use ASP.NET naming: `ctl00_ContentPlaceHolder1_...`)

### Potential Challenges

1. **ViewState Handling**: ASP.NET forms require ViewState for POST requests
2. **Dynamic Content**: Search results may load via AJAX
3. **Rate Limiting**: Need to respect server resources
4. **Authentication**: May be required for detailed data

### Recommended Approach

1. **Start with Selenium** (if AJAX-heavy):
   - Can handle JavaScript rendering
   - Can interact with forms naturally
   - Slower but more reliable for complex sites

2. **Optimize to Requests** (if possible):
   - Once we understand the API/endpoints
   - Much faster for bulk scraping
   - Requires reverse-engineering AJAX calls

## Resources

- **Exploration Script**: `scripts/explore_sincsports.py`
- **Integration Plan**: `docs/SINCSPORTS_EXPLORATION.md`
- **Team Matching Docs**: `docs/TEAM_MATCHING_EXPLAINED.md`
- **Scraper Template**: `src/scrapers/template.py`


















