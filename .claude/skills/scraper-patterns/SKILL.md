---
name: scraper-patterns
description: "Web scraping patterns for PitchRank - rate limits, error handling, existing scraper conventions, per-provider endpoint quirks, and team-name parsing for provider matchers. Use when writing or debugging a scraper, adding a provider, building a provider matcher's fuzzy gates, or resolving provider review-queue items by hand."
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

## Sequential Walks on `team_details`

A plain `requests.Session` loop — no ZenRows, no concurrency — is its own rate regime: egress
is a single direct IP rather than proxied residential, so the concurrency defaults and the
`WAFBreaker` machinery above do not apply. `scripts/reconcile_teams_with_gotsport.py` walks
this way.

**Pace at a fixed 3 s.** The fixed-delay warning under Rate Limiting guards against several
workers lining their bursts up; one process has no one to line up with, so a constant sleep is
correct here. Measured across every US state, 2026-09-09 to 2026-09-16: 3 s carried ~166,000
calls with near-zero failed lookups; 2 s degraded before it failed, chunk time climbing from 19
to 38 minutes at a constant setting and then blocking; 1.5 s blocked hard after ~9,000 calls.
Budget `delay + ~0.35 s` per **call** — ~1,075 calls/hour at 3 s, and ~1,250 teams/hour, since
~85% of teams carry a resolvable alias and the rest cost no request. Raise the delay when chunk
times drift upward rather than lowering it.

**Separate a provider block from a local network outage before reacting.**
`TeamDetailsResolver` collapses a WAF 403, a timeout and a DNS failure into `{}` alike, and
`reconcile_teams_with_gotsport.py` stops after `--abort-after` (default 10) consecutive
**failed** lookups with **exit code 75**. A 404 is the origin answering and clears the streak,
so an abort means nothing answered — not that ten teams were missing. Resolve one id the
current slice already answered for, through `src/utils/gotsport_team_details.TeamDetailsResolver`,
and read the result:

- **Reachable** — a real block. Wait out a cooldown (300 s, the documented WAF default) and add
  a second to the delay.
- **Unreachable** — the network. Retry in a few minutes at the same pace, and spend none of the
  `--abort-after` allowance on it.

**Walk a large population in chunks, and record each chunk's offset and exit code.** No script
in the repo emits such a log, so a driver has to write one. 500 rows per chunk (`--limit`'s
default); resume from the last recorded chunk, where exit 0 advances to the next offset and
anything else redoes the same one, since an aborted chunk examined only part of its slice.
`fetch_target_teams` sorts on the immutable `team_id_master`, so the window cannot re-sort
between runs even after the walk renames teams. *Checkpointing* below covers the same job for
the scraper classes; this endpoint's response is described under *Team details payload
contract*.

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

Five adjacent seams disagree about how a team id is typed, and every one fails without raising:

- `_parse_api_match` (`gotsport.py:664`) takes `team_id: int` and matches by strict equality
  against the payload's integer at `:675`. A string id matches nothing, so the team yields
  **zero games and no error**. Its `since_date` is a `date` with no default; a raw timestamp
  raises a `TypeError` the method catches, returning `None`.
- `_game_data_to_dict` (`:845`) takes `team_id: str`, and `src/scrapers/base.py:52` emits
  `"team_id": str(team_id)` — game rows carry the **provider** id as text.
- `club_cache` (`:334`) is string-keyed behind an exact `in` test at `:809`. An integer key
  misses and falls through to a direct `self.session.get`.
- `_finalize_queue_items` (`scripts/drain_queue.py:365`) indexes by **`team_id_master`**, not the
  provider id.
