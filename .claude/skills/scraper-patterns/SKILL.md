---
name: scraper-patterns
description: Web scraping patterns for PitchRank - rate limits, error handling, existing scraper conventions
---

# Scraper Patterns Skill for PitchRank

You are working on PitchRank's web scrapers. Follow these patterns to match existing code.

## Rate Limiting (CRITICAL)

### GotSport Limits

Do not copy numbers from here or from any other doc. Every knob is an env
override — `GOTSPORT_DELAY_MIN`, `GOTSPORT_DELAY_MAX`, `GOTSPORT_MAX_RETRIES`,
`GOTSPORT_TIMEOUT`, `GOTSPORT_RETRY_DELAY` — and the two classes in
`src/scrapers/gotsport.py` deliberately default differently: `GotSportScraper`
(team API, polite) and `GotsportScraper` (event scraping, aggressive). Read the
constructor you are subclassing, then the workflow that runs it — the scrape
workflows override the delay pair inline, and most of them the retry count and
timeout too. None sets `GOTSPORT_RETRY_DELAY`, and no env template carries any
of them, so in CI the constructor default is the only value that knob has.

### Delay Pattern
```python
import random
import time

class MyScraper(BaseScraper):
    def _delay(self) -> None:
        """Random spacing so requests stay under the provider's rate limit."""
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))

    def scrape_all(self, teams):
        # Use between EVERY request
        for team in teams:
            data = self.scrape_team(team)
            self._delay()  # Always delay
```

### NEVER Bypass Limits
```python
# BAD - No delay
for team in teams:
    scrape_team(team)  # Will get IP banned

# BAD - Fixed delay (bursts line up with other workers and trip the limiter)
time.sleep(1.0)

# GOOD - Random delay across the range this scraper was configured with
time.sleep(random.uniform(self.delay_min, self.delay_max))
```

## CloudFront WAF (gotsport)

GotSport fronted `system.gotsport.com/api/v1/*` with a CloudFront WAF (per-IP
burst rate limiter) circa 2026-05-01. A tripped IP returns **HTTP 403 with
`Server: CloudFront`** and a CloudFront-branded HTML error body — distinct from
a real "team not found" which is `HTTP 404` with `Server: nginx` and JSON body
`{"error":"Team Not Found"}`. Lockout persists for multiple minutes; fresh
sessions and cookies don't help.

Coordination: the module-level `WAFBreaker` singleton in
`src/scrapers/gotsport.py` detects the 403+CloudFront combination via
`_is_cloudfront_waf_block`, then opens the breaker. All concurrent workers
sharing the scraper pause on the `WAFBreaker._async_event` (orchestrator) and
`WAFBreaker.wait_if_open_sync` (per-thread retry loop) until a `threading.Timer`
fires `_resume()`. A second trip in the same run raises `WAFBlockedError`,
which the orchestrator catches and exits with code 2.

Cooldown defaults to 300 s (`_WAF_COOLDOWN_DEFAULT`), overridable via
`GOTSPORT_WAF_COOLDOWN_SEC`.

CLI default `--concurrency` is **5** for residential IPs in
`scripts/scrape_games.py`. CI picks concurrency adaptively in
`.github/workflows/scrape-games.yml`: **8 per shard** with ZenRows, **10** for direct
requests (20 was rolled back after a 97% WAF error rate).
Do not raise the local default without re-measuring the sustained rate — empirically
~15 req/s sustained from one IP trips the WAF (measured 2026-05-18). Back off when it
trips; do not route around it.

## ZenRows Tiers and Routing

Credit tiers: base request 1, `js_render` 5, `premium_proxy` 10, both 25. The scrapers default
to `premium_proxy=true, js_render=false`, so every proxied GotSport API call costs **10
credits**. Measured three times on 2026-09-03 against the live API, the same
`/api/v1/teams/{id}/matches` fetch costs **1 credit** on default params. `mode: 'auto'` is worse
than either — it escalates on failure and billed 25 credits for one dead team id.

**Treat the cheap tier as unproven at volume.** Those 1-credit measurements come from 10- and
11-URL probes, and the operator reports that running with ZenRows off entirely usually trips the
CloudFront WAF, which is why `use_zenrows` stays on. Whether datacenter IPs survive a few
thousand URLs is open; residential is the known-good configuration. Recommend the cheap tier
only alongside volume evidence.

