# SQUADI Scraper Design

**Date:** 2026-05-04
**Status:** Approved (pending implementation plan)
**Owner:** Dallas Heidt
**Provider code:** `squadi`

## Goal

Add a new league-pipeline scraper for the SQUADI platform so PitchRank rankings can ingest games from US state-soccer associations that publish on Squadi. v1 scope: **New Jersey Youth Soccer (NJYS)** State Cup competitions. The same code path is reused for any other US state on Squadi by changing one organisation UUID.

## Context

- SQUADI hosts public livescore data at `https://registration.us.squadi.com/` (SPA) backed by a JSON API at `https://api.us.squadi.com/`.
- NJYS publishes its **State Cup** competitions on Squadi (single-elimination cup format: Round of 64 → Final). Regular-season league play for NJYS lives elsewhere (GotSport / TGS) and is out of scope.
- API has no user auth — instead, an anonymous public-read **token is hardcoded in the SPA bundle** (`/static/js/main.<hash>.js`). The token rotates only when Squadi redeploys the SPA, which is rare.
- For NJYS year 2026 (Squadi `yearRefId=8`), exactly one competition is currently published: *"NJYS State Cups - Spring 2026 (15U-19U)"* (`uniqueKey=076cbf4a-26f8-4878-9d86-8fea4d43b7c6`, integer `id=261`).

## §1 Architecture

Single CLI script at `scripts/scrape_squadi_competition.py`, modeled on `scripts/scrape_playmetrics_league.py`. Pure-JSON public API → 27-column canonical CSV → `import_games_enhanced.py`. No new dependencies (`requests`, `pandas`, `zoneinfo`).

```
┌─────────────────────────────┐
│ scrape_squadi_competition.py│  CLI
└──────────────┬──────────────┘
               │
        ┌──────▼──────┐
        │ TokenHarvest│  Fetch SPA, regex `main.<hash>.js` → token
        └──────┬──────┘
               │
        ┌──────▼────────────┐
        │ CompetitionDiscovery│  /reference/year + /competitions/list
        └──────┬────────────┘  filter statusRefId==2, deleted_at IS NULL
               │
        ┌──────▼─────┐
        │ Per-comp:  │  /division → /round/matches
        │ Walk       │  emit rows
        └──────┬─────┘
               │
        ┌──────▼────────────────┐
        │ Two artifacts:        │
        │ data/raw/squadi/      │
        │   <run_id>/games.csv  │  → import_games_enhanced.py
        │   <run_id>/teams.csv  │  → team upserter + matcher
        └───────────────────────┘
```

## §2 Components

### 2.1 `SquadiTokenHarvester`
- Fetches `https://registration.us.squadi.com/`, regex `main.<hash>.js` from HTML, fetches the bundle.
- Regex out the auth token (pattern: hex string `[a-f0-9]{256,512}` adjacent to `"authorization"` / `"token"` literal).
- Cache in-memory + on disk at `~/.cache/squadi/token.json` (TTL 24h).
- 401 on any API call → invalidate cache, refetch once, retry. Second 401 → fail loudly with logged Squadi build hash.
- Bundle regex finds no token → abort with exit code 3 (Squadi changed bundle structure; needs human investigation).

### 2.2 `SquadiClient`
Thin wrapper around `requests.Session`:
- Pre-set `authorization` + `accept: application/json` headers, browser-like `User-Agent`.
- Methods: `list_years(org_uuid)`, `list_competitions(org_uuid, year_ref_id)`, `list_divisions(competition_uuid)`, `get_round_matches(competition_int_id)`.
- 3-attempt retry on 5xx with exponential backoff (0.5s, 1s, 2s) — same pattern as `src/scrapers/template.py`.
- 0.3s delay between calls (`SQUADI_DELAY_SEC` env override).

### 2.3 `CompetitionDiscovery`
- Inputs: `org_uuid`, optional `year_ref_id`, optional `competition_uuid` override, optional `--url` parser.
- Output: list of competition dicts to scrape.
- Filters: `statusRefId == 2` (active/published), `deleted_at IS NULL`, optional name-blocklist (`SQUADI_COMP_BLOCKLIST` env, default skips `"Demo Comp"`).

