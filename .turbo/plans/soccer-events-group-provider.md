---
status: done
---

# Plan: Soccer Events Group provider (Chicago Cup first)

## Context

The operator wants Soccer Events Group (soccereventsgroup.com, on the 3 Step Sports
platform) added as a data provider. Every team registered for an SEG event should be linked
in PitchRank under its SEG team id, and the event's results imported. The first event is the
2026 Chicago Cup, ProgramID `19206` (Vernon Hills IL, Sep 4–7 2026; 294 teams in 58 divisions,
mostly IL/WI/IN/IA). The tool is reusable per event id, runs by hand, and has no scheduled
workflow.

What the site publishes, measured 2026-09-14 against the live event (probe captures are in the
planning session's scratchpad, not the repo):

- **Teams** — `GET /api/team/list?affiliationId=80&programIds=<id>` returns JSON:
  `programTeams[0].divisions[]` with `divisionId`, `divisionName` ("Boys - U11 Platinum"),
  `gender` (true = boys), and `teams[]` with `teamId`, `teamName` (often with trailing spaces or
  a trailing NBSP), `origin` ("Chicago, IL") and `state`. No club field.
- **Division cohorts** — `GET /api/program/<id>` returns `program` (`start`, `end`, `city`,
  `state`, `name`) and `divisions[]` with `id`, `primaryName`, `sessionName` ("U11"), and
  `oldestEligibleBirthdate` ("2015-08-01T00:00:00"). That marks the older edge of an
  Aug 1–Jul 31 band, so the cohort's younger year is that year + 1.
- **Results** — only playoff bracket games are public. They are server-rendered on
  `/site/teams/details.aspx?TeamID=<id>` inside `BracketPanel`, as `<table class="game">`
  blocks:
  - One row per side. Cells: `td.team` with class `winner`/`loser` or neither; `td.score`;
    `td.title` on the top row ("Semifinal", "Championship", "4th Place Game", "Consolation");
    `td.time` on the bottom row (" 9/6 3:00P, Field 08").
  - Pool play is not published anywhere. Every team page shows `NoGamesWarning` ("The schedule
    for this team is not currently available"). The standings table carries only totals.
  - Measured across all 58 divisions: **91 bracket games**, ~390 unpublished pool games.
  - One team page per division shows that division's whole bracket. The one division split into
    two groups (Boys U12 Silver La Liga, 8 teams) lists all 8 on one page.
  - Bracket names are re-cased ("Sc Hammers Bu8" for "SC Hammers BU8"). All 91 games map back to
    division team ids by case-insensitive, whitespace-normalized name. Seven only matched once
    trailing whitespace/NBSP was stripped.
  - 14 games have no winner/loser class: 8 are level scores (e.g. a 1-1 semifinal whose team
    then appears in the final), 6 are 0-0.
- Pages are slow (~20 s each), and responses declare `charset=utf-8`.

Operator decisions (2026-09-14):

1. Import every bracket game. Pool games are skipped because they are unpublished.
2. **Ages U10–U19 only.**
   - Skip the U8 and U9 divisions (25 teams, 11 bracket games), including the Girls U8/U9 mixed
     division.
   - Keep the U18/19 divisions and file them on the u19 board.
   - Skip Girls "HS Bronze" and "HS Silver" (8 teams, 2 games): each mixes U15–U19 and cannot be
     read reliably.
   - Net: **~261 teams, ~78 bracket games**. Skipped teams are listed, not dropped silently.
3. **Cohort comes from SEG's division, never from the team name.** Names run a season stale:
   "CFYSC 10U Boys Premier" played U11 and is already on PitchRank's u11 board; "Chicago Empire
   u9 Gold 1 Girls" played U10 and PitchRank holds it at u10.
4. **Only import games from the last 14 days** (`--days-back 14` default). All Chicago Cup games
   (Sep 6–7) fall inside it.
5. **A 0-0 bracket game imports as a 0-0 draw.**
6. **Teams:**
   - Link to an existing PitchRank team when it is clearly the same squad (≥0.90).
   - Send 0.75–0.90 and birth-year-conflict matches to the review queue. Do **not** create those.
   - Create a new team (with SEG's state) only below 0.75 or when there is no candidate.
   - Save every link with the SEG team id.
   - Dry run first; write only on an explicit execute.

## Pattern Survey

All paths and line numbers are from `origin/main` (d9d401ba2). Nothing on main handles Soccer
Events Group or 3 Step Sports. The search covered `3stepsports`, `soccereventsgroup`,
`affiliationId`, `programIds` and `details.aspx?TeamID`. SOM Sports and Squadi have no code on
main; they appear only in a comment at `supabase/migrations/20260911120000_seed_affinity_or_provider.sql:9`.

### Analogous Features

- `scripts/discover_sincsports_via_tournament.py:210-269` — **closest match for team
  registration.**
  - Registers a tournament's teams from its roster, not from games: builds
    `SincSportsGameMatcher(discovery_mode=True)` and calls `_match_team(..., state_code=record.state_code)`
    once per team.
  - Skips teams that already have an alias using `bulk_existing_aliases` (:81, batches of 100 IDs).
  - Sorts results into buckets and writes a low-confidence audit CSV.
  - `--dry-run` returns before touching the database (:193-196).
- `scripts/scrape_sincsports_tournament_schedule.py:72-122, 202-220` — **games half of that pair.**
  - Writes one record per team per game using the provider's own team IDs, with no age group.
  - Those games then match through the aliases the roster pass created.
  - `--auto-import` runs `import_games_enhanced.py` as a subprocess.
- `src/scrapers/sincsports_events.py:121-186` — `parse_teamlist` is a pure, no-network roster
  parser. It returns `TeamRecord` (`src/scrapers/sincsports_clubs.py:88`: provider_team_id,
  team_name, club_name, age_group, gender, state_code).
- `src/models/sincsports_matcher.py`:
  - `:549-640` — `_match_team` calls `super()._match_team(..., state_code=)`, auto-creates on a
    miss, and writes the alias here via `self._create_alias`, not in the create helper.
  - `:99-156` — suppresses review-queue writes in discovery mode.
  - `:660-742` — stores the provider-supplied state on the new team.
- `src/models/affinity_or_matcher.py` — the newest auto-create `_match_team` (`:567-615`).
  - `:254-271` `_club_for` infers the club from the team name when the feed has none.
  - `:273-303` `_state_for_new_team`.
  - `:617-682` `_create_new_affinity_or_team`: its `.select().eq().eq().single()` pre-insert
    lookup and the insert are both gated by `dry_run`.
- `src/models/playmetrics_matcher.py:47-58` — the `default_state_code=None` multi-state contract;
  `:385-436` sets state.
- `scripts/scrape_affinity_or_tournament.py` — source of these conventions:
  - `:46-58` every `TOURNAMENTS` entry carries `season_year`.
  - `:62-90` `REQUIRED_COLUMNS` is the CSV schema.
  - `:213-259` `ScrapeFetchError` makes an unreadable page fail loudly instead of looking like an
    empty division.
  - `:369-393` score rules: a blank pair is kept only for future dates; a single score is dropped.
  - `:403` resolves the age group against the event's season.
- `scripts/extract_and_import_tgs_teams.py:285-460` — batch-inserts teams plus `direct_id`
  aliases with no matcher at all (no fuzzy match, no review queue). `:91-216` fills missing
  club/state on existing teams.
- `scripts/import_sincsports_teams.py:134` — **anti-pattern:** builds the matcher without
  `dry_run`, so its dry run still writes.
- `src/tournaments/alias_writer.py` — the roster-intake writers `upsert_team_alias` (`:103`) and
  `enqueue_match_review` (`:269`), called from `src/scrapers/gotsport.py:58`. They protect
  manually curated aliases and clamp the review confidence, but have no `dry_run` option.
- `src/etl/enhanced_pipeline.py:264-273` (`affinity_or` branch) and `:284-298`
  (`playmetrics_tournament`) — how a provider is wired into `_ensure_initialized`.
- `supabase/migrations/20260911120000_seed_affinity_or_provider.sql` — the seed migration:
  `INSERT INTO providers ... ON CONFLICT (code) DO NOTHING`, plus a comment on the missing-provider
  error raised at `enhanced_pipeline.py:149-162`.

### Reusable Utilities

- `src/models/game_matcher.py`:
  - `:796` `GameHistoryMatcher._match_team` — direct id → alias → fuzzy. The birth-year guard
    demotes to review at `:879-908`; review rows are written at `:910-963`.
  - `:1568` `_create_alias` — updates an existing `(provider_id, provider_team_id)` row; gated by
    `dry_run`.
  - `:1633` `_create_review_queue_entry`.
  - `:1116` `_new_team_id_master` — stable ids in a dry run.
  - `:494` `_resolve_state_from_club` — returns a state only when the club's rows are unanimous.
  - `:386` `extract_club_from_team_name`; `:278` `extract_team_variant`.
- `src/utils/team_utils.py`:
  - `:70` `calculate_age_group_from_birth_year(birth_year, current_year)` takes the band's
    **younger** year. Pass the event's season; the default reads the wall clock.
  - `:8` `_soccer_season_year(now)` returns the Aug 1 season for any date.
- `scripts/scrape_tgs_event.py:158` `season_year_of(game_date)`; `:152` `_tracked_age_group`
  (limits to U10–U19 and folds U18 into u19).
- `src/scrapers/_age_normalization.py:20` `normalize_age` (U18 → u19). No existing helper derives a
  cohort from a birthdate.
- `src/utils/us_states.py:16` `STATE_CODE_TO_NAME`; `:83` `state_name_to_code`.
- **No "City, ST" origin parser exists.** The nearest two:
  - `scripts/scrape_playmetrics_tournament.py:77,110` `derive_state_from_address` — requires a ZIP.
  - `scripts/extract_and_import_tgs_teams.py:73` `_resolve_state_code` — private to that script.
- Club and name helpers:
  - `src/utils/placeholder_clubs.py:63` `is_placeholder_club`.
  - `src/utils/club_normalizer.py:601` `normalize_club_name`; `:850` `are_same_club`, which can call
    two clubs the same on canonical id alone (see `affinity_or_matcher.py:90-127`).
  - `src/utils/team_name_utils.py:1069` `resolve_distinction`.
- `src/models/affinity_or_matcher.py` — tighter checks that stop distinct squads merging, all
  private to that module: `:90` `_is_same_club`, `:166` `_tiers_conflict`, `:182`
  `_extract_lane_number`, `:74` `_token_sort_ratio` (standard library only; rapidfuzz is not
  installed).
- `src/etl/enhanced_pipeline.py:355` `_should_accept_for_insert` — accepts a game with valid
  scores, or with both scores blank on a future date.

### Convention Anchors

- **Pipeline wiring:** an `elif self.provider_code.lower() == "<code>"` branch in
  `_ensure_initialized`, passing `dry_run=self.dry_run`.
  `tests/unit/test_provider_matcher_dry_run.py:59-65` finds the branch by splitting the source text
  on `== "<code>"`, so that exact spelling is load-bearing.
- **Hand-written rosters to extend:**
  - `tests/unit/test_provider_matcher_dry_run.py:28-35` `AUTOCREATING_MATCHERS`.
  - `tests/unit/test_provider_matcher_dry_run.py:68-74`, the list of create helpers (`affinity_or`
    was never added here).
  - `tests/unit/test_birth_year_guard_wiring.py:55-62` `_SUBCLASS_PATHS`.
  - `scripts/repair_defective_aliases.py:14-16`, a prose list whose line references have already
    drifted.
  - `CLAUDE.md:322-330`, the Data Providers table (also missing `affinity_or`).
- **Derived guard that applies automatically:** `tests/unit/test_placeholder_clubs.py:106,181`
  fails when a function whose name matches `club…state` or `state…from…club` does not import
  `src.utils.placeholder_clubs`.
- **Test double shape:** `_db_with_no_existing_team` (`test_provider_matcher_dry_run.py:38-42`)
  models only the `.select().eq().eq().single().execute()` pre-insert lookup. A create helper that
  queries any other way gets a truthy mock back and returns early.
- **File layout:**
  - Per-event provider scrapers live in `scripts/` as module-level functions with argparse
    (`scrape_affinity_or_tournament.py`, `scrape_playmetrics_tournament.py`,
    `scrape_tgs_event.py`).
  - `src/scrapers/` holds per-team `BaseScraper` subclasses (`template.py:30`) and reusable parsers.
  - Matchers live in `src/models/<provider>_matcher.py`.
- **Test structure:**
  - `tests/unit/test_scrape_<provider>.py` swaps out the module's `_fetch` with inline HTML
    (`test_scrape_affinity_or.py:156-160`), or loads committed fixtures from
    `tests/fixtures/<provider>/` (`test_sincsports_events.py:22`).
  - Matcher tests use `_FakeQuery`/`_FakeDB` (`test_affinity_or_matcher.py:154-216`).
  - A test checks that every configured event declares its season
    (`test_scrape_affinity_or.py:80-84`).
- **Provider-native team IDs:** TGS, PlayMetrics and SincSports override `_match_by_provider_id` to
  skip the age-group check (`tgs_matcher.py:409`, `playmetrics_matcher.py:75`,
  `sincsports_matcher.py:475`). Hashed IDs are used only when the source has none
  (`scrape_affinity_or_tournament.py:107`).
- **State cannot reach a team through the games CSV:**
  - `match_game_history` never passes `state_code` (`game_matcher.py:639-683`).
  - The CSV loader drops `state_code` and `age_year`; only `age_group`, `state` and `schedule_id`
    survive (`scripts/import_games_enhanced.py:83-108`).
  - So a provider-supplied state must be set during the roster pass. Only SincSports'
    `_match_team` signature accepts `state_code` (`:557`), and the base forwards it only when it is
    not None (`game_matcher.py:860-863`).
- **Review queue:**
  - The database requires `confidence_score >= 0.75 AND < 0.90`
    (`20240201000003_add_match_review_queue.sql:14`).
  - The base matcher inserts the score unclamped (`game_matcher.py:1660`); `alias_writer.py:58,294`
    clamps it.
  - Because the base matcher queues a review row and the subclass then auto-creates anyway, one
    unmatched team ends up with both a review row and a new team. SincSports' discovery mode exists
    to prevent that (`sincsports_matcher.py:124-156`).
- **Same-day rematch dedup:** only `playmetrics_tournament` puts `schedule_id` into the dedup key
  and game ID (`enhanced_pipeline.py:1223-1235, :1261-1264, :574-580`). IMP-213 (open) records
  that every other provider collapses same-pair, same-date games into one. Bracket events are that
  shape, and pages scraped per team show every game twice.
- **Dry run:** the matcher must receive `dry_run` (CLAUDE.md Code Quality). With no scheduled
  workflow, the rollover-freeze coverage test (which scans only workflows) never applies to this
  provider.

### Proposed Alignment

Blend two precedents.

- **Structure — SincSports' two-script pair:** a roster pass that runs each team through the
  matcher's `_match_team` with the provider's state, then a games script that writes native team
  IDs for `import_games_enhanced.py`.
- **Wiring — the Affinity OR PR:** seed migration, pipeline branch with `dry_run`, the three
  hand-written test rosters, the season pinned to the event, loud fetch errors, and fetch-swapping
  scraper tests.
- **Don't copy from Affinity OR:** hashed IDs or default-state stamping. SEG supplies real team IDs
  and a state per team.
- **Decide deliberately** on the review-row-plus-auto-create double write and on same-day rematch
  dedup. Precedents exist for both (`discovery_mode`, the `schedule_id` carve-out), and bracket
  events trigger both.

### How this plan resolves the survey's open items

- **Structure.** One driver script runs the roster pass and then the games, rather than two
  scripts. The games step needs the roster pass's in-memory link results to hold back games that
  touch a team pending review. That is the only way a dry run can preview the games that would
  import.
- **Review-plus-create double write.** Resolved differently from both precedents, because the
  operator ruled that uncertain matches are reviewed, not created:
  - 0.75–0.90 and birth-year conflicts keep the base review row and create nothing.
  - Only low-confidence and no-candidate results are created, and their review rows are
    suppressed.
- **Same-day rematch dedup.** Does not bite. A bracket never pairs the same two teams twice, and
  semifinals and finals fall on different days. Parsing one page per division yields each game
  once, and the script de-duplicates on (division, both team ids, date) as a guard.

## Implementation Steps

0. **Branch and workspace setup**
   - The shared checkout `C:\PitchRank` sits on the unrelated branch
     `codex/matchbalance-intake-infrastructure` with five staged frontend files and many
     untracked files from other sessions. Do not branch in place, stash, or stage any of it.
   - Create a worktree off `origin/main`:
     `git fetch --all --prune` then
     `git worktree add -b soccereventsgroup-provider C:\pitchrank-seg-provider origin/main`.
   - Unset the upstream the worktree inherits from `origin/main`.
   - Verify a clean baseline before editing: `git -C C:\pitchrank-seg-provider status --short`
     must print nothing.
   - Copy this plan file into the worktree's `.turbo/plans/`.
   - DB-touching commands in the worktree run with the main checkout's env:
     `python -m dotenv -f C:\PitchRank\.env run -- python ...`.

1. **Seed the provider row**
   - Add `supabase/migrations/<timestamp>_seed_soccereventsgroup_provider.sql`, mirroring
     `20260911120000_seed_affinity_or_provider.sql`:
     `INSERT INTO providers (code, name, base_url) VALUES ('soccereventsgroup', 'Soccer Events Group', 'https://www.soccereventsgroup.com') ON CONFLICT (code) DO NOTHING;`
   - Include a comment explaining why: `EnhancedETLPipeline._ensure_initialized` raises
     `ValueError("Provider not found")` before any dry-run branch, and the driver needs the id too.
   - Applying the row to the hosted database is an outward-facing write. Ask the operator before
     applying it; it is required before the first dry run.

2. **Extract the squad-separation gates into a shared module (pure move)**
   - Create `src/models/squad_name_gates.py` and move these out of `src/models/affinity_or_matcher.py`
     unchanged, docstrings included: `_token_sort_ratio` (:74), `_is_same_club` (:90),
     `_TIER_TOKENS`, `_TIER_ALIASES`, `_CLUB_AMBIGUOUS_TIERS`, `_extract_tier_tokens`,
     `_tiers_conflict` (:166), `_extract_lane_number` (:182).
   - Drop the leading underscore on the moved names (`token_sort_ratio`, `is_same_club`,
     `extract_tier_tokens`, `tiers_conflict`, `extract_lane_number`, and the constants).
   - In `affinity_or_matcher.py`, re-import them under the existing private names
     (`from src.models.squad_name_gates import is_same_club as _is_same_club`, …) so every
     call site and `tests/unit/test_affinity_or_matcher.py` keep resolving unchanged.
   - Preserve everything else in `affinity_or_matcher.py`: `_normalize_for_affinity_or`,
     `_normalize_club_for_affinity`, the class, and module constants `STATE_CODE`/`STATE_NAME`.
   - Its existing tests are the check that behavior did not move.

3. **Matcher: `src/models/soccereventsgroup_matcher.py`, class `SoccerEventsGroupGameMatcher(GameHistoryMatcher)`**
   - **`__init__(self, supabase, provider_id=None, alias_cache=None, registration_mode=False, dry_run=False)`**
     - Call `super().__init__(..., dry_run=dry_run)`.
     - Keep base thresholds (auto-approve 0.90, review 0.75), per CLAUDE.md Team Matching.
     - Store `registration_mode`.
   - **`_fuzzy_match_team(self, team_name, age_group, gender, club_name=None, state_code=None)`**
     - Mirror the gated loop of `AffinityORGameMatcher._fuzzy_match_team`
       (`affinity_or_matcher.py:393-541`), with these SEG differences:
     - Return `None` when `state_code` is None. Only the roster pass supplies state, so the
       game-import path never fuzzy-matches and relies on the aliases the roster pass wrote.
     - Candidate query: `teams` filtered by `age_group`, `gender`, and state
       (`state_code = <SEG state>` or `state_code IS NULL`, so a stateless existing row is not
       missed and duplicated), paginated with `.range()`.
     - Provider club: `extract_club_from_team_name` on the normalized name.
     - Name normalization: base `_normalize_team_name` plus stripping U-age tokens (`U14`, `GU14`,
       `U14G`, `14U`, `14uG`). Do **not** reuse `_normalize_for_affinity_or`: its `14B→2014`
       rewrite reads a token as a birth year, the Oregon trap.
     - Gates, in order: club (`is_same_club`, threshold from
       `MATCHING_CONFIG["affinity_club_similarity_threshold"]`), variant (`extract_team_variant`),
       tier, lane (`extract_lane_number`).
     - Tier tokens: `extract_tier_tokens(name)` plus the SEG-local tokens `pre` (Pre-ECNL, Pre-GA)
       and `aspire` (GA Aspire). Chicago names carry both, and without them "Chicago FC United U14
       GA Aspire" reads as the same tier as "… U14 GA", and "FC Pride U11 Pre-ECNL" as ECNL.
       Apply `tiers_conflict` to the widened sets. Do not add the tokens to the shared module;
       that would change Oregon.
     - Keep the ECNL/RL score adjustment and deterministic tie-break from the Oregon loop.
     - Every returned candidate dict must carry `team_name`; the birth-year guard reads it
       (`tests/unit/test_birth_year_guard_wiring.py`).
   - **`_calculate_match_score`** — mirror the Oregon club+variant boost
     (`affinity_or_matcher.py:546-554`) using `is_same_club`.
   - **`_create_review_queue_entry`** (explicit signature, as in `sincsports_matcher.py:122-146`)
     - In `registration_mode`, suppress rows whose `match_details["match_method"]` is
       `"fuzzy_low_confidence"` or `"no_match"`; those teams are about to be created.
     - Always let `"fuzzy"` rows (0.75–0.90 or birth-year conflict) through to `super()`.
   - **`_match_team(self, provider_id, provider_team_id, team_name, age_group, gender, club_name=None, state_code=None)`**
     1. Call `super()._match_team(..., state_code=state_code)`. The base forwards `state_code` to
        `_fuzzy_match_team` only when it is non-None (`game_matcher.py:860-863`).
     2. Matched → return it, with `created: False`.
     3. `method == "fuzzy_review"` → return unmatched with `review: True`. The base already wrote
        the review row; create nothing.
     4. Otherwise, if `registration_mode`, `state_code`, `team_name`, `age_group` and `gender` are
        all present → call `_create_new_soccereventsgroup_team(...)`, then
        `self._create_alias(match_method="direct_id", confidence=1.0, review_status="approved")`.
        The alias is written in `_match_team`, not in the create helper, following
        `sincsports_matcher.py:590-617`. Return `matched: True, method: "direct_id", created: <bool>`.
     5. Not in `registration_mode` → return the base result unchanged. The pipeline never creates
        SEG teams; the roster pass is the only creator.
   - **`_create_new_soccereventsgroup_team(self, team_name, club_name, age_group, gender, provider_id, provider_team_id, state_code) -> Tuple[str, bool]`**
     - Mirror `_create_new_affinity_or_team` (`affinity_or_matcher.py:617-682`).
     - Pre-insert lookup: exactly `.select("team_id_master").eq("provider_id", …).eq("provider_team_id", …).single().execute()`.
       That is the shape `_db_with_no_existing_team` models.
     - `team_id_master` via `_new_team_id_master`.
     - Clean `team_name` of a club prefix; `club_name` inferred from the name.
     - Normalized `age_group` and `gender`.
     - `state_code` from SEG, and `state` from `STATE_CODE_TO_NAME`.
     - `provider_id`, `provider_team_id` = SEG `teamId` as a string.
     - `distinction` via `resolve_distinction(clean_team_name, club_name, state_code)`.
     - Insert only when `not self.dry_run`.
     - Do not set `state_source`: no provider matcher does, and inventing a value is out of scope.
   - **Naming:** no method or function name matching `club…state` / `state…from…club`, or
     `tests/unit/test_placeholder_clubs.py` requires a placeholder-club import.

4. **Wire the pipeline**
   - In `src/etl/enhanced_pipeline.py` `_ensure_initialized`, add an
     `elif self.provider_code.lower() == "soccereventsgroup":` branch beside the `affinity_or`
     branch (`:264-273`).
   - It constructs `SoccerEventsGroupGameMatcher(self.supabase, provider_id=self.provider_id, alias_cache=self.alias_cache, dry_run=self.dry_run)`,
     with `registration_mode` left False, and logs which matcher is in use.

5. **Driver: `scripts/import_soccereventsgroup_event.py`**
   - Module-level functions plus argparse, following `scripts/scrape_affinity_or_tournament.py`.
   - **CLI**
     - `--program-id` (required int).
     - `--days-back` (default 14).
     - `--output-dir` (default `data/raw/soccereventsgroup/`; confirm it is git-ignored).
     - `--delay-min` / `--delay-max` (random sleep between page fetches).
     - `--execute` (default is a dry run).
   - **HTTP**
     - A `requests.Session` with urllib3 `Retry(total=2, backoff_factor=1, status_forcelist=[500,502,503,504])`
       (no 429) and the browser `HEADERS`.
     - `timeout=90` (pages take ~20 s).
     - Sequential fetches with `random.uniform(delay_min, delay_max)` between them.
     - Set `response.encoding = "utf-8"` when the content type carries no charset.
     - A non-200 or unparseable response raises `ScrapeFetchError`, so a failed page never passes
       for an empty division.
   - **`fetch_program(program_id)` / `fetch_team_list(program_id)`** — the two JSON endpoints.
     `affiliationId` comes from `program.affiliationId`, never a constant.
   - **`event_season(program)`** — `_soccer_season_year` applied to `program.start`. The event, not
     the wall clock, decides the cohort.
   - **`division_cohort(division, season) -> Optional[str]`**
     1. Read every U-number in `sessionName`.
     2. Return `None` (skip the division) when there is none (`HS`), or when they collapse to more
        than one cohort after folding U18 into u19 (`U8/U9`). `U18/19` collapses to `u19` and is
        kept.
     3. Take the younger year = `oldestEligibleBirthdate` year + 1, and compute
        `calculate_age_group_from_birth_year(younger_year, season)`.
     4. Return `None` when it disagrees with the label's cohort; the provider changed convention.
     5. Return `None` outside u10–u19.
     6. Return the lowercase age group.
   - **`parse_origin_state(team)`** — prefer `team["state"]`; fall back to the `", ST"` suffix of
     `origin`. Accept only a code in `STATE_CODE_TO_NAME`, otherwise `None`.
   - **`build_roster(program, team_list) -> (in_scope: List[TeamRow], skipped: List[TeamRow])`**
     - `TeamRow` fields: `seg_team_id` (str), `team_name` (whitespace/NBSP-collapsed),
       `division_id`, `division_name`, `age_group`, `gender` ("Male"/"Female" from the division's
       bool), `state_code`.
     - Every team in a skipped division goes to `skipped`, together with the reason.
   - **`register_teams(matcher, provider_id, roster) -> Dict[str, Outcome]`**
     - Skip teams already aliased via a 100-id `.in_()` pre-check, as in
       `discover_sincsports_via_tournament.py:81`; those are `already_linked`.
     - Call `matcher._match_team(..., state_code=row.state_code)` for the rest.
     - Classify each into `linked_existing` (fuzzy_auto, with the matched team's name and
       confidence), `created`, `review` or `error`.
   - **`parse_bracket_games(html) -> List[BracketGame]`**
     - Parse with BeautifulSoup; each `table.game` becomes two sides of (name, score, winner flag).
     - Take the title from the top row and "M/D H:MMA/P, Field X" from the bottom row.
     - Scores must be digits on both sides, otherwise drop the game.
     - A game with no winner/loser class is still a game. Level scores import as a draw, including
       0-0 (operator decision 5).
   - **`resolve_game_date(md, program)`** — month/day take the year from `program.start`. If that
     date falls before the program start (an event spanning New Year), use the next year.
   - **`collect_games(session, in_scope_divisions, roster, days_back, today)`**
     - Fetch one team page per in-scope division (first team) and parse the bracket.
     - Map each side to a SEG team id by normalized case-insensitive name within that division. A
       name that does not map is recorded as `unmapped` and its game skipped.
     - Keep games dated in `[today - days_back, today]`.
     - De-duplicate on (division_id, sorted team ids, date).
   - **`build_csv_rows(games, outcomes, program)`**
     - A game joins the CSV only when both teams' outcomes are linked (`already_linked`,
       `linked_existing` or `created`). Games touching a `review` or `error` team are held back.
     - Write two rows per game (home = top bracket row, away = bottom) using `REQUIRED_COLUMNS`
       from the Oregon scraper.
     - Values: `provider = "soccereventsgroup"`; `event_id = program id`;
       `event_name = "<program name> - <division name>"`;
       `schedule_id = "<division_id>-<title>-<date>"`; `age_group`; gender `"Boys"`/`"Girls"`;
       `team_id`/`opponent_id` = SEG ids; `state_code`/`state` per team.
     - `result` via the Oregon `_compute_result` convention; `venue` = the field text;
       `game_time`; `source_url`; `scraped_at`.
   - **`main`** runs in order:
     1. Fetch the program and team list.
     2. Build the roster, then print skipped divisions and teams.
     3. Construct `SoccerEventsGroupGameMatcher(registration_mode=True, dry_run=not args.execute)`
        with the provider id looked up from `providers.code`. Fail with a clear message when absent.
     4. Register teams.
     5. Collect games.
     6. Write the games CSV plus a report CSV (one row per roster team: outcome, matched PitchRank
        team name and confidence) into `--output-dir`.
     7. Print the summary (see Verification).
     8. Only with `--execute`, run `scripts/import_games_enhanced.py <csv> soccereventsgroup` as a
        subprocess, as in `scrape_sincsports_tournament_schedule.py:202-220`. In a dry run, print
        that command instead.
     - The dry run runs the importer on nothing: its aliases are not written, so the import would
       only report unmatched teams and mislead.

6. **Guard rosters and docs**
   - `tests/unit/test_provider_matcher_dry_run.py`:
     - Add `("soccereventsgroup", SoccerEventsGroupGameMatcher)` to `AUTOCREATING_MATCHERS`.
     - Add `("soccereventsgroup", SoccerEventsGroupGameMatcher, "_create_new_soccereventsgroup_team")`
       to the create-helper parametrization, with the kwargs the helper takes.
   - `tests/unit/test_birth_year_guard_wiring.py`: add
     `("src.models.soccereventsgroup_matcher", "SoccerEventsGroupGameMatcher")` to `_SUBCLASS_PATHS`.
   - `scripts/repair_defective_aliases.py:14-16`: add the new matcher to the prose list of
     auto-creating matchers.
   - `CLAUDE.md` Data Providers table: add a row —
     `Soccer Events Group | soccereventsgroup | JSON team list + bracket HTML | Tournament brackets (manual, per event)`.

7. **Tests**
   - **Fixtures** in `tests/fixtures/soccereventsgroup/`, trimmed from the live captures:
     - `program.json`: `description` and marketing HTML removed; keep the divisions U8, U8/U9,
       U10, U11 Platinum, U18/19 Gold, HS Bronze.
     - `team_list.json`: the matching divisions, including a name with a trailing NBSP.
     - `team_page_bracket.html`: the U11 Platinum bracket — a 1-1 semifinal with no winner class,
       a 5-1 championship with winner/loser.
     - `team_page_zero_zero.html`: a 0-0 championship.
   - **`tests/unit/test_import_soccereventsgroup_event.py`** — assert literal expected values,
     never module constants (CLAUDE.md Verification):
     - `division_cohort`: U10 → `"u10"`; U18/19 → `"u19"`; U8, U8/U9 and HS → `None`.
     - `division_cohort`, event-pinned: season 2026 derived from a 2026-09-04 start gives the same
       answer when the clock is patched to 2027-08-15.
     - A label/cutoff disagreement returns `None`.
     - `parse_origin_state`: `"Chicago, IL"` → `"IL"`; a non-US or garbage origin → `None`.
     - `build_roster`: skipped teams carry reasons; a trailing NBSP is collapsed.
     - `parse_bracket_games`: exact games with scores; 1-1 kept; 0-0 kept; a non-digit score dropped.
     - Name mapping: re-cased and trailing-whitespace names resolve to the literal SEG id.
     - Date window, one test per bound: day `today-14` included, `today-15` excluded.
     - `resolve_game_date`: 9/6 with a 2026-09-04 start → `2026-09-06`; a New-Year span rolls
       forward.
     - `build_csv_rows`: a game touching a `review` team is held back while its neighbour imports;
       a 0-0 row has `goals_for=0, goals_against=0` and the draw result code.
     - A fetch error raises `ScrapeFetchError` rather than returning no games.
   - **`tests/unit/test_soccereventsgroup_matcher.py`** — use a `_FakeDB` whose query double
     records at `.execute()`, per CLAUDE.md:
     - (a) 0.80 confidence: no team insert, one review row, `review: True`.
     - (b) Birth-year conflict at 0.95: review row, no alias, no insert.
     - (c) No candidates, registration mode: one team insert carrying the SEG `state_code` and
       `state`, one `direct_id` alias with the SEG id, and zero review rows.
     - (d) Same as (c) outside registration mode: no insert, no alias.
     - (e) `state_code=None`: `_fuzzy_match_team` returns `None` and issues no candidate query.
     - (f) Tier gates, one test per token so each half can be mutated alone: "… U14 GA Aspire" vs
       "… U14 GA"; "… Pre-ECNL" vs "… ECNL"; "… ECNL RL" vs "… ECNL". Each rejects.
     - (g) Same club, same variant, same tier: auto-links ≥0.90 and writes a `fuzzy_auto` alias.
     - (h) Dry run: the create path writes nothing and still returns a stable `team_id_master`.
   - Existing `tests/unit/test_affinity_or_matcher.py` must pass untouched after step 2.

## Verification

- **CI-equivalent gate, from the worktree:**
  - `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
  - `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`
  - Expected: green, including the three extended rosters and the untouched Oregon matcher tests.
- **Mutation checks on the new guards** (CLAUDE.md), each on a scratch copy of the module, then
  restore and clear stale `.pyc`. The listed test must fail each time:
  - Delete the `registration_mode` check in `_match_team` step 4 → (d).
  - Let `"fuzzy"` rows be suppressed → (a).
  - Remove `pre` → Pre-ECNL test; remove `aspire` → Aspire test.
  - Drop the U18→u19 fold → U18/19 test.
  - Drop the multi-cohort rejection → U8/U9 test.
  - Change `days_back` inclusion to `>` → lower-bound test.
- **Provider row** — after the operator approves applying step 1's migration,
  `select code from providers where code='soccereventsgroup'` returns one row.
- **Dry run against the live event** — `python -m dotenv -f C:\PitchRank\.env run -- python scripts/import_soccereventsgroup_event.py --program-id 19206`.
  - The summary must show: 294 teams fetched; 33 skipped (U8/U9: 25, HS: 8) and listed with
    reasons; 261 in scope split into already-linked / linked-existing / created / review / error.
  - Games: 78 bracket games in the window, 0 unmapped names, and a held-back count equal to the
    games touching review teams.
  - Read the report CSV row by row, not just the summary:
    - Every `linked_existing` pair must be the same squad: same club, same tier (GA vs GA Aspire,
      ECNL vs ECNL RL vs Pre-ECNL), same colour/lane.
    - Every `created` team must truly be absent from PitchRank. Spot-check a sample with
      `mcp__supabase__execute_sql` by club and age.
    - A surprising rate (e.g. >40% created when most Chicago clubs are already on GotSport) is a
      finding to investigate before executing.
    - Named pair supplied by the operator: SEG team `590399` "AFC Union U15G N1" (Girls U15 Gold,
      WI) must be `linked_existing` to `5b6b37ce-031b-4e77-83eb-9a5b4e667c2f` ("AFC Union U15N1",
      u15, WI). The glued `U15N1` token is a normalization edge case. If this pair lands in
      `review` or `created`, fix the name normalization before executing, and add the pair as a
      matcher unit test.
  - Confirm the teams table is untouched:
    `select count(*) from team_alias_map where provider_id = <seg provider uuid>` is 0.
- **Execute** only after the operator OKs the dry-run report: rerun with `--execute`.
- **Post-execute cross-checks, by independent query:**
  - Alias count for the provider equals linked + created.
  - `teams` rows with `provider_id = <seg uuid>` equals `created`.
  - `games` rows for the provider equal the imported bracket games, every one dated 2026-09-06 or
    2026-09-07.
  - The five 0-0 games are stored as 0-0.
  - Review-queue rows with `provider_id = 'soccereventsgroup'` equal the `review` count.
- **Idempotency** — a second `--execute` run reports every team `already_linked` and the importer
  inserts 0 new games.

## Context Files

- `src/models/affinity_or_matcher.py` — the gated fuzzy loop, create helper and gate helpers to
  extract; the closest matcher to mirror.
- `src/models/game_matcher.py:796-970, 1116-1140, 1568-1680` — base `_match_team` result shapes,
  `_new_team_id_master`, `_create_alias`, `_create_review_queue_entry` (deduped on pending
  provider_team_id).
- `src/models/sincsports_matcher.py:99-156, 549-645` — review suppression and alias-in-`_match_team`
  pattern.
- `scripts/discover_sincsports_via_tournament.py` — roster-pass driver shape and buckets.
- `scripts/scrape_affinity_or_tournament.py` — CSV schema, `ScrapeFetchError`, result codes,
  event-pinned season.
- `scripts/import_games_enhanced.py:70-140` — which CSV columns survive into the pipeline.
- `src/etl/enhanced_pipeline.py:140-165, 255-300, 305-380` — provider lookup, matcher wiring, score
  acceptance.
- `tests/unit/test_provider_matcher_dry_run.py`, `tests/unit/test_birth_year_guard_wiring.py`,
  `tests/unit/test_affinity_or_matcher.py`, `tests/unit/test_scrape_affinity_or.py` — guard rosters
  and test doubles to extend and mirror.
- `supabase/migrations/20260911120000_seed_affinity_or_provider.sql` — seed migration template.
