---
status: done
---

# Plan: Tourney Central Tournament Scraper and Importer

## Context

Tourney Central (`*.tourneycentral.com`, run by Rivershark Inc.) hosts 52 youth tournaments,
mostly in Ohio and Michigan, one subdomain each, all on the same CGI layout. PitchRank does not
scrape it today. The user wants an operator-run command that takes a tournament's address and
imports that tournament: its teams are linked or created, and its scored games are imported.
The first target is the Warrior Fall Classic (`https://wfc.tourneycentral.com`, 2026-10-10/11):
106 teams and 183 scored games across 21 divisions, of which 85 teams and 146 games are outside
the U9 divisions.

The approved spec is `.turbo/specs/tourney-central-scraper.md` and is the source of truth for
product decisions:
- run per tournament, with no schedule
- mirror Athletes2Events
- age from the team's own name
- skip U9 and below and small-sided play
- import cross-age games and also list them
- keep same-day rematches apart through `REMATCH_PROVIDERS`

Each page is one GET with a browser User-Agent: no proxy, no bot challenge, no ZenRows cost.

## Pattern Survey

All anchors are `origin/main` @ b87a01a71, read with `git show`.

### Analogous Features
- **`scripts/import_athletes2events_event.py:1-1147`** is the closest driver.
  - Flow:
    1. `collect_event` (:1000-1037)
    2. `build_roster` (:646-688)
    3. `existing_aliases` (:691)
    4. a dry-run preview of `register_teams` (:709)
    5. `shared_links` conflicts (:789)
    6. on `--execute`, a second `register_teams`, then `unsaved_links` (:746) and `unsaved_reviews` (:776)
    7. `off_board_links` (:811)
    8. `build_csv_rows` (:861-943)
    9. three CSVs, written by `main` (:1040-1143)
  - The importer runs only under `--execute`, as `subprocess.run([sys.executable,
    "scripts/import_games_enhanced.py", csv, PROVIDER_CODE])` (:1142-1143). A dry run returns at
    :1136-1138. Because of that, `import_games_enhanced.py`'s column whitelists apply.
    `schedule_id` is whitelisted at :109 and :182.
  - Cross-age games are **imported and also listed** (`build_csv_rows` docstring :864-872;
    `tests/unit/test_import_athletes2events_event.py:410`).
- **`src/models/athletes2events_matcher.py`** is the matcher contract.
  - Module and constructor:
    - `_presplit` :64-70, and `_squad_marks` :73-83, which binds `tier_extra=TOURNAMENT_TIER_TOKENS`.
    - `__init__` :94-111 takes `registration_mode` and `dry_run`.
  - Overrides:
    - `_create_review_queue_entry` :113-136 clamps to `REVIEW_QUEUE_CLAMP`.
    - `_match_by_provider_id` :141-158 does no age or gender re-check.
    - `_without_club` :160-171 strips both the written and the stored club.
    - `_fetch_candidates` :173-193 pages by 1000, ordered by `team_id_master`, same state or null.
    - `_fuzzy_match_team` :195-274 returns None when there is no state.
    - `_calculate_match_score` :276-281 is never clamped.
  - `_match_team` :283-345 calls `super()._match_team`, then `_create_new_athletes2events_team`
    **by name** (:316), then writes the alias (`direct_id`, 1.0, `approved`) at :326-336.
  - `_create_new_athletes2events_team` :347-394:
    - The pre-check `.single()` swallows PGRST116.
    - **The club prefix is stripped at :376-378.**
    - The `dry_run` gate is at :392-393.
    - It returns `(id, was_created)`.
- **`src/models/yssl_matcher.py:111-195`**: `YSSLGameMatcher(Athletes2EventsGameMatcher)` reuses
  that matcher whole. It overrides `_create_new_athletes2events_team` under the inherited name to
  keep the full team name (:155-195, docstring :20-23).
- **`scripts/import_yssl.py`** is the newest copy of the driver shape. It re-defines the
  registration helpers locally (:580-842) rather than importing them, and
  `schedule_id=f"yssl-{game_no}"` (:806).