### 2.4 `MatchExtractor`
- Per competition: fetch divisions + round matches sequentially.
- For each match, emit **two CSV rows** (team1-perspective + team2-perspective) per the field map in §A.
- Emit **one team-row per (`teamUniqueKey`, `divisionId`)** to `teams.csv` (deduped within run).
- Apply transformations: timezone conversion, age-group regex, gender parse, club-name split, PK→draw rule, dual-age older-cohort rule (see §B).

### 2.5 Outputs
- `data/raw/squadi/<scrape_run_id>/games.csv` (27-col canonical — see §A)
- `data/raw/squadi/<scrape_run_id>/teams.csv` (matcher seed — see §C)
- `data/raw/squadi/<scrape_run_id>/manifest.json` (run metadata: org, comps, counts, token hash, status)
- `data/raw/squadi/<scrape_run_id>/raw/<comp_uuid>/{competition.json, divisions.json, round_matches.json}` (audit trail, optional via `--keep-raw`)

### 2.6 Provider registration (one-time DDL)
- New row in `providers` table: `code="squadi"`, `name="Squadi"`, `base_url="https://api.us.squadi.com"`, `country="US"`.
- Migration file at `migrations/<timestamp>_add_squadi_provider.sql`.
- Add `provider_code.lower() == "squadi"` branch to `enhanced_pipeline._ensure_initialized()` — uses standard `GameHistoryMatcher` (no Squadi-specific subclass needed).

## §3 Data flow

```
CLI invocation
  │
  ├─[--url] → parse {orgKey, compKey, yearId} from query string
  ├─[--competition-key] → single comp, skip discovery
  └─[--org-key + optional --year-ref-id] → discover all matching comps
  │
  ▼
SquadiTokenHarvester.get_token()   (cache hit? else fetch SPA → regex bundle → store)
  │
  ▼
CompetitionDiscovery.resolve()
  └─ returns [{compInt, compUUID, name, yearRefId, orgUUID, orgInt}, ...]
  │
  ▼
for each competition (sequential, ~5-10s each):
  ├─ GET /livescores/division?competitionKey=<UUID>
  │    └─ keep {divisionId, divisionName, age, grade}
  ├─ GET /livescores/round/matches?competitionId=<INT>&divisionId=&teamIds=&ignoreStatuses=[1]
  │    └─ flatten: rounds[] → matches[]
  ├─ for each match:
  │    ├─ resolve division (in-memory join via divisionId)
  │    ├─ parse age_group + gender + tier from divisionName
  │    ├─ validate vs team-name birth year (warn-only)
  │    ├─ compute game_date, game_time (UTC → America/New_York)
  │    ├─ compute result (W/L/D from team*ResultId; PK→D)
  │    ├─ emit row[team1-perspective] → games_buffer
  │    ├─ emit row[team2-perspective] → games_buffer
  │    └─ upsert (teamUUID, divisionId) → teams_buffer (dedup)
  └─ optional: persist raw JSON to raw/<compUUID>/
  │
  ▼
write games.csv (27-col), teams.csv, manifest.json
  │
  ▼
log summary JSON (see §4 observability)
```

**Concurrency:** sequential per competition (rate-limit politeness, 0.3s between calls). One NJYS competition has ~24 divisions × ~10-30 matches = ~500-700 matches → ~1 minute end-to-end.

**Idempotency:** fully idempotent — run twice, get identical CSVs (modulo `scrape_run_id` and `scraped_at`). Downstream `import_games_enhanced.py` dedupes via `game_uid`.

**Incremental scrapes:** out of scope for v1. Cup-format competitions are short-lived (a few weekends); a full re-scrape takes ~1 min. Revisit if Squadi adds long-running league competitions.

## §4 Error handling

**Token failures**
- 401 → invalidate cached token, refetch from SPA bundle, retry once. Second 401 → exit 2 with logged Squadi build hash.
- Bundle regex misses → exit 3 (signals Squadi changed bundle structure).

**Network / 5xx**
- 3 retries with exponential backoff. Persistent failure on a single competition → log + skip that comp, continue with others. Persistent failure on token harvest → abort.

