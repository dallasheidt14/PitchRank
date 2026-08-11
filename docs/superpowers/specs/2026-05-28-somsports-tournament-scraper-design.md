# SOM Sports / athletes2events Tournament Scraper

**Date:** 2026-05-28
**Status:** Draft for implementation planning
**Initial target:** Club America Cup (event 72), May 23-25, 2026

## Purpose

Add a new data source: `somsports.athletes2events.com`. Built first against Club America Cup, but structured so any future event on the same platform can be ingested by pointing the CLI at a different event ID.

## Scope

- **Initial event:** Club America Cup, event ID `72`
- **Age range:** U10-U19 (note: U18 divisions on the source map to U19 canonically — `gotcha_no_u18_age_group.md`)
- **Genders:** Boys and Girls
- **Tiers:** All flights (Oro / Plata / Bronce / Champions Group)
- **Cadence:** One-time post-tournament pull. No live polling.
- **Out of scope:** Live score polling, college coach data, schedule changes detection, image/logo download.

## Architecture

New `ProviderScraper` adapter matching the existing pattern used by `src/scrapers/gotsport.py`. Same wire format (`ScrapedTeam`, `TournamentGame`), same `IntakeJournal` for resumability, same downstream pipeline (`import_games_enhanced.py` → `GameHistoryMatcher` → `games` table).

### File layout

| Path | Purpose |
|---|---|
| `src/scrapers/somsports.py` | `SomSportsScraper(ProviderScraper)` — fetch + parse |
| `src/models/somsports_matcher.py` | `SomSportsGameMatcher(GameHistoryMatcher)` — name normalization quirks |
| `scripts/scrape_somsports_tournament.py` | CLI driver with event-id, age/tier filters |
| `supabase/migrations/20260528000000_seed_somsports_provider.sql` | Provider row |
| `config/settings.py` | Add `'somsports'` entry to `PROVIDERS` dict |
| `tests/scrapers/test_somsports.py` | Fixture-based HTML parsing tests (no network) |
| `tests/fixtures/somsports/` | Saved HTML samples: groups page, schedule page, edge cases |

### Provider registration

```sql
INSERT INTO providers (code, name, base_url, active)
VALUES ('somsports', 'SOM Sports / athletes2events', 'https://somsports.athletes2events.com', true);
```

```python
# config/settings.py — PROVIDERS dict
"somsports": {
    "code": "somsports",
    "name": "SOM Sports / athletes2events",
    "base_url": "https://somsports.athletes2events.com",
    "adapter": "src.scrapers.somsports",
},
```

## Data flow

```
CLI (--event-id 72 --age-min u10 --age-max u19)
  │
  ▼
SomSportsScraper.fetch_event_metadata()
  GET /events/{event_id}/groups
  → EventMetadata(event_id, name, dates, venues)
  │
  ▼
SomSportsScraper.discover_flights()
  Parse groups page → [(age_group, gender, tier, flight_id)]
  Filter: age in {u10..u19}, all genders, all tiers
  │
  ▼
For each flight in scope:
  SomSportsScraper.fetch_flight()
    GET /events/{event_id}/schedules?flight-id={flight_id}
    → (list[ScrapedTeam], list[TournamentGame])
  │
  ▼
IntakeJournal.write(jsonl)
  reports/somsports/72/intake/raw_scrape.jsonl
  │
  ▼
import_games_enhanced.py --provider somsports --input <jsonl>
  → GameHistoryMatcher (via SomSportsGameMatcher)
  → games table (deduped on provider_id + home_provider_id + away_provider_id + game_date + scores)
  → team_alias_map for new matches
```

## Parsing contract

### Groups page (`/events/{event_id}/groups`)

Server-rendered HTML. For each flight, extract:
- Anchor `href` with `flight-id` query param → integer flight ID
- Heading text containing the age (e.g., `Boys-U15`) and tier label (`Oro`, `Plata`, `Bronce`, `Grupo de Campeones`)
- Team count (informational, used for sanity check after fetch)

**Age parsing:** match `(Boys|Girls)[-\s]U(\d+)` from heading. Map `U7-U19` to canonical age groups, with U18 → U19 fold.

**Dual-age divisions** (e.g., "Oro 2014/15 11v11"): take the older cohort per `gotcha_slash_age_tokens.md`. So `2014/15` → U12 (2014 birth year in May 2026).

### Schedule page (`/events/{event_id}/schedules?flight-id={id}`)

Two parseable structures:

**Standings table** — one block per group (A/B/C…). Columns: position, team name, MP, W, D, L, GF, GA, GD, Pts. Team names link to a team detail URL containing a numeric provider team ID.

**Game results table** — rows: game number, date, time, home team, score (`H-A` or empty/`-` for unplayed), away team, field, venue. Date headers separate days.