- **`scripts/import_soccereventsgroup_event.py`**: `parse_origin_state` (:299-305) parses
  `City, ST`, and event and board seasons are kept separate (:240-280).
- **`src/etl/enhanced_pipeline.py:309-339`**: the `athletes2events` and `yssl` branches. The
  `else` fallback (:366-368) builds `GameHistoryMatcher` **without `dry_run`**.

### Reusable Utilities
- Import packaged from `scripts.import_athletes2events_event`, which is provider-agnostic:
  - `respell_ages` :541
  - `age_from_name(team_name, division_birth_year, event_season)` :552-610. Its bound is a
    **birth year**, and on `NO_AGE_IN_NAME` / `ODD_YEAR_SPAN` (:537-538) it returns the bound itself.
  - `board_cohort` :613-622
  - `split_club(team_name, host)` :625-640. Only `HOST_CLUBS` is A2E-specific; an unknown host
    falls through to the generic split.
  - Precedent for importing these packaged: `scripts/discover_sincsports_via_tournament.py:50-56`.
- `src/tournaments/alias_writer.py:58` `REVIEW_QUEUE_CLAMP`
- `src/utils/provider_ids.py:16-23` `clean_provider_id`
- `src/utils/us_states.py:16` `STATE_CODE_TO_NAME` (50 states plus DC)
- `src/utils/team_utils.py:8` `_soccer_season_year`
- **Not reusable:** A2E's `_get` (:340-349) forces UTF-8 when the HTTP header has no
  charset. Tourney Central sends a bare `text/html` and declares ISO-8859-1 only in `<meta>`.

### Convention Anchors
- **Provider seed:** a header comment plus `INSERT INTO providers (code, name, base_url) VALUES
  (...) ON CONFLICT (code) DO NOTHING;`. See `supabase/migrations/20260919120000_seed_athletes2events_provider.sql`.
  The newest migration on origin/main is `20261012120000_server_side_team_search.sql`.
- **Hand-written registries.** In `tests/unit/test_provider_matcher_dry_run.py`:
  - `AUTOCREATING_MATCHERS` :32-43, plus imports :20-30
  - the `(provider, cls, create)` parametrize :85-96
  - `REGISTRATION_MATCHERS` :151

  In `tests/unit/test_birth_year_guard_wiring.py`: `_SUBCLASS_PATHS` :55-66.

  The pipeline tests (:67-82) split `_ensure_initialized`'s source on `== "<code>"` and then on
  `elif`. The branch must therefore contain `dry_run=self.dry_run` and `self.matcher = <Cls>(`,
  and no comment in it may contain the word "elif".
- **`REMATCH_PROVIDERS`** (`src/models/game_matcher.py:462`) is covered by parametrization derived
  from the set (`tests/unit/test_rematch_game_uid.py:38,46`). Joining it also disables
  fixture-score fills for the provider (`enhanced_pipeline.py:1600-1608`). That is harmless here,
  because only scored games are imported.
- **Driver test conventions** (`tests/unit/test_import_athletes2events_event.py`):
  - `FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "<provider>"` (:20-26)
  - `_PageFetcher` (:38-56)
  - the `run_main` fixture monkeypatches the client, the session, the matcher, the DB helpers,
    `_soccer_season_year`, `date` and `subprocess.run` (:573-636)
  - `_Response` decodes raw bytes by the declared charset (:771-783)
- **Matcher test double:** `tests/unit/test_athletes2events_matcher.py:22-140`. It records at
  `execute()`, raises `APIError(PGRST116)` on a zero-row `.single()`, and enforces the
  review-queue CHECK.
- **Doc registries:**
  - `CLAUDE.md` provider table
  - the per-provider sections of `.claude/skills/scraper-patterns/SKILL.md`
  - `tests/unit/test_agent_doc_references.py` fails when a doc names an untracked path or an
    unregistered flag

### Proposed Alignment
Follow the Athletes2Events pattern end to end. Subclass the A2E matcher as YSSL does. Copy the
driver's registration and CSV helpers per provider, as YSSL did. Import only the provider-agnostic
age and club helpers, packaged. Write a fetch helper of its own that reads the `<meta>` charset.