**Empty / malformed responses**
- `competitions/list` returns `[]` → log warning, exit 0 with empty output (cron-friendly).
- `round/matches` returns `{rounds: []}` → log warning, no rows emitted for that comp.
- Match `matchStatus != "ENDED"` and scores missing → skip silently (scheduled but not played).
- Match `matchStatus == "ENDED"` but scores `null` → emit with `result="U"` and log warning (forfeits, abandoned games — `import_games_enhanced.py` handles "U").

**Parse failures (per-row, fail-soft)**
- `divisionName` regex miss → fall back to `division.age` integer field. Both miss → emit row with `age_group=""`, log warning. Importer routes blank-age rows to review queue.
- Team-name birth-year ≠ division-derived age → log INFO ("play-up suspected: team X birth=2014 in u11 division"), trust division.
- Timezone conversion failure (malformed `startTime`) → emit row with `game_date=""`, log warning.

**Output integrity**
- Write CSVs to `<run_id>.tmp/`, atomic rename to `<run_id>/` on success. Partial-failure runs leave a `.tmp/` directory + `manifest.json` with `status="partial"`.
- Manifest always written, even on abort, with whatever was completed before the crash.

**Observability**
- Per-run summary log line (single JSON object): `{run_id, org_uuid, comps_total, comps_ok, comps_failed, games_emitted, teams_emitted, parse_warnings, token_refresh_count, duration_sec}`.
- Standard Python `logging` at INFO; `--verbose` flag for DEBUG. Errors → stderr; summary → stdout.

**Not handled (explicit non-goals for v1)**
- Concurrent / parallel competitions — sequential is fast enough.
- Resumable scrapes — full re-run is ~1 min, retry beats resume.
- Match-level diff detection — every run is a full re-emit; importer dedupes.

## §5 Testing

**Unit tests** (`tests/scrapers/test_squadi.py`, pytest):
- **Token harvester** — fixture: mock SPA HTML + bundle JS containing a fake token. Verify regex extraction, cache hit/miss/expiry, 401-triggered refresh.
- **Competition discovery** — fixture: canned `/competitions/list` JSON (real NJYS yearRefId=6 response, captured 2026-05-04, redacted). Verify `statusRefId==2` filter, `deleted_at` filter, name-blocklist.
- **Match → CSV row** — fixture: canned `/round/matches` payload, one match per scenario:
  - Standard finished (W/L) → 2 rows, correct team-perspectives
  - Drawn regulation, no PKs → both rows `result="D"`
  - Drawn regulation + PKs → both rows `result="D"`, `meta.pk_winner` populated
  - Forfeit (`matchSubstatusRefId` indicating forfeit, scores null) → 2 rows `result="U"`
  - Scheduled-not-played (`matchStatus != "ENDED"`) → 0 rows
- **Age-group parsing** — table-driven on `divisionName`:
  - `"11U Boys Challenge Cup"` → `("u11", "Boys", "Challenge Cup")`
  - `"15U/16U Girls National Championship Series"` → `("u16", "Girls", "National Championship Series")` (older-cohort rule)
  - `"18U Boys Champions League"` → `("u19", "Boys", "Champions League")` (u18→u19 remap)
  - Malformed input → fallback to `division.age` int → final fallback returns `("", "", "")` with warning
- **Club-name parsing** — `"Mount Olive SC - STA Mount Olive 2014 EDP Boys"` → `("Mount Olive SC", "...")`; no-dash names → club=full name.
- **Timezone conversion** — `"2024-09-06T22:30:00.000Z"` → `game_date="2024-09-06"`, `game_time="18:30"`. Plus midnight-spanning case: 03:00 UTC → previous-day 23:00 ET.
- **Birth-year cross-check** — `"... 2014 EDP Boys"` in u11 division → no warning; same team in u14 division → INFO log emitted, division still wins.

**Integration test** (`tests/scrapers/test_squadi_integration.py`, marked `@pytest.mark.integration`, opt-in via `RUN_LIVE_TESTS=1`):
- Live API hit against NJYS Spring 2026 State Cup. Asserts:
  - Token harvest succeeds
  - At least 1 division returned
  - At least 1 match returned with `resultStatus="FINAL"` once games start (skipped early in season)
  - CSV emits the 27-column header in correct order
  - All emitted `state_code="NJ"`, `provider="squadi"`