**Inside `GotSportScraper.scrape_team_games`, only the match-list call routes through
ZenRows.** `_extract_club_name` (`src/scrapers/gotsport.py:638`) and
`_fetch_club_name_for_team_id` (`:797`) both use `self.session` directly, so 1–31 requests per
team leave the runner's IP sequentially, inside the parse loop. `drain_queue.py` at concurrency
20 measured 0.45–1.6 teams/sec with **zero** WAF or CloudFront hits in the slowest run — those
runs are latency-bound, not block-bound, and work that only speeds up the match-list call
addresses the smaller half. The event-scraping class is not affected: `_subpage_fetcher`
(`:3427`) and the API resolver both route through ZenRows already.

### ZenRows Batch API

Base `https://async.api.zenrows.com/v1`, header `X-API-Key`.

**Three sources, in this order: a live capture of the deployed service, then the
schema, then the prose.** Read the vendor OpenAPI schema — docs/openapi.yaml in the
GitHub repository `ZenRows/zenrows-python-sdk`, 2026-09-03 — which corrected four prose
claims that each fail only on a paid run. But a capture from the running service
outranks it in turn for anything operational: the
schema says a result link lasts 24 hours and the observed one carried
`X-Amz-Expires=7200`, and plans built on the longer figure silently lose bodies.

**Submissions cap at 1,000 tasks.** `maxItems: 1000` on both `SubmitJobRequest.tasks`
and `AddTasksRequest.tasks`; the prose says 10,000.

- ≤1,000 tasks: `POST /jobs` with `status:'closed'`, tasks inline.
- Above that: `POST /jobs` with `status:'open'` → `POST /jobs/{id}/tasks` in ≤1,000 batches →
  `POST /jobs/{id}/close`. An **open run fetches immediately** rather than waiting for the close,
  so later chunks stream in while earlier ones are in flight; `last_batch_received` stays false
  until close. One job means one `run_id` and one cumulative spend.

**The poll response is a run; a create response is a job.** `GET /jobs/{id}/runs/{run_id}`
answers with `status` and `stats` at the root. Only a create nests the run under
`latest_run` — and a create's own root `status` is the *job's* (`open`/`closed`), so a
reader that accepts either shape files a job status as a run status.

**`stats.spend` is an object**, carrying an integer `credits` and a currency `cost`.
Reporting it whole prints a dict where an operator expects a number.

**`POST /jobs/{id}/stop` answers 409 once the run is already terminal.** Re-read the run
and treat it as terminal rather than as a failure; the vendor documents one meaning for
that status and never enumerates its `code` values, so the run's own status is the
discriminator. `POST /jobs/{id}/close` behaves the same way on an already-closed job.

**Settle on the run's counter, never on result rows.** `RunStats` requires `total`,
`completed`, `successful` and `failed`, with `completed` defined as `successful + failed`.
A `TaskResult` row exists from task creation and carries a `pending` status, so counting
rows counts work that has not happened. After a stop the counter cannot reach `total` at
all: `stopJob` leaves pending tasks "as-is — not re-queued, not synchronously failed", and
`RunStatus.stopped` *means* `completed < total`. Wait for `completed` to stop advancing,
under a cap — the counter going quiet is the signal, and the cap is what stops a stalled
run waiting forever.

**`Idempotency-Key` is declared on `submitJob` and `rerunJob` only.** `addTasks` takes no
such parameter and offers no dedupe, so replaying a lost add-tasks response appends the
chunk again and bills every task in it twice. Send the key on job creation, reuse it on an
unknown outcome, and rotate it on an explicit 503.

**Send add-tasks once, and read its rejections narrowly.** A 409 or a 429 there means the
chunk was refused rather than taken, so both are safe to repeat — the documented cause of
that 409 is ingestion still in progress. Everything else leaves the outcome unknown and
must not be replayed. **A create's 409 is a different animal**: it is a conflict, not a job
to adopt. The `Problem` envelope defines no job id, a genuine same-body replay returns the
original 2xx instead, and no endpoint looks a job up by key — so a job that may exist is
found through `GET /jobs` or the dashboard.

**`result_url` comes in two forms.** A presigned link, which must not carry the
credential, or a relative `/v1/jobs/<id>/runs/<run>/tasks/<tid>/content` path, which
requires `X-API-Key`. That path already includes `/v1`, so appending it to a base that ends
in `/v1` yields `/v1/v1/...` and a per-task 404 — `urljoin` handles it. Attach the
credential per request rather than as a session default, and set `allow_redirects=False`
so each hop is authorised on its own origin: `requests` strips only `Authorization` when a
redirect changes host and carries a custom header verbatim, so a key attached to the
content endpoint would otherwise follow a 302 to whatever storage host it names.

