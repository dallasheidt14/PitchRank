# Plan: Team Discovery — Find & Create New Teams Not Yet in DB

## Problem Statement

PitchRank scrapes games from 5 providers (GotSport, TGS, Modular11, SincSports, AthleteOne). When games are imported, opponent teams are matched via a 3-tier system (direct ID → fuzzy match → review queue). However, **GotSport's base `GameHistoryMatcher` does NOT auto-create new teams** — it only sends unmatched teams to the review queue or leaves `NULL` master IDs on game records. Only TGS and Modular11 matchers auto-create teams via their `_create_new_*_team()` overrides.

This means there is a growing pool of **"phantom" teams** — referenced in game data (as opponent IDs/names) but never created in the `teams` table. These teams are invisible to rankings.

## Current State

| Component | What it does | Gap |
|-----------|-------------|-----|
| `GameHistoryMatcher._match_team()` | Tries direct ID → alias → fuzzy. If no match: adds to `team_match_review_queue` with `NULL` suggestion | **Never creates a new team** for GotSport opponents |
| `TGSGameMatcher._match_team()` | Overrides base: creates new team if no match found | Only covers TGS provider |
| `Modular11GameMatcher` | Creates teams from CSV scrape data | Only covers Modular11 |
| `export_unknown_opponents.py` | Exports partial-linked games (one side `NULL`) | **Diagnostic only** — doesn't create teams |
| `auto_match_unknown_opponents.py` | Tries to match exported unknowns to existing teams | **Only matches to existing teams**, doesn't create new ones |
| `discover_u12_teams.py` | Crawls SincSports opponent links to find new team IDs | **Ad-hoc, single age group, single provider** |
| `find_missing_teams.py` | Compares CSV team IDs to DB | **TGS-specific, diagnostic only** |
| `team_match_review_queue` | Holds uncertain matches (0.75–0.90) | **Requires manual review**, no auto-creation path |

## Sources of Undiscovered Teams

1. **GotSport opponent IDs** — When we scrape team A's games, opponent team B has a `provider_team_id` but may not exist in `teams`. The game gets `away_team_master_id = NULL`.
2. **Review queue backlog** — Teams in `team_match_review_queue` with `no_match` method and no `suggested_master_team_id` are truly new teams.
3. **Event scraping** — GotSport event brackets contain teams not in our 25K tracked list.
4. **Cross-provider teams** — A team may exist in TGS but not in GotSport, or vice versa.

## Proposed Plan (5 Steps)

### Step 1: Identify Candidate Teams from Partial-Linked Games

**Goal**: Extract all unique provider team IDs that appear in games but have no corresponding `teams` entry.

**Approach**:
- Query `games` for rows where `home_team_master_id IS NULL` OR `away_team_master_id IS NULL`
- Extract the `home_provider_team_id` / `away_provider_team_id` from the NULL side
- Cross-reference against `teams` table and `team_alias_map` to confirm they truly don't exist
- Also query `team_match_review_queue` for entries with `match_method = 'no_match'` and `suggested_master_team_id IS NULL`
- Deduplicate by `(provider_id, provider_team_id)` pair

**Output**: A list of `(provider_id, provider_team_id, provider_team_name, age_group, gender, game_count)` candidates.

**New script**: `scripts/discover_new_teams.py` (Phase 1: discovery/audit)

### Step 2: Enrich Candidates with Provider Details

**Goal**: For each candidate, fetch full team metadata from the provider API.

**Approach**:
- **GotSport**: Use `GotSportScraper._fetch_club_name_for_team_id()` and the rankings API (`/api/v1/teams/{id}`) to get `full_name`, `club_name`, `age_group`, `gender`, `state`
- **TGS**: Already handled by `TGSGameMatcher` (auto-creates), but verify no orphans remain
- **SincSports**: Use `SincSportsScraper` to crawl team page and extract metadata
- **Modular11**: Already handled by `Modular11GameMatcher`, but verify
- Rate-limit all API calls (respect existing `GOTSPORT_DELAY_MIN/MAX` settings)
- Cache results to avoid re-fetching on retries

**Output**: Enriched candidate list with full metadata. Candidates missing required fields (`team_name`, `age_group`, `gender`) are flagged for manual review.

**Enhanced in**: `scripts/discover_new_teams.py` (Phase 2: enrichment)

### Step 3: Validate & Deduplicate Against Existing Teams

**Goal**: Prevent creating duplicate teams for candidates that ARE in the DB under a different name/alias.