**Snapshot tests** — JSON fixtures committed under `tests/scrapers/fixtures/squadi/`. CI doesn't hit live API; refresh fixtures manually with `python scripts/scrape_squadi_competition.py --refresh-fixtures`.

**Manual verification before merging:**
1. `python scripts/scrape_squadi_competition.py --org-key 7cfab077-... --year-ref-id 6` (Fall 2024, finalized historical data, ideal for first end-to-end check)
2. Inspect `games.csv` row count vs Squadi UI division-by-division
3. Spot-check 3 matches against the live UI: scores, dates, team names match
4. Run `import_games_enhanced.py --provider squadi --csv data/raw/squadi/<run_id>/games.csv --dry-run` — verify dedupe, age-group acceptance, no review-queue explosion
5. Inspect review-queue diff: how many Squadi teams couldn't be matched to existing PitchRank teams (NJYS overlap with TGS / GotSport entries)?

**Rollback plan** — provider is additive. If data quality issue: `UPDATE games SET is_excluded=true WHERE provider_id=<squadi_uuid>` and re-rank. No code revert needed.

## §A Per-game fields → 27-column CSV

| CSV column | Squadi source | Transformation |
|---|---|---|
| `provider` | constant | `"squadi"` |
| `scrape_run_id` | generated | `uuid4()` per CLI invocation |
| `event_id` | `competition.uniqueKey` | UUID, stable across runs |
| `event_name` | `competition.name` | e.g. `"NJYS State Cups - Spring 2026 (15U-19U)"` |
| `schedule_id` | `roundId` + `divisionId` | composite, e.g. `"r3632-d390"` |
| `age_year` | derived from `division.age` + `comp.yearRefId` | birth year = `comp_year - division.age - 1` (e.g. age=10, comp_year=2026 → 2015) |
| `age_group` | parsed from `division.divisionName` | regex `(\d+)U` → `"u11"` lowercase; dual-age picks older; u18→u19 remap |
| `gender` | parsed from `division.divisionName` | `"Boys"` / `"Girls"` |
| `team_id` | `team1.teamUniqueKey` | UUID — survives Squadi reseeding |
| `team_id_source` | `team1.id` | int — fallback alias |
| `team_name` | `team1.name` | full string `"<Club> - <Team>"` |
| `club_name` | parsed from `team1.name` | left of first `" - "` separator; fallback = full name |
| `opponent_id` | `team2.teamUniqueKey` | UUID |
| `opponent_id_source` | `team2.id` | int |
| `opponent_name` | `team2.name` | full string |
| `opponent_club_name` | parsed from `team2.name` | same rule as `club_name` |
| `state` | constant per org | `"New Jersey"` (lookup keyed by `organisationUniqueKey`) |
| `state_code` | constant per org | `"NJ"` |
| `game_date` | `startTime` | UTC ISO → `America/New_York` → `YYYY-MM-DD` |
| `game_time` | `startTime` | UTC ISO → `America/New_York` → `HH:MM` |
| `home_away` | always `"H"` for team1's row | Squadi convention: `team1Id`=home, `team2Id`=away (cup games often neutral; downstream ranking ignores HFA) |
| `goals_for` | `team1Score` | int |
| `goals_against` | `team2Score` | int |
| `result` | `team1ResultId` | `1`→`W`, `2`→`L`, `3`→`D`. **PK shootout → `D`**, regulation outcome wins. PK winner stored in `meta.pk_winner` only |
| `venue` | `venueCourt.venue.name` + court | e.g. `"Turkey Brook Park (Budd Lake) - Field 4"` |
| `source_url` | constructed | `https://registration.us.squadi.com/livescoreSeasonFixture?organisationKey=<org>&competitionUniqueKey=<comp>&yearId=<year>&divisionId=<divUUID>` |
| `scraped_at` | generated | ISO timestamp at scrape time |
| `division_name` | `division.divisionName` | e.g. `"11U Boys Challenge Cup"` |

**Two rows per match** (team1-perspective, team2-perspective). `import_games_enhanced.py` dedupes via `game_uid`.

## §B Per-match `meta` (JSON, for future use)

