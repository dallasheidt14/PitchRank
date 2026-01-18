# New Data Sources - Quick Start Guide

## Overview

This guide provides a quick reference for adding new data sources to PitchRank's scraping system.

## Quick Steps

### 1. Explore the Data Source

Use the exploration script to understand the site structure:

```bash
python scripts/explore_data_source.py https://example.com --team-id 12345
```

This will:
- Check robots.txt
- Look for API endpoints
- Inspect page structure
- Test team endpoint patterns

### 2. Create the Scraper

Copy the template and customize:

```bash
cp src/scrapers/template.py src/scrapers/newsource.py
```

Then implement:
- `scrape_team_games()`: Main scraping logic
- `validate_team_id()`: Team validation
- Helper methods as needed

### 3. Register the Provider

Add to `config/settings.py`:

```python
PROVIDERS = {
    # ... existing providers ...
    'newsource': {
        'code': 'newsource',
        'name': 'New Source',
        'base_url': 'https://example.com',
        'adapter': 'src.scrapers.newsource'
    }
}
```

### 4. Add Database Entry

Create a migration or manually insert:

```sql
INSERT INTO providers (code, name, base_url) 
VALUES ('newsource', 'New Source', 'https://example.com')
ON CONFLICT (code) DO NOTHING;
```

### 5. Test the Scraper

```python
from supabase import create_client
from src.scrapers.newsource import NewSourceScraper
import os

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

scraper = NewSourceScraper(supabase, 'newsource')

# Test validation
is_valid = scraper.validate_team_id('12345')
print(f"Team valid: {is_valid}")

# Test scraping
games = scraper.scrape_team_games('12345')
print(f"Found {len(games)} games")
```

### 6. Use the Scraper

```bash
# Scrape games
python scripts/scrape_games.py --provider newsource

# Or use in Python
from scripts.scrape_games import scrape_games
await scrape_games(provider='newsource')
```

## Implementation Patterns

### REST API Pattern

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
        game = self._parse_match(match, team_id, since_date)
        if game:
            games.append(game)
    
    return games
```

### HTML Scraping Pattern

```python
from bs4 import BeautifulSoup

def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None):
    url = f"{self.BASE_URL}/teams/{team_id}"
    response = self.session.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    games = []
    for row in soup.select('table.games tr'):
        game = self._parse_row(row, team_id, since_date)
        if game:
            games.append(game)
    
    return games
```

### Selenium Pattern (JavaScript-heavy sites)

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None):
    driver = webdriver.Chrome()  # Or use headless
    url = f"{self.BASE_URL}/teams/{team_id}"
    driver.get(url)
    
    # Wait for JavaScript
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "game-row"))
    )
    
    games = []
    for element in driver.find_elements(By.CLASS_NAME, "game-row"):
        game = self._parse_element(element, team_id, since_date)
        if game:
            games.append(game)
    
    driver.quit()
    return games
```

## Common Issues & Solutions

### Issue: Rate Limiting

**Solution**: Add delays between requests

```python
import time
import random

# In scrape_team_games()
time.sleep(random.uniform(1.0, 2.0))  # Random delay
```

### Issue: Authentication Required

**Solution**: Add authentication to session

```python
def _init_http_session(self):
    session = super()._init_http_session()
    session.headers.update({
        'Authorization': f'Bearer {os.getenv("API_KEY")}'
    })
    return session
```

### Issue: SSL Errors

**Solution**: Configure SSL verification

```python
def _init_http_session(self):
    session = super()._init_http_session()
    session.verify = False  # Only if necessary
    # Or use certifi:
    import certifi
    session.verify = certifi.where()
    return session
```

### Issue: Date Format Mismatch

**Solution**: Normalize date parsing

```python
from datetime import datetime

def _parse_date(self, date_str: str) -> date:
    """Parse various date formats"""
    formats = [
        '%Y-%m-%d',
        '%m/%d/%Y',
        '%d/%m/%Y',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%SZ',
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    raise ValueError(f"Could not parse date: {date_str}")
```

## Testing Checklist

- [ ] Scraper can validate team IDs
- [ ] Scraper can fetch games for a team
- [ ] Date filtering works correctly
- [ ] Error handling is robust
- [ ] Rate limiting is implemented
- [ ] Data format matches GameData structure
- [ ] Integration with scrape_games.py works
- [ ] Database import works correctly

## Resources

- **Full Documentation**: `docs/NEW_DATA_SOURCES_EXPLORATION.md`
- **Template Scraper**: `src/scrapers/template.py`
- **Reference Implementation**: `src/scrapers/gotsport.py`
- **Exploration Script**: `scripts/explore_data_source.py`

## Support

For questions or issues:
1. Check the full exploration document
2. Review the GotSport scraper as a reference
3. Test with the exploration script
4. Contact the team for assistance


