**Approach**:
- For each enriched candidate, run the existing fuzzy matching pipeline (`GameHistoryMatcher._fuzzy_match_team()`) against all teams in the same `(age_group, gender)` cohort
- Apply club normalizer (`src/utils/club_normalizer.py`) to compare club names
- Apply team name utils (`src/utils/team_name_utils.py`) for distinction-based matching (colors, directions, coach names)
- **Thresholds**:
  - Score ≥ 0.90 → **This IS an existing team** → create alias only (no new team)
  - Score 0.75–0.90 → **Uncertain** → add to review queue with enriched metadata
  - Score < 0.75 → **Truly new team** → proceed to creation
- **Division tier protection**: ECNL ≠ ECNL-RL, HD ≠ AD — never merge across tiers (use existing `has_protected_division()` from `find_queue_matches.py`)

**Output**: Three buckets: `alias_only`, `review_needed`, `create_new`

### Step 4: Create New Teams & Aliases

**Goal**: Insert confirmed new teams into `teams` and `team_alias_map`.

**Approach**:
- For each team in `create_new` bucket:
  1. Generate UUID (`team_id_master`)
  2. Normalize `age_group` (strip "U" prefix, lowercase)
  3. Normalize `gender` → `"Male"` or `"Female"`
  4. Extract `club_name` using `extract_club_from_team_name()`
  5. Insert into `teams` table with all metadata
  6. Insert into `team_alias_map` with `match_method = 'direct_id'`, `confidence = 1.0`, `review_status = 'approved'`
- For each team in `alias_only` bucket:
  1. Insert into `team_alias_map` pointing to existing `team_id_master`
- Batch inserts (500 per batch) to respect Supabase limits
- **Dry-run mode** (`--dry-run`): log what would be created without writing to DB

**Output**: Count of teams created, aliases created, review queue entries added

### Step 5: Backfill NULL Master IDs in Games

**Goal**: Now that new teams exist, update the `NULL` master IDs in existing game records.

**Approach**:
- For each newly created team, find games where:
  - `home_provider_team_id = provider_team_id AND home_team_master_id IS NULL`
  - `away_provider_team_id = provider_team_id AND away_team_master_id IS NULL`
- Update the `NULL` master ID to the new `team_id_master`
- Use batch updates via Supabase RPC for efficiency
- Track count of games backfilled
- **Important**: This does NOT violate game immutability — we're filling in missing references, not changing game data (scores, dates, etc.)

**Output**: Count of games backfilled per team

## Script Interface

```bash
# Full discovery + dry run (safe, read-only)
python scripts/discover_new_teams.py --dry-run

# Discovery + enrichment for specific provider
python scripts/discover_new_teams.py --provider gotsport --dry-run

# Execute creation (writes to DB)
python scripts/discover_new_teams.py --provider gotsport --execute

# Execute with backfill
python scripts/discover_new_teams.py --provider gotsport --execute --backfill

# Limit scope (for testing)
python scripts/discover_new_teams.py --provider gotsport --limit 100 --dry-run

# Export candidates to CSV for review
python scripts/discover_new_teams.py --provider gotsport --export-csv data/exports/new_teams_candidates.csv
```

## Safety Measures

1. **Dry-run by default** — No DB writes unless `--execute` is explicitly passed
2. **Division tier protection** — Never merge ECNL/ECNL-RL, HD/AD
3. **Deduplication** — Full fuzzy match pass before creation
4. **Audit trail** — Log every decision (created, aliased, queued, skipped) with reasons
5. **Batch limits** — Process in batches of 500, with rate limiting on API calls
6. **Rollback support** — Track all created team UUIDs for potential cleanup
7. **Review queue** — Uncertain matches go to `team_match_review_queue`, not auto-created

## Automation (Future)

Once validated manually, this can be added to the weekly cycle:
- **Schedule**: After Monday PM game scrape, before ranking calculation
- **Workflow**: New GitHub Action `discover-new-teams.yml`
- **Flow**: `scrape_games → discover_new_teams → calculate_rankings`

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `scripts/discover_new_teams.py` | **Create** | Main discovery + creation script |
| `src/models/game_matcher.py` | **No change** | Reuse `_fuzzy_match_team()` for dedup |
| `src/utils/club_normalizer.py` | **No change** | Reuse for club name matching |
| `src/scrapers/gotsport.py` | **No change** | Reuse API client for enrichment |
| `.github/workflows/discover-new-teams.yml` | **Create (future)** | Automation workflow |

## Expected Impact

- **GotSport**: Likely 500–2000+ opponent teams currently missing (based on partial-linked games)
- **Rankings**: More teams = more complete SOS calculations = better rankings accuracy
- **Data quality**: Fewer `NULL` master IDs = cleaner game records