- `squadi_match_id` (`match.id`) — for incremental scrapes if added later
- `squadi_competition_id_int` (`match.competitionId`) — needed to call `/round/matches`
- `round_name` (`round.name`) — `"Round of 64"`, `"Final"`, etc.
- `round_sequence` (`round.sequence`) — bracket order
- `is_finals` (`match.isFinals`)
- `finals_alias` (`match.finalsAlias`) — bracket position
- `match_status`, `result_status`, `match_substatus_ref_id`
- `is_results_locked`
- `has_penalty`, `team1_penalty_score`, `team2_penalty_score`, `pk_winner`
- `extra_time_played` (any `extraStartTime*` non-null)
- `venue_lat`, `venue_lng`, `venue_court_lat`, `venue_court_lng`
- `tier` parsed from `divisionName` after age+gender → `"Challenge Cup"`, `"National Championship Series"`, etc.

## §C Matcher-side requirements (`teams.csv`)

| Column | Squadi source |
|---|---|
| `provider` | `"squadi"` |
| `provider_team_id` | `team.teamUniqueKey` (UUID — primary alias key) |
| `provider_team_id_source` | `team.id` (int — secondary alias) |
| `team_name` | `team.name` |
| `club_name` | parsed left-of-dash |
| `age_group` | from division (`"u15"` etc.) |
| `gender` | from division |
| `state` / `state_code` | `"New Jersey"` / `"NJ"` |
| `division_name` | `division.divisionName` |
| `tier` | parsed from `divisionName` |
| `external_org_id` | extracted from `team.logoUrl` regex `/org_(\d+)/` — Squadi's club-org ID, useful for grouping teams at the same club |
| `meta.squadi_team_id_int` | `team.id` |
| `meta.squadi_competition_uuid` | competition UUID — provenance |

**Matcher contract:** existing `GameHistoryMatcher` looks up `team_aliases` by `provider_team_id` first; on miss, fuzzy-matches against `teams` filtered by `(state_code, age_group, gender)` plus `team_name`/`club_name` similarity. The `external_org_id` from `logoUrl` is a tie-breaker when two clubs share a short name.

**Age resolution strategy:** Team objects in Squadi do **not** carry an age field. Authority for age is the **division** they played in (`division.divisionName` → `(\d+)U`). The team-name birth-year parse (e.g. `"... 2014 EDP Boys"`) is a sanity check only; on mismatch, log INFO ("play-up suspected") and trust the division. Multi-division teams emit one team-row per `(teamUUID, divisionId)` pair — same shape the matcher already handles for PlayMetrics teams that play across age bands.

## §D Provider/team-table seed (one-time)

- Insert row in `providers`: `code="squadi"`, `name="Squadi"`, `base_url="https://api.us.squadi.com"`, `country="US"`.
- One-time alias seeding for NJYS teams already in PitchRank from other providers (TGS / GotSport / EDP) — manual review queue route via existing `team_match_review_queue` flow.

## §E Explicit non-goals

- Player rosters / lineups (`team*LineupConfirmed`)
- Officiating data (`recordUmpire`, `enableMatchOfficialRecording`)
- Match action logs (`matchAction`)
- Pause tracking (`pauseStartTime`, `totalPausedMs`)
- Livestream URLs (revisit if marketing pipeline wants them)
- Raw logo URLs (kept only as the `external_org_id` regex source, not stored)
- Tournament/event-pipeline ingestion (MatchBalance backtests) — v1 is league-pipeline only, per user direction (rankings.io use case)
- Multi-state v1 — code is org-keyed and supports any US state on Squadi, but only NJYS is configured/tested for v1

## CLI summary

```bash
# Default — auto-discover all active comps for an org+year (cron mode)
python scripts/scrape_squadi_competition.py --org-key 7cfab077-... [--year-ref-id 8]

# Single comp by UUID (backfill / debugging)
python scripts/scrape_squadi_competition.py --competition-key 076cbf4a-...

# Paste browser URL straight from Squadi
python scripts/scrape_squadi_competition.py --url "https://registration.us.squadi.com/livescoreSeasonFixture?organisationKey=...&competitionUniqueKey=..."

# Other flags
--keep-raw           # Persist raw JSON responses for audit
--verbose            # DEBUG-level logging
--dry-run            # Validate config + token, no output written
```

