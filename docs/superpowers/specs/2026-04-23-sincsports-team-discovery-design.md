# SincSports Team Discovery — Design

**Date:** 2026-04-23
**Status:** Draft — awaiting user review
**Author:** Claude (brainstorming session with Dallas)

## Background

SincSports (`soccer.sincsports.com`) is an ASP.NET tournament and team management platform
that hosts schedules and results for a large share of US youth club soccer events. PitchRank
already has a per-team scraper (`src/scrapers/sincsports.py`) that pulls games for a single
team via `/team/games.aspx?teamid=NCM14762`, plus a matcher (`src/models/sincsports_matcher.py`)
used during game import to resolve opponents to master team IDs.

What PitchRank does **not** have is a way to seed the `teams` table with SincSports teams
ahead of event scraping. Without that seed, the first event we scrape has to fuzzy-resolve
every opponent against the rest of the database, which is both slow and prone to false
negatives because schedule-page HTML rarely carries clean `state_code`, `age_group`, or
`club_name` metadata.

The SincSports "Clubs & Teams" search page (`/sicclubs.aspx?sinc=Y`) exposes a structured
filter UI (State × Age × Gender × Type × USA Rank) that returns teams with all four metadata
fields explicitly known from the filter inputs. That is the ideal discovery source.

An incomplete earlier attempt lives at `scripts/search_sincsports_teams.py`: it loads the
page and captures `__VIEWSTATE`, but never figured out the ASP.NET postback fields needed to
submit a filtered search. This design supersedes that script.

## Goals

1. Populate `teams` and `team_alias_map` with SincSports club teams for **Boys/Men and
   Girls/Women, U10–U19, across all 50 US states + DC**, with full metadata
   (`team_name`, `club_name`, `age_group`, `gender`, `state_code`).
2. Reuse `SincSportsGameMatcher` for cross-provider dedup so discovered teams link to
   existing records (e.g. a team already in DB via GotSport or TGS) rather than
   creating duplicates.
3. Produce a resumable, observable, rerunnable pipeline — matches the TGS import ergonomics
   (`scripts/extract_and_import_tgs_teams.py`) with a rich progress UI, dry-run mode, and
   CSV checkpoint.
4. Feed the existing weekly hygiene workflows — no new hygiene logic required; post-discovery,
   `data-hygiene-weekly.yml` and `unknown-opponent-hygiene-weekly.yml` continue to run as-is.

## Non-goals

- **Event scraping.** This design is discovery-only. A separate spec will cover scraping
  `teamlist.aspx` + `schedule.aspx` for tournament results once discovery is live.
- **Co-Ed, Recreation, High School, Adult team types.** Only `Type = Team` club teams.
- **International / territories.** No Puerto Rico, Canada, Mexico, XX-International.
- **Historical back-coverage.** We scrape the current SincSports directory as-is; no
  attempt to reconstruct teams that existed in prior seasons.
- **New matcher logic.** `SincSportsGameMatcher` is verified current and reused as-is.

## Architecture

Three deliverables, in order of dependency.

### A. `src/scrapers/sincsports_clubs.py` — scraper class

New file; does not modify the existing `sincsports.py` (that scraper is team-centric and
should stay focused).

```python
class SincSportsClubsScraper:
    BASE_URL = "https://soccer.sincsports.com"
    SEARCH_PAGE = "/sicclubs.aspx?sinc=Y"

    def __init__(self, delay_min: float = 2.0, delay_max: float = 3.0, ...):
        self.session = self._init_http_session()  # mirrors sincsports.py

    def discover_teams(
        self,
        states: List[str],        # e.g. ["Arizona", "California", ...]
        ages: List[str],          # e.g. ["U10", "U11", ..., "U19"]
        genders: List[str],       # e.g. ["Boys / Men", "Girls / Women"]
        usa_ranks: Optional[List[str]] = None,   # None = all 7 tiers
    ) -> Iterator[TeamRecord]:
        """Yields TeamRecord per discovered team. Deduped by provider_team_id."""
```

Internals:

- **Session bootstrap.** GET `sicclubs.aspx?sinc=Y`, parse `__VIEWSTATE`,
  `__EVENTVALIDATION`, `__VIEWSTATEGENERATOR`. Cache for session.
- **Filter submission.** POST with form fields for the Search Teams button. Exact field
  names must be captured from the live page during implementation — see "Unknowns" below.
- **Pagination.** Replay with `__EVENTTARGET=...$lnkPageN` postbacks until no more pages
  or result count plateaus.
- **Row parsing.** Each result row exposes a link to `/team/default.aspx?teamid=NCM14762`.
  Extract `provider_team_id` from the `teamid` query param; extract `team_name`, `club_name`
  (rendered in result row), and infer `age_group` / `gender` / `state_code` from the
  filter values we submitted (not from the row — the filter inputs are authoritative).
- **Throttling.** 2.0–3.0s random delay between requests, `Retry(total=3, backoff=0.5)`
  for 500-series, custom retry for 429. Configurable via env vars mirroring the existing
  scraper (`SINCSPORTS_DELAY_MIN` etc.).
- **Error surfacing.** `.errors` attribute accumulates per-combo failures for the driver
  to report; does not raise on partial failures.

A `TeamRecord` dataclass lives in this module:

```python
@dataclass
class TeamRecord:
    provider_team_id: str          # "NCM14762"
    team_name: str                 # "NC Fusion U12 PRE ECNL Boys Red"
    club_name: Optional[str]       # "NC Fusion"
    age_group: str                 # "u12"
    gender: str                    # "Male" | "Female"
    state_code: Optional[str]      # "NC", "CA", "AZ", ...
```

`usa_rank` is submitted as a filter (all 7 tiers checked) but **not** captured on the
`TeamRecord` — discarded per design decision. Revisit if ranking-cohort filtering becomes
a concrete need.

### B. `scripts/discover_sincsports_teams.py` — driver script

New file; mirrors the shape of `scripts/extract_and_import_tgs_teams.py` (argparse + rich
progress + dry-run + summary), but sources teams from the scraper rather than a CSV.

Flow:

1. **Load env** (`.env.local` then `.env`), validate Supabase creds.
2. **Resolve `provider_id`** for `code='sincsports'` (create row if missing, same as
   `import_sincsports_teams.py` does).
3. **Build filter grid**: states × ages × genders. Default is all 50 + DC, U10–U19,
   both genders. CLI flags let you scope it down for testing / incremental runs:
   - `--states "AZ,CA,NC"` — comma-separated state postal codes (mapped to SincSports
     filter labels internally).
   - `--ages "u10,u11,u12"` — comma-separated age groups.
   - `--genders "male,female"` — gender selector.
4. **Scrape phase.** Instantiate `SincSportsClubsScraper`; iterate `discover_teams(...)`;
   write to an in-memory dict keyed by `provider_team_id` (dedupe). Every N teams, flush
   to a CSV checkpoint: `data/exports/sincsports_teams_discovery_<timestamp>.csv` with
   columns `provider_team_id, team_name, club_name, age_group, gender, state_code`.
5. **Resume support.** If `--resume <csv_path>` is passed, read the CSV first, seed the
   in-memory dict, and skip `(state, age, gender)` combos already fully represented.
6. **Bulk pre-check** (mirrors TGS pattern): batch `IN(...)` queries against `team_alias_map`
   in chunks of 100 to find SincSports `provider_team_id`s already aliased. Skip those.
7. **Match phase.** For each remaining team, call
   `SincSportsGameMatcher._match_team(provider_id, provider_team_id, team_name, age_group,
   gender, club_name)`. The matcher:
   - Tier 1: direct ID → already handled by step 6, should not hit here except on race
     conditions.
   - Tier 2: fuzzy cross-provider match → creates an alias (`match_method='fuzzy_auto'`
     if ≥0.91, `'manual_review'` if 0.75–0.91). Pending review rows do **not** link games
     until approved, matching existing hygiene semantics.
   - Tier 3: no match → creates a new `teams` row + direct_id alias
     (`match_method='direct_id'`, confidence `1.0`).

   Note: state_code is not currently accepted by `_match_team()`. The matcher uses it
   only as a scoring tiebreaker, queried from the candidate row. **Approved addition:**
   extend `_create_new_sincsports_team()` in `src/models/sincsports_matcher.py` to accept
   and persist `state_code` (backward-compatible, default `None`). This is required to
   realize the main metadata-quality benefit of doing discovery upfront.
