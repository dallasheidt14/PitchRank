---
type: plan
status: done
---

# Plan: Add PlayMetrics Scraper Provider

## Context

PitchRank needs a fifth ingestion provider: PlayMetrics (used by several state youth leagues, starting with Wisconsin's SECL & State League Fall 2025). PlayMetrics exposes a public, unauthenticated JSON API at `api.gb.playmetrics.com/external/lss/*` that returns teams, schedules, and standings in a single call per division — cleaner input than any existing provider. The scraper and matcher must plug into the existing `EnhancedETLPipeline` flow without altering behavior for GotSport, TGS, Affinity WA, or the weekly hygiene pipeline.

Deliverables: (1) a new JSON-API scraper modeled on `scripts/scrape_tgs_event.py`, (2) a new `PlayMetricsGameMatcher(GameHistoryMatcher)` that inline-autocreates teams using state-scoped fuzzy logic (Affinity-style) plus TGS-style provider-native integer IDs, (3) one-line routing in `src/etl/enhanced_pipeline.py`, (4) a new weekly workflow modeled on `.github/workflows/tgs-event-scrape-import.yml`. State is populated scraper-side via a hardcoded `{governing_body_id → state_code}` map (starting with `{1014: "WI"}`). Forfeits are dropped at scrape time.

## Pattern Survey

### Analogous Features

- `C:/PitchRank/scripts/scrape_tgs_event.py:1-793` — Public JSON-API scraper. **Closest analog.** `resolve_config()` precedence CLI > ENV > default; emoji-prefixed `print()` logging; `ThreadPoolExecutor` parallelism; `normalize_api_game()` → 27-column canonical CSV (see `REQUIRED_COLUMNS` at lines 27-55); `is_future_game()` filter; `--dry-run` flag; always writes header-only CSV on 0 rows.
- `C:/PitchRank/scripts/scrape_affinity_wa_tournament.py:1-439` — Public-HTML scraper with hardcoded `STATE_CODE="WA"` and MD5-derived synthetic team IDs. Useful reference for state-scoped behavior and deterministic ID synthesis when a provider doesn't supply them.
- `C:/PitchRank/src/models/game_matcher.py:442-1540` — Base `GameHistoryMatcher`. Reads thresholds FROM `MATCHING_CONFIG` (defined at `config/settings.py:187-202`) into instance attributes at lines 447-450: `self.fuzzy_threshold=0.75`, `self.auto_approve_threshold=0.9`, `self.review_threshold=0.75`, `self.fuzzy_confidence_ceiling=0.99`, `self.club_variant_match_boost=0.15`, `self.affinity_club_similarity_threshold=0.9`. Override seams: `_match_team` (684), `_match_by_provider_id` (830), `_match_by_alias` (1019), `_fuzzy_match_team` (1061), `_calculate_match_score` (1309), `_normalize_team_name` (1286), `_create_alias` (1392), `_create_review_queue_entry` (1456).
- `C:/PitchRank/src/models/tgs_matcher.py:57-696` — `TGSGameMatcher(GameHistoryMatcher)`. Autocreates teams in `_match_team` (line 512) via `_create_new_tgs_team` (586). Skips age-group gate in `_match_by_provider_id` because TGS IDs are unique per team. Strips club prefix before delegating to `super()._normalize_team_name`.
- `C:/PitchRank/src/models/affinity_wa_matcher.py:1-393` — `AffinityWAGameMatcher(GameHistoryMatcher)`. Hard-filters `state_code="WA"` in `_fuzzy_match_team` (line 105). Reads `club_variant_match_boost` from `MATCHING_CONFIG` in `_calculate_match_score` (line 249, reads via `.get(..., 0.35)` at line 256 — but `MATCHING_CONFIG["club_variant_match_boost"]` is set to `0.15` in `config/settings.py:195`, so the effective value is 0.15, not 0.35). Autocreates via `_create_new_affinity_wa_team` (line 339) with hardcoded state.
- `C:/PitchRank/src/etl/enhanced_pipeline.py:210-245` — **Provider→matcher routing lives here**, not in `scripts/import_games_enhanced.py`. Plain `elif self.provider_code.lower() == "<code>":` chain. Current providers: `modular11`, `tgs`, `sincsports`, `affinity_wa`.
- `C:/PitchRank/.github/workflows/tgs-event-scrape-import.yml:1-183` — Scrape → pre-create teams → `import_games_enhanced.py --stream --concurrency 8 --checkpoint` pipeline. `has_games` gating step parses `wc -l`. Dual artifacts (CSV + logs). Single cron `30 6 * * 1`. **Closest workflow analog for PlayMetrics.**
- `C:/PitchRank/.github/workflows/wa-scraper.yml:1-162` — Two-cron DST workaround, per-age bucketed CSVs merged into one. Not needed here since we're pulling a whole league in one run.

### Reusable Utilities

- `C:/PitchRank/src/utils/enhanced_validators.py:17,47` — `parse_game_date`, `EnhancedDataValidator.validate_game/team/batch`. Enforces `home_away∈{H,A}`, goals 0–50, age `u10–u19`, gender `{Male,Female,Boys,Girls,Coed}`, state 2-letter uppercase.
- `C:/PitchRank/src/utils/team_name_utils.py` — `extract_club_from_team_name`, `extract_distinctions`, `extract_team_variant`, `normalize_club_for_comparison`, `normalize_name_for_matching`. **Canonical home for matcher-side name utilities.**
- `C:/PitchRank/src/utils/club_normalizer.py` — `normalize_to_club`, `similarity_score`, `are_same_club`. Used by both TGS and Affinity matchers for canonical-club matching.
- `C:/PitchRank/src/utils/team_utils.py` — `calculate_age_group_from_birth_year`, module-level `CURRENT_YEAR`.
- `C:/PitchRank/src/models/game_matcher.py:61-363` — Module-level `TEAM_COLORS`, `TEAM_DIRECTIONS`, `_NON_COACH_WORDS`, `_REGION_CODES`, `_PROGRAM_NAMES`, `_AGE_PATTERNS` + top-level `extract_team_variant` (263), `extract_club_from_team_name` (363). Subclasses import these directly.
- `C:/PitchRank/src/models/game_matcher.py:461` — `generate_game_uid(provider, game_date, team1_id, team2_id)` staticmethod — deterministic `game_uid`. Use this; do not roll a new hash.
- `C:/PitchRank/src/models/game_matcher.py:1392` — `_create_alias` already upserts `team_alias_map` on every successful fuzzy-auto / autocreate match. No explicit cache-write path needed in the subclass.
- No shared HTTP client, retry helper, or CSV writer helper exists. Each scraper rolls its own (convention).

### Convention Anchors

- **Canonical 27-column CSV** (Affinity + TGS identical order, must match `scripts/scrape_tgs_event.py:27-55` `REQUIRED_COLUMNS` exactly): `provider, scrape_run_id, event_id, event_name, schedule_id, age_year, age_group, gender, team_id, team_id_source, team_name, club_name, opponent_id, opponent_id_source, opponent_name, opponent_club_name, state, state_code, game_date, game_time, home_away, goals_for, goals_against, result, venue, source_url, scraped_at`. Importer at `scripts/import_games_enhanced.py:80-108` reads a subset; extras are informational. **PlayMetrics emits these 27 columns plus a 28th `division_name` column** appended at the end (PlayMetrics has `division.name` cleanly; the importer reads this column into `games.division_name` if present).
- **Output path**: `data/raw/{provider}/<prefix>_<ts>.csv` where `ts = datetime.now(UTC).isoformat().replace(':','-').replace('.','-')`.
- **Scrape run ID**: `f"{iso_utc_ts}_{uuid4.hex[:6]}"`.
- **Deterministic synthesized team_id** (when provider lacks one): `f"{provider}:{md5(team_name.lower().strip())[:12]}"`. Not needed for PlayMetrics — use native `teams[].team.id` as string.
- **`games` uniqueness**: composite unique index on `(provider_id, home_provider_id, away_provider_id, game_date, COALESCE(home_score,-1), COALESCE(away_score,-1))` + `idx_games_uid_unique` on `game_uid`. **Games are immutable** (`supabase/migrations/20240201000001_add_game_corrections.sql:60` raises on UPDATE); corrections go through `game_corrections` table. Re-scrapes do NOT update existing rows; duplicates are pre-dedup'd in memory at `src/etl/enhanced_pipeline.py:299` (`_make_composite_key`) and constraint violations are caught at insert.
- **`team_alias_map` schema**: `id, provider_id, provider_team_id, team_id_master, match_confidence, match_method, review_status, created_at, division` + `UNIQUE(provider_id, provider_team_id)`. Lookup: `(provider_id, provider_team_id)` + `review_status='approved'`. Base `_create_alias` caps fuzzy-auto confidence at 0.99; only `direct_id`/`import` methods get 1.0.
- **`providers` row must exist** before first import: `INSERT INTO providers (code, name, base_url)`. Looked up by `game_matcher.py:1524`.
- **Workflow env-var pattern**: per-step env blocks (not workflow-level), three Supabase vars matching `.github/workflows/tgs-event-scrape-import.yml:76-80`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (the role key aliased from the service key). `PYTHONPATH: ${{ github.workspace }}`. Python 3.11.
- **Artifact**: `actions/upload-artifact@v5`, `retention-days: 30`, separate CSV + logs artifacts, name pattern `{provider}-{identifier}-${{ github.run_number }}`.
- **Row-count reporting**: `wc -l` on CSV → `$GITHUB_OUTPUT` (`has_games=true/false`). Importer prints `IMPORT_RESULT:{json}` at `scripts/import_games_enhanced.py:637`.
- **Logging**: scrapers use bare `print()` (TGS emoji-prefixed, Affinity plain); matchers use `logging.getLogger(__name__)` with `[Provider]` bracketed prefix.

### Proposed Alignment

Mirror TGS most closely for the scraper and workflow (public JSON API, provider-native integer team IDs, emoji logging, always-header CSV, `has_games` gating, dual artifacts). Mirror Affinity WA's state-scoping for the matcher (the `state_code` filter in `_fuzzy_match_team` and hardcoded state constant on autocreated teams), since this scrape produces single-state Wisconsin data. Autocreate inline in `_match_team` (both TGS and Affinity do this); confidence threshold stays at the base default `0.90` to match Affinity WA and avoid setting a new precedent. Pull distinction extractors exclusively from `src/utils/team_name_utils.py` and `src/models/game_matcher` module-level symbols — do not import from `scripts/*` (reversing the src→scripts boundary and inheriting script-level side effects is a divergence we're explicitly rejecting).