## Implementation Steps

1. **Set up an isolated branch off `origin/main`.**
   - The shared checkout `C:\PitchRank` is on the unrelated branch `fix/fixture-score-fill`,
     about 80 commits behind `origin/main`. It also holds unstaged edits from other work:
     `.claude/skills/merging-duplicate-teams/*`, `.claude/skills/supabase-pitchrank/SKILL.md`,
     `.turbo/improvements.md` and `scripts/view_teams.py`. Do not branch in place, and do not
     stash or touch those files.
   - Run `git fetch --all --prune`, then
     `git worktree add -b feat/tourney-central-scraper C:\pitchrank-tourney-central origin/main`.
     In the worktree, run `git branch --unset-upstream`.
   - Copy the untracked spec `C:\PitchRank\.turbo\specs\tourney-central-scraper.md` into the
     worktree at the same path. It ships with this branch.
   - Confirm `git status --short` in the worktree shows only that spec.
   - Run everything that touches the database from the worktree as
     `python -m dotenv -f C:\PitchRank\.env run -- python <script>`. A worktree has no `.env`.

2. **Seed the provider row.**
   - Create `supabase/migrations/20261014120000_seed_tourneycentral_provider.sql`. Before naming
     it, check that no newer migration has landed on `origin/main`; if one has, use a later
     timestamp.
   - It inserts `('tourneycentral', 'Tourney Central', 'https://tourneycentral.com')` with
     `ON CONFLICT (code) DO NOTHING`.
   - Its header comment says one row covers every subdomain, because team ids are one
     platform-wide sequence (no collision among 444 ids from four tournaments).
   - It is hand-applied: the owner runs the SQL in the dashboard, then
     `supabase migration repair --status applied 20261014120000` from the worktree, after copying
     `C:\PitchRank\supabase\.temp` into it.

3. **Add `TourneyCentralGameMatcher` in `src/models/tourneycentral_matcher.py`.**
   - Subclass `Athletes2EventsGameMatcher`, as `src/models/yssl_matcher.py:111` does. The club,
     squad and tier gates, state scoping, the review clamp, the alias write in `_match_team`
     (:326-336) and the `registration_mode`/`dry_run` constructor are all inherited unchanged.
   - Override `_create_new_athletes2events_team` under that inherited name, because
     `_match_team` calls it by name at :316. Copy A2E :347-394, but drop the club-prefix strip at
     :376-378, so a created team keeps its name as written (`Club Ohio Dayton U11B Green`).
   - Keep the PGRST116-swallowing pre-check and the `if not self.dry_run:` insert gate. The
     columns written are those of A2E :380-391: `team_id_master`, `team_name`, `club_name`,
     `age_group`, `gender`, `state_code`, `state`, `provider_id`, `provider_team_id` and
     `distinction` (`resolve_distinction`).
   - Write a module docstring explaining why it subclasses, and the two things that differ.
   - Override `_fuzzy_match_team` to gate on the club field and, when that matches none, on the written
     club (added in review: `VASC B12/13`, club field `Valentis`, was about to duplicate a
     stored `VASC B12/13`).

4. **Add the pipeline branch in `src/etl/enhanced_pipeline.py`.**
   - After the `yssl` branch (:330-339), add `elif self.provider_code.lower() == "tourneycentral":`.
     It lazy-imports `TourneyCentralGameMatcher`, logs, and builds it with `self.supabase`,
     `provider_id=self.provider_id`, `alias_cache=self.alias_cache` and `dry_run=self.dry_run`.
   - Pass no `registration_mode`: only the driver's roster pass creates teams.
   - Comments in the branch must not contain the word "elif".

5. **Join `REMATCH_PROVIDERS`.**
   - In `src/models/game_matcher.py:462`, add `"tourneycentral"`. WFC's 7 same-day pool/final
     rematches otherwise collapse into one game each.
   - Update the comment above the set if it names its members.