**Bodies are raw JSON even though a result row's `type` field reports `html`.** Separately,
the body response's own `Content-Type` carries no charset, which is what drives `requests`
to ISO-8859-1: `response.text` then mojibakes every accented name while still parsing
cleanly. Parse the bytes — `json.loads(response.content)`.

**Results are cursor-paginated** at `GET /jobs/{id}/runs/{run_id}/results` →
`{results, next_cursor}`; follow the cursor until it is absent, and stop if a page returns
the one just used.

**Statuses, and what each obliges.** `RunStatus` is exactly `running`, `pending`,
`completed`, `stopped`, `failed`, `deleted`; `failed` is an account-level fault
(insufficient credits, inactive subscription) carrying a `failure_reason`, so it must
reach the operator as a failure rather than as an empty but successful sweep. `TaskStatus`
is `pending`, `processing`, `successful`, `failed`. `result_url` and `error` are exclusive
across the two *terminal* states only — a non-terminal row has neither — so read per-task
outcome from `status`. The run-level `failure_reasons` is a rollup that cannot identify
which task failed; its buckets are `bad_target` (bad host, 404, 410, too large) and
`blocked` (anti-bot denials). No per-task code means "target returned 403" — `RESP002` is
404-specific, `AUTH009`/`BLK0001` are ZenRows-side.

**`ScraperParams` rejects an unknown key with `400 invalid_argument`**, and lists
`premium_proxy` and `proxy_country` among the supported ones, so a typo fails the
submission rather than silently billing the other tier.

**`TaskInput.external_id`**: `maxLength: 128`, pattern `^[A-Za-z0-9._-]+$`. Match it with
`re.fullmatch` — Python's `$` admits a trailing newline that the vendor's ECMA pattern
rejects, and one bad id fails the whole chunk.

## GotSport Endpoint Quirks

### Team details payload contract

`https://system.gotsport.com/api/v1/team_ranking_data/team_details?team_id=<id>`

Verified live 2026-08-30 across 32 samples. The response holds exactly:

```
id, name, club_name, city_state_country, website_url, login_url,
primary_coach_name, coach_names, primary_manager_name, manager_names,
team_logo_url_full, image, team_association, display_gender, display_age_group
```

There is **no `full_name`, `state`, `age` or `gender` key**. Reading those four returns `""`
on every call and never raises, so the failure is silent and the caller falls through to
whatever fallback it has. Seven hand-copied resolvers in `scripts/` read the wrong set; the
symptom was discovered teams inheriting their opponent's cohort and state.

- `team_association` is a registration body, not a postal code. Map it with
  `src/utils/team_association_map.to_state_code` — `CAN` is California North, not Canada.
- `display_age_group` is a label, not a number: `Open` for adult teams, `U8`/`U9` for cohorts
  PitchRank does not board, `U18` and `U20` for the u19 board (`U19` itself appeared in none
  of the 32 samples), and `U21` for aged-out 2006 teams. Normalize with
  `src/utils/age_group.normalize_age_group`, which folds both boundary ages into u19.
- A missing id answers **HTTP 404** with a valid JSON body (`{"message": "Can not find team"}`).
  Without `raise_for_status()` that body parses into an all-empty dict that looks like a real
  team with no metadata. A 404 is a permanent answer worth caching; a 403 WAF block is not.

### Schedule pages

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
- Resolver lives at `src/scrapers/gotsport.py:_resolve_api_team_id_from_event_page` and routes through the module-level `_zenrows_get` helper. It sends `js_render=false` since this is a JSON endpoint, but also `premium_proxy=true` (`gotsport.py:1033-1038`), so it bills at the premium-proxy tier — see the ZenRows section above for what that costs.

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

### Silent type traps at the parser boundary

Four adjacent seams disagree about how a team id is typed, and every one fails without raising:

- `_parse_api_match` (`gotsport.py:660`) takes `team_id: int` and matches by strict equality
  against the payload's integer at `:671`. A string id matches nothing, so the team yields
  **zero games and no error**. Its `since_date` is a `date` with no default; a raw timestamp
  raises a `TypeError` the method catches, returning `None`.
- `_game_data_to_dict` (`:841`) takes `team_id: str`, and `src/scrapers/base.py:52` emits
  `"team_id": str(team_id)` — game rows carry the **provider** id as text.
- `club_cache` (`:330`) is string-keyed behind an exact `in` test at `:805`. An integer key
  misses and falls through to a direct `self.session.get`.
- `_finalize_queue_items` (`scripts/drain_queue.py:365`) indexes by **`team_id_master`**, not the
  provider id.