8. **Summary report.** Rich table with counts: teams scraped, already-aliased (skipped),
   fuzzy-auto linked, queued for review, new teams created, errors. Breakdown by state
   and by match method.

CLI:

```
python scripts/discover_sincsports_teams.py
    [--states "AZ,CA,..."]          # default: all 50+DC
    [--ages "u10,u11,..."]          # default: u10-u19
    [--genders "male,female"]       # default: both
    [--resume path/to/csv]          # skip combos already in checkpoint
    [--dry-run]                     # scrape + print, no DB writes
    [--checkpoint-every 500]        # rows between CSV flushes
    [--max-combos 5]                # testing: cap total combos scraped
```

### C. `.github/workflows/sincsports-team-discovery.yml` — manual trigger

New workflow, modeled on `data-hygiene-weekly.yml` but **manual-only** (no cron). Per
design decision: run ad-hoc until we understand the right cadence.

- **No `schedule:`** — `workflow_dispatch` only.
- `workflow_dispatch` inputs: `dry_run`, `states` (for targeted reruns), `ages`, `genders`.
- Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (same pattern as existing workflows).
- Artifacts: upload the CSV checkpoint + `logs/discover.log`.
- `timeout-minutes: 180` — conservative; expected runtime ~45–60 min for full grid.

Benefits of manual-only v1:
- First real runs will surface ASP.NET postback oddities, rate-limit thresholds, and
  captcha risk. Unsafe to run on an autopilot cron until those are characterized.
- Incremental state-by-state expansion is the safer rollout path.

## Data flow

```
sicclubs.aspx (ASP.NET)
    |  POST {state, age, gender, rank checkboxes, __VIEWSTATE, __EVENTVALIDATION}
SincSportsClubsScraper.discover_teams()
    |  yields TeamRecord per row
discover_sincsports_teams.py
    |  in-memory dedupe by provider_team_id
    |  CSV checkpoint at data/exports/sincsports_teams_discovery_<ts>.csv
    |  bulk pre-check team_alias_map (100-row IN batches) -> skip existing
    |  per remaining team:
    |      SincSportsGameMatcher._match_team(...)
    |          |-> tier 1: direct_id alias (rare here; mostly caught by pre-check)
    |          |-> tier 2: fuzzy cross-provider -> alias created
    |          |-> tier 3: no match -> teams row + direct_id alias created
    |  summary report
teams + team_alias_map
    |  (subsequent event scraping resolves opponents fast via direct_id tier 1)
    |  (weekly hygiene pipelines clean up the rest)
```

## Filter grid (v1 defaults)

- **Button:** Search Teams (not Search Clubs — we want team-level rows, not club-level
  aggregates).
- **Type:** Team.
- **Gender:** Boys/Men, Girls/Women. Skip Co-Ed.
- **Age:** U10, U11, U12, U13, U14, U15, U16, U17, U18, U19 (10 values).
- **USA Rank:** all 7 tiers checked (Gold, Silver, Bronze, Red, Blue, Green, Non-Ranked).
  The scraper submits explicit checkbox state for each tier — we do not rely on
  "all unchecked = all" behavior since that is unverified.
- **State:** all 50 US states + DC. No territories, no international.

Combo count: 51 × 10 × 2 = 1,020. At 2.5s average delay = ~43 minutes of scrape time
before any DB writes.

## Error handling

- **Scraper-level:** per-combo failure is logged to `.errors` and surfaced in the summary.
  A combo failing does not block subsequent combos. Retry logic (3 attempts, backoff)
  handles transient 500s; 404s are logged and skipped; 429 triggers longer backoff.
- **Driver-level:** matcher failures (e.g. Supabase outage mid-run) are caught per-team
  and recorded to a separate error list. The CSV checkpoint persists regardless, so a
  rerun with `--resume` picks up where it left off.