**Precedence:** `--url` > `--competition-key` > (`--org-key` + optional `--year-ref-id`) > env defaults.

## Key endpoints (for reference)

All under `https://api.us.squadi.com`:
- `GET /common/common/reference/year` — list of yearRefId → calendar year (e.g. `id=6 → "2024"`, `id=7 → "2025"`, `id=8 → "2026"`)
- `GET /livescores/competitions/list?organisationUniqueKey=<UUID>&yearRefId=<int>` — competitions for org+year
- `GET /livescores/division?competitionKey=<UUID>` — divisions for a competition
- `GET /livescores/round/matches?competitionId=<INT>&divisionId=&teamIds=&ignoreStatuses=[1]` — all rounds + matches with scores, team names, team UUIDs, division IDs, venue info

## NJYS-specific constants (v1)

| Field | Value |
|---|---|
| `organisationUniqueKey` | `7cfab077-e619-47e4-ab36-0febc29501a2` |
| `organisationId` (int) | `380` |
| `state` / `state_code` | `"New Jersey"` / `"NJ"` |
| Timezone | `America/New_York` |
| Spring 2026 cup `competitionUniqueKey` | `076cbf4a-26f8-4878-9d86-8fea4d43b7c6` (id=261) |

## Implementation notes

- v1 implemented on branch `scraper/squadi-nj` (commits `0625ebc18` through `42ff17cc9`).
- Token build hash at first scrape: `e68022e7` (length 448).
- Dry-run gates passed 2026-05-04:
  - **16.1 Token harvest**: `token len=448 build=e68022e7` — pass.
  - **16.2 NJYS 2026 (yearRefId=8) discovery + dry-run**: comps_total=1, comps_ok=1, games_emitted=642 (321 games × 2 perspectives), teams_emitted=297, skipped_scheduled=61, duration_sec=1.32, status=ok, dry_run=true — pass.
  - **16.3 NJYS Fall 2024 (yearRefId=6) discovery + dry-run**: comps_total=2, comps_ok=2, games_emitted=1580 (790 games × 2), teams_emitted=667, duration_sec=2.58, status=ok, dry_run=true. Competitions: "State Cups Fall 2024 (11U-14U)" (games=730 teams=606) + "NJ ODP Friendlies (December 2024)" (games=60 teams=61) — pass.
  - **16.4 --no-dry-run CSV write**: games rows=1580, unique team UUIDs=648, distinct results=['D','L','W'] (no 'U' = no unplayed games in dataset), distinct age_groups=['','u11','u12','u13','u14'], distinct genders=['Boys','Girls'], state_codes=['NJ'], manifest.status=ok — pass with one noted observation (see below).
  - **16.6 Importer dry-run**: Errored as expected — `Provider not found: squadi` (PGRST116, 0 rows). Migration `20260504000000_add_squadi_provider.sql` not yet applied to Supabase. Not blocking.
- CSV observation: 120 rows (all from "NJ ODP Friendlies") carry `age_group=''` and `age_year=''`. ODP select teams (e.g. "NJ BLUE TEAM") have no parseable birth-year in their name — expected and harmless; importer can skip or null-fill these rows.
- Production deploy still required:
  - Apply migration `supabase/migrations/20260504000000_add_squadi_provider.sql`.
  - Run `python scripts/import_games_enhanced.py data/raw/squadi/<run_id>/games.csv squadi --dry-run` to verify importer dedupe + matcher behavior.
  - Spot-check 3 matches in the live Squadi UI vs the CSV (gate 16.5).
  - Run real import (gate 16.7) followed by rankings health check (gate 16.8).
- Open follow-ups:
  - Triple-nested for/for/for in `main()` competition_uuid resolution path could extract to a helper for readability (cosmetic).
  - `json.loads(tr["meta"])` in main's dedup loop re-decodes per row — pre-parse if dataset grows large.
  - If review-queue overlap with TGS/GotSport/EDP teams is excessive on first import, consider a `SquadiGameMatcher` subclass with state-scoped autocreate (mirroring PlayMetrics).
  - ODP Friendlies rows with empty age_group: decide whether to filter them out pre-import or let the importer null-fill and skip matching.
