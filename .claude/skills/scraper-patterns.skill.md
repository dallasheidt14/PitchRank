---
name: scraper-patterns
description: Web scraping patterns for PitchRank - rate limits, error handling, existing scraper conventions
---

# Scraper Patterns Skill for PitchRank

You are working on PitchRank's web scrapers. Follow these patterns to match existing code.

## Rate Limiting (CRITICAL)

### GotSport Limits
```python
GOTSPORT_DELAY_MIN = 0.1   # Minimum seconds between requests
GOTSPORT_DELAY_MAX = 2.5   # Maximum seconds between requests
GOTSPORT_TIMEOUT = 30      # Request timeout
GOTSPORT_MAX_RETRIES = 2   # Retry attempts
```

### Delay Pattern
```python
import random
import time

def polite_delay():
    """Random delay to avoid detection."""
    delay = random.uniform(0.1, 2.5)
    time.sleep(delay)

# Use between EVERY request
for team in teams:
    data = scrape_team(team)
    polite_delay()  # Always delay
```

### NEVER Bypass Limits
```python
# BAD - No delay
for team in teams:
    scrape_team(team)  # Will get IP banned

# BAD - Fixed delay (detectable pattern)
time.sleep(1.0)

# GOOD - Random delay
time.sleep(random.uniform(0.1, 2.5))
```

## Request Pattern

### Standard Request
```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session():
    """Session with retry logic."""
    session = requests.Session()
    retries = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

session = create_session()
response = session.get(url, timeout=30)
```

### Headers (Match Browser)
```python
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

response = session.get(url, headers=HEADERS, timeout=30)
```

## Error Handling

### HTTP Errors
```python
def scrape_page(url: str) -> Optional[str]:
    try:
        response = session.get(url, timeout=30)

        if response.status_code == 429:
            logger.warning(f"Rate limited on {url}")
            time.sleep(60)  # Back off for a minute
            return None

        if response.status_code == 503:
            logger.warning(f"Service unavailable: {url}")
            return None

        response.raise_for_status()
        return response.text

    except requests.Timeout:
        logger.error(f"Timeout on {url}")
        return None
    except requests.RequestException as e:
        logger.error(f"Request failed for {url}: {e}")
        return None
```

### Parse Errors
```python
def parse_team_page(html: str) -> Optional[dict]:
    try:
        soup = BeautifulSoup(html, 'lxml')
        # ... parsing logic
        return data
    except Exception as e:
        logger.warning(f"Parse error: {e}")
        return None  # Return None, don't crash
```

## Data Extraction Pattern

### Match Existing Format
```python
def extract_game(row) -> dict:
    """Extract game data in standard format."""
    return {
        'provider': 'gotsport',
        'team_id': str(row.get('team_id', '')),
        'team_name': row.get('team_name', '').strip(),
        'opponent_id': str(row.get('opponent_id', '')),
        'opponent_name': row.get('opponent_name', '').strip(),
        'goals_for': safe_int(row.get('goals_for')),
        'goals_against': safe_int(row.get('goals_against')),
        'game_date': parse_date(row.get('date')),
        'event_name': row.get('event', '').strip(),
        'scraped_at': datetime.now().isoformat(),
    }

def safe_int(value) -> Optional[int]:
    """Safely convert to int."""
    try:
        return int(value) if value else None
    except (ValueError, TypeError):
        return None
```

## Output Format

### JSONL for Large Datasets
```python
import json

with open('output.jsonl', 'w') as f:
    for game in games:
        f.write(json.dumps(game) + '\n')
```

### CSV for Analysis
```python
import csv

with open('output.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=games[0].keys())
    writer.writeheader()
    writer.writerows(games)
```

## Progress Tracking

### Use Rich for CLI
```python
from rich.progress import track
from rich.console import Console

console = Console()

for team in track(teams, description="Scraping..."):
    data = scrape_team(team)
    polite_delay()
```

### Checkpointing
```python
import json

CHECKPOINT_FILE = 'scrape_checkpoint.json'

def save_checkpoint(state: dict):
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(state, f)

def load_checkpoint() -> dict:
    try:
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {'last_team_index': 0}
```

## CLI Pattern

```python
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--provider', required=True, choices=['gotsport', 'tgs'])
parser.add_argument('--limit-teams', type=int, help='Max teams to scrape')
parser.add_argument('--dry-run', action='store_true')
parser.add_argument('--output', default='data/raw/scrape_output.jsonl')

args = parser.parse_args()

if args.dry_run:
    console.print("[yellow]DRY RUN - No data will be saved[/yellow]")
```

## What NOT to Do

### ❌ Concurrent Requests to Same Host
```python
# BAD - Will get banned
with ThreadPoolExecutor(max_workers=10) as executor:
    results = executor.map(scrape_team, teams)
```

### ❌ No User-Agent
```python
# BAD - Looks like a bot
requests.get(url)
```

### ❌ Ignore Robots.txt for Heavy Scraping
```python
# Be respectful of rate limits even if not in robots.txt
```

### ❌ Retry Immediately
```python
# BAD - Hammers server on failure
while not success:
    response = requests.get(url)

# GOOD - Exponential backoff
for attempt in range(3):
    try:
        response = requests.get(url)
        break
    except:
        time.sleep(2 ** attempt)
```

## Testing New Scrapers

1. **Small sample first**
   ```bash
   python scrape.py --provider gotsport --limit-teams 5 --dry-run
   ```

2. **Check output format**
   ```python
   # Validate fields match expected schema
   ```

3. **Verify rate limiting**
   - Watch for 429 errors
   - Check request timing in logs

4. **Full run with checkpointing**
   ```bash
   python scrape.py --provider gotsport --limit-teams 100
   ```