- `str(obj.get("<id key>", ""))` turns a present `null` into the string **`"None"`**, because
  the default fills only a missing key. `"None"` is truthy, so any truthiness test reads it as a
  real id. An approved alias keyed on it attaches every game carrying it from that provider to
  one team; GotSport's did, for thousands of games.
  - Read the raw value through `clean_provider_id` (`src/utils/provider_ids.py`), which maps
    `None`, `"None"`, `"null"` and blanks to `""`, and test later with `is_blank_provider_id`.
    The importer, matcher and admin link routes all refuse a blank id by that definition.
  - `str(v) if v else ""` (`src/scrapers/sincsports.py:427`) handles a real `null` but passes
    an id that is already the string `"None"`.
  - `src/scrapers/template.py:202`, the starting point for new scrapers, still carries the unsafe form.
  - Pin it with a fixture whose id is `null` and assert the parsed id is `""`. A game count
    cannot see this trap.

`src/scrapers/base.py:28-40` is the canonical pattern for the split: provider id for scraping and
for the game dict, master id for `_get_last_scrape_date` and `_log_team_scrape`. Carry both ids
per team, and verify a change here by asserting a **non-zero game count** — asserting that
nothing raised passes while the parser silently returns nothing.

## TGS Endpoint Quirks

### The API host is AthleteOne, not Total Global Sports

Call TGS at `https://api.athleteone.com/api` — the `BASE` constant in
`scripts/scrape_tgs_event.py`. TGS migrated to AthleteOne;
`public.totalglobalsports.com` is only the human-facing site and the value stored in
`games.source_url`, and `providers.base_url` still records it, so both point at the
wrong host for API work.

Requesting an API path on the public host returns **HTTP 200 with HTML**, so the call
fails at `json()` rather than as a clean 404 and reads like a WAF block. Check the host
before investigating a block.

### Event details payload contract

`{BASE}/Event/get-event-details-by-eventID/{event_id}` — verified live across three
events. Under `data`, the fields worth reading:

```
eventID, name, eventTypeID, eventSubTypeID, stateCode, stateID,
city, address, zip, country, countryID, startDate, endDate
```

`eventTypeID` is 1 for a tournament and 2 for a league — the only way to tell them apart,
and it exists nowhere in the database. `stateCode` is **where the event was held**, so it
is a travel signal: use it to gate or cross-check, never as a team's own state. Canadian
events return a province (`ON`, `BC`), not a US state.

`scrape_tgs_event.get_event_details` already fetches this payload on every event and keeps
only `name`, so the other fields cost no extra request.

## SincSports Schedule Pages

### Access

SincSports pages sit behind a Cloudflare challenge that answers plain `requests` on the
schedule, rankings and clubs pages with 403; the ZenRows `--via-proxy` option on the tournament
driver is untested against it. A same-origin `fetch()` from a page already open on
`soccer.sincsports.com` passes. Capture in a
real browser with `scripts/sincsports_capture_bundle.js` through the Playwright MCP
`browser_evaluate` tool, then parse offline with
`scripts/scrape_sincsports_tournament_schedule.py --from-bundle`. `browser_evaluate` rejects a
trailing semicolon after the function, and its `filename` must sit under the checkout root in a
folder that already exists. Per-team game histories are gated behind SincVIP.

### Layouts and paging

- `schedule.aspx` renders either the old `div.form-row.game-row` layout or the newer `sched2`
  layout. A league division opens on standings, so request `&mode=schedule` to get games.
- Both layouts show 50 games per page via `&gpage=N`. The pager (`sched-pager` or `sched2-pager`)
  links only nearby pages: a 312-game division's page 1 links pages 1–4 of 7. Take the page count
  from its "N games" total as well as its links (`parse_page_count`); trusting links alone
  truncates silently.
- A sched2 root links every division. An old-layout root links only the one it shows and lists
  the rest as `<select>` option values; the capture script reads both, while
  `parse_tournament_index` reads links only. Codes are `UxxM##` boys, `UxxF##` girls.
- Team ids are `a[data-team]` in sched2 and `teamid=` in old-layout links. Old-layout league
  pages link team names to `schedule2.aspx`, old-layout tournaments to `schedule.aspx`.

### Status and dates

