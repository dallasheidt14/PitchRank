---
status: done
spec: docs/superpowers/specs/2026-05-28-somsports-tournament-scraper-design.md
---

# Plan: SOM Sports / athletes2events Tournament Scraper

## Context

PitchRank currently ingests tournament games from GotSport, SincSports, Affinity-WA, and PlayMetrics. Club America Cup (May 23-25, 2026) ran on `somsports.athletes2events.com` (SOM Sports / athletes2events platform), which PitchRank has not yet integrated. This plan adds a new provider adapter `somsports` with a tournament scraper, matcher, CLI driver, migration, and tests. Initial target is event 72 (Club America Cup, U10-U19, all flights, both genders); the CLI is event-ID-parameterized so future events on the same platform reuse the work.

The site is server-rendered HTML with two key page types: `/events/{id}/groups` (flight index) and `/events/{id}/schedules?flight-id={id}` (per-flight teams + standings + games). Team detail pages at `/events/{id}/schedules?team-id={id}` carry `(STATE)` in their header — so a two-pass scrape (flights → team enrichment) yields enough metadata for auto-create of unmatched canonical teams (team_name, club_name, age_group, gender, state_code, coach).

## Pattern Survey

### Analogous Features
- `src/scrapers/provider.py:86-123` — `ProviderScraper` ABC. **Not** subclassed for this work (see Proposed Alignment); SOM Sports follows the peer-script pattern.
- `src/scrapers/gotsport.py` — only `ProviderScraper` implementer. Uses `IntakeJournal`. **Not** mirrored.
- `src/scrapers/sincsports_schedule.py:107-239` — pure parser module (`parse_division`, `parse_tournament_index`) emitting `TournamentGame` dataclass, thin live wrapper (`SincSportsScheduleScraper`) with shared session + `SINCSPORTS_DELAY_MIN/MAX` jitter. Closest HTML-parsing analog. **Mirror this split.**
- `scripts/scrape_sincsports_tournament_schedule.py:1-213` — CLI driver: `argparse` with `--tid --year --include-cancelled --include-scheduled --auto-import --dry-run`. `load_dotenv(".env.local")` then `.env`. JSONL output at `data/raw/sincsports_games_tournament_{tid}_{ts}.jsonl`. `--auto-import` subprocess-shells to `scripts/import_games_enhanced.py {out} sincsports`. `perspective_record()` at line 72 is the canonical H+A row shape. **Mirror this CLI.**
- `scripts/scrape_affinity_wa_tournament.py:184-378` — HTML tournament with flight-discovery → flight-scrape flow. `discover_flights()` parses listing page for `(division_name, flight_guid, gender, age)`; per-flight scrape parses results table with date headers using `requests` + `bs4(html, "lxml")` + hand-rolled 3-attempt retry. `_team_hash()` at line 89 generates a synthetic team ID when source has none. **Mirror the flight-discovery + per-flight-parse shape**; we do NOT need `_team_hash` because SOM Sports has stable numeric team IDs.
- `scripts/scrape_playmetrics_tournament.py:80-107` — `derive_division_age_group(division_name)` parses U-tokens and slash forms ("U15/16" → take higher → u16; "2014/15" → take older → u12). **Extract this helper to a shared module so SOM Sports and PlayMetrics consume the same logic** (per `architecture_age_pattern_drift.md` memory: AGE_PATTERN already duplicated across 4 files — do not make it 5).

### Reusable Utilities
- `src/scrapers/_age_normalization.py:20` — `normalize_age(age_int) -> Optional[str]` returns `"u10".."u17","u19"` with U18→U19 fold. **Use for the U18→U19 canonicalization** the spec calls out.
- `src/scrapers/_http.py:43-204` — `retry_session_get(session, url, *, attempts, retry_delay, baseline_bytes, is_event_url, provider, **kwargs)` for 429/timeout/short-body handling with `Retry-After` parsing. **Use this** instead of hand-rolling retries.
- `src/utils/team_name_utils.py` — `extract_club_from_team_name`, `normalize_name_for_matching`, `has_ecnl_only`, `has_ecnl_rl`, `extract_team_variant`. **Use in `SomSportsGameMatcher._normalize_team_name`**.
- `src/utils/club_normalizer.py:601-865` — `normalize_to_club(name, fuzzy_threshold=0.85)`, `similarity_score`. Every matcher imports these.
- `src/tournaments/alias_writer.py` — `upsert_team_alias`, `enqueue_match_review`. Matcher writes alias rows here (not in `import_games_enhanced.py`).
- `src/models/game_matcher.py:439` — `GameHistoryMatcher` base. Override `_normalize_team_name` (1318), `_fuzzy_match_team` (1093), `_match_team` (704) as needed.
- `src/models/sincsports_matcher.py:87,213,325,660` — `SincSportsGameMatcher` is the closest mirror: overrides `_normalize_team_name` (strips leading age prefixes), `_fuzzy_match_team`, has `_create_new_sincsports_team(...) -> (id, was_created)` auto-create returning the tuple shape. **Mirror this structure**.

