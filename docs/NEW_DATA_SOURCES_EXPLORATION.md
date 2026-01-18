# New Data Sources Exploration

## Overview

This document explores integrating three new data sources into PitchRank's scraping infrastructure:
1. **SincSports** (https://soccer.sincsports.com)
2. **Modular11** 
3. **AthleteOne**

## Current Scraping Architecture

### Architecture Overview

PitchRank uses a modular scraper architecture:

```
BaseProvider (ABC)
    ↓
BaseScraper (combines BaseProvider + ETLPipeline)
    ↓
Provider-specific scrapers (GotSportScraper, etc.)
```

### Key Components

1. **Base Classes** (`src/base/__init__.py`):
   - `GameData`: Standardized game data structure
   - `TeamData`: Standardized team data structure
   - `BaseProvider`: Abstract base for all providers
   - `BaseScraper`: Combines provider interface with ETL pipeline

2. **Scraper Implementation** (`src/scrapers/base.py`):
   - Handles team discovery (`_get_teams_to_scrape()`)
   - Incremental scraping (`_get_last_scrape_date()`)
   - Logging (`_log_team_scrape()`)
   - Data conversion (`_game_data_to_dict()`)

3. **Provider Configuration** (`config/settings.py`):
   ```python
   PROVIDERS = {
       'gotsport': {
           'code': 'gotsport',
           'name': 'GotSport',
           'base_url': 'https://www.gotsport.com',
           'adapter': 'src.scrapers.gotsport'
       },
       # ... other providers
   }
   ```

4. **Database Schema**:
   - `providers` table: Stores provider metadata
   - `teams` table: Links teams to providers via `provider_id`
   - `team_scrape_log` table: Tracks scraping activity

### Current GotSport Implementation

**File**: `src/scrapers/gotsport.py`

**Key Features**:
- Uses GotSport API: `https://system.gotsport.com/api/v1/teams/{team_id}/matches`
- Supports ZenRows proxy (optional)
- Incremental scraping with date filtering
- Rate limiting (1.5-2.5s delays)
- SSL error handling with retries
- Club name extraction

**API Pattern**:
```python
def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
    api_url = f"{self.BASE_URL}/teams/{normalized_team_id}/matches"
    params = {'past': 'true'}
    # ... fetch and parse matches
```

## Site Analysis

### 1. SincSports (https://soccer.sincsports.com)

#### Site Overview
- **URL**: https://soccer.sincsports.com/sicClubs.aspx?sinc=Y
- **Purpose**: Tournament management and team rankings
- **Features**: Clubs & Teams directory, USA Rank rankings, Tournaments, Leagues

#### Data Available
From the site exploration:
- **Clubs & Teams**: Searchable directory with filters:
  - Gender: Boys/Men, Girls/Women, Co-Ed
  - State: All US states + Canada, Mexico, Puerto Rico
  - Age Groups: U04 through U19, Adult
  - Type: Club Team, Recreation, Adult, High School, Other
  - USA Rank: Gold, Silver, Bronze, Red, Blue, Green, Non-Ranked
- **Tournaments**: Event listings (`/sictournaments.aspx`)
- **Leagues**: League listings (`/sicleagues.aspx`)
- **USA Rank**: Rankings system (`/sicrank.aspx`)

#### Technical Analysis

**Site Structure**:
- ASP.NET application (`.aspx` pages)
- Uses form-based filtering (dropdowns, checkboxes)
- Likely server-side rendering (no obvious client-side API)

**Potential Access Methods**:

1. **Web Scraping** (Most Likely):
   - Parse HTML tables after form submission
   - May require POST requests with form data
   - Need to handle pagination
   - May need to scrape individual team pages for game history

2. **API Discovery** (Recommended First Step):
   - Check browser network tab for AJAX calls
   - Look for JSON endpoints when filters change
   - May have hidden API endpoints

3. **Direct Contact**:
   - Contact SincSports support for API access
   - They may offer data export or API for partners

#### Implementation Strategy

**Phase 1: Discovery**
```python
# Check for API endpoints
# Inspect network requests when filters change
# Look for patterns like:
# - /api/clubs/search
# - /services/clubservice.asmx
# - JSON responses
```

**Phase 2: Web Scraping (if no API)**
```python
# Use requests + BeautifulSoup or Selenium
# Handle form submissions
# Parse team listings
# Navigate to team detail pages for game history
```

**Phase 3: Integration**
- Create `SincSportsScraper` class
- Map SincSports team IDs to PitchRank format
- Handle age group normalization (U04-U19)
- Extract game data from team pages

#### Challenges
- **Authentication**: May require login for detailed data
- **Rate Limiting**: Need to respect server load
- **Data Format**: May need to parse HTML tables
- **Team ID Format**: Unknown structure (may be numeric or alphanumeric)

#### Recommended Approach
1. **First**: Use browser dev tools to inspect network requests
2. **Second**: Contact SincSports for API access
3. **Third**: Implement web scraper if no API available

---

### 2. Modular11

#### Site Overview
- **Status**: Limited public information available
- **Purpose**: Tournament management system (assumed)

#### Research Needed

**Immediate Actions**:
1. Visit the Modular11 website
2. Identify the base URL
3. Check for:
   - Public API documentation
   - Developer resources
   - Data export features
   - Login requirements

**Questions to Answer**:
- What is the exact URL?
- Does it have a public API?
- What data is available (teams, games, tournaments)?
- Is authentication required?
- What is the team ID format?
- How are games structured?

#### Implementation Strategy

**Phase 1: Site Discovery**
```bash
# Visit site and document:
# - URL structure
# - Authentication requirements
# - Data endpoints
# - API availability
```

**Phase 2: API/Scraping Analysis**
- Check for REST/GraphQL APIs
- Inspect network requests
- Document data structures
- Identify rate limits

**Phase 3: Scraper Development**
- Follow same pattern as GotSportScraper
- Adapt to Modular11's data format

#### Next Steps
1. **User Action Required**: Provide Modular11 website URL
2. Explore site structure
3. Document findings
4. Create scraper implementation plan

---

### 3. AthleteOne

#### Site Overview
- **URL**: https://athleteone.com
- **Purpose**: Sports association management system
- **Features**: Player/staff registration, reporting, communication

#### Research Findings

From web search:
- Association System for managing sports organizations
- Player and staff registration
- Reporting capabilities
- Communication tools
- Privacy policy indicates data collection/monitoring

#### Technical Analysis

**Potential Access Methods**:

1. **API Access** (Preferred):
   - May have API for registered associations
   - Contact AthleteOne support for API documentation
   - May require partnership/agreement

2. **Web Scraping** (If no API):
   - Likely requires authentication
   - May have anti-scraping measures
   - Need to respect privacy policy

#### Implementation Strategy

**Phase 1: Contact & Documentation**
```python
# Priority: Contact AthleteOne support
# Questions:
# - Do you offer API access?
# - What data is available?
# - What are the authentication requirements?
# - Are there rate limits?
```

**Phase 2: API Integration** (If Available)
- Follow REST API patterns
- Implement OAuth/API key authentication
- Map AthleteOne data to PitchRank format

**Phase 3: Web Scraping** (If No API)
- Use Selenium for authenticated sessions
- Parse HTML/JSON responses
- Handle pagination and rate limiting

#### Challenges
- **Authentication**: Likely required
- **Privacy**: Must comply with privacy policy
- **Data Access**: May be restricted to registered associations
- **API Availability**: Unknown if public API exists

#### Recommended Approach
1. **First**: Contact AthleteOne support for API access
2. **Second**: Review their developer documentation (if available)
3. **Third**: Implement authenticated scraper if needed

---

## Integration Plan

### Step 1: Create Scraper Template

Create a template file that new scrapers can follow:

**File**: `src/scrapers/template.py`
```python
"""Template for new scraper implementations"""
from typing import List, Optional
from datetime import datetime
import logging

from src.scrapers.base import BaseScraper
from src.base import GameData

logger = logging.getLogger(__name__)


class TemplateScraper(BaseScraper):
    """Template scraper - replace with actual provider name"""
    
    BASE_URL = "https://example.com/api"
    
    def __init__(self, supabase_client, provider_code: str = 'template'):
        super().__init__(supabase_client, provider_code)
        # Initialize session, configure delays, etc.
    
    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
        """
        Scrape games for a specific team
        
        Args:
            team_id: Provider-specific team ID
            since_date: Only scrape games after this date (for incremental updates)
        
        Returns:
            List of GameData objects
        """
        # TODO: Implement scraping logic
        # 1. Normalize team_id
        # 2. Build API URL or web scraping request
        # 3. Fetch data
        # 4. Parse into GameData objects
        # 5. Filter by since_date
        # 6. Return list
        
        games = []
        # ... implementation
        
        return games
    
    def validate_team_id(self, team_id: str) -> bool:
        """Validate if team ID exists in provider"""
        # TODO: Implement validation
        try:
            # Check if team exists
            return True
        except Exception:
            return False
```

### Step 2: Add Provider Configuration

Update `config/settings.py`:

```python
PROVIDERS = {
    # ... existing providers ...
    'sincsports': {
        'code': 'sincsports',
        'name': 'SincSports',
        'base_url': 'https://soccer.sincsports.com',
        'adapter': 'src.scrapers.sincsports'
    },
    'modular11': {
        'code': 'modular11',
        'name': 'Modular11',
        'base_url': 'https://modular11.com',  # Update with actual URL
        'adapter': 'src.scrapers.modular11'
    },
    'athleteone': {
        'code': 'athleteone',
        'name': 'AthleteOne',
        'base_url': 'https://athleteone.com',
        'adapter': 'src.scrapers.athleteone'
    }
}
```

### Step 3: Database Migration

Create migration to add new providers:

```sql
-- Add new providers
INSERT INTO providers (code, name, base_url) VALUES
    ('sincsports', 'SincSports', 'https://soccer.sincsports.com'),
    ('modular11', 'Modular11', 'https://modular11.com'),
    ('athleteone', 'AthleteOne', 'https://athleteone.com')
ON CONFLICT (code) DO NOTHING;
```

### Step 4: Testing Framework

Create test utilities:

**File**: `tests/test_scrapers.py`
```python
"""Test utilities for scrapers"""
import pytest
from src.scrapers.base import BaseScraper

def test_scraper_interface(scraper: BaseScraper, team_id: str):
    """Test that scraper implements required interface"""
    # Test scrape_team_games
    games = scraper.scrape_team_games(team_id)
    assert isinstance(games, list)
    
    # Test validate_team_id
    is_valid = scraper.validate_team_id(team_id)
    assert isinstance(is_valid, bool)
```

## Implementation Priority

### High Priority: SincSports
- **Reason**: Most information available, clear site structure
- **Next Steps**:
  1. Inspect network requests for API endpoints
  2. Contact SincSports for API access
  3. Implement web scraper if needed
  4. Test with sample teams

### Medium Priority: AthleteOne
- **Reason**: Known site, but requires contact for API access
- **Next Steps**:
  1. Contact AthleteOne support
  2. Review developer documentation
  3. Implement based on available access method

### Low Priority: Modular11
- **Reason**: Limited information available
- **Next Steps**:
  1. **User Action**: Provide website URL
  2. Explore site structure
  3. Follow same process as other sites

## Common Implementation Patterns

### Pattern 1: REST API Scraper

```python
def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None):
    api_url = f"{self.BASE_URL}/teams/{team_id}/games"
    params = {}
    if since_date:
        params['since'] = since_date.isoformat()
    
    response = self.session.get(api_url, params=params)
    data = response.json()
    
    games = []
    for match in data.get('matches', []):
        game = self._parse_match(match, team_id)
        if game:
            games.append(game)
    
    return games
```

### Pattern 2: Web Scraper (HTML Parsing)

```python
def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None):
    team_url = f"{self.BASE_URL}/teams/{team_id}"
    response = self.session.get(team_url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    games = []
    for row in soup.select('table.games tr'):
        game = self._parse_table_row(row, team_id)
        if game and self._should_include(game, since_date):
            games.append(game)
    
    return games
```

### Pattern 3: Selenium Scraper (JavaScript-Heavy Sites)

```python
def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None):
    driver = self._get_selenium_driver()
    team_url = f"{self.BASE_URL}/teams/{team_id}"
    driver.get(team_url)
    
    # Wait for JavaScript to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "game-row"))
    )
    
    games = []
    for element in driver.find_elements(By.CLASS_NAME, "game-row"):
        game = self._parse_element(element, team_id)
        if game:
            games.append(game)
    
    return games
```

## Legal & Ethical Considerations

### Terms of Service
- **Review**: Check each site's Terms of Service
- **Compliance**: Ensure scraping is permitted
- **Rate Limiting**: Respect server resources
- **Data Usage**: Comply with data usage policies

### Best Practices
1. **Rate Limiting**: Implement delays between requests
2. **User-Agent**: Use identifiable user agent
3. **Robots.txt**: Check and respect robots.txt
4. **Contact First**: Reach out for API access before scraping
5. **Error Handling**: Gracefully handle errors without overwhelming servers

## Next Steps

### Immediate Actions
1. ✅ Document current architecture
2. ✅ Analyze SincSports site structure
3. ⏳ **User Action**: Provide Modular11 URL
4. ⏳ Contact SincSports for API access
5. ⏳ Contact AthleteOne for API access

### Development Tasks
1. Create scraper template
2. Implement SincSports scraper (after API discovery)
3. Implement AthleteOne scraper (after contact)
4. Implement Modular11 scraper (after site exploration)
5. Add provider configurations
6. Create database migrations
7. Write tests

### Testing Tasks
1. Test scraper with sample teams
2. Verify data format compatibility
3. Test incremental scraping
4. Test error handling
5. Performance testing

## Resources

### Current Codebase
- `src/scrapers/base.py`: Base scraper implementation
- `src/scrapers/gotsport.py`: Reference implementation
- `config/settings.py`: Provider configuration
- `scripts/scrape_games.py`: Scraping orchestration

### External Resources
- SincSports: https://soccer.sincsports.com
- AthleteOne: https://athleteone.com
- Modular11: [URL needed]

### Documentation
- PitchRank Scraper Details: `docs/SCRAPER_DETAILS.md`
- Event Scraper: `docs/EVENT_SCRAPER.md`

## Questions for User

1. **Modular11**: What is the exact website URL?
2. **Priority**: Which provider should be implemented first?
3. **Access**: Do you have existing accounts/API keys for any of these sites?
4. **Data Focus**: What specific data do you need from each site?
   - Team listings?
   - Game history?
   - Tournament results?
   - Rankings?
5. **Timeline**: What is the target timeline for integration?


