- Cancelled, postponed and forfeited sched2 games carry `.sched2-gstat-off` in the venue slot
  (`Forfeit`, `Canceled - Weather`, `Blackout - Postponed`), often beside a recorded score such as
  4-0. Take status from it; `.sched2-mark` and `.sched2-typechip` never carry it, so a forfeit read
  from those looks played. `.sched2-gstat-note` (`Kicks from the Mark`) is informational.
- sched2 day headers print a weekday and "Mon D" with no year. The team links carry `year=`, the
  event year; of that year and the years either side, the right one puts the date on the printed
  weekday (`_sched2_day_date`).
- `Jan 1` is the site's placeholder for games with no real date, printed under either `MON` or
  the event year's own weekday, and it can carry a score (a 0-0 marked played).
  `parse_division_pages` leaves every 1 January game undated so none of them import.

### Rec, small-sided and adult play

PitchRank never imports rec, small-sided (3v3–6v6) or adult play; 7v7 and 9v9 are standard U9–U12
formats and stay in. SincSports' own tags are not enough: a league tagged Competitive can still run
divisions named "Rec First Division". The capture script searches with Recreation and Small Sided
unticked and skips excluded league and division names, and the import command skips any division
or event whose name matches the same pattern (`is_excluded_play`), so an older capture cannot
bring them in either. Keep the two patterns identical.

### Finding leagues

Each league season has its own tid (a spring and a fall tid per league). The Leagues list
(`events.aspx?sinc=Y&leagues=Y`) is an ASP.NET form: set `ctl00$ContentPlaceHolder1$tbFrom` and
submit `ctl00$ContentPlaceHolder1$btnSearch`. Unlike the tournament view it accepts past From
Dates, filters on end date, and returns at most 30 leagues with no pager, so walk the From Date
forward. Featured leagues render the same card with an `F` in every control id
(`lnkFEventName`, `lblFDate`).

### Finding past tournaments

The tournament view of `events.aspx` lists upcoming events only and ignores a past From Date.
Past events with results are on `usarankevents.aspx`:

- Set `ctl00$ContentPlaceHolder1$tbFrom` and `ctl00$ContentPlaceHolder1$tbEnd` (M/D/YYYY) and submit
  `ctl00$ContentPlaceHolder1$btnSearch`. The date range filters the list; the State dropdown did
  not (2026-09-13).
- The list shows 30 events a page. Page it from inside the page with
  `eo_Callback("cpEvents", "<page>")`, pages numbered from 1, and wait under a cap for its
  "Displaying: X to Y / N" text to change before reading rows or firing the next page. A callback
  fired before the previous one lands cancels it; pages landed in about a second on 2026-09-15,
  where an earlier session allowed up to 120 s. Each row's `schedule.aspx?tid=` link gives the tid,
  beside the event name, start date and state.
- Most listed events are not run on SincSports: their root has no divisions, and their results
  are SincVIP-gated (see Access). Of 252 uncaptured events from Aug 1 to Sep 15, 2026, 242 had no
  divisions and the other 10 were girls or adult only. Pass the new tids to the capture script's
  `divisions` mode: it reads each root's division links and `<select>` options and captures only
  boys divisions, so an event with none costs one request and yields nothing.
- New tournaments are the listed tids missing from earlier captures under `data/raw/sincsports_*`.
  Re-capturing a recent event is safe: games already stored are skipped and a late score comes in
  as a new game, but a corrected score does not replace the stored one.

## Soccer Events Group Pages

soccereventsgroup.com runs on 3 Step Sports and answers `requests` sent with a browser
User-Agent, no proxy. `scripts/import_soccereventsgroup_event.py` is the driver.

- `/api/program/<id>` returns `{program, divisions}`. `program.start` dates the event and
  `program.affiliationId` feeds the roster call.
- `/api/team/list?affiliationId=<a>&programIds=<id>` is the roster: JSON, teams under
  `programTeams[].divisions[].teams[]`, each with its numeric team id, `origin`
  ("Chicago, IL") and `state`.