`src/scrapers/base.py:28-40` is the canonical pattern for the split: provider id for scraping and
for the game dict, master id for `_get_last_scrape_date` and `_log_team_scrape`. Carry both ids
per team, and verify a change here by asserting a **non-zero game count** — asserting that
nothing raised passes while the parser silently returns nothing.

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
        # 429 is deliberately absent: src/scrapers/_http.py owns it at the app
        # level ("Do NOT add 429 to urllib3's Retry — it is owned here", :13).
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

session = create_session()
response = session.get(url, timeout=30)
```

This sets no `allowed_methods`, so urllib3's default applies and POST is excluded from
*read*-error retries only. The connect-replay gap in **Retry Semantics** below applies to this
session exactly as it does to an explicit `["GET","HEAD"]` mount.

### Retry Semantics

**`allowed_methods` does not keep POSTs out of urllib3's retry.** `Retry.increment` gates its
*read*-error branch on `_is_method_retryable(method)` but leaves the *connection*-error branch
ungated (verified against the installed urllib3 2.5.0). So an `allowed_methods=["GET","HEAD"]`
mount — the shape used in `src/scrapers/_zenrows.py:74-88` — still lets a POST be replayed when
the connection fails.

`src/scrapers/sincsports_clubs.py` is where this actually bites. Its `_init_http_session`
docstring at `:151-158` records the belief being corrected — *"POST is deliberately excluded
from `allowed_methods` because EO callbacks rotate form state on every response — an
HTTP-level POST retry would resend a stale body"* — and `:286` POSTs through that session. The
app level is sound there: `:284` re-fetches form state on every attempt. The uncovered gap is
the transport-level connect replay, which resends the stale body the docstring is guarding
against. A client that must own replay itself — anything sending an `Idempotency-Key` that
changes between attempts, for instance — mounts `HTTPAdapter(max_retries=0)` and retries at the
app level.

**Decide retriability from the status, not from the backoff value.** `backoff_for_event`
(`src/scrapers/_http.py:86`) returns `0.0` for a 409, for a 200, and for a 503 carrying
`Retry-After: 0` — all three identical (measured). Treating a `0.0` wait as "not retriable"
therefore skips exactly the retry the server explicitly asked for, silently. Branch on status
membership the way `retry_session_get` does at `src/scrapers/_http.py:179-182`, and use
`backoff_for_event` only for how long to wait.

### Headers
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
# BAD - some endpoints return degraded HTML to an unset UA
requests.get(url)
```

### ❌ Ignore Robots.txt for Heavy Scraping
```python
# Honor robots.txt Disallow rules, and respect rate limits even when robots.txt is silent
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
   python scripts/scrape_games.py --provider gotsport --limit-teams 5
   ```

   There is no `--dry-run` on this script. Omitting `--auto-import` skips the game
   import, but the run still writes `team_scrape_log` rows and updates
   `teams.last_scraped_at` (`scripts/scrape_games.py:511`, before the import branch),
   so even a 5-team sample touches the database.

2. **Check output format**
   ```python
   # Validate fields match expected schema
   ```

3. **Verify rate limiting**
   - Watch for 429 errors
   - Check request timing in logs

4. **Full run with checkpointing**
   ```bash
   python scripts/scrape_games.py --provider gotsport --limit-teams 100
   ```

## Reading a Provider's Age Labels

A provider's division label does not carry its own season. `BU11` means one
birth year in the season that wrote it and a different one a year later, so a
cohort inferred from the wall clock silently drifts every Aug 1 on any job that
re-scrapes historical events.

**Corroborate the convention against the provider's own team names.** Team names
usually embed a birth year (`Cook Inlet SC - 2016 Girls`), and that year is
season-invariant, so the dominant year inside a division tells you which season
the label was written in:

```python
implied_season = dominant_birth_year_in_team_names + u_age - 1
```

**Sample several events from different play dates before encoding a rule.** One
event proves nothing. TGS looked like it labelled with the upcoming season until
two older events showed labels two seasons behind their play dates, which killed
the rule a single event had suggested. Divisions whose team names carry no year
give no signal at all, so treat coverage as partial and prefer skipping an
unreadable division over guessing its cohort.

**Reject labels that name more than one cohort.** `U13-U19` and `U15 - U18` are
catch-alls, not cohorts; filing their teams under the first age listed puts
every older team in the youngest group. Accept a multi-age label only when every
age it lists collapses to the same cohort (`GU18/19`, since U18 folds into U19).

**Resolve gender from the provider's own field where one exists.** Prefix
sniffing misses age-first labels (`U11 Girls` has no leading `G`), and an
unresolved gender does not stay empty downstream — `normalize_gender("")`
returns `"Male"`.
