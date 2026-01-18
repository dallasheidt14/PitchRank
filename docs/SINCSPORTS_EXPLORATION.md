# SincSports Exploration & Integration Plan

## Overview

This document tracks the exploration and integration of SincSports as a new data source for PitchRank. The key challenge is mapping SincSports team IDs to existing master teams that were originally created from GotSport.

## Current Architecture Understanding

### Team Storage System

PitchRank uses a **multi-provider team mapping system**:

1. **`teams` table**: Master team records
   - `team_id_master` (UUID) - Primary identifier
   - `provider_team_id` (TEXT) - Provider-specific ID (e.g., GotSport ID)
   - `provider_id` (UUID) - References the provider
   - **Key**: `UNIQUE(provider_id, provider_team_id)` - One team can have multiple provider IDs!

2. **`team_alias_map` table**: Maps provider IDs to master teams
   - `provider_id` + `provider_team_id` → `team_id_master`
   - Supports multiple providers mapping to the same master team
   - Used for fast O(1) lookups during game import

### Matching Strategy

The system uses a **3-tier matching strategy**:

1. **Direct ID Match**: Check `team_alias_map` for existing mapping
2. **Alias Map Lookup**: Check historical mappings
3. **Fuzzy Matching**: Match by team name, club name, age group, gender

**Key Insight**: The system already supports multiple providers! We just need to:
- Add SincSports as a new provider
- Create mappings from SincSports team IDs to master teams
- Use the existing fuzzy matching to link SincSports teams to existing GotSport teams

## SincSports Site Analysis

### Site Structure

- **Base URL**: https://soccer.sincsports.com
- **Technology**: ASP.NET (.aspx pages)
- **Main Pages**:
  - `/sicClubs.aspx` - Clubs & Teams directory
  - `/sictournaments.aspx` - Tournaments
  - `/sicleagues.aspx` - Leagues
  - `/sicrank.aspx` - USA Rank rankings

### Search Functionality

The site has a search interface with filters:
- Gender: Boys/Men, Girls/Women, Co-Ed
- State: All US states + Canada, Mexico, Puerto Rico
- Age Groups: U04 through U19, Adult
- Type: Club Team, Recreation, Adult, High School, Other
- USA Rank: Gold, Silver, Bronze, Red, Blue, Green, Non-Ranked

**Critical**: Need to inspect browser network requests to understand:
- How search results are loaded (AJAX? POST form?)
- What the team URL structure looks like
- How team IDs are formatted

## Integration Strategy

### Phase 1: Discovery (Current)

**Goals**:
1. Understand SincSports team ID format
2. Find how to access team data
3. Find how to access game/match data
4. Identify API endpoints (if any)

**Actions**:
- [x] Create exploration script
- [ ] Use browser dev tools to inspect network requests
- [ ] Document team URL patterns
- [ ] Document team ID format
- [ ] Find game/match endpoints

### Phase 2: Provider Setup

**Steps**:

1. **Add Provider to Database**:
```sql
INSERT INTO providers (code, name, base_url) 
VALUES ('sincsports', 'SincSports', 'https://soccer.sincsports.com')
ON CONFLICT (code) DO NOTHING;
```

2. **Add Provider to Config** (`config/settings.py`):
```python
PROVIDERS = {
    # ... existing ...
    'sincsports': {
        'code': 'sincsports',
        'name': 'SincSports',
        'base_url': 'https://soccer.sincsports.com',
        'adapter': 'src.scrapers.sincsports'
    }
}
```

### Phase 3: Scraper Implementation

**Key Requirements**:

1. **Team Discovery**:
   - How do we find teams to scrape?
   - Can we search by filters?
   - Is there a team listing endpoint?

2. **Team ID Format**:
   - Numeric? (e.g., `12345`)
   - Alphanumeric? (e.g., `ABC123`)
   - In URL? (e.g., `/team.aspx?id=12345`)
   - In data attributes?

3. **Game Data Access**:
   - Team detail page with game history?
   - Separate games endpoint?
   - Tournament/league pages?

4. **Scraper Pattern**:
   - **If API exists**: REST API scraper (like GotSport)
   - **If no API**: Web scraper with BeautifulSoup/Selenium

### Phase 4: Team Mapping Strategy

**The Challenge**: 
- Existing teams have GotSport IDs
- SincSports teams will have different IDs
- Need to map SincSports teams to existing master teams

**Solution**: Use existing fuzzy matching system!

**Process**:

1. **Scrape SincSports Team**:
   ```python
   # Get team data from SincSports
   sincsports_team = {
       'provider_team_id': 'SINC12345',  # SincSports ID
       'team_name': 'FC Dallas U12 Boys',
       'club_name': 'FC Dallas',
       'age_group': 'u12',
       'gender': 'Male',
       'state': 'TX'
   }
   ```