### Convention Anchors
- **Provider seed migration**: `supabase/migrations/20260507000000_seed_playmetrics_tournament_provider.sql` — `INSERT INTO providers (code, name, base_url) VALUES ('<code>','<name>','<url>') ON CONFLICT (code) DO NOTHING;` with header comment explaining `EnhancedETLPipeline._ensure_initialized()` does the lookup. Filename pattern: `YYYYMMDDHHMMSS_seed_<code>_provider.sql`. Latest existing migration is `20260526100000` — new one uses `20260528000000`.
- **PROVIDERS dict entry** (`config/settings.py:55`): each entry has `code`, `name`, `base_url`, `adapter` (dotted Python path). Existing entries: `gotsport`, `tgs`, `usclub`, `sincsports`, `athleteone`. Add `somsports` mirroring these.
- **Matcher routing** (`src/etl/enhanced_pipeline.py:228-244`): elif/elif chain on `self.provider_code.lower()`. Each branch lazy-imports its matcher subclass and constructs `(supabase, provider_id, alias_cache)`. Add `elif self.provider_code.lower() == "somsports"` branch mirroring `sincsports` at line 228.
- **CLI driver layout** (`scripts/scrape_*.py`): shebang → docstring → argparse → `load_dotenv(".env.local")` fallback `.env` → `sys.path.append(str(Path(__file__).parent.parent))` → `main()` → JSONL output → optional `--auto-import` subprocess call. Mirror exactly.
- **Test fixtures**: `tests/fixtures/<provider>/event_<id>__group_<gid>.html` style (gotsport) or `schedule_<slug>.html` (sincsports_events). Tests at `tests/unit/test_<provider>_*.py` use `FIXTURES = Path(__file__).parent.parent / "fixtures" / "<provider>"`. Pure parser tests against saved HTML, **no HTTP mocking, no pytest-vcr**.
- **HTTP standard**: `requests` + `bs4`. `BeautifulSoup(html, "lxml")` for tournament HTML (affinity). Rate limit: `time.sleep(random.uniform(delay_min, delay_max))` with env-tunable `SOMSPORTS_DELAY_MIN/MAX` (defaults 1.0/2.0 sec).
- **Score parser**: each tournament driver inlines `try: int(score_str) except ValueError: None`. No shared `"3-1" -> (3,1)` parser today. Inline OK; one regex helper for `r"(\d+)\s*[-vV:]\s*(\d+)"` is enough.

### Proposed Alignment
- **Mirror the peer-script pattern, NOT `ProviderScraper`**. Only GotSport uses the ABC; SOM Sports follows the SincSports/Affinity-WA/PlayMetrics convention. (Confirmed product decision: see spec section "Adapter pattern".)
- **Mirror `scrape_sincsports_tournament_schedule.py` for the CLI + JSONL output** (battle-tested via `import_games_enhanced.py`). Same `perspective_record` row shape (H + A perspective per game).
- **Mirror `scrape_affinity_wa_tournament.py` for two-pass HTML flight-discovery → flight-scrape**, then add a third pass: team-detail enrichment for state code.
- **Mirror `SincSportsGameMatcher` for the matcher subclass**: override `_normalize_team_name` (strip ECNL/MLS-Next/RL/AD/EA + coach-name-suffix markers), override `_fuzzy_match_team` if needed, add `_create_new_somsports_team(...) -> (id, was_created)` returning the canonical tuple shape, gated on state+club+age availability from the team detail enrichment pass.
- **Extract `derive_division_age_group` to a shared module** (`src/scrapers/_age_normalization.py` — add it next to `normalize_age`) so PlayMetrics and SOM Sports consume the same parser. Refactor PlayMetrics's import in the same PR. This serves the current goal (we need the helper) and de-dupes per `architecture_age_pattern_drift.md`.
- **Resume strategy**: per-flight done-marker file (`reports/somsports/{event_id}/.flights_done/{flight_id}.done`). Each parsed flight touches its marker; `--resume` skips flights with existing marker. Simpler than IntakeJournal's team-level skip-set and matches the flight-level semantics the spec specifies.
- **Unmatched team policy**: two-pass scrape + auto-create with full state (confirmed product decision). Matcher's `_create_new_somsports_team` creates the canonical row when `_fuzzy_match_team` returns no match ≥ 0.9; logs the creation; surfaces auto-created list in run summary.

