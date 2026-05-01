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

## GotSport Endpoint Quirks

GotSport event pages expose three different schedule URLs with very different
contents. Pick the right one for the event type, or you will silently miss
games.

### Per-group page (`/schedules?group={X}`)

- One big match table per page, columns: `Match # | Time | Home Team | Results | Away Team | Location | Division`.
- Tournament-style events: shows played + upcoming. Parser-friendly. Default walk target.
- League/season events (NPL, CCL, ECNL season brackets): shows **upcoming fixtures only**. Played history is NOT here. The "Results" column is `-` for every visible row.

### Per-group results page (`/results?group={X}`)

- Round-robin standings matrix (NxN team grid). Cells contain `2-0`, `3-1`, `-`, etc.
- **No per-game dates, no venues, no match IDs** — useless to the existing `_parse_games_from_schedule_page` parser.
- Do not try to add this as a parser target.

### Per-team page (`/schedules?team={REGISTRATION_ID}`)

- One `<table>` per match for the team's full event schedule (past + future).
- Same 7-column layout as the per-group page, so the existing parser handles each table without changes.
- **Required for league/season events** — this is the only endpoint that surfaces played history with real dates.
- **Must use the registration ID, not the API team ID.** `/schedules?team={api_id}` redirects to `home.gotsport.com/login/`. Registration IDs come from the `team={\d+}` query param in per-group page hrefs (also accumulated in `api_team_id_cache` after the per-group walk).
- **No longer exposes `rankings.gotsport.com/teams/{api_id}` or `system.gotsport.com/teams/{api_id}` anchor links** as of 2026-05-01. The legacy HTML-scraping strategies in `_resolve_api_team_id_from_event_page` (rankings link parse, `/teams/{id}` link parse, JS `team_id` parse) are dead — the only team-id-bearing link on the page is `/matches_export?team={reg_id}`, which is the registration ID, not the API ID. Use the JSON API instead (next subsection).

### API endpoint (`/api/v1/teams/{id}/matches?past=true`)

- Source of truth for canonical team_id resolution. **Not CAPTCHA-protected** (verified 2026-05-01) even on events whose HTML pages are CAPTCHA-gated.
- Status-based classifier:
  - `200` + non-empty list → `{id}` is a valid API team ID. Each match has `homeTeam.team_id` (canonical), `home_team_reg_id` (per-event registration), and the away mirrors. Match the queried `{id}` against `home_team_reg_id` / `away_team_reg_id` to pick the right canonical `team_id`.
  - `200` + non-empty list with NO self-match → conservatively treat as unresolved. Promoting `{id}` would risk re-injecting a registration ID into `team_alias_map` as if it were canonical.
  - `200` + empty list → ambiguous (brand-new team, or stale id). Treat as unresolved.
  - `404` → `{id}` is a registration ID, not an API team ID. Deterministic.
- Resolver lives at `src/scrapers/gotsport.py:_resolve_api_team_id_from_event_page` and routes through the module-level `_zenrows_get` helper. ZenRows uses basic proxy (`js_render=false`) since this is a JSON endpoint — ~1 credit per call vs ~25 with JS render.

### HTML-CAPTCHA failure vs API-resolution failure

These are different failure modes with different telemetry surfaces:

- **HTML CAPTCHA** (event main page, per-team schedule page): `_fetch_event_page` raises `EventCaptchaGatedError` and `_write_captcha_artifact` writes `reports/<event_key>/intake/captcha_challenge.json`. Operators can replay these via a future CAPTCHA-solver integration.
- **API resolution failure** (4xx/5xx/timeout from `_resolve_api_team_id_from_event_page`): the resolver returns `None`, the parser drops the row, and `scrape_games_from_schedule_pages` increments `self._last_resolution_metrics["dropped_unresolved"]`. The per-event summary JSON (`data/raw/new_events_*_summary.json`) carries `teams_resolved` / `teams_unresolved` / `games_dropped_unresolved`. **No `captcha_challenge.json` is written for API failures** — the API isn't CAPTCHA-protected, so non-200 means a different class of failure (registration ID, gotsport API outage, ZenRows budget exhausted). Look at `_last_resolution_metrics["dropped_unresolved"]` and the workflow logs, not at `reports/<event_key>/intake/`.

### Walking pattern in `scrape_games_from_schedule_pages`

1. Per-group walk first (always — populates `api_team_id_cache` keyed by reg_id).
2. Per-team walk second, iterating `api_team_id_cache.keys()` and calling the same parser.
3. Validator dedup (`provider:date:sorted_team_ids`) collapses the home/away duplicates.
4. Disable per-team walk with `GOTSPORT_SKIP_PER_TEAM_WALK=1`. Cap with `GOTSPORT_MAX_TEAM_PAGES` (default 200).

### Tournament vs season-event runtime

Per-team walk roughly 5x's the HTTP request count vs per-group walk alone (~96 team pages vs ~20 group pages for a typical event). Stays well under the 3-hour workflow timeout but will exceed the `GOTSPORT_EVENT_TIMEOUT=240s` warn-only threshold for some events.

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