- Take a division's birth year from `oldestEligibleBirthdate`, the Aug 1 cutoff: year + 1 is
  the band's younger year. Accept the division only when the cutoff is Aug 1 and the leading
  age of `sessionName` ("U10 Bronze"; the tier follows the age) names one cohort that agrees
  with that birth year in the event's own season; skip it otherwise. File teams on the board
  that birth year sits on this season, never from the label or the team name. A label with no
  U-age ("HS"), one spanning two boards ("U13/U14") or a board below U10 is skipped.
- `/site/teams/details.aspx?TeamID=<id>` carries the division's bracket in the element whose
  id ends `BracketPanel`: one `table.game` per game, `td.team` (classes `winner`/`loser`),
  `td.score`, `td.title` ("Semifinal") and `td.time` ("9/6 3:00P, Field 08"). One page per
  division is enough. The time has no year: use `program.start`'s year, or the next year for
  a date before the start.
- Pool play is not published; brackets are the only results.
- Bracket pages re-case team names, and roster names can end in NBSP. Collapse whitespace
  (NBSP included) and compare case-insensitively against that division's roster only; report
  a name the division does not hold rather than importing the game.
- A drawn game (0-0, 1-1) marks neither side; take the result from the scores, not the classes.
  Import a 0-0 as a draw rather than skipping it.

## Athletes2Events Pages