## Implementation Steps

> **Before starting:** Branch from `origin/main`, NOT the current `fix/null-score-backfill` working tree. The working tree currently has uncommitted modifications (`.pyc` files, `CLAUDE.md`, many untracked files in `data/`, `logo/`, `scripts/`) unrelated to this work. Per `feedback_verify_branch.md` and `feedback_git_stash.md`: do NOT stash; create a fresh worktree-free branch.
>
> Setup commands (verify clean before edits):
> ```bash
> cd C:/PitchRank
> git fetch origin
> git checkout -b feat/somsports-scraper origin/main
> git status  # must show clean working tree (only .pyc allowed)
> ```
> If the working tree shows tracked modifications to files this plan edits (`config/settings.py`, `src/etl/enhanced_pipeline.py`, `scripts/scrape_playmetrics_tournament.py`), STOP and resolve before continuing.

1. **Extract `derive_division_age_group` to a shared module**
   - Move `derive_division_age_group(division_name: str) -> Optional[str]` from `scripts/scrape_playmetrics_tournament.py:80-107` to `src/scrapers/_age_normalization.py` (next to `normalize_age`).
   - Also move the two regex constants it depends on (`_DIV_U_SLASH_RE` and `_DIV_U_TOKEN_RE` at `scripts/scrape_playmetrics_tournament.py:73-74`). Leave `_VENUE_STATE_RE` at line 77 in playmetrics — it's only used by `derive_state_from_address`, which stays.
   - Update `src/scrapers/_age_normalization.py` imports — the file currently imports only `Optional` from `typing`. Add: `import re` and extend the typing import to `from typing import List, Optional`.
   - Preserve the existing logic exactly: slash-form older-cohort-wins for both birth-year (`2014/15` → u12) and U-token (`U15/16` → u16) variants. Preserve the U18→U19 fold at lines 105-106.
   - In `scripts/scrape_playmetrics_tournament.py`, replace the local definition + the two regex constants with `from src.scrapers._age_normalization import derive_division_age_group`. Remove the now-unused `_DIV_U_SLASH_RE`, `_DIV_U_TOKEN_RE`, and the original function.
   - Verify no other callers: `grep -rn "derive_division_age_group" --include="*.py" C:/PitchRank` — only `scrape_playmetrics_tournament.py` should match (caller) and the new home in `_age_normalization.py` (definition).

2. **Add provider seed migration**
   - Create `supabase/migrations/20260528000000_seed_somsports_provider.sql`.
   - Header comment explains: `EnhancedETLPipeline._ensure_initialized()` looks up provider_id by code; this row is needed before the scraper's first import.
   - Body:
     ```sql
     INSERT INTO providers (code, name, base_url)
     VALUES ('somsports', 'SOM Sports / athletes2events', 'https://somsports.athletes2events.com')
     ON CONFLICT (code) DO NOTHING;
     ```
   - Apply via `supabase db push` after merge (do NOT apply during implementation — done as part of deploy).

3. **Add `somsports` entry to `PROVIDERS` dict**
   - In `config/settings.py:55-86` (`PROVIDERS = {...}`), add (preserving all existing entries `gotsport`, `tgs`, `usclub`, `sincsports`, `athleteone`):
     ```python
     "somsports": {
         "code": "somsports",
         "name": "SOM Sports / athletes2events",
         "base_url": "https://somsports.athletes2events.com",
         "adapter": "src.scrapers.somsports",
     },
     ```
   - Preserve `MATCHING_CONFIG` (lines 187-207) untouched. Preserve every other constant in the file.