**Score parsing:** `"3-1"` → `home_score=3, away_score=1`. Empty / dash / `vs` → unplayed game, **skip** (we only ingest played games for ranking purposes).

**Venue mapping:** capture venue string verbatim into `games.venue`. Field string (e.g., "Field 03 11v11") into a sub-field or appended to venue (TBD by writing-plans based on existing schema usage).

## Matching strategy

Full integration. New `SomSportsGameMatcher` extends `GameHistoryMatcher` with provider-specific normalization:

1. **Strip ECNL/MLS tier markers** from team names before fuzzy match (`B07/08`, `MLS Next`, `ECNL`, `ECRL`, `AD`, `RL`)
   — these are tier flags PitchRank tracks via `league_tier`, not part of canonical club name
2. **Multi-year birth handling** (`B07/08`, `2007/2008`) — pass to existing `team_name_utils` age extractor; older birth year wins per `gotcha_slash_age_tokens.md`
3. **Coach name suffix** (`- Jorge Reyes`, `Aleu`) — strip after final `,` or trailing `-` for matching, retain in raw record
4. **Direct ID promotion** — first scrape of a team creates `team_alias_map` row with provider team ID. Subsequent scrapes hit by ID, skipping fuzzy.

Unmatched teams (confidence < `auto_approve_threshold=0.9`) → review queue, no game emitted until resolved.

## CLI interface

```
python scripts/scrape_somsports_tournament.py \
  --event-id 72 \
  --age-min u10 \
  --age-max u19 \
  --tiers all \
  --output-dir reports/somsports/72/intake \
  [--dry-run] [--resume]
```

`--resume` reads existing `raw_scrape.jsonl` and skips already-fetched flights.

## Error handling

- **Network failure on a flight:** log + skip + continue. Failed flights listed in summary; rerun with `--resume`.
- **Parsing failure on a row:** log with raw HTML snippet, quarantine to `quarantine_games`-bound staging, continue.
- **Unparseable age/gender:** log + skip flight with a clear "manual classification needed" warning.
- **Score format mismatch:** treat as unplayed, skip.
- **Duplicate provider team ID with different team name** (rare, indicates source data issue): log + skip game, do not silently choose one.

No silent skips. Every drop logged with reason.

## Testing

Fixture-driven, no network:

1. `test_parse_groups_page` — saved HTML of `/events/72/groups` → expected flight list (~26 flights for U10-U19)
2. `test_parse_schedule_page_oro` — full Boys-U19 Oro flight → 12 teams, 21 games, standings rows
3. `test_parse_schedule_page_unplayed_games` — fixture with `-` / blank scores → unplayed filtered out
4. `test_parse_dual_age_division` — "2014/15" division → U12 canonical
5. `test_age_filter_excludes_u9` — U10-U19 filter drops U7/U8/U9 flights
6. `test_matcher_strips_ecnl_markers` — `"Crossfire B07/08 Academy ECNL"` → `"Crossfire Academy"` for fuzzy
7. `test_matcher_handles_coach_suffix` — `"Beach FC B07/08 ECRL - Jorge Reyes"` → strip `- Jorge Reyes`
8. `test_intake_journal_resume` — partial JSONL → second run skips completed flights

Integration smoke test: `--dry-run` against live event 72, assert ≥20 flights discovered and ≥100 games parsed.

## Acceptance criteria

1. Migration applied: `providers` table has `somsports` row
2. CLI run against event 72 with `--age-min u10 --age-max u19` produces `raw_scrape.jsonl` with all in-scope flights
3. `import_games_enhanced.py` consumes the JSONL with zero schema errors
4. ≥90% of teams auto-match to canonical (Surf Cup is well-known SoCal/NorCal clubs already in PitchRank)
5. Unmatched teams appear in review queue with confidence < 0.9
6. `games` table has new rows tagged `provider_id = <somsports uuid>` with valid home/away master IDs
7. All 8 unit tests pass
8. Re-running with `--resume` is a no-op (idempotent)

## Open questions (deferred to writing-plans)

- Exact `IntakeJournal` schema reuse vs. SOM-specific extension (look at `src/intake/journal.py` for current `EventMetadata` fields)
- Whether `field` belongs in `games.venue` or a new column (audit current usage)
- Rate limiting — verify SOM Sports tolerates back-to-back requests; default to 1 req/sec with jitter
- HTTP client choice — match existing scrapers (`requests` + `BeautifulSoup4` is standard in this repo per the explore report)

## Out of scope (for later)

- Live polling during active tournaments
- College coach data ingestion
- Logo/image downloading
- Cross-tournament team alias merging (handled downstream by existing dedupe)
- Other events on athletes2events.com (CLI is event-ID-parameterized so adding one is trivial, but not built in this iteration)