Athletes2Events is a white-label tournament platform: each host club runs its events on its own
subdomain (`crossfire.`, `somsports.` for Surf Cup Sports, and some fifty more in certificate
logs, among them `arizonasurf.`, `utahsurf.`, `vegascup.`, `washingtonrush.`). The provider code
`athletes2events` covers them all; the older `somsports` row predates it and holds no data. Pages
are server-rendered HTML with a declared UTF-8 charset and answer `requests` sent with a browser
User-Agent, no proxy and no bot challenge. `scripts/import_athletes2events_event.py` is the
driver; it takes `--event-url` and reads the host from it, because one provider row covers every
subdomain. Event 130 (Crossfire's 2026 ZF Labor Day Challenge) is the event it was built against.

### Pages and ids

Every page is `https://<host>.athletes2events.com/events/<event_id>/...`:

- `groups` — every division and flight. A division carries gender, U-age and its birth-date
  cutoff ("Boys-U19 (Born on or after: Aug 01, 2007)"); each flight (Gold, Silver, Silver 2) links
  to `schedules?flight-id=<n>`.
- `schedules?flight-id=<n>` — `table.schedule-table` holds standings (position, logo, team link,
  MP W D L GF GA GD POINTS, goals capped at 6). Each day is one `table.matches-table`: a colspan
  header row with the date ("Sat Sep 05, 2026"), then nine columns — Game #, Division/Flight, Group
  (A, A/B, Semi-Finals A, Final), Time, Home, Result, Away, Field, Location. Every team cell links
  to `schedules?team-id=<n>`.
- `schedules?team-id=<n>` — the team page, the only source of a team's state and coach. Its header
  reads `<Boys|Girls>-U<n> <team name> (<ST>) - Matches Team ID# <n> Coach: <name> Manager: <name>`
  (sometimes `Managers:`).
- `details` — `Event Dates: From <Mon DD, YYYY> to <Mon DD, YYYY>`, `Entry Deadline: <Mon DD, YYYY>`,
  and Boys/Girls fee tables that repeat each division's birth cutoff beside its price. Take the
  event's season from the dates here: they give it outright, so nothing has to infer a season from
  game dates. Take the per-division cutoffs from `groups` instead, which is fetched anyway for its
  flight links and lists the divisions that actually *ran* — a fee table lists the divisions
  *offered* at registration, and the two need not agree (they did at event 130, all 17, but a
  division in `groups` and absent from the fee table would be silently dropped). The page carries
  no team or flight links, so the roster still comes from the flight and team pages. The other
  pages are `fields`, `scoring-rules`, `event-rules` and `event-coaches`. The last lists attending
  college coaches with their emails; do not store it.

Event ids and team ids are one platform-wide sequence, so a team id is unique without its
subdomain. An event requested on the wrong subdomain redirects to that host's home page, which
lists the host's current events. Team ids mostly carry over between events but not always — of
17 teams that played both Crossfire events 124 and 130, 11 kept their id — so name-match an
unfamiliar id before creating a team.

- Results read `7 - 0`; a shootout reads `1 - 1 (3 - 4)`, recorded at its regulation score as a
  draw. A bracket slot the site never filled keeps a placeholder name (`Team-2`) with a score and
  no team link; hold that game.
- There is no club field. A team's logo is its club's — every team of a club shares one image
  file — but the image carries no text, `alt="Logo"` and a timestamp file name, so it names
  nothing.
- Logo `src` values are presigned S3 URLs carrying the host's AWS access key id. The bucket also
  serves them unsigned. Strip every `img` `src` from a captured page before committing it as a
  fixture: the repo is public.

### Reading an Athletes2Events team

The team page header is `<Gender>-U<division age> <Club> <Team> (<ST>)`, with nothing separating
club from team.

- **The age group comes from the team's own name, never the division** — the division is only
  where it played. Read the name through the label key in CLAUDE.md's Age Groups section. A
  division is still an upper bound: a team plays up, never down, so it is the division's age or
  younger (27 of 220 teams in event 130 played up).
- Owner's fallbacks (2026-09-18): no age in the name, or an odd span such as `G2018-2016` — use the
  division's age; two U-ages (`U12/13`, `U11/U12`) — leave the team out; a `B12`-style tag whose
  birth-year reading is older than its division — read it as Boys U12. A single birth year (`B16`)
  fits two ages; take the one the division allows.
- Skip U8 and U9: no board.
- The club is the words before the first age token, league tag or comma. `XF` or a bare
  `Crossfire` is **Crossfire Premier**; `Crossfire Select` is the separate club **Crossfire Select
  Soccer Club** — both are PitchRank's stored names. A nickname before the age token stays
  attached to the club (`NK Dire Wolves BU11`), so compare against PitchRank's clubs rather than
  trusting the split.
- A comma usually precedes the coach's surname, not the team name (`NSC EBU12, Oviedo`).
- The state is the `(ST)` in the team page header.

### Matching Athletes2Events teams

The gates in Provider Matcher Name Parsing below apply. This platform glues squad marks together:

- `RCL1`, `RCL 1` and `RCL-1` are one squad label — RCL is a team-name distinction here, not a
  league — and `ECNL2` is ECNL squad 2. Count a label only when both names carry one.
- A squad letter glued to the age or year is a squad mark: `B-U10B`, `GU10A`, `B15C`.
- Coach surnames and nicknames tell squads apart (`Delgado` against `Reyes`, `Attack` against
  `Bravo`), but no gate reads them yet, so such squads tie and go to review.
- A PitchRank row named by one birth year (`XF 2016 RCL 2`, `XF B13 ECNL`) is usually last
  season's record of the squad. Two event squads landing on one such row (`ECNL 1` and `ECNL 2`
  on `XF B13 ECNL`) is a conflict, not a link.

### Importing Athletes2Events games

- `EnhancedETLPipeline` selects `Athletes2EventsGameMatcher` and passes `dry_run`, so a
  `--dry-run` import writes nothing. Before that branch existed the provider fell through to the
  bare `GameHistoryMatcher`, constructed without `dry_run`, and a dry run still wrote aliases and
  review rows. Write the team aliases first so every game's teams resolve by id, and import only
  games whose two teams are both settled.
- The importer validates both teams against one age group per game, so a game between teams of
  different stored ages — a team playing up — inserts half-matched (see Repairing a half-matched
  game below). The driver holds those back and writes them to its own `*_cross_age.csv`, since
  `off_board_links` compares each team only against its own division and never the two to each
  other.

## Provider Matcher Name Parsing

Rules for a provider matcher that gates fuzzy candidates on the team name
(`src/models/soccereventsgroup_matcher.py` follows them):

- Avoid `game_matcher.extract_team_variant` and `extract_distinctions()["coach_name"]` as a
  squad gate. Both read tier and band tokens ("ECNL-RL", the "/13" of "G2012/13") as a coach,
  so two spellings of one squad are rejected and a duplicate team is created.