4. **Write `src/scrapers/somsports.py` (parser module + thin live wrapper)**
   - **Pure parser functions** (no network):
     - `parse_groups_page(html: str) -> list[FlightRef]` — extract all `(flight_id, age_group, gender, tier_label, raw_division_name)` tuples from `/events/{id}/groups`. Use `BeautifulSoup(html, "lxml")`. Match anchors with `flight-id=` query param via regex on `href`. Parse `(Boys|Girls)-?U(\d+)` from heading. Run age through `normalize_age` (U18→U19 fold) and `derive_division_age_group` (slash-form handling).
     - `parse_schedule_page(html: str) -> tuple[list[ScrapedTeam], list[TournamentGame]]` — given a `?flight-id=N` page, return:
       - Teams from the standings table(s) — capture `provider_team_id` from team link `?team-id=N`, team name, group letter (A/B/C), standings position, MP/W/D/L/GF/GA/GD/Pts.
       - Games from the results table — capture game_id, date, time, home name, away name, home_score, away_score, field, venue. Skip rows where score is empty/dash (unplayed).
     - `parse_team_detail_page(html: str) -> TeamDetail` — extract `state_code` from `(XX)` in page header, plus `coach`, `manager` if present. Used in pass 2.
     - `_parse_score(s: str) -> tuple[Optional[int], Optional[int]]` — `re.fullmatch(r"\s*(\d+)\s*[-vV:]\s*(\d+)\s*", s)`. Empty/dash → `(None, None)`.
   - **Dataclasses** in same file (mirror `TournamentGame` shape from `sincsports_schedule.py`):
     - `FlightRef(flight_id: int, age_group: str, gender: str, tier_label: str, raw_division_name: str)`
     - `ScrapedTeam(provider_team_id: str, team_name: str, group_letter: str, position: int, mp: int, w: int, d: int, l: int, gf: int, ga: int, gd: int, pts: int)`
     - `TournamentGame(game_id: str, game_date: date, kickoff_time: Optional[str], home_provider_team_id: str, home_team_name: str, away_provider_team_id: str, away_team_name: str, home_score: Optional[int], away_score: Optional[int], field: Optional[str], venue: Optional[str], flight_id: int)`
     - `TeamDetail(provider_team_id: str, state_code: Optional[str], coach: Optional[str], manager: Optional[str])`
   - **Live wrapper** `SomSportsScraper`:
     - Constructor: `(session: requests.Session = None, delay_min: float = 1.0, delay_max: float = 2.0)` — env-tunable via `SOMSPORTS_DELAY_MIN/MAX`.
     - `fetch_groups(event_id: int) -> list[FlightRef]` — GET `/events/{event_id}/groups`, call `parse_groups_page`.
     - `fetch_flight(event_id: int, flight_id: int) -> tuple[list[ScrapedTeam], list[TournamentGame]]` — GET `/events/{event_id}/schedules?flight-id={flight_id}`, call `parse_schedule_page`.
     - `fetch_team_detail(event_id: int, provider_team_id: str) -> TeamDetail` — GET `/events/{event_id}/schedules?team-id={provider_team_id}`, call `parse_team_detail_page`.
     - All three use `src.scrapers._http.retry_session_get` for 429/backoff handling and `time.sleep(random.uniform(self.delay_min, self.delay_max))` between requests.