2. **Match to Master Team**:
   ```python
   # Use existing GameHistoryMatcher
   matcher = GameHistoryMatcher(supabase, sincsports_provider_id)
   
   match_result = matcher.match_team(
       provider_id=sincsports_provider_id,
       provider_team_id='SINC12345',
       team_name='FC Dallas U12 Boys',
       club_name='FC Dallas',
       age_group='u12',
       gender='Male'
   )
   
   # Result:
   # - If match found: Use existing team_id_master
   # - If no match: Create new master team
   # - Create entry in team_alias_map linking SincSports ID to master team
   ```

3. **Create Alias Mapping**:
   ```sql
   INSERT INTO team_alias_map (
       provider_id,
       provider_team_id,
       team_id_master,
       match_confidence,
       match_method,
       review_status
   ) VALUES (
       'sincsports-uuid',
       'SINC12345',
       'existing-master-team-uuid',
       0.95,  -- High confidence fuzzy match
       'fuzzy_auto',
       'approved'
   );
   ```

**Benefits**:
- Same team from different providers → Same master team
- Games from both providers contribute to same team's ranking
- No duplicate teams in rankings
- Automatic deduplication

### Phase 5: Game Import

**Process**:

1. **Scrape Games from SincSports**:
   ```python
   scraper = SincSportsScraper(supabase, 'sincsports')
   games = scraper.scrape_team_games('SINC12345', since_date=last_scrape)
   ```

2. **Import Games** (uses existing pipeline):
   ```python
   # Games have SincSports team IDs
   game = {
       'provider': 'sincsports',
       'team_id': 'SINC12345',
       'opponent_id': 'SINC67890',
       # ... other game data
   }
   
   # Import pipeline automatically:
   # 1. Matches team_id to master team via team_alias_map
   # 2. Matches opponent_id to master team
   # 3. Creates game record with master team IDs
   ```

3. **Result**: Games from SincSports are linked to master teams, contributing to rankings alongside GotSport games!

## Implementation Checklist

### Discovery Phase
- [ ] Run exploration script
- [ ] Use browser dev tools to inspect network requests
- [ ] Document team URL structure
- [ ] Document team ID format
- [ ] Find game/match data endpoints
- [ ] Test accessing a sample team's data
- [ ] Test accessing a sample team's game history

### Provider Setup
- [ ] Add SincSports to `providers` table
- [ ] Add SincSports to `config/settings.py`
- [ ] Verify provider UUID is created

### Scraper Development
- [ ] Create `src/scrapers/sincsports.py`
- [ ] Implement `scrape_team_games()` method
- [ ] Implement `validate_team_id()` method
- [ ] Handle authentication (if required)
- [ ] Handle rate limiting
- [ ] Test with sample teams

### Team Mapping
- [ ] Test fuzzy matching with SincSports teams
- [ ] Verify alias map creation
- [ ] Test matching SincSports team to existing GotSport team
- [ ] Verify same master team is used

### Game Import
- [ ] Test importing games from SincSports
- [ ] Verify games link to correct master teams
- [ ] Verify games don't duplicate existing games
- [ ] Test incremental scraping

### Integration Testing
- [ ] Test full scraping workflow
- [ ] Verify rankings include games from both providers
- [ ] Test error handling
- [ ] Performance testing

## Key Questions to Answer

1. **Team ID Format**: What does a SincSports team ID look like?
2. **Team Discovery**: How do we find teams to scrape? (Search? Listing? Tournament pages?)
3. **Game Data**: Where is game history stored? (Team page? Separate endpoint?)
4. **API Access**: Is there an API, or do we need web scraping?
5. **Authentication**: Is authentication required?
6. **Rate Limits**: What are the rate limits?
7. **Data Structure**: What does the game/match data structure look like?

## Next Steps

1. **Immediate**: Use browser dev tools to inspect SincSports site
   - Open https://soccer.sincsports.com/sicClubs.aspx?sinc=Y
   - Open Network tab
   - Perform a search
   - Document all requests/responses
   - Click on a team to see URL structure

2. **Short-term**: Create initial scraper based on findings
   - Implement basic team discovery
   - Implement game scraping
   - Test with sample data

3. **Medium-term**: Full integration
   - Add to scraping pipeline
   - Test team matching
   - Verify rankings accuracy

## Resources

- **Exploration Script**: `scripts/explore_sincsports.py`
- **Scraper Template**: `src/scrapers/template.py`
- **Reference Implementation**: `src/scrapers/gotsport.py`
- **Team Matching Docs**: `docs/TEAM_MATCHING_EXPLAINED.md`
- **System Overview**: `docs/SYSTEM_OVERVIEW.md`


