- **Duplicate key errors (23505):** mirror the TGS script — fall back to row-by-row on
  batch conflicts, treat duplicate as "already exists" and continue.
- **Captcha / block:** if the scraper detects captcha HTML patterns or receives a hard
  403 for several combos in a row, it aborts the run with a clear error rather than
  continuing to hammer the site. Manual intervention required. We will document the
  expected threshold in comments during implementation.

## Testing strategy

- **Unit tests** (`tests/scrapers/test_sincsports_clubs.py`):
  - HTML fixture parsing: given a canned `sicclubs.aspx` response HTML, assert parsed
    `TeamRecord`s match expected fields.
  - Pagination: given a fixture with 2 pages of results, assert all rows are yielded
    and deduped.
  - Empty result handling: no teams for a (state, age, gender) combo returns an empty
    iterator, not an error.

- **Integration test** (`tests/integration/test_sincsports_discovery.py`, gated by env):
  - With live network, scrape a single narrow combo (`--states AZ --ages u14 --genders male`)
    against a test Supabase project. Assert ≥1 team was created with full metadata.
  - Skip by default in CI; opt-in via `RUN_LIVE_SINCSPORTS_TESTS=1`.

- **Dry-run validation before the first real run:**
  1. `--dry-run --states AZ --ages u12 --genders male` — confirms scraper parses real HTML.
  2. Review the CSV output for field completeness, state_code correctness, age/gender
     accuracy.
  3. Re-run without `--dry-run`, scoped to AZ only, against production DB.
  4. Spot-check 20 random teams in `teams` table — correct metadata, correct aliases.
  5. Expand to remaining 49 states + DC.

## Unknowns to resolve during implementation

These are deferred to the implementation plan — they can't be locked without hitting the
live page:

1. **Exact form field names** for the State dropdown, Age dropdown, Gender selector,
   Type selector, and USA Rank checkboxes. Will be captured via browser devtools
   inspection of a Search Teams submission.
2. **Pagination mechanism.** Postback via `__EVENTTARGET` is the likely answer, but
   could be AJAX-driven "Show More" or a page-size dropdown. Confirm during scraper
   bootstrap.
3. **Rate limit thresholds.** Current sincsports.py uses 2–3s delay. If 429s appear
   under load, we increase; if not, we may tighten.
4. **"All states" multi-select.** If the page supports selecting multiple states in one
   query, we can collapse 51 states into 1 query per (age, gender) combo — 20 total
   combos instead of 1,020. This is a 50x speedup if available.

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| ASP.NET viewstate rotation breaks mid-run | Partial data loss | CSV checkpoint + `--resume` |
| SincSports layout change | Parser errors | Unit tests against fixture HTML; monitor `.errors` rate |
| Fuzzy matcher false positives link wrong teams | Data corruption | Matcher already gates 0.91+ for auto-approve; 0.75–0.91 goes to `manual_review` and does not link games until approved |
| State code mapping mismatch (SincSports uses full names; DB uses postal codes) | Teams created without state_code | Internal mapping dict in scraper; unit test covers round-trip |
| 1,020 combos × 100ms fuzzy per team = slow | Runtime ~1hr scrape + ~30min match | Acceptable for monthly job; checkpoint allows chunked runs |
| Hitting rate limits / captcha | Run aborts | Per-run 2.0–3.0s delay; abort on repeated 429/403 |

## Resolved design decisions

Recorded 2026-04-23 during brainstorming:

1. **Workflow cadence:** manual trigger only (`workflow_dispatch`), no cron in v1.
2. **USA rank:** submit as filter (all 7 checked) but **do not persist** on `TeamRecord`
   or `teams`.
3. **state_code extension:** approved — `_create_new_sincsports_team()` gets a
   backward-compatible `state_code` parameter so discovered teams land in the DB with
   full state metadata.

## Next steps

1. User reviews this spec and responds to the three open questions.
2. On approval, invoke the `writing-plans` skill to produce a step-by-step implementation
   plan.
3. Execute the plan via `executing-plans`, validating each phase (scraper fixture parsing
   → dry-run → narrow live run → full live run).