5. **Write `src/models/somsports_matcher.py`**
   - Mirror `src/models/sincsports_matcher.py` structure exactly. The sincsports matcher is the canonical template — read lines 87-156 (class + `_create_review_queue_entry`), 213-245 (`_normalize_team_name`), 555-640 (`_match_team` override that does the alias write), and 660-775 (`_create_new_sincsports_team` returning `(team_id_master, was_created)`).
   - Module-level regex constants (named to mirror sincsports's `_SINCSPORTS_*` pattern):
     ```python
     # Multi-year birth tokens: B07/08, G06/07, 2007/2008
     _SOMSPORTS_BIRTH_RANGE_RE = re.compile(r"\b(?:[BG]\d{2}/\d{2}|20\d{2}/(?:20)?\d{2})\b", re.IGNORECASE)
     # Tier/league markers SOM Sports decorates team names with
     _SOMSPORTS_TIER_MARKERS_RE = re.compile(
         r"\b(?:ECNL(?:\s*RL)?|ECRL|MLS\s*Next(?:\s*HD)?|MLS\s*AD|RL|AD|EA\d?|Academy)\b",
         re.IGNORECASE,
     )
     # Trailing coach-name-suffix: " - Jorge Reyes" or ", Aleu" at end of string
     _SOMSPORTS_COACH_SUFFIX_RE = re.compile(r"\s*[-,]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s*$")
     ```
   - Class `SomSportsGameMatcher(GameHistoryMatcher)`:
     - Constructor: `(supabase, provider_id=None, alias_cache=None)` — mirror sincsports's `__init__` at line 100 minus `discovery_mode` (we don't need the discovery-vs-import split). Set `fuzzy_threshold = 0.75`, `auto_approve_threshold = 0.91`, `review_threshold = 0.70` (same as sincsports).
     - Override `_normalize_team_name(self, name: str, club_name: Optional[str] = None) -> str` — do ALL stripping inline, mirroring sincsports at line 213. Order:
       1. `name = _SOMSPORTS_BIRTH_RANGE_RE.sub("", name).strip()` — strip `B07/08`/`2007/2008`
       2. `name = _SOMSPORTS_TIER_MARKERS_RE.sub("", name).strip()` — strip ECNL/MLS-Next/RL/AD/EA markers
       3. `name = _SOMSPORTS_COACH_SUFFIX_RE.sub("", name).strip()` — strip trailing coach suffix
       4. `name = re.sub(r"\s{2,}", " ", name).strip()` — collapse runs of spaces
       5. `return super()._normalize_team_name(name)` — delegate to base for shared `normalize_name_for_matching`. Do NOT forward `club_name` to `super()` (base signature is `(self, name)` only — sincsports drops `club_name` here too, see line 245).
     - Override `_match_team(self, provider_id, provider_team_id, team_name, age_group, gender, club_name=None, state_code=None) -> Dict` — mirror sincsports lines 555-640. This is where the alias write lives, NOT in the create helper:
       1. Call `base_result = super()._match_team(provider_id, provider_team_id, team_name, age_group, gender, club_name, state_code=state_code)`.
       2. If `base_result["matched"]`, return as-is (base already wrote the alias for matched paths).
       3. Else, gate on `team_name and age_group and gender` (skip create if any missing), then call `self._create_new_somsports_team(team_name=..., club_name=..., age_group=..., gender=..., provider_id=..., provider_team_id=..., state_code=..., coach=...)` — returns `(new_team_id, was_created)`.
       4. After successful create, call `self._create_alias(provider_id=provider_id, provider_team_id=provider_team_id, team_name=team_name, team_id_master=new_team_id, match_method=("direct_id" if provider_team_id else "import"), confidence=1.0, age_group=age_group, gender=gender, review_status="approved")`. This is the same `_create_alias` sincsports calls at line 608 — it lives on the base `GameHistoryMatcher` and handles the `alias_cache` priming and dry-run gate. **Do NOT call `src.tournaments.alias_writer.upsert_team_alias` directly.**
       5. Return `{"matched": True, "team_id": new_team_id, "method": match_method, "confidence": 1.0, "created": was_created}`.
     - Override `_fuzzy_match_team(...)` to accept the `state_code` kwarg and forward to `super()._fuzzy_match_team(team_name, age_group, gender, club_name, state_code=state_code)` — mirrors sincsports at line 325. This is required because the subclass-side `_match_team` calls `super()._match_team(..., state_code=state_code)` which dispatches polymorphically back through `_fuzzy_match_team`.
     - Add `_create_new_somsports_team(self, team_name, club_name, age_group, gender, provider_id, provider_team_id=None, state_code=None, coach=None) -> Tuple[str, bool]` — mirror `SincSportsGameMatcher._create_new_sincsports_team` at line 660 exactly:
       1. Generate stable `provider_team_id` via `hashlib.md5(f"{team_name}_{age_group}_{gender}".encode()).hexdigest()[:16]` if missing (defensive — SOM Sports always provides one, but mirror sincsports's NOT NULL guard).
       2. Pre-INSERT lookup by `(provider_id, provider_team_id)` — return `(existing_team_id, False)` if found.
       3. Build `team_data` dict with `team_id_master`, `team_name` (cleaned of club-name prefix), `club_name`, `age_group` (lowercased), `gender` (normalized to `"Male"`/`"Female"`), `state_code`, `provider_id`, `provider_team_id`, `distinction` (via `resolve_distinction(clean_team_name, club_name, state_code)`), `created_at` ISO timestamp. **Persist `coach` only if the `teams` table has a `coach` column** — grep `supabase/migrations/` for `teams` schema before assuming; the existing sincsports template at line 728 does NOT include `coach`. If `teams` lacks a `coach` column, drop the kwarg from the team_data dict but keep it on the function signature (for future use + JSONL row inclusion).
       4. `INSERT` into `teams`.
       5. Handle `23505` duplicate-key fallback identically to sincsports lines 749-773 — re-lookup by `(provider_id, provider_team_id)` and return `(existing_id, False)`.
       6. Return `(team_id_master, True)` on successful insert.
   - Wire into matcher routing: in `src/etl/enhanced_pipeline.py`, insert a new `elif self.provider_code.lower() == "somsports":` branch **between the existing `playmetrics_tournament` branch (ends at line 266) and the final `else:` (line 267)**. There are TWO playmetrics branches in this chain (`playmetrics` at line 242 and `playmetrics_tournament` at line 252) — both must be preserved untouched. Lazy-import `from src.models.somsports_matcher import SomSportsGameMatcher` and construct:
     ```python
     elif self.provider_code.lower() == "somsports":
         from src.models.somsports_matcher import SomSportsGameMatcher
         logger.info("Using SomSportsGameMatcher (tournament + auto-create)")
         self.matcher = SomSportsGameMatcher(
             self.supabase, provider_id=self.provider_id, alias_cache=self.alias_cache
         )
     ```
     **Preserve every other elif branch verbatim** (modular11 at line 210, tgs at 223, sincsports at 228, affinity_wa at 235, playmetrics at 242, playmetrics_tournament at 252, the final else at 267). Preserve the alias-cache preload block above the chain (lines 174-207) including its `try/except` and `self.alias_cache = {}` fallback at line 207.

6. **Write `scripts/scrape_somsports_tournament.py` (CLI driver)**
   - Mirror `scripts/scrape_sincsports_tournament_schedule.py` exactly for env loading, `sys.path` setup, argparse, JSONL output, `--auto-import`.
   - Args: `--event-id INT (required)`, `--age-min STR (default "u10")`, `--age-max STR (default "u19")`, `--tiers STR (default "all", csv of oro,plata,bronce,champions)`, `--output-dir PATH (default data/raw)`, `--resume`, `--dry-run`, `--auto-import`.
   - **Per-flight state is durably persisted before any final JSONL emit** so a crash mid-run doesn't lose work and `--resume` is safe:
     - `reports/somsports/{event_id}/flights/{flight_id}.json` — per-flight result: `{teams: [...], games: [...]}`. Written atomically (write to `.tmp` then `os.replace`) at the end of a successful Pass 2 parse for that flight. Its existence is the resume marker — no separate `.done` file. Per-flight presence + valid JSON load = "this flight is complete, skip on `--resume`".
     - `reports/somsports/{event_id}/team_details.json` — accumulator of `{provider_team_id: TeamDetail}` from Pass 3. Written atomically after each team-detail fetch so a Pass 3 crash doesn't lose partial enrichment. On `--resume`, load this file and only fetch missing team IDs.
   - Main flow:
     - **Pass 1**: `flights = scraper.fetch_groups(event_id)`; filter by age range, gender (both), tiers; log count.
     - **Pass 2** (per flight): if `--resume` and `reports/somsports/{event_id}/flights/{flight_id}.json` loads cleanly, skip the network fetch and use the cached result. Otherwise `(teams, games) = scraper.fetch_flight(event_id, flight_id)` and atomically write the per-flight JSON. Build the in-memory union of all flights' teams + games as Pass 2 progresses.
     - **Pass 3** (team-detail enrichment, deduped across flights, runs ONLY after Pass 2 completes for ALL in-scope flights): for each unique `provider_team_id` not already in `team_details.json`, `detail = scraper.fetch_team_detail(event_id, team_id)` and atomically extend the cache file. **Pass 3 must finish before any JSONL row is written** — otherwise rows would carry `state_code=None`.
     - **Final JSONL emit** (after Pass 3 completes for all teams): for each game in the in-memory union, join the team-detail enrichment by `provider_team_id`, then write one JSONL row per perspective (H + A) using the `perspective_record(g, perspective="H"|"A")` shape from `scrape_sincsports_tournament_schedule.py:72`. Each row carries `provider_team_id`, `team_name`, `opponent_provider_team_id`, `opponent_team_name`, `state_code` (from enrichment cache), `club_name` (parsed via `extract_club_from_team_name`), `age_group` (canonical), `gender`, `gf`, `ga`, `result`, `game_date`, `kickoff_time`, `field`, `venue`, `flight_id`, `division_name`, `event_id`, `event_name` (parsed from the groups page header, e.g. "Club America Cup").
     - Output path: `data/raw/somsports_tournament_{event_id}_{ts}.jsonl`. Written in one pass at the end — partial state lives in the `reports/somsports/{event_id}/` cache files only.
     - `--auto-import`: after the JSONL is fully written, `subprocess.run([sys.executable, "scripts/import_games_enhanced.py", str(out_path), "somsports"], check=True)`.
     - `--dry-run`: run Passes 1-3 (so the dry-run is representative of the real network footprint), skip the final JSONL write, log a per-flight summary table (flight, teams, games, days_covered) plus a Pass 3 summary (teams enriched, states distinct). **Side effect: dry-run still writes the per-flight cache files and `team_details.json` under `reports/somsports/{event_id}/`** — this is intentional so a subsequent non-dry-run benefits from the prefetched state. Mention this explicitly in the `--dry-run` argparse help string so operators aren't surprised.
   - **Resume semantics summary**: the user can interrupt at any point and re-run with `--resume`. Pass 2 skips flights with valid cached JSON; Pass 3 skips team IDs already in `team_details.json`; the final JSONL is re-emitted from cached state (idempotent). On the unhappy path where Pass 2 crashes mid-flight after the network fetch but before the atomic write, that flight is simply re-fetched on resume — no silent partial data.

7. **Write fixture-based tests `tests/scrapers/test_somsports.py` and fixtures under `tests/fixtures/somsports/`**
   - Save HTML samples (via curl/browser save):
     - `tests/fixtures/somsports/event_72_groups.html` — full `/events/72/groups`
     - `tests/fixtures/somsports/event_72_flight_727_schedule.html` — Boys-U19 Oro Bracket
     - `tests/fixtures/somsports/event_72_flight_with_unplayed_games.html` — flight with `-` scores
     - `tests/fixtures/somsports/event_72_dual_age_flight.html` — "2014/15" division
     - `tests/fixtures/somsports/event_72_team_3318_detail.html` — `(CA)` state header
   - Tests:
     - `test_parse_groups_page` — ≥26 flights for U10-U19 boys+girls, all tiers.
     - `test_parse_schedule_page_oro_full` — 12 teams, 21 games, standings rows match expected.
     - `test_parse_schedule_page_unplayed_filtered` — unplayed rows return `None,None` scores; CLI filters them out before JSONL write.
     - `test_parse_dual_age_division` — `derive_division_age_group("Oro 2014/15 11v11")` → `"u12"`.
     - `test_age_filter_u10_u19` — `parse_groups_page` + filter drops U7/U8/U9 flights, includes U10-U19, folds U18→U19.
     - `test_parse_team_detail_state` — `parse_team_detail_page` extracts `state_code="CA"` from `"(CA)"`.
     - `test_matcher_normalizes_ecnl_markers` — `SomSportsGameMatcher._normalize_team_name("Crossfire B07/08 Academy ECNL")` strips `B07/08` (via `_SOMSPORTS_BIRTH_RANGE_RE`) + `ECNL` and `Academy` (via `_SOMSPORTS_TIER_MARKERS_RE`) inside the override, leaving roughly `"Crossfire"` after the base's shared normalization. **Exact expected output** depends on what `super()._normalize_team_name` (base `normalize_name_for_matching`) does to the residual — pin the expected value by running the helper once in a fixture-build script and capturing the actual output, then encode it as the test assertion. Do not hand-guess.
     - `test_matcher_strips_coach_suffix` — `_normalize_team_name("Beach FC B07/08 ECRL - Jorge Reyes")` strips `- Jorge Reyes` (via `_SOMSPORTS_COACH_SUFFIX_RE`), `B07/08` (via `_SOMSPORTS_BIRTH_RANGE_RE`), and `ECRL` (via `_SOMSPORTS_TIER_MARKERS_RE`). Pin the expected output the same way as above.
     - `test_resume_skips_cached_flights` — write a valid `reports/somsports/{event_id}/flights/{flight_id}.json` cache file (small fixture), run the CLI with `--resume --dry-run` against a mocked `SomSportsScraper.fetch_flight` that fails if called. Patch target: `scripts.scrape_somsports_tournament.SomSportsScraper.fetch_flight` (patch at the CLI's import site, not on the source module). Assert the run completes without the failing call (i.e., flight was loaded from cache instead).
     - `test_perspective_record_h_and_a` — single game produces 2 JSONL rows with mirrored teams/scores.
   - **Separate routing test** lives outside `tests/scrapers/` because it tests `EnhancedETLPipeline`: `tests/unit/test_enhanced_pipeline_routing.py::test_somsports_routes_to_somsports_matcher` — see Verification section for the contract. This 11th test is not counted in the "10 parser/matcher tests" but must pass for Step 5's routing wiring to be considered done.
   - Smoke test (gated by `RUN_LIVE=1` env): `--dry-run` against live event 72, assert ≥20 flights and ≥100 games observed.

## Verification

End-to-end checks once steps 1-7 land:

- **Unit tests pass**: `pytest tests/scrapers/test_somsports.py -v` — all 10 tests green.
- **Migration applies cleanly**: `supabase db reset --debug` against a fresh local stack; verify `SELECT code FROM providers WHERE code='somsports';` returns a row.
- **PROVIDERS dict round-trips**: `python -c "from config.settings import PROVIDERS; assert 'somsports' in PROVIDERS"`.
- **Matcher routing wires**: add `tests/unit/test_enhanced_pipeline_routing.py::test_somsports_routes_to_somsports_matcher` — uses an in-memory mock for `self.supabase` (mock `.table().select().execute()` to return empty data so the alias preload at lines 174-207 short-circuits cleanly into `self.alias_cache = {}`), instantiates `EnhancedETLPipeline` with `provider_code="somsports"`, calls `_ensure_initialized()`, asserts `type(p.matcher).__name__ == "SomSportsGameMatcher"`. Run via `pytest tests/unit/test_enhanced_pipeline_routing.py -v`. A bare `python -c` construction is not viable because the preload chain hits Supabase before the matcher branch is reached.
- **Live dry-run** (network required): `python scripts/scrape_somsports_tournament.py --event-id 72 --dry-run` — log shows ≥26 flights filtered to U10-U19 (both genders, all tiers), ≥100 games, no unhandled exceptions.
- **End-to-end with --auto-import** (against staging Supabase, not prod): `python scripts/scrape_somsports_tournament.py --event-id 72 --auto-import`.
  - `data/raw/somsports_tournament_72_*.jsonl` exists with 2 rows per game (H+A perspectives).
  - `import_games_enhanced.py` exits 0.
  - `SELECT count(*) FROM games WHERE provider_id = (SELECT id FROM providers WHERE code='somsports');` returns a count matching JSONL games (not perspectives — half the JSONL row count).
  - `SELECT count(*) FROM team_alias_map WHERE provider_id = (SELECT id FROM providers WHERE code='somsports');` ≥ number of unique scraped teams.
  - Spot-check: `SELECT * FROM teams WHERE team_name LIKE '%Crossfire%' AND age_group='u19' AND gender='M' ORDER BY created_at DESC LIMIT 5;` — verify state_code populated.
- **Resume idempotency**: re-run the same command. Log shows all flights skipped via `.flights_done/` markers. No new rows in `games` (UNIQUE constraint protects, but the skip should fire first).
- **Edge: unplayed game filtering**: spot-check a Monday playoff fixture that was bracket-pending. JSONL should exclude any game with `home_score IS NULL OR away_score IS NULL`.
- **Edge: U18→U19 fold**: spot-check `SELECT DISTINCT age_group FROM teams WHERE team_id_master IN (SELECT team_id_master FROM team_alias_map WHERE provider_id = (...));` — only `u10..u17, u19` (no `u18`).

## Context Files

Files to read in full before starting implementation:

- `docs/superpowers/specs/2026-05-28-somsports-tournament-scraper-design.md` — the spec this plan implements
- `src/scrapers/sincsports_schedule.py` — closest HTML parser analog; mirror the pure-functions + thin-wrapper split
- `scripts/scrape_sincsports_tournament_schedule.py` — CLI driver template (argparse, env, JSONL, `perspective_record`, `--auto-import`)
- `scripts/scrape_affinity_wa_tournament.py` — HTML flight-discovery + per-flight scrape flow; `_fetch` retry pattern
- `scripts/scrape_playmetrics_tournament.py` — for `derive_division_age_group` extraction (Step 1) and CLI shape
- `src/models/sincsports_matcher.py` — closest matcher analog; `_create_new_sincsports_team` returning `(id, was_created)` tuple
- `src/models/game_matcher.py` — base `GameHistoryMatcher`, override points (`_normalize_team_name`, `_fuzzy_match_team`, `_match_team`)
- `src/etl/enhanced_pipeline.py:209-269` — matcher routing chain (add `somsports` elif branch)
- `config/settings.py:55-86` — `PROVIDERS` dict shape; also `MATCHING_CONFIG` at 187-207
- `supabase/migrations/20260507000000_seed_playmetrics_tournament_provider.sql` — migration template
- `src/scrapers/_age_normalization.py` — destination for the extracted `derive_division_age_group`
- `src/scrapers/_http.py` — `retry_session_get` for HTTP retry/backoff
- `src/scrapers/provider.py` — `ScrapedTeam`/`CanonicalResolution` dataclasses (for type alignment, even though we're not subclassing `ProviderScraper`)
- `src/tournaments/alias_writer.py` — `upsert_team_alias` for the auto-create alias write
- `src/utils/team_name_utils.py` — `extract_club_from_team_name`, `normalize_name_for_matching`, ECNL helpers
- `tests/scrapers/` (existing test files for one of sincsports/affinity_wa/playmetrics) — pytest convention, fixture loading pattern