6. **Write the driver `scripts/import_tourneycentral_event.py`.**
   - **Header.** The layout of `import_athletes2events_event.py`: a module docstring describing
     the site, its pages and the run, with a Usage line; then `sys.path.append` and the `# noqa:
     E402` imports; the `.env.local`-else-`.env` load; `PROVIDER_CODE = "tourneycentral"`; and
     `OUTPUT_DIR = Path("data/raw/tourneycentral")`.
   - **Imports, packaged:** `from scripts.import_athletes2events_event import _BAND,
     _LEADING_AGE, NO_AGE_IN_NAME, ODD_YEAR_SPAN, age_from_name, board_cohort, respell_ages,
     split_club`. Everything else is
     copied locally, as `import_yssl.py` does.
   - **Constants and dataclasses.**
     - Copy `REQUIRED_COLUMNS`, `CROSS_AGE_COLUMNS`, `HEADERS`, `SCRAPE_TS`, `SCRAPE_RUN_ID`
       and `LINKED_OUTCOMES` from A2E :95-173.
     - `REPORT_COLUMNS` matches A2E's with its first column renamed `tc_team_id`.
     - `Event(host, subdomain, name, start, end)`, with a `season` property as in A2E :257-268.
     - `Division(code, gender, young_age, old_age, players)`, where `players` is the
       format's side size, or None.
     - `TeamRow`, as A2E :280-294 with `tc_team_id`.
     - `Outcome`, unchanged.
     - `EventGame(division_code, game_no, game_date, game_time, venue, home_id, home_score,
       away_id, away_score, source_url)`.
   - **Network.**
     - `ScrapeFetchError`.
     - `make_session()` mounts A2E's retry adapter (`Retry(total=2, backoff_factor=1,
       status_forcelist=[500, 502, 503, 504])`) with `HEADERS`, so a connection error or 5xx is
       retried twice and anything else is not.
     - `_fetch(session, url) -> str`:
       - GET with timeout 90. A request error or any non-200 raises `ScrapeFetchError`.
       - Decode `response.content`, never `.text`, through `_encoding`. That is the header's
         charset as `requests` parsed it; else the `<meta ... charset=...>` in the first 2 KB of
         bytes; else UTF-8. A declared ISO-8859-1 or ASCII is read as windows-1252, as browsers
         read it, and a label that is no text encoding falls back to UTF-8.
     - A GET is used for every page. Measured 2026-10-14: the GET and POST forms return the same
       7 games and the same 4 teams.
   - **URL builders.**
     - `parse_event_url(url) -> (host, subdomain)` uses an anchored
       `^https?://(([a-z0-9][a-z0-9-]*)\.tourneycentral\.com)(?:/\S*)?$` with
       `re.IGNORECASE | re.ASCII`
       and raises `ValueError` otherwise.
     - `games_page_url(host)` gives `https://<host>/games.html`.
     - `team_list_url(host, code)` gives `https://<host>/cgi-bin/teams.cgi?fnc=adiv&t_div=<code>`.
     - `schedule_url(host, code)` gives `https://<host>/cgi-bin/teams.cgi?fnc=sked&sny=Y&t_div=<code>`.
     - URL-encode the code.
   - **Parsers, BeautifulSoup.**
     - `parse_games_page(html, host, subdomain) -> (Event, List[str])`:
       - The event name is the `<title>`.
       - The play dates are the `<option value="YYYY-MM-DD">` values, and `start`/`end` are
         their min and max. When there are none, raise `ScrapeFetchError("no play dates")`.
       - The division codes are the non-empty options of the first `select[name=t_div]`. When
         there are none, raise `ScrapeFetchError("no divisions")`.
     - `parse_division_code(code) -> Optional[Division]`:
       - Regex `^([BG])(\d{2})(?:-(\d{2}))?\s*(?:(\d{1,2})\s*v\s*\d{1,2})?(?:\D.*)?$`, ASCII-bound.
         This maps `B11Gold`, `B107v7Gold`→(10, 7v7), `B129v9Red`→(12, 9v9) and
         `B14-15Gold`→(14, 15). The tail may not start with a digit, so `B2015Gold` is refused.
       - It returns None for anything else; the caller reports that as a problem.
     - `skip_division(division) -> Optional[str]` gives `"U9 and below: no board"` when
       `old_age <= 9` (so a combined U9-10 division is kept), `"small-sided"` when `players` is 6
       or fewer, else None.
     - `parse_team_list(html, division, source_url) -> (List[TeamListing], List[str])`:
       - A page without the "Team/Location" header raises `ScrapeFetchError`.
       - One `TeamListing(tc_team_id, team_name, club, location, coach)` per row carrying an
         `input[name=t]`.
       - The name is the cell's `<b>`, the club its `<i>`, and the location the cell's remaining
         text after both, ignoring any `[ + ]` website link. The coach is the next cell.
       - The id is read through `clean_provider_id` and must match `[1-9][0-9]{0,9}`; a row that
         fails is a problem, not a team.
     - `parse_schedule(html, division, source_url) -> Tuple[List[EventGame], List[str]]`:
       - Walk the rows. A row whose single wide cell holds a bold date (`Saturday, Oct 10, 2026`)
         sets the current date.
       - A row with at least nine cells whose `No.` cell is all digits is a game, and gives:
         - `No.` (column 1) as `game_no`, plus the time and the field
         - the two `fnc=sked&t=(\d+)` links as home and away ids
         - the two centre score cells
       - A row missing either team link, or a score that is not a digit, is counted as a
         problem, not raised. Game numbers must match `[0-9]{1,5}` and link ids
         `[1-9][0-9]{0,9}`.
       - A page without the `No.` header raises `ScrapeFetchError`: a 200 maintenance page must
         not read as a division with no games.
   - **Roster helpers.**
     - `state_from_location(location) -> Optional[str]`: the two-letter uppercase tokens after
       commas, filtered to `STATE_CODE_TO_NAME`; exactly one distinct code, else None.
     - `club_for(club_cell, team_name, host) -> (club, written)`: the club is the italic cell
       unless it is blank or starts with `tournament only` (case-insensitive), in which case it
       is the name's own club. `written` is the prefix the club field matches when the field
       opens the name; otherwise `split_club(respell_ages(name), host)[1]`, cut at the first
       bare band (`13/14`) and then cut back before its first squad mark
       (`club_before_squad_marks`), since words before the age can still be marks (`Lakota FC
       Pre-ECNL`, `Ohio Premier North`). A club-field prefix stays whole: cutting it took the
       club's own words (`Elite FC`, `Dayton Futbol Academy`) and duplicated two WFC teams.
     - `label_season_mismatch(listings, event_season) -> Optional[str]`, judged **per
       event**:
       - For every team name carrying a two-year band (`B15/16`, `2016/2017`, `B13/14`), take the
         younger year's U-age under `event_season`. Skip a pair younger than
         `event_season - 6`, as A2E :569 does.
       - Count teams whose U-age lies within their division's ages (`young_age <= u_age <=
         old_age`), and teams one year below `young_age`.
       - With fewer than 5 band-named teams, return None.
       - If the one-below count exceeds the at-age count, return a reason naming both counts.
       - Import A2E's `_BAND` (and `_LEADING_AGE` for `club_for`) rather than copying them.
       - Do **not** judge per division. Measured on WFC, `B11White`'s only two band-named teams
         both play up (`Warrior SC B16/17 White`, `Olimpia USA Black 2016/2017`), and a
         per-division test drops it. The event as a whole reads 41 at age and 5 one below, or
         28 and 5 across the 17 in-scope divisions.
   - **`build_roster(team_lists, event, board_season) -> (in_scope, skipped)`**, mirroring A2E
     :646-688:
     - `age_from_name(respell_ages(name), None, event.season)`: no division is passed, so it is
       neither a bound nor a fallback (corrected during implementation to the owner's standing
       rule). Use the original name everywhere else.
     - Skip reasons, in order:
       - the name is unreadable
       - no birth year (the `age_from_name` reason, with `NO_AGE_IN_NAME` / `ODD_YEAR_SPAN`
         reworded to "no age in the team name" / "odd year span in the team name")
       - no board (`board_cohort` is None)
       - no US state in the location
   - **Registration.** Copy A2E :691-850 (`existing_aliases`, `register_teams`,
     `unsaved_links`, `pending_reviews`, `unsaved_reviews`, `shared_links`, `off_board_links`,
     `teams_by_id`), renaming `a2e_team_id` to `tc_team_id`, reading the local `PROVIDER_CODE`,
     and writing "Tourney Central" in messages.
   - **`build_csv_rows(games, roster, outcomes, event)`**, copying A2E :861-943 including the
     cross-age record:
     - `event_id=f"{event.subdomain}-{event.season}"`
     - `event_name=f"{event.name} - {game.division_code}"`
     - `schedule_id=f"{event.subdomain}-{game.game_no}"`
     - `venue` is the field
     - `source_url` is `schedule_url`
     - Copy `_compute_result` and `write_csv`.
   - **`report_rows`**, as A2E :954-982.
   - **`collect_event(fetch_html, host, subdomain, board_season, days_back, today, pause)`**:
     1. Fetch the games page and parse the divisions. Each unparseable code is a problem, and
        each skipped division is reported with its reason.
     2. For each kept division, fetch its team list and its schedule.
     3. Run `label_season_mismatch` over the kept divisions' team names. A mismatch raises
        `LabelSeasonError` with its reason. `main` catches it, prints it and exits 1 before any
        registration.
     4. Build the roster, then filter the games to `today - days_back .. today`.

     A `ScrapeFetchError` anywhere propagates out of `collect_event`. `main` catches it, as it
     does `LabelSeasonError`, prints it and exits 1, so nothing is registered. The report and
     cross-age CSVs pass every value through `csv_safe`; the importer's own CSV keeps names as
     written.
   - **`parse_args` and `main`**, mirroring A2E :985-1143:
     - `--event-url`, `--days-back` (default 14), `--output-dir`, `--delay-min` 1.0,
       `--delay-max` 2.0 and `--execute`.
     - Look up the provider row by code and exit red when it is missing.
     - Run the preview `register_teams` with `TourneyCentralGameMatcher(...,
       registration_mode=True, dry_run=True)`, then `shared_links`. On execute, a writer matcher
       and the unsaved checks; then `off_board_links`.
     - CSVs are named `{subdomain}_{season}_{stamp}_{games|cross_age|teams}.csv`.
     - The summary table uses A2E's rows plus "divisions skipped".
     - The importer subprocess runs on `--execute` only.

7. **Add the fixtures, `tests/fixtures/tourneycentral/`.**
   - Copy them byte for byte, still Latin-1, from the 2026-10-14 capture.
     Name each file after the page it captures:
     - `games.html`
     - `sked_B11Gold.html` and `adiv_B11Gold.html` (a final with Champion and Finalist
       notes)
     - `sked_B14-15Gold.html` and `adiv_B14-15Gold.html` (a two-age division; `VASC B12/13` plays
       up)
     - `adiv_B14-15Red.html` and `sked_B14-15Red.html` (a `[ + ]` website link)
     - `adiv_G13Gold.html` and `sked_G13Gold.html` (the `Tournament Only team` club)
     - `adiv_B13Red.html` and `sked_B13Red.html` (`Parkersburg, WV, WV`)
   - To refresh them, re-fetch the same pages with `_fetch`, at the same pacing.
   - Before committing, read each file for anything that should not be published. The pages
     carry public tournament data only.

8. **Write `tests/unit/test_import_tourneycentral_event.py`.** Follow the A2E driver tests'
   fixture loading and `_Response` byte-decoding double.
   - **Expected values are literals.**
   - **Fetch:** `_fetch` decodes Latin-1 bytes declared only in `<meta>`; a header charset wins
     over the meta; a non-200 or transport error raises `ScrapeFetchError`; the session's adapter retries
     500/502/503/504 twice and nothing else.
   - **`parse_event_url`:** accepts any path on the host and rejects other hosts.
   - **`parse_games_page`:** gives `Warrior Fall Classic`, 2026-10-10..11, season 2026, and 21 codes.
   - **`parse_division_code`:**

     | Code | Result |
     |---|---|
     | `B11Gold` | (Male, 11, 11, None) |
     | `B107v7Gold` | (10, 10, 7) |
     | `B129v9Red` | (12, 12, 9) |
     | `G14-15Gold` | (Female, 14, 15) |
     | `B09Red` | skipped as U9 |
     | `B105v5Gold` | skipped as small-sided |
     | `BU11` | None |

   - **`parse_team_list` on `adiv_B11Gold.html`:** 4 rows, with
     `("317819", "Warrior SC B15/16 White", "Warrior Soccer Club", "Dayton, OH", "Tuan Ha")`
     among them. On `adiv_B14-15Red.html`, the `[ + ]` row parses to its own name, club and
     location.
   - **`parse_schedule` on `sked_B11Gold.html`:** 7 games, numbers 71-77, the first two dated
     2026-10-10 and the last 2026-10-11. Game 77 is `315843` 3 – `317819` 2. No seed text
     (`A2 -`, `- A4`) appears in any field.
   - **`state_from_location`:**

     | Location | State |
     |---|---|
     | `Kettering, OH, QC` | OH |
     | `Parkersburg, WV, WV` | WV |
     | `GC Cosmos 2014/2015 white, OH` | OH |
     | `Toronto, ON` | None |
     | `` (empty) | None |
     | `Columbus, OH, MI` | None |

   - **`club_for`:** the `Tournament Only team` fallback, and the written club for
     `Warrior SC B15/16 White` is `Warrior SC`.
   - **`build_roster` ages:**

     | Team (division) | Result |
     |---|---|
     | `Warrior SC B15/16 White` (B11Gold) | u11 |
     | `NWC 2033 Boys Elite (U12)` | u12 |
     | `VASC B12/13` (B14-15Gold) | u14 |
     | `WOU B14` (B129v9Red) | u13 (older than its division; the division does not bound it) |
     | `PC United 12u` | u12 |
     | `RVSC Rampage` (B13Red, no age in name) | skipped, "no age in the team name" |
     | `Bluffton Legacy Red` (G14-15Red) | skipped, "no age in the team name" |
     | `Ohio Fusion SC BU11/U10 Blue` | skipped, two U-ages |

   - **`label_season_mismatch`:**
     - None for the WFC fixture divisions together.
     - None for a synthetic event of `B11White`'s two play-up names plus four at-age names. This
       pins the per-event judgement.
     - A reason for a synthetic event of six band-named teams that all read one year below.
     - None for four band-named teams that all read one below (too few to judge).
   - **`build_csv_rows`:**
     - a cross-age pair is imported and recorded
     - a game with an unsettled team is held
     - every required column is written
     - two games between the same teams on one date get distinct `schedule_id`s
   - **A `run_main` test, as in the A2E test file (:573-636):**
     - a dry run writes the three CSVs and never calls `subprocess.run`
     - `--execute` calls it with `PROVIDER_CODE`
     - a `ScrapeFetchError` on one schedule exits non-zero before `register_teams` runs

9. **Write `tests/unit/test_tourneycentral_matcher.py`.** Take the double from
   `tests/unit/test_athletes2events_matcher.py:22-140`, including the PGRST116 raise.
   - A created team keeps `Club Ohio Dayton U11B Green` whole, with `club_name="Club Ohio Dayton"`,
     the state and the provider id.
   - A dry run inserts nothing and still returns a deterministic id.
   - A team row already carrying the id returns `was_created=False`.
   - A same-state candidate with the same club and squad links through the inherited gates.

10. **Add the matcher to the test registries.**
    - In `tests/unit/test_provider_matcher_dry_run.py`:
      - import `TourneyCentralGameMatcher`
      - add `("tourneycentral", TourneyCentralGameMatcher)` to `AUTOCREATING_MATCHERS`
      - add `("tourneycentral", TourneyCentralGameMatcher, "_create_new_athletes2events_team")`
        to the create parametrize
      - add `"tourneycentral"` to `REGISTRATION_MATCHERS`, and update its comment
    - Add `("src.models.tourneycentral_matcher", "TourneyCentralGameMatcher")` to `_SUBCLASS_PATHS`
      in `tests/unit/test_birth_year_guard_wiring.py`.

11. **Update the docs.**
    - Add a Tourney Central row to the `CLAUDE.md` Data Providers table: code `tourneycentral`,
      HTML scraping, operator-run per tournament via
      `scripts/import_tourneycentral_event.py --event-url`.
    - Add a "Tourney Central Pages" section to `.claude/skills/scraper-patterns/SKILL.md`
      covering:
      - the GET URLs and the division-code grammar
      - the team-list cells, the location quirks and the `Tournament Only team` club
      - team ids being platform-wide but new per tournament entry
      - Latin-1 declared only in `<meta>`
      - game numbers being unique per event, and same-day rematches
    - In the same file, correct the stale "Importing Athletes2Events games" sentence that says the
      driver holds cross-age games back. It imports them and lists them (A2E :864-872). That
      sentence is where the spec's first draft went wrong.
    - Name only tracked paths and real flags; `tests/unit/test_agent_doc_references.py` checks both.

## Verification

- Run `python -m pytest tests/unit/test_import_tourneycentral_event.py
  tests/unit/test_tourneycentral_matcher.py tests/unit/test_provider_matcher_dry_run.py
  tests/unit/test_birth_year_guard_wiring.py tests/unit/test_rematch_game_uid.py
  tests/unit/test_agent_doc_references.py`.
  - All pass.
  - The registry and rematch tests now carry `tourneycentral` cases.
- Then run the CI gate: `python -m ruff check src/ scripts/ config/ tournament_intake.py
  dashboard.py` and `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`. Run it
  serially; `-n` exhausts the paging file on this machine.
- **Mutation checks**, each run on a scratch copy and checked by the **name** of the failing
  test, not just a red suite:
  - Remove `"tourneycentral"` from `REMATCH_PROVIDERS`: the rematch test for it fails.
  - Restore the club-prefix strip in the override: the full-name matcher test fails.
  - Drop `dry_run=self.dry_run` from the pipeline branch: the pipeline dry-run test fails.
  - Make `_fetch` use `.text`: the Latin-1 decode test fails.
  - Pass the division as `age_from_name`'s bound: the `WOU B14` case fails.
  - Fall back to the division for a name with no age: the `RVSC Rampage` case fails.
  - Judge `label_season_mismatch` per division: the `B11White` play-up case fails.
- **Live dry run, after the owner applies the provider seed:**
  `python -m dotenv -f C:\PitchRank\.env run -- python scripts/import_tourneycentral_event.py
  --event-url https://wfc.tourneycentral.com --days-back 30`.
  - Expected scope: 17 divisions in scope and 4 skipped as U9, with no other skips.
  - Expect 146 games in window and 85 teams before skips.
  - Read the team report and the games CSV rows themselves. Give the user these counts before any
    `--execute`:
    - already linked, linked to an existing team, created, review, conflict, error
    - left out, broken down by reason
    - games to import, and the cross-age games among them
  - Spot-check that the 7 rematch pairs appear as 14 distinct row pairs with distinct
    `schedule_id`s.
- **After an approved `--execute`**, read the database, not the summary:
  - `team_alias_map` rows for the provider UUID
  - `team_match_review_queue` rows filtered by the provider **code** `tourneycentral`
  - `games` for the provider UUID, dated 2026-10-10..11
  - `quarantine_games` where `raw_data->>'provider' = 'tourneycentral'`

  Then confirm both games of each rematch pair exist, except a final that repeats its pool
  game's orientation and score.

## Context Files

- `.turbo/specs/tourney-central-scraper.md`: the approved product decisions, the site facts, and the WFC figures.
- `scripts/import_athletes2events_event.py` (origin/main): the driver to mirror. Read its whole flow, not just the cited helpers.
- `src/models/athletes2events_matcher.py` (origin/main): the inherited matcher contract.
- `src/models/yssl_matcher.py` (origin/main): the precedent for subclassing and keeping the full name.
- `tests/unit/test_import_athletes2events_event.py` and `tests/unit/test_athletes2events_matcher.py` (origin/main): the test doubles and fixture conventions to copy.
- `.claude/skills/scraper-patterns/SKILL.md`: the Athletes2Events, matcher-name-parsing and "Reading a Provider's Age Labels" sections.