**Inline autocreate vs. TGS-style pre-create-teams step:** TGS's workflow includes a pre-create step (`scripts/extract_and_import_tgs_teams.py`) because TGS wants to skip fuzzy matching entirely — its provider IDs are authoritative and cross-provider collision isn't a concern for its data. PlayMetrics is different: Wisconsin clubs likely already exist in PitchRank from GotSport/TGS tournament scrapes, so we **want** fuzzy matching as the primary path to resolve cross-provider duplicates inline. Pre-creating PlayMetrics teams before fuzzy would create duplicates that weekly hygiene would then need to merge. The subclass autocreates only after `super()._match_team` tries alias → direct_id → fuzzy and all miss, so genuinely new teams are the only ones created fresh.

## Implementation Steps

1. **Create scraper `scripts/scrape_playmetrics_league.py`**
   - Model on `scripts/scrape_tgs_event.py:1-793`. Reuse its `resolve_config()` precedence pattern, module-level `SCRAPE_TS`/`SCRAPE_RUN_ID` set inside `main()`, emoji logging, `--dry-run` semantics, always-write-header-only-on-empty behavior.
   - CLI args (argparse): `--league-url <url>` (alternative to explicit IDs), `--governing-body-id <int>`, `--league-id <int>`, `--key <str>`, `--output-dir <path>` (default `data/raw/playmetrics`), `--dry-run` flag, `--max-workers <int>` (default 1; PlayMetrics is one-call-per-division — parallelism optional).
   - Env-var overrides (resolve_config precedence): `PLAYMETRICS_LEAGUE_URL`, `PLAYMETRICS_OUTPUT_DIR`, `PLAYMETRICS_MAX_WORKERS`, `PLAYMETRICS_DELAY_SEC` (default 0.3 like TGS).
   - Hardcoded module-level: `GB_STATE_MAP = {1014: "WI"}` — add entries as leagues onboard.
   - URL parser: given `https://playmetricssports.com/g/leagues/{gb}-{league}-{key}/league_view.html`, regex out `(gb, league, key)` tuple. Same resolver accepts explicit flags.
   - HTTP: plain `requests.post(url, data=json.dumps(body), headers={'content-type': 'text/plain;charset=UTF-8'}, timeout=30)`. Inline try/except with **3 retries** and exponential backoff (`sleep(1 * (attempt+1))` seconds between tries), matching `scripts/scrape_affinity_wa_tournament.py:_fetch()` pattern. Single-retry was insufficient given 72 division calls per league run.
   - Flow:
     1. `POST /external/lss/league` → extract `name` (league), `start_date`, `end_date`, `divisions[]` (id, name, gender, min_age, max_age).
     2. For each division in `divisions[]`: `POST /external/lss/division` → get `teams[]`, `schedule[]`, `sport_configuration`, `standings`. Sleep `PLAYMETRICS_DELAY_SEC` between calls.
     3. **Skip division if** `"futsal" in (sport_configuration or {}).get("name", "").lower()` (keeps futsal out). Warn-log when `sport_configuration` is `None` or `.name` is missing — don't silently drop divisions with unexpected shape (per `memory/gotcha_futsal_in_rankings.md`, futsal exclusion is a hard correctness requirement).
     4. Build in-memory `team_lookup[team.id] → {team_name, club_id, club_name}` from `teams[]`.
     5. For each `game` in `schedule[]`:
        - **Skip if** `status not in {"Played"}` (allowlist: excludes `"Forfeit"`, `"Rescheduled"`, and any future/unknown status values — safer than a blocklist because it protects against stale-score leaks on rescheduled games and unknown future status strings).
        - **Skip if** `home_team_id`/`away_team_id` not in `team_lookup` (orphan reference).
        - Emit TWO rows (one row per team's perspective, same as TGS/Affinity): one with `team_id=home_team_id, home_away="H"`, one with `team_id=away_team_id, home_away="A"`.
   - Field mapping per emitted row (27-column canonical order matching `scripts/scrape_tgs_event.py:27-55` `REQUIRED_COLUMNS` exactly, plus `division_name` appended as column 28; empty strings for unpopulated fields):
     - `provider` = `"playmetrics"`
     - `scrape_run_id` = module-level `SCRAPE_RUN_ID`
     - `event_id` = `""` (PlayMetrics uses league_id; leave blank)
     - `event_name` = league.name (e.g., `"SECL & State League Fall 2025"`)
     - `schedule_id` = `str(game.id)` (stable, e.g., `"64419"`)
     - `age_year` = `""` (PlayMetrics doesn't provide birth year directly)
     - `age_group`: derive from `division.min_age` (PitchRank convention slots dual-age divisions to the younger cohort so same-aged players across divisions rank together). Map:
       - `min_age` in `10..17` → `f"u{min_age}"`
       - `min_age == 18` → `"u19"` (PitchRank merges u18 into u19 — `config/settings.py:86-96` `_BIRTH_YEARS` skips 18; U19 encompasses birth years 2007 AND 2008)
       - `min_age == 19` → `"u19"`
       - Anything else → log warning, skip the division (not in `AGE_GROUPS`)
     - `gender` = `"Male"` if `division.gender == "M"` else `"Female"`
     - `team_id` = `str(team.id)` (the underlying `teams[].team.id`, e.g., `"23118"`)
     - `team_id_source` = same as `team_id`
     - `team_name` = `teams[].team.name`
     - `club_name` = `teams[].club.name`
     - `opponent_id` = `str(opponent_team.id)`
     - `opponent_id_source` = same as `opponent_id`
     - `opponent_name` = opponent's `team.name`
     - `opponent_club_name` = opponent's `club.name`
     - `state` = `"Wisconsin"` (mapped from `GB_STATE_MAP[governing_body_id]` → STATE_CODE_TO_NAME)
     - `state_code` = `GB_STATE_MAP[governing_body_id]` (`"WI"` for gb=1014). At scraper startup, assert `governing_body_id in GB_STATE_MAP` with message `f"Unknown PlayMetrics governing_body_id {governing_body_id}. Add an entry to GB_STATE_MAP in scripts/scrape_playmetrics_league.py."` — fail fast on unknown governing bodies rather than silently producing empty state_codes (no regex fallback; `field.address` isn't guaranteed to be present for every game).
     - `game_date` = `game.start_datetime[:10]` (`"2025-09-06"` from ISO UTC). **Timezone caveat:** `start_datetime` is UTC, so an evening game at 9pm local in Central time (`CDT = UTC-5`) becomes `02:00Z` the next day — naive slicing would return the wrong local date. During implementation, verify against the PlayMetrics web UI for a sample of evening games; if slicing gives the wrong date, convert to `America/Chicago` (or to the state's local tz via `pytz`) before the `[:10]` slice.
     - `game_time` = `game.time` (e.g., `"10:30 AM"`)
     - `home_away` = `"H"` or `"A"`
     - `goals_for` / `goals_against` = from `home_team_score`/`away_team_score`, flipped for A-row; empty string if unplayed
     - `result` = `W`/`L`/`D` if scores present, else `U`
     - `venue` = `field.name` + `" "` + `field.address` (joined, strip trailing whitespace; empty if field missing)
     - `source_url` = `f"https://playmetricssports.com/g/leagues/{gb}-{league}-{key}/divisions/{division.id}/division_view.html"`
     - `scraped_at` = ISO UTC timestamp of the scrape
     - `division_name` = `division.name` (column 28; e.g., `"19U Girls First"`, `"18/19U Girls A/B"`) — beyond the canonical 27 but read by `scripts/import_games_enhanced.py:82-108` into `games.division_name`
   - Output filename: `data/raw/playmetrics/playmetrics_{gb}_{league}_{key}_{ts}.csv` (ts with `:` and `.` replaced by `-`).
   - End-of-run print: `📊 Scraped {total_games} games across {division_count} divisions; {skipped_non_played} non-played games dropped ({forfeit_count} forfeits, {other} other statuses); {futsal_dropped} futsal divisions skipped.`
   - Exit cleanly (no `sys.exit`) on no-data; still write header-only CSV.

2. **Ensure providers row exists (pre-launch manual step, document in plan only)**
   - Before first real import, run one-time SQL against Supabase:
     ```sql
     INSERT INTO providers (code, name, base_url)
     VALUES ('playmetrics', 'PlayMetrics', 'https://playmetricssports.com')
     ON CONFLICT (code) DO NOTHING;
     ```
   - Do NOT automate this in the scraper or matcher.

3. **Create matcher `src/models/playmetrics_matcher.py`**
   - Model hybrid: TGS structure (JSON API, integer IDs → `_match_by_provider_id` skips age-group gate) + Affinity WA state-scoping (WI-filter in `_fuzzy_match_team`, hardcoded state on autocreated teams).
   - `class PlayMetricsGameMatcher(GameHistoryMatcher)` — imports from `src/*` and `config/` only (NOT from `scripts/*`):
     - `from config.settings import MATCHING_CONFIG` — canonical source (mirrors `src/models/affinity_wa_matcher.py:20`; `game_matcher` re-exports it via line 13 but `config.settings` is the single source of truth).
     - `from src.models.game_matcher import GameHistoryMatcher, extract_team_variant, extract_club_from_team_name`
     - `from src.utils.team_name_utils import normalize_name_for_matching, normalize_club_for_comparison`
     - `from src.utils.club_normalizer import are_same_club, similarity_score`
     - `logger = logging.getLogger(__name__)` with `[PlayMetrics]` prefix convention.
   - Module constants: `STATE_CODE = "WI"` (default; matcher looks up per-row state at runtime — see `_match_team` below), `PROVIDER_CODE = "playmetrics"`.
   - `__init__(self, supabase, provider_id, alias_cache=None)` — call `super().__init__()`, do NOT override any thresholds (keep base `fuzzy_threshold=0.75`, `auto_approve_threshold=0.9`, `review_threshold=0.75` as defined in `config/settings.py:187-202`).
   - Override `_match_by_provider_id(self, row)` (mirror `tgs_matcher.py:404`): skip age-group validation because PlayMetrics `teams[].team.id` is stable-per-team; confidence 1.0; `match_method="direct_id"`.
   - Override `_fuzzy_match_team(self, row, candidates)` (mirror `src/models/affinity_wa_matcher.py:133-140`): narrow candidate query with `.eq("state_code", row.get("state_code") or STATE_CODE)`, `.eq("age_group", row["age_group"])`, `.eq("gender", row["gender"])` **only**. Apply the club gate **in Python** after the query, via `are_same_club(candidate["club_name"], row["club_name"], threshold=MATCHING_CONFIG["affinity_club_similarity_threshold"])` — do NOT use a SQL `.ilike("club_name", ...)` prefix filter (it rejects legitimate candidates whose `club_name` differs by prefix, e.g., `"Bavarian United"` vs `"Bavarian Soccer Club"` both normalize to the same canonical club). Then apply base `_calculate_match_score` to the filtered candidates.
   - Override `_match_team(self, provider_id, provider_team_id, team_name, age_group, gender, club_name=None)` (mirror `src/models/tgs_matcher.py:512-584` exactly — do NOT re-implement the alias/direct_id/fuzzy ladder in the subclass; the base class owns those paths including the 0.75/0.90 thresholds and review-queue routing):
     1. Call `base_result = super()._match_team(provider_id, provider_team_id, team_name, age_group, gender, club_name)`.
     2. **If `base_result.get("matched")` is True, return `base_result` immediately** (alias hit, direct provider-id hit, fuzzy auto-approve, OR review-queue routing all resolve here — base already does the right thing).
     3. On `matched=False` AND `team_name` + `age_group` + `gender` all present: call `new_team_id = self._create_new_playmetrics_team(team_name, club_name, age_group, gender, provider_id, provider_team_id)`.
     4. Create alias so next scrape cache-hits: `self._create_alias(provider_id, provider_team_id, team_name, team_id_master=new_team_id, match_method=("direct_id" if provider_team_id else "import"), confidence=1.0, age_group=age_group, gender=gender, review_status="approved")`.
     5. Return `{"matched": True, "team_id": new_team_id, "method": match_method, "confidence": 1.0}`.
     6. On any exception during autocreate, log and return `base_result` as fallback (mirror TGS `except Exception` at lines 574-576).
   - Implement `_create_new_playmetrics_team(self, team_name, club_name, age_group, gender, provider_id, provider_team_id)` (mirror `src/models/tgs_matcher.py:586-696` exactly — these are the fields the `teams` table actually has per `supabase/migrations/20240101000000_initial_schema.sql:28-51`):
     - Generate `team_id_master = str(uuid.uuid4())`.
     - Normalize gender: `gender_normalized = "Male" if gender.upper() in ("M","MALE","BOYS","B") else "Female"` (the `teams.gender` CHECK constraint only allows `'Male'`/`'Female'`, NOT `'Boys'`/`'Girls'`).
     - Lowercase age_group: `age_group_normalized = age_group.lower()`.
     - Insert into `teams` with ONLY the columns that exist: `team_id_master, team_name, club_name (fall back to team_name if None), age_group=age_group_normalized, gender=gender_normalized, provider_id, provider_team_id, state_code=(row_state_code or STATE_CODE), state=STATE_CODE_TO_NAME.get(state_code), created_at=datetime.utcnow().isoformat()+"Z"`. Do NOT include `external_id`, `source`, or `is_deprecated` — the first two don't exist on the teams table; `is_deprecated` defaults to False at the DB level.
     - **Duplicate-key race recovery** (mirror `tgs_matcher.py:671-694`): wrap the insert in `try/except`; on exception, check if `"duplicate key"` or `"23505"` is in `str(e).lower()` — if so, look up existing team via `self.db.table("teams").select("team_id_master").eq("provider_id", provider_id).eq("provider_team_id", provider_team_id).single().execute()` and return its `team_id_master`. This handles the race where two CSV rows for a brand-new team both trigger autocreate.
     - Return `team_id_master`.
   - Do NOT override `_create_alias` or `_create_review_queue_entry` — base behavior is correct.

4. **Add provider→matcher routing in `src/etl/enhanced_pipeline.py`**
   - Open `src/etl/enhanced_pipeline.py` and locate the `_ensure_initialized()` method (the elif chain lives at lines 210-245 inside that method — NOT at module level). Locate the `elif self.provider_code.lower() == "affinity_wa":` block.
   - Add immediately below it:
     ```python
     elif self.provider_code.lower() == "playmetrics":
         from src.models.playmetrics_matcher import PlayMetricsGameMatcher
         self.matcher = PlayMetricsGameMatcher(
             self.supabase, provider_id=self.provider_id, alias_cache=self.alias_cache
         )
     ```
   - Do NOT modify the `modular11`, `tgs`, `sincsports`, `affinity_wa`, or default branches.

5. **Create workflow `.github/workflows/playmetrics-scrape-import.yml`**
   - Model on `.github/workflows/tgs-event-scrape-import.yml:1-183`.
   - `name: PlayMetrics League Scrape & Import`
   - Triggers:
     - `schedule: - cron: '30 6 * * 1'` (Sunday 06:30 UTC — mirrors TGS; Sunday evening Central/Mountain to catch weekend games).
     - `workflow_dispatch:` with inputs `league_url` (default `'https://playmetricssports.com/g/leagues/1014-1514-8ccd4dbb/league_view.html'` — the SECL test league) and `dry_run` (default `'false'`).
   - `timeout-minutes: 120`.
   - Env block with **three** Supabase vars matching `.github/workflows/tgs-event-scrape-import.yml:76-80` exactly: `SUPABASE_URL: ${{ secrets.SUPABASE_URL }}`, `SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}`, `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}` (role key aliased from the service key). Plus `PYTHONPATH: ${{ github.workspace }}`. Do NOT add `NEXT_PUBLIC_SUPABASE_URL` or `SUPABASE_KEY` aliases — the template doesn't use them.
   - Steps:
     1. `actions/checkout@v5`
     2. `actions/setup-python@v6` with `python-version: '3.11'` and `cache: 'pip'`.
     3. `pip install -r requirements.txt` (mirror TGS).
     4. **Scrape step**: `python scripts/scrape_playmetrics_league.py --league-url "${LEAGUE_URL}" --output-dir data/raw/playmetrics 2>&1 | tee logs/playmetrics_scrape.log`. Set `LEAGUE_URL` from input or fallback. Exit code respected by `set -euo pipefail`.
     5. **Find CSV step** (mirror TGS `has_games` gate at `tgs-event-scrape-import.yml:~80`): locate newest file in `data/raw/playmetrics/playmetrics_*.csv`; `wc -l` → `has_games=true/false`; write to `$GITHUB_OUTPUT`.
     6. **Import step**: skipped if `has_games=false` or `dry_run=true`. Command: `python scripts/import_games_enhanced.py "${CSV_FILE}" playmetrics --stream --concurrency 8 --checkpoint 2>&1 | tee logs/playmetrics_import.log`.
     7. **Upload CSV artifact**: `actions/upload-artifact@v5`, name `playmetrics-csv-${{ github.run_number }}`, path `data/raw/playmetrics/*.csv`, retention 30.
     8. **Upload logs artifact**: same action, name `playmetrics-logs-${{ github.run_number }}`, path `logs/playmetrics_*.log`, retention 30.
     9. **Summary step** (`if: always()`): write `## PlayMetrics Scrape Summary` block to `$GITHUB_STEP_SUMMARY` with league name, division count, game count, forfeits dropped, import result.
   - Do NOT add a pre-create-teams step (we autocreate inline in the matcher, per product decision).

## Verification

- **Season-over-season team.id stability check** (one-time, before first production import — validates the core assumption that `teams[].team.id` is stable within a season):
  - Scrape the SECL league today; save the sorted list of `teams[].team.id` values to `stability_check_t0.txt`.
  - Re-scrape 7 days later; save to `stability_check_t7.txt`.
  - `diff stability_check_t0.txt stability_check_t7.txt` — expected: identical (any new IDs are net-new team registrations, not reassigned existing ones). If IDs rotate mid-season, escalate before first production import — the plan's `_match_by_provider_id` cache-hit strategy assumes stable IDs.
- **Scraper dry-run sanity** (from `C:/PitchRank`):
  - `python scripts/scrape_playmetrics_league.py --league-url "https://playmetricssports.com/g/leagues/1014-1514-8ccd4dbb/league_view.html" --dry-run`
  - Expected: prints the summary line (`📊 Scraped N games across 72 divisions; S non-played dropped (F forfeits, R other); 0 futsal divisions skipped.`) with N > 0 and per-division counts visible in the log. Division count depends on where the season is — Week 1 might be N=20, mid-season N=2000. CSV is NOT written in dry-run.
- **Scraper wet run**:
  - Same command without `--dry-run`. Confirm `data/raw/playmetrics/playmetrics_1014_1514_8ccd4dbb_<ts>.csv` exists, every row has `state_code="WI"`, no rows with `status in {"Forfeit","Rescheduled"}` (we filter at scrape time so they never appear).
  - Confirm column order matches the 27-column canonical list + `division_name` as column 28 (`head -1 <csv>` equals the list in Convention Anchors).
- **Importer validator dry-run**:
  - `python scripts/import_games_enhanced.py <csv> playmetrics --validate-only` — expected: all rows pass `EnhancedDataValidator.validate_batch`; any failures logged with row index + reason. Specific non-failures to watch for: zero `age_group` rejections (our mapping produces u10-u17, u19 only — never invalid u18), zero `home_away` rejections (always H or A), zero `gender` rejections (normalized to Male/Female).
- **Matcher behavior sanity** (manual test in Python REPL or a scratch script — do not add a permanent test file):
  - Instantiate `PlayMetricsGameMatcher` against a test Supabase row.
  - Given a synthetic row with `club_name="Bavarian United"`, `state_code="WI"`, `age_group="u19"`, `gender="Female"`, `team_name="U18 Girls Blue"`, confirm exactly one of these observable outcomes (not both):
    - (a) A new `team_alias_map` row with `match_method IN ('fuzzy_auto','direct_id','import')` and `review_status='approved'` — the base matcher resolved the team via alias/direct-id/fuzzy OR our subclass autocreated a new team row.
    - (b) A new `team_match_review_queue` row with `status='pending'` — the base matcher found a borderline (0.75-0.90) fuzzy candidate.
  - Verify any new `teams` row has `state_code='WI'`, `age_group='u19'`, `gender='Female'` and has NO `external_id` or `source` column set (those columns don't exist).
- **End-to-end import wet run**:
  - After `INSERT INTO providers ('playmetrics', …)`: `python scripts/import_games_enhanced.py <csv> playmetrics --stream --concurrency 8 --checkpoint`.
  - Confirm `IMPORT_RESULT:{json}` line shows matched + created team counts + game insertion count.
  - Spot-check `teams` table: `SELECT count(*) FROM teams WHERE provider_id=(SELECT id FROM providers WHERE code='playmetrics');` should equal roughly the unique team count in the CSV (there's no `source` column on teams — provider linkage is via `provider_id` FK).
  - Spot-check `games` table: `SELECT count(*) FROM games WHERE provider_id=(SELECT id FROM providers WHERE code='playmetrics');` should equal approximately half the CSV row count (CSV has two rows per game).
- **Workflow manual-dispatch**:
  - Trigger `.github/workflows/playmetrics-scrape-import.yml` via GitHub UI with default inputs. Confirm both artifacts upload, summary block populates, exit code 0.
- **Edge-case spot-checks**:
  - Division where `sport_configuration.name` contains `"futsal"` (any case) → excluded entirely from CSV (log line `futsal_dropped > 0`). Divisions with other sport-configuration values (including `None`/missing) are warn-logged but NOT skipped — Step 1 only filters futsal explicitly.
  - Division with 0 played games → no rows emitted for that division, scrape continues.
  - Schedule entry with `home_team_id` not in `teams[]` (shouldn't happen per API contract but verify defensive skip + logged warning).
  - Re-run on same league → games table rejects duplicates via composite unique index; importer summary reports duplicates-skipped count rather than erroring.

## Context Files

Files to read in full before starting implementation:

- `C:/PitchRank/scripts/scrape_tgs_event.py` — scraper template structure, `resolve_config` precedence, `normalize_api_game`, emoji logging, CSV writing conventions.
- `C:/PitchRank/scripts/scrape_affinity_wa_tournament.py` — state-scoped scraper reference, retry/backoff pattern, header-only-on-empty behavior.
- `C:/PitchRank/scripts/import_games_enhanced.py` — exact CSV column subset read at lines 80-108, `IMPORT_RESULT` print format at 637.
- `C:/PitchRank/config/settings.py:187-202` — `MATCHING_CONFIG` definition: `fuzzy_threshold=0.75`, `auto_approve_threshold=0.9`, `review_threshold=0.75`, `club_variant_match_boost=0.15`, `affinity_club_similarity_threshold=0.9`, `fuzzy_confidence_ceiling=0.99`. Read this to confirm the real threshold values before coding the matcher.
- `C:/PitchRank/config/settings.py:86-96` — `AGE_GROUPS` / `_BIRTH_YEARS`. Confirms `u18` is NOT a valid age_group (merges into `u19`).
- `C:/PitchRank/src/models/game_matcher.py` — base class override seams (lines 442-1540), `MATCHING_CONFIG` consumed at 447-450 (defined in `config/settings.py`), module-level constants and utilities (61-363), `generate_game_uid` (461), `_create_alias` (1392).
- `C:/PitchRank/src/models/tgs_matcher.py` — closest matcher template: `_match_by_provider_id` override (404), `_match_team` autocreate branching (512), `_create_new_tgs_team` structure (586), duplicate-key race recovery (671-694).
- `C:/PitchRank/src/models/affinity_wa_matcher.py` — state-scoping pattern in `_fuzzy_match_team` (105), `_match_team` override (265), `_create_new_affinity_wa_team` at line 339.
- `C:/PitchRank/src/etl/enhanced_pipeline.py` — the one-line routing insertion point (lines 210-245) and the `_make_composite_key` dedup logic (299).
- `C:/PitchRank/src/utils/enhanced_validators.py` — `parse_game_date` (17), `EnhancedDataValidator` (47), exact age/gender/state validation rules.
- `C:/PitchRank/src/utils/team_name_utils.py` — canonical name-utility import home for the matcher (`extract_distinctions`, `normalize_name_for_matching`, `normalize_club_for_comparison`).
- `C:/PitchRank/src/utils/club_normalizer.py` — `are_same_club`, `similarity_score` helpers used by fuzzy match.
- `C:/PitchRank/.github/workflows/tgs-event-scrape-import.yml` — workflow template: cron, env block, `has_games` gating, dual artifacts, summary.
- `C:/PitchRank/supabase/migrations/20240101000000_initial_schema.sql` — `teams`, `games`, `team_alias_map`, `providers` table definitions.
- `C:/PitchRank/supabase/migrations/20240201000001_add_game_corrections.sql` — `game_uid` unique index + games-are-immutable trigger context.