- Gate squads on `colors`, `directions` and `team_number` from `extract_distinctions`, squad
  codes (N1, S2), and tiers via `squad_name_gates.extract_tier_tokens` / `tiers_conflict`,
  dropping "ga" on a boys team (Girls Academy is girls-only, so there it means Georgia).
  Count a squad number or code only when both names carry one. Leave `location_codes` out: it
  collects leftover words ("Lou" of "Lou Fusz") and rejects real matches.
- Strip the club from both names before reading squad marks, or a club's own words
  ("Blue Fire", "Blue Star") read as colors.
- Extract the club yourself before calling `extract_club_from_team_name`. Normalize a glued age
  and gender ("U15G", "14uG", "BU07") to `U<n>`, strip a leading U-age, and cut the name at a
  two-digit band ("14/15", "15/16B") or a Boys/Girls word. Left in, a glued form or band stays
  in the club, and a leading `U12` yields no club at all. Collapse dotted initials too:
  `extract_distinctions` reads the "S" of "S.C." as the direction South.
- Break equal scores on an exact name match, then a same-state candidate over a stateless one;
  send a remaining tie to review rather than taking the first candidate.
- Cap review-queue confidence with `src/tournaments/alias_writer.REVIEW_QUEUE_CLAMP` (0.89).
  `team_match_review_queue` requires 0.75 <= confidence < 0.90, the clamp covers only the
  upper bound, and the base `_create_review_queue_entry` logs a refused insert and drops the row.
- When two teams registered in one event link to the same PitchRank team, they are two squads:
  hold each new fuzzy link to it as a conflict, and keep a link that was already approved or
  whose team row carries the provider team id (`import_soccereventsgroup_event.shared_links`).

To test matching against production without writes, construct the matcher with
`dry_run=True` and a provider id that has no aliases, so every team goes through fuzzy
matching. Teams an earlier real run created then appear as existing candidates, so the
replay's link counts overstate what a first run on a fresh event does.

### Mirroring that matcher for a new provider

Four things a first-draft port gets wrong. Symbols are named rather than line-numbered: the
shared helpers moved out of the Soccer Events Group matcher on 2026-09-20 and every line
anchor into that file went stale in the same commit.

- **`_fetch_candidates` is on the subclass, not the base.** It is defined on
  `SoccerEventsGroupGameMatcher` and called from its `_fuzzy_match_team`;
  `GameHistoryMatcher` has no equivalent. A new matcher that inherits the base and mirrors only
  the obvious overrides raises `AttributeError` the first time registration reaches candidate
  matching.
- **Never clamp `_calculate_match_score`.** That override adds `club_variant_match_boost` and
  caps at `min(1.0, ...)`. `REVIEW_QUEUE_CLAMP` is 0.89 while `auto_approve_threshold` is 0.90
  (`config/settings.py`, enforced in `GameHistoryMatcher._match_team`), so clamping ordinary
  scores makes `fuzzy_auto` unreachable and turns every auto-link into a review. The clamp
  belongs in `_create_review_queue_entry` and on the equal-rank tie path inside
  `_fuzzy_match_team`, nowhere else.
- **The shared name helpers live in `src/models/tournament_name_gates.py`**, which Soccer
  Events Group and Athletes2Events both import: `canonical_team_name`, `club_from_team_name`,
  `without_club`, `tier_tokens`, `is_boys`, `squad_marks` and `squads_conflict`. Two hooks keep
  the providers apart — `pre`, a callable applied before anything is read from a name, and
  `tier_extra`, the tiers the shared set omits. **Bind `tier_extra` explicitly.** Its default is
  empty, and `TOURNAMENT_TIER_TOKENS` (`pre`, `aspire`, `ea`, `ad`, `hd`) is in neither
  `squad_name_gates.TIER_TOKENS` nor that default, so a bare call stops telling "GA Aspire" from
  "GA" and "Pre-ECNL" from "ECNL". Each matcher wraps the shared `squad_marks` in a local one
  that binds it; emptying that binding flips 9 of the 16 parametrized tier cases in
  `tests/unit/test_soccereventsgroup_matcher.py` (measured).
  `scripts/import_soccereventsgroup_event.py` imports `canonical_team_name` from the matcher
  module rather than from the gates module, so that re-export is load-bearing.
- **A club the host writes under another name must be stripped from both sides.** Where the
  driver expands a written club to the name PitchRank stores, the stored form does not occur in
  either team name, so stripping it alone leaves the club's own words to read as squad marks —
  "Crossfire Select" leaves `select`, a tier token, and every stored row whose name omits the
  word is then refused. Stripping only the written form inverts the defect onto the rows that
  carry it. `Athletes2EventsGameMatcher._without_club` strips both, and the driver carries the
  written spelling on `TeamRow.club_as_written`.
- **`squad_name_gates.py` is under `src/models/`**, not `src/utils/`.

**Three hand-written test registries must gain the new matcher**, none of them derived, so omitting
any one passes green while covering nothing: `AUTOCREATING_MATCHERS` in
`tests/unit/test_provider_matcher_dry_run.py`; the separate `(provider, cls, create)` parametrize
list on `test_autocreate_writes_nothing_in_dry_run` in that same file, which calls the named create
helper with `dry_run=True` and asserts `insert` was never called; and `_SUBCLASS_PATHS` in
`tests/unit/test_birth_year_guard_wiring.py`. A matcher that creates only from a roster pass must
also join `REGISTRATION_MATCHERS` in the first of those files, or its identity tests run against a
team it never creates and pass on `None`.

And the matcher needs its own branch in `EnhancedETLPipeline._ensure_initialized`'s provider
chain (`src/etl/enhanced_pipeline.py`): the `else` fallback constructs a bare `GameHistoryMatcher` **without** `dry_run`, so until
that branch exists the provider's `--dry-run` import still writes aliases and review rows.

### Carry two seasons, never one

A per-event tournament provider needs both, and they are not interchangeable:

- **Event season** — from the event's own start date (`import_soccereventsgroup_event.py:240-242`).
  Used *only* to interpret labels: validating a division's birth cutoff against its U-age
  (`division_birth_year`, `:245-268`) and reading a U-age in a team's name (`name_age_mismatch`,
  `:283-296`).
- **Board season** — `_soccer_season_year()` from the wall clock, used by `board_cohort`
  (`:271-280`) to decide which board a birth year sits on *now*. `main` passes it at `:752`,
  `build_roster` uses it at `:321`. Its docstring: "Boards move every Aug 1, so a team from an
  earlier season's event is filed by its age now, not by the label it played under."

Collapsing them files a historical event's teams onto a stale board, and base alias matching then
rejects the mismatched stored age (`src/models/game_matcher.py:1002-1009`). This is the same point
*Reading a Provider's Age Labels* makes below — a label does not carry its own season — applied to
the two places the season is consumed.

### Resolving provider review items by hand

- Link a team with an approved `team_alias_map` row: `match_method` "manual", or "direct_id"
  when the target team row already carries that provider team id (`teams.provider_team_id`).
  First check that no other team in the same event already links to the target.
- Make a new team through the provider matcher's create helper plus a direct_id alias.
- Read the alias back, then set the queue row's `status` ("approved" for a link, "rejected"
  for a new team), `reviewed_by` and `reviewed_at`. The base `_create_alias` logs a failed
  write and returns normally.
- Write the alias directly rather than through the `approve_team_match` RPC. The RPC inserts
  `match_method = 'manual_review'`, which the `valid_match_type` CHECK from migration
  `20240201000004` does not allow, and where the insert does land its `ON CONFLICT DO NOTHING`
  keeps any existing alias.

### Repairing a half-matched game

In a Soccer Events Group game import, the base `GameHistoryMatcher._validate_team_age_group`
refuses a link whose team's stored age group or gender no longer matches the game, and the
game inserts with that side NULL. Other providers differ: the TGS, SincSports and PlayMetrics
matchers override `_match_by_provider_id` without the check.

- Hold such games back before the import (`import_soccereventsgroup_event.off_board_links`).
  **Read what that check actually covers.** It compares each *linked* team's stored age group and
  gender against **its own** roster row's division values (`:475-497`), and skips `created`
  outcomes entirely — which is not a harmless narrowing, because `LINKED_OUTCOMES` (`:140`) *does*
  include `created`, so it declines to examine exactly the outcome the CSV builder will still emit
  rows for. It never compares a game's two teams to each other. So it catches a link whose stored
  board has drifted from its division, and it does **not** catch a correctly assigned U10 team
  playing a correctly assigned U11 opponent — that pair passes cleanly, and `build_csv_rows` then
  stamps the **home** team's age (`:648`) and gender (`:649`) onto both importer rows, inserting
  the away side half-matched on either axis. A provider that must hold cross-age games back needs a
  second, game-level check comparing both teams' boards before either row is emitted. The only
  prior art is `src/models/modular11_matcher.py`, and it is a loose fit: it rejects the whole game
  rather than holding it, and only once `abs(home_age - away_age) >= 2` (`:1875`), so the U10/U11
  pair above passes that too. A one-year gap is caught nowhere.
- To repair a stored one, re-point the alias to the team on the right board, then re-run the
  import with a `--days-back` that covers the game's date. The composite duplicate check
  (provider, both provider ids, date, both scores) finds the stored row, and
  `EnhancedETLPipeline._backfill_duplicate_team_links` fills only its NULL master ids. It skips
  Modular11 and dry runs.
- Read the game back afterwards. A game outside the window is not re-imported at all, a
  changed score inserts a second row beside the half-matched one, and the run's summary does
  not report the fill.
- Leave the game un-excluded: exclusion does not stop the fill, but it stays on the repaired
  row and hides it. Let the backfill write the team id rather than writing it by hand.

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

### Decoding an HTML response

**A `Content-Type: text/html` response carrying no charset decodes as ISO-8859-1**, the RFC 2616 default:
`requests.utils.get_encoding_from_headers({"content-type": "text/html"})` returns `'ISO-8859-1'`
(requests 2.32.5). GotSport serves UTF-8 and declares no charset anywhere — of the 55 fixture
pages, 53 carry non-ASCII including Arabic, and not one declares a `<meta charset>`. (The two
without non-ASCII are synthetic fixtures rather than captured pages.)

Set the encoding before anything reads `.text`:

```python
if "charset" not in str(response.headers.get("content-type", "")).lower():
    response.encoding = "utf-8"
```

Skipping it costs matches, not just tidiness. A team the provider gives no id for is matched on
its **name**, so a mojibaked name loses exactly the team a provider id could not rescue.
`_fetch_once` in `src/tournaments/gotsport_event_roster.py` carries the shipped form, placed ahead
of the bot-challenge check because that check reads `.text` too.

Give the test double raw bytes plus an `encoding`, and let its `text` decode them the way
`requests` does. A double that hands back a ready-made `str` makes every charset look identical and
cannot fail when this regresses.

The same default drives the JSON-body trap under ZenRows Batch API above, where the remedy is to
parse `response.content` instead.

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
        'team_id': clean_provider_id(row.get('team_id')),
        'team_name': row.get('team_name', '').strip(),
        'opponent_id': clean_provider_id(row.get('opponent_id')),
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

**Check a sample before calling a division's ages unreliable.** Read the birth
years in its team names first. When sampling `teams`, skip rows this provider
created or matched, since their age group came from the division, and compare
against the board the division maps to this season rather than its printed label.
Raise the doubt with the operator when that sample disagrees.

**Once a division's cohort is resolved, a team's name can only veto it.** A U-age
in the name that differs from the division's, read against the event's own
season, sends a not-yet-linked team to the review queue instead of linking or
creating it. The name never sets the team's age
(`import_soccereventsgroup_event.name_age_mismatch`).
