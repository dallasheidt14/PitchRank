---
status: done
---

# Plan: HTG Sports per-event importer

## As built (2026-11-09)

What changed from the plan below, and why:

- **Sporting Columbia 14/15B Navy played U12 Boys Blue (division 54981), not Red I.** The Context
  section below repeats a misreading: the page redraws a beat after the division picker changes, so a
  snapshot showed Blue's table under Red I's id. The API was right all along. Fixtures are therefore
  U12 Boys Blue and U10 Boys Blue.
- **The token stubs are inline strings in the tests**, not `index.html` / `main.js` fixture files.
- **The API facts were re-measured.** A call without the token answers **204 No Content**, not an
  empty 200, and the API declares `charset=utf-8`. The driver accepts 200 alone either way, and parses
  bytes regardless.
- **Peer review (codex) found three changes:**
  - A forfeit is held when any copy of the game flags it, in whichever division it is read first.
  - A game whose copies disagree is held, as `disputed`, and is no longer imported from the first copy.
  - A team whose name has no age is left out when it is listed in divisions of different ages. The
    check lives in the fallback itself (`_division_fallback` in the Tourney Central driver), so the
    skipped row carries no age.
  - Its fourth finding, that a same-day rematch with identical scores collides on the composite key,
    is the existing IMP-213 limit shared by every rematch provider. It is documented, not fixed.
- **A second review round (six internal reviewers plus codex) changed:**
  - **Placeholders.** A standings slot named `TBD`/`TBA`/"to be determined"/`Bye` is reported and never
    registered; the fallback would have given event 14129's `TBD` slot the u14 board.
  - **Two birth years.** A name with two of them ("Club 2012 Est 2019") is left out rather than filed
    by its division, since `age_from_name` reports it as no age.
  - **Copies and forfeits.** A forfeit is read before the team ids, so a copy with an empty slot still
    counts. One comparison (`_same_game`, venue included) now decides whether copies of a game
    disagree, inside one division or across two.
  - **Ids and reuse.** Every id the API sends is read by one rule (`_id`, through `clean_provider_id`),
    so a division id sent as text is read. The driver imports Tourney Central's session setup and its
    `--state`/`--age`/`--gender` validators rather than copying them.
  - **Tests.** The coverage review found `main`'s safety steps reachable only through tests of the
    functions beneath it, so the tests now drive `main` itself, and pin `htgsports` in
    `REMATCH_PROVIDERS` by literal rather than through the set.
  - **Dry-run files.** The owner chose to keep the dry run writing its CSVs as the sibling drivers do,
    against CLAUDE.md's "a dry run writes nothing" rule: each run writes new dated files and nothing
    reads them back.
  - **Skipped, with the reason.** An incomplete copy holding the game was skipped because one game has
    one record, so copies cannot disagree outside a live-scoring race. Extracting `main`'s registration
    sequence was skipped because it is IMP-389's consolidation. Skipped as minor: a NamedTuple return,
    shared test doubles, and a pipeline-branch `registration_mode` test, a gap every provider shares.
- **A club-spelling gap in the shared matcher showed up in the dry run.** HTG writes `SPORTING BV`
  where PitchRank stores `Sporting Blue Valley`. The club read from a stored team's name stops at the
  first age token, so `SPORTING BV Real Madrid 16/17` reads as club `SPORTING BV Real Madrid`, and an
  exact-name team is skipped and recreated. A prefix-match variant measured only 6 more links plus
  18 weak reviews over the 274 would-be new teams, so the shared matcher was left unchanged and the
  gap went to the backlog.
- **Production steps as run:**
  - Provider row `htgsports` inserted; the ledger was repaired for `20261109120000`.
  - Seven approved `manual` aliases were written before `--execute`. Five are existing teams of the same
    or a near-identical name (Real Madrid 16/17, Academy White 16/17, Academy 14/15 as `Academy 15`,
    Pre-NAL 14/15 as `Pre-NAL 15`, Sporting Iowa Grey U11B).
    The other two are owner rulings on U12 Boys Blue teams: DASC U12B Black is `DASC BU12 Black`, and
    SPORTING BV Pre-MLS Next 15/16 is the White 15/16 squad (`7cecc3bb…`).
  - Aberdeen 12/13 was not linked: the stored `SPORTING BV Aberdeen 12` is on u15, while the HTG band
    reads u14.
  - Both events ran with `--age` for CVSC's U-age names (`CVSC 10B` played U10 7v7) and DMSC U18/19.
    The girls event also used `--leave-out` for a `TBD` placeholder team; that run came before the
    placeholder filter, and the driver now drops such a slot itself.

## Context

A subscriber reported that a Kansas City tournament's results were missing from PitchRank and from every
other ranking site. The tournament, the 2026 Children's Mercy Heartland Invitational, ran on **HTG Sports**
(`events.htgsports.net`), a platform PitchRank has never collected from. Boys event 14130 ran Nov 6-8 (71
divisions); girls event 14129 ran Oct 30-Nov 1 (35 divisions). Heartland Soccer runs both and lists its
Kansas City leagues on the same platform, so more HTG events will follow.

The outcome is an operator-run, per-event importer in the mould of the Tourney Central one (point it at an
event URL; dry run by default, `--execute` writes), and both Heartland events imported. Owner decisions
(2026-11-09):

- **Plan directly**, not `/turboplan`.
- **Boys and girls** events both.
- **No-age names take the division's age.** A team whose name states no age, or an odd year span, takes its
  division's single age. A mixed division ("U14/15 Girls", "High School Boys") leaves such a team out. A
  name that states an age always wins, so the division is never a bound and never a tiebreak (memory
  `team-name-decides-age-not-division`).
- **Share the code.** HTG calls the Tourney Central driver's roster and CSV functions instead of copying
  them. Those functions gain optional provider arguments whose defaults keep Tourney Central byte-identical
  (IMP-389 direction).
- **Import before merge.** Once targeted tests and one review pass, dry-run both events from the branch,
  show the owner the counts, then `--execute`. The PR follows.

### What HTG serves (observed 2026-11-09)

- The SPA is at `https://events.htgsports.net/?eventid=<id>#/scheduleresults/<divisionId>`. JSON comes from
  `https://events.htgsports.net/api/<path>?format=json`.
- Every API call needs the header `HTGSports-Token: <GUID>`; without it the body is empty. The value is a
  constant hard-coded in the public bundle `app/main.js?<ver>`, which the event index page references. It
  appears twice: `headers.common["HTGSports-Token"]="…"` and `{"HTGSports-Token":"…"}`. It is the same for
  every visitor (a public client key, not a credential), so the driver reads it from the bundle each run.
- **Endpoints:**
  - `eventSummary2/<event>`: `Name`, `StartDateAsString` "11/6/2026", `EndDateAsString`.
  - `divisions/<event>`: a list of `{Name, Id, SizeDescr, Format, MaxDOB, Publish}`. Names read like
    `U12 Boys Red I (2014/15) 9v9`, `U10 Girls Red (17/18) 7v7`, `U14/15 Girls Green (2012/13) 11v11`,
    `U18/19 Girls Red (2007/08) 11v11` and `High School Boys Blue 11v11`. `SizeDescr` is `7v7`, `9v9` or
    `11v11`. The bands match this season (U12 = 2014/15).
  - `standings/<event>/<division>/false`: one row per team with `Id` (the HTG team id), `Name`,
    `ClubName`, `Location` "Des Moines, IA", `Coach`, `PoolId`. **Rows also carry coach and manager phone
    numbers and the manager's name. Never store, log or commit these.**
  - `GamesForDivision/<event>/<division>`, one row per game:
    - `Id`, unique per game.
    - `Team1Id`/`Team2Id` (HTG team ids) and the `HomeTeam`/`VisitingTeam` names.
    - `HomeTeamScore`/`VisitingTeamScore`, `-1` when unplayed.
    - `Date` "11/06/2026", `Time` " 7:00PM", `Field`.
    - `Type` (`Pool`, `Final`, …), `Pool1ID`/`Pool2ID`.
    - The flags `NoShow1/2`, `Forfeit1/2` and `IgnoreResult1/2`.
  - `coaches/<event>` is personal data (names, DOB). Never fetch it.
- Sporting Columbia 14/15B Navy played U12 Boys Red I: W 3-1 Sporting BV Pre-MLS Next 15/16, W 3-2 DASC U12B
  Black, W 4-1 FC Vardar U12 B Red, D 2-2 RFA 2014/2015.

## Pattern Survey

(From `/survey-patterns`, run against `C:\pitchrank-htgsports` at `2b3183767`; `tc` =
`scripts/import_tourneycentral_event.py`, `a2e` = `scripts/import_athletes2events_event.py`, `seg` =
`scripts/import_soccereventsgroup_event.py`, `dm` = `scripts/import_demosphere.py`.)

### Analogous Features

- **Tourney Central driver (the template):**
  - `build_roster` (`tc:651-719`), the roster helpers (`tc:727-884`) and `build_csv_rows` (`tc:898-979`).
  - `main` (`tc:1156-1277`) runs a dry-run preview (`tc:1212`) and then a writer matcher (`tc:1222`).
  - It verifies saved links and reviews (`tc:1226-1231`) and diverts conflicts and links to other boards.
  - It shells out to `import_games_enhanced.py <csv> PROVIDER_CODE` (`tc:1276`).
- **Provider-neutral as written:**
  - Functions: `state_from_location` (`tc:641`), `label_season_mismatch` (`tc:585`), `existing_aliases`
    (`tc:727`, takes `provider_id`), `unsaved_links` (`tc:782`), `unsaved_reviews` (`tc:812`),
    `off_board_links` (`tc:847`), `teams_by_id` (`tc:873`), `_compute_result` (`tc:890`),
    `_for_spreadsheets` (`tc:982`), `write_csv` (`tc:986`).
  - Constants: `LINKED_OUTCOMES` (`tc:202`), `NAME_WITHOUT_AN_AGE` (`tc:209`), `REQUIRED_COLUMNS`
    (`tc:125`), `CROSS_AGE_COLUMNS` (`tc:173`), and `SCRAPE_TS`/`SCRAPE_RUN_ID` (`tc:199-200`, set at import
    time).
- **Neutral, but with Tourney Central wording:**
  - `register_teams` (`tc:745`): its log line only (`tc:764`).
  - `shared_links` (`tc:825`): the reason text (`tc:843`), which `tests/unit/test_import_tourneycentral_event.py:922-930` pins.
  - `report_rows` (`tc:994`): the `tc_team_id` key (`tc:1002`), which `REPORT_COLUMNS` (`tc:156`) also uses.
- **`build_roster` (`tc:651`) changes how ages are read:** it always applies `respell_ages` (`tc:681`), as
  `club_for` does (`tc:627`).
- **Bound to the provider code:**
  - `pending_reviews` (`tc:796`) filters `.eq("provider_id", PROVIDER_CODE)` (`tc:803`), and the review queue
    stores the code (`src/models/game_matcher.py:1692-1701`). Reused unchanged, every HTG review would turn
    into "review item was not saved".
  - `build_csv_rows` (`tc:898`) writes `"provider": PROVIDER_CODE` (`tc:942`) and builds `event_id` and
    `schedule_id` from `event.subdomain` (`tc:944`, `tc:946`). The importer reads that column for the game
    uid and rematch handling (`src/models/game_matcher.py:763-777`) and for dedup
    (`src/etl/enhanced_pipeline.py:1354`). `tests/unit/test_import_tourneycentral_event.py:839` pins `"tourneycentral"`.
- **Bound to the Tourney Central site:**
  - URL handling: `_EVENT_URL` (`tc:216`), `parse_event_url` (`tc:367`) and the URL builders (`tc:377-386`).
  - HTML parsers: `parse_games_page`, `parse_division_code`, `parse_team_list` and `parse_schedule`
    (`tc:396-571`).
  - Fetching: `_encoding`/`_fetch` (`tc:333-364`), and `make_session` with `HEADERS`, which accept HTML only
    (`tc:191-197`, `tc:325`).
  - Orchestration: `collect_event` (`tc:1101`) and `main`, whose summary title (`tc:1253`) and matcher class
    (`tc:1213`, `tc:1222`) are Tourney Central's.
  - The argparse validators' wording (`tc:1072-1098`).
- **Dataclasses:**
  - `Event(host, subdomain, name, start, end)` with a `.season` (`tc:239-250`).
  - `Division(code, gender, young_age, old_age, players)` (`tc:253`).
  - `TeamListing` and `TeamRow` are keyed `tc_team_id` (`tc:262`, `tc:271`); nothing checks what the field
    holds.
  - `Outcome` (`tc:288`) and `EventGame(division_code, game_no, …)` (`tc:296`).
- **Cross-driver imports:**
  - `dm:69-84` imports age/club readers and `existing_aliases`, `teams_by_id`, `unsaved_links`,
    `unsaved_reviews` and `write_csv` from `a2e`.
  - `dm:85` imports `NAME_WITHOUT_AN_AGE` and `_for_spreadsheets` from `tc`.
  - Demosphere keeps its own `register_teams`, `shared_links`, `pending_reviews`, `off_board_links`,
    `build_csv_rows` and `report_rows` (`dm:723-940`).
  - No driver imports another's `register_teams`, `pending_reviews`, `shared_links` or `off_board_links`.
    The Tourney Central plan chose to copy them (`.turbo/plans/tourney-central-scraper.md:195-198`).
- **No provider-code parameter exists in any copy:** `seg:431,642`, `scripts/import_yssl.py:655,802`,
  `dm:791,900`, `a2e:767,907`, `tc:803,942`. IMP-389 (`.turbo/improvements.md:2554-2563`) proposes one;
  IMP-388 covers club-cut and age-wording drift.
- **JSON-API drivers:**
  - Soccer Events Group: `make_session` (`seg:197-202`), `_get` (`seg:205-214`: timeout 90, raises
    `ScrapeFetchError` on a transport error or a non-200), `fetch_json` (`seg:217-222`: a non-JSON body
    raises), per-endpoint wrappers (`seg:225-230`) and JSON `HEADERS` (`seg:129-135`).
  - Kitman: `scripts/scrape_mlsnext_kitman.py:220-225`.
  - PlayMetrics: `scripts/scrape_playmetrics_league.py:368-392`.
- **Forfeits are never imported:**
  - Demosphere (`dm:193`, `dm:405-407`, `dm:857-862`, counted at `dm:1129`).
  - PlayMetrics (`scripts/scrape_playmetrics_league.py:604-608`).
  - SincSports (`scripts/scrape_sincsports_tournament_schedule.py:359`).
  - Affinity (scraper-patterns skill).
  - Tourney Central keeps digit scores only (`tc:547-549`).
  - Nothing handles a no-show or an ignore-result flag; the validator rejects negative goals
    (`src/utils/enhanced_validators.py:198-200`).

### Reusable Utilities

- `split_club(team_name, host)` (`a2e:625-640`): `host` feeds only `HOST_CLUBS.get(host, ())`
  (`a2e:245-253`, crossfire only), so `events.htgsports.net` is harmless. `club_for` passes the host through
  (`tc:627`).
- The age readers `age_from_name`, `board_cohort` and `respell_ages` (`a2e:552`, `:613`, `:541`). Call
  `age_from_name(name, None, season)`. With no division it returns `NO_AGE_IN_NAME` /
  `ODD_YEAR_SPAN` (`a2e:537-538`) exactly when the name states no age or an odd span.
- `club_before_squad_marks` (`src/models/tourneycentral_matcher.py:27-41`) and `TourneyCentralGameMatcher`
  (`:44-115`; its existence check is wrapped against PGRST116 at `:82-97`).
- `DemosphereGameMatcher(TourneyCentralGameMatcher)` (`src/models/demosphere_matcher.py:29-45`), the
  subclass template.
- `csv_safe` (`src/tournaments/reports/render_csv.py:62`), `clean_provider_id`
  (`src/utils/provider_ids.py:25`), and `_soccer_season_year` through `Event.season`.
- Key-from-script regex precedent: `_CAPTCHA_SITEKEY_RE` / `_find_sitekey` (`src/scrapers/gotsport.py:912-976`).
  There is no helper for reading a JS bundle and none for .NET dates.
- Custom-header redirect precedent: `scripts/batch_drain_queue.py:585-619`. `requests` strips only
  `Authorization` on a host change, so a custom header must not ride a redirect.

### Convention Anchors

- **Session and errors:**
  - Every driver's `make_session` uses `Retry(total=2, backoff_factor=1, status_forcelist=[500,502,503,504])`.
  - Fetch failures raise `ScrapeFetchError` (`tc:313-318`, `seg:189-194`), and a 200 page missing its
    expected structure raises too (`tc:476-477`).
- **Run shape:**
  - Dry run by default; the CSVs are written either way (`tc:1036`, `tc:1270-1272`).
  - The run refuses to start without a providers row (`tc:1171-1174`).
  - Imports are packaged with `# noqa: E402`. Importing `tc` runs its `load_dotenv`/`logging.basicConfig`,
    which Demosphere already accepts.
- **Output:** `data/raw/<provider>/` (`tc:121`), gitignored by `data/*` (`.gitignore:7`), three files per
  run (`tc:1241-1251`).
- **Importer whitelist:** `scripts/import_games_enhanced.py:83-110` keeps `schedule_id` and drops
  `scrape_run_id`, `event_id`, `age_year` and `game_time`.
- **Tests:**
  - Tourney Central driver: `_PageFetcher` (`tests/unit/test_import_tourneycentral_event.py:31-55`),
    `_Response`/`_Session` with raw bytes (`:75-98`), a `_Query`/`_client` PostgREST double that records at
    `execute()` and projects the selected columns (`:1057-1088`), `_FakeMatcher` (`:1138-1154`), and the
    `run_main` monkeypatch fixture (`:1177-1250`).
  - Monkeypatching: patching a function in `tc` does not reach a function the HTG module imported by name,
    and vice versa.
  - Soccer Events Group JSON fixtures: `tests/unit/test_import_soccereventsgroup_event.py:25-31`. Its
    `_Session` records no headers, so do not copy it for header assertions.
  - Contact-detail scrub test: `tests/unit/test_import_demosphere.py:1084-1098`.
  - Matcher double: `_DB` (`tests/unit/test_athletes2events_matcher.py:1-22,111`) raises PGRST116 on a
    zero-row `.single()`.
- **Registration points:**
  1. The seed migration (template `supabase/migrations/20261014120000_seed_tourneycentral_provider.sql`;
     newest is `20261106120000_seed_affinity_ga_provider.sql`).
  2. The pipeline branch `src/etl/enhanced_pipeline.py:405-426`, written literally as
     `self.provider_code.lower() == "htgsports"` because the tests split the source on `== "{provider}"`
     (`tests/unit/test_provider_matcher_dry_run.py:76-91`).
  3. `REMATCH_PROVIDERS` (`src/models/game_matcher.py:476`, comment `:469-475`). It flows to
     `SCHEDULE_ID_SUFFIX_PROVIDERS` (`:482`), fill-disable (`src/etl/enhanced_pipeline.py:1751-1756`),
     `scripts/exclude_unscored_fixture_twins.py:140` and `tests/unit/test_rematch_game_uid.py:38,46`.
  4. In `tests/unit/test_provider_matcher_dry_run.py`: the import (`:33`), `AUTOCREATING_MATCHERS`
     (`:36-51`), the `(provider, cls, create)` list (`:95-107`) and `REGISTRATION_MATCHERS` (`:163`).
  5. `_SUBCLASS_PATHS` in `tests/unit/test_birth_year_guard_wiring.py:55-71` (it skips a class that does not
     override `_fuzzy_match_team`, `:83-84`).
  6. The Data Providers table, `CLAUDE.md:392-410`.
  7. `.claude/skills/scraper-patterns/SKILL.md`: a provider section (models: `:807-887` and `:564-590`), the
     cross-references at `:486-487`, `:742-743`, `:1222` and `:1615-1619`, and the checklist at `:1167-1180`.
  8. `.claude/skills/merging-duplicate-teams/SKILL.md:179` (prose list; the code is an allowlist and needs no
     change).
  9. IMP-389, `.turbo/improvements.md:2554`.
  - Not needed: a workflow, the rollover-freeze lists, `scripts/team_cleanup/apply_stage.py`, the frontend.

### Proposed Alignment

Take the Tourney Central driver's run shape and the Soccer Events Group driver's JSON fetching, and import
`tc`'s neutral helpers and dataclasses as Demosphere does. `pending_reviews`, `build_csv_rows`,
`shared_links` and `register_teams` need the decided provider arguments. `report_rows`' `tc_team_id`
column is renamed on the HTG side.

## Implementation Steps

Work in `C:\pitchrank-htgsports` (branch `feat/htgsports-importer`, cut from `origin/main` `2b3183767`,
upstream unset). `C:\PitchRank` is ~190 commits behind with unrelated dirty files; do not edit it. Before
editing, check `git -C C:/pitchrank-htgsports status --porcelain` holds only this plan. Python scripts that
need the database run from the worktree as
`python -m dotenv -f C:\PitchRank\.env run -- python scripts/<x>.py …`.

1. **Optional provider arguments on the Tourney Central driver** (`scripts/import_tourneycentral_event.py`).
   Every default is today's value, so Tourney Central output and its existing tests are unchanged.
   - `pending_reviews(supabase, tc_team_ids, provider_code=PROVIDER_CODE)`: filter on `provider_code`.
   - `build_csv_rows(games, roster, outcomes, event, provider_code=PROVIDER_CODE)`: write `provider_code` into
     the `provider` column.
   - `shared_links(outcomes, provider_name="Tourney Central")` and
     `register_teams(matcher, provider_id, roster, already, provider_name="Tourney Central")`: use the name in
     the reason and the log line.
   - `build_roster(…, division_age_fallback=False)`:
     - When the fallback is on and `age_from_name(..., None, season)` returns `NO_AGE_IN_NAME` or
       `ODD_YEAR_SPAN`, take the division's age.
     - This applies only when `board_cohort` of `young_age` and of `old_age` agree (U12, or U18/19 → u19).
     - The birth year is `_birth_year_on_board(f"u{young_age}", event.season)` and the source reads
       `"division U<n> (no age in name)"`.
     - A mixed division keeps today's skip reason. `--age` still overrides.
2. **Provider seed migration**: `supabase/migrations/20261109120000_seed_htgsports_provider.sql`.
   - Copy the Tourney Central seed: `INSERT INTO providers (code, name, base_url) VALUES ('htgsports', 'HTG
     Sports', 'https://events.htgsports.net') ON CONFLICT (code) DO NOTHING;`
   - Its header comment says one row covers every HTG event and that HTG team ids are platform-wide.
3. **Matcher**: `src/models/htgsports_matcher.py`, `class HtgSportsGameMatcher(TourneyCentralGameMatcher)`.
   - It has a module docstring and no overrides. HTG's standings print a club field beside the team name,
     exactly the case `TourneyCentralGameMatcher._fuzzy_match_team` handles, and a created team keeps its
     full registered name.
4. **Pipeline and rematch wiring.**
   - In `src/etl/enhanced_pipeline.py`, add an `elif self.provider_code.lower() == "htgsports":` branch beside
     the Tourney Central one (`:405-415`). It constructs `HtgSportsGameMatcher(self.supabase,
     provider_id=self.provider_id, alias_cache=self.alias_cache, dry_run=self.dry_run)` with the same
     "alias-only; teams come from the roster pass" comment and log line.
   - In `src/models/game_matcher.py:476`, add `"htgsports"` to `REMATCH_PROVIDERS`: a pool game and a final
     between the same two teams on one day are two games, and every HTG game carries a unique `Id`.
5. **Driver**: `scripts/import_htgsports_event.py`. Its module docstring describes the API, the token, the
   two stages and the age rule, as `tc`'s does.
   - **Imports from `tc`:**
     - Dataclasses: `Event`, `Division`, `TeamListing`, `TeamRow`, `Outcome`, `EventGame`.
     - Errors: `ScrapeFetchError`, `LabelSeasonError`.
     - Constants: `REQUIRED_COLUMNS`, `CROSS_AGE_COLUMNS`, `REPORT_COLUMNS`.
     - Roster and output functions: `skip_division`, `label_season_mismatch`, `build_roster`,
       `existing_aliases`, `register_teams`, `unsaved_links`, `pending_reviews`, `unsaved_reviews`,
       `shared_links`, `off_board_links`, `teams_by_id`, `build_csv_rows`, `report_rows`, `write_csv`,
       `_for_spreadsheets`, `_clean_name`.
   - **Constants:** `PROVIDER_CODE = "htgsports"`, `PROVIDER_NAME = "HTG Sports"`, `HOST =
     "events.htgsports.net"` and `OUTPUT_DIR = Path("data/raw/htgsports")`.
   - **URL.** `_EVENT_URL` matches `https://events.htgsports.net/...?eventid=<1-9 digits>...` and is
     ASCII-bound with `re.IGNORECASE | re.ASCII`. `parse_event_url(url) -> str` returns the event id or raises
     `ValueError`.
   - **Session and token.** `make_session()` copies the `seg` shape with browser `User-Agent` headers.
     - `read_api_token(session, event_id)` fetches `https://events.htgsports.net/?eventid=<id>` and reads the
       `app/main.js?…` src, then fetches that bundle and reads the GUID. `_TOKEN` matches
       `HTGSports-Token"\]?\s*[:=]\s*"([0-9A-Fa-f]{8}-…{12})"` (ASCII-bound).
     - It raises `ScrapeFetchError` when the bundle or the token is missing, or when two different tokens
       appear.
     - The token is never printed or logged.
   - **API fetch.** `fetch_api(session, token, path)` sends a GET to `https://events.htgsports.net/api/<path>`
     with `params={"format": "json"}`, `headers={"HTGSports-Token": token, "Accept": "application/json"}`,
     `timeout=90` and `allow_redirects=False`.
     - The token goes per request, never on the session, so no other request carries it and no redirect can
       forward it.
     - It raises `ScrapeFetchError` on a transport error, a non-200 (3xx included), an empty body or a non-JSON
       body.
     - It parses `json.loads(response.content)`, not `.text`, because of the no-charset ISO-8859-1 trap.
   - **Parsers (pure, over the JSON):**
     - `parse_event_summary(data, event_id) -> Event` takes `host=HOST`, `subdomain=f"htg{event_id}"`, the
       `Name`, and start/end from `StartDateAsString`/`EndDateAsString` (`%m/%d/%Y`). It raises
       `ScrapeFetchError` when there is no name or no dates.
     - `parse_division(item) -> Optional[Division]`, with the name as `code`:
       - `^U(\d{1,2})(?:/(\d{1,2}))?\s+(Boys|Girls)\b` reads the ages and gender; `High School (Boys|Girls)\b`
         reads as U15–U19.
       - `players` comes from `SizeDescr` `(\d{1,2})v\d{1,2}`.
       - It returns None for any other shape (reported as a problem), a second age that is not first+1, or an
         age above 19. Unpublished divisions (`Publish` false) are skipped.
     - `parse_standings(rows, division) -> (List[TeamListing], problems)`:
       - Each listing carries `tc_team_id=clean_provider_id(Id)` held to `[1-9][0-9]{0,9}`, `team_name=Name`,
         `club=ClubName`, `location=Location` and `coach=Coach`.
       - Phone and manager fields are never read.
       - A non-list body raises `ScrapeFetchError`; an empty list is allowed.
     - `parse_games(rows, division, source_url) -> (List[EventGame], problems, counts)`:
       - `game_no` is the `Id` and `game_date` comes from `Date` (`%m/%d/%Y`). `game_time` and `venue` are
         stripped.
       - Home is `Team1Id`/`HomeTeamScore`, away `Team2Id`/`VisitingTeamScore`.
       - A game with a missing team id is an "unfilled bracket slot". A negative or non-integer score is "no
         score" (unplayed).
       - Any `Forfeit1/2` or `NoShow1/2` game is skipped and counted under `forfeits`, not imported.
       - `IgnoreResult1/2` games are kept and counted under `ignored_by_standings`.
       - A non-list body raises.
   - **`collect_event(fetch, event_id, board_season, days_back, today, pause, leave_out, states, age_groups,
     genders)`** takes `fetch(path) -> parsed JSON`.
     1. Fetch the summary and the divisions.
     2. For each division, parse it; record a `skip_division` reason or move on.
     3. Fetch its standings and its games, pausing between calls.
     4. Dedupe games across divisions by `game_no`. A crossover game can appear in two divisions; report it
        when the details differ.
     5. Run `label_season_mismatch`, raising `LabelSeasonError`.
     6. Call `build_roster(…, division_age_fallback=True)`.
     7. Window the games by `days_back`, as `tc:1101-1153` does.
     - It returns the `tc` tuple plus the forfeit and ignored counts.
   - **CLI.** `parse_args` takes `--event-url`, `--days-back` (default 14), `--output-dir`, `--delay-min`/`--delay-max`
     (1.0/2.0), `--execute`, `--leave-out`, `--state`, `--age` and `--gender`, the same as `tc:1025-1069`.
     Its validators say "HTG team id".
   - **`main`** mirrors `tc:1156-1277`:
     - Matchers: `HtgSportsGameMatcher`.
     - Provider arguments: `pending_reviews(…, provider_code=PROVIDER_CODE)`,
       `shared_links(…, provider_name=PROVIDER_NAME)`, `register_teams(…, provider_name=PROVIDER_NAME)` and
       `build_csv_rows(…, provider_code=PROVIDER_CODE)`.
     - The team report's first column is renamed `htg_team_id` (`REPORT_COLUMNS[0]` replaced and each row's
       key moved).
     - The summary table is titled "HTG Sports" and adds `forfeits (not imported)` and
       `results the site's standings ignore` rows.
     - The output prefix is `htg{event_id}_{season}_{stamp}`, and the importer subprocess gets
       `PROVIDER_CODE`.
6. **Fixtures**: `tests/fixtures/htgsports/`, captured from the live API for event 14130 by the driver's own
   `fetch_api`.
   - Files: `event_summary.json`, `divisions.json` (trimmed to the divisions used, plus one each of U08,
     High School and U14/15-style), and `standings_<div>.json` plus `games_<div>.json` for U12 Boys Red I
     (Sporting Columbia's) and one 7v7 U10 division.
   - Also `index.html` and `main.js` stubs: small synthetic files carrying the real script-tag and token-line
     shapes with a placeholder GUID `00000000-0000-0000-0000-000000000000`.
   - Scrub before committing. Replace every phone field with `""`, set `Manager` to `""`, and replace each
     `Coach` with `Coach <n>`.
7. **Tests**: `tests/unit/test_import_htgsports_event.py`, plus a matcher identity test in the existing
   registries.
   - URL parsing accepts the hash-route URL and rejects another host and a non-ASCII digit.
   - Token reading covers both bundle shapes, a missing script tag, a missing token, and conflicting tokens.
   - `fetch_api` runs through a `_Session` double that records URL, params, headers, timeout and
     `allow_redirects`, and returns bytes plus a content type. It asserts:
     - the token header is on API calls and on no session-level header;
     - `allow_redirects=False`;
     - a 302, an empty body and HTML-instead-of-JSON all raise;
     - non-ASCII names decode from bytes.
   - Division parsing is parametrized over every name shape in Context. The expected ages, gender and players
     are written as literals.
   - Standings parsing drops nothing but phones. It asserts no phone digits and no manager name reach a
     `TeamListing`.
   - Games parsing covers unplayed `-1`, forfeit and no-show (skipped and counted), ignore-result (kept and
     counted), an unfilled slot, and cross-division dedupe.
   - The `build_roster` fallback, with one row per conjunct:
     - a no-age name in a single-age division takes it;
     - a no-age name in U14/15 is left out;
     - U18/19 → u19;
     - a name with an age in another division keeps the name's age;
     - `--age` beats the fallback;
     - the Tourney Central default (`division_age_fallback=False`) still leaves a no-age name out.
   - A composition test drives `collect_event` over the fixtures through a path-keyed fake fetcher. It finds
     Sporting Columbia 14/15B Navy as u12 Male MO and its four games.
   - A `main` test copies the `run_main` monkeypatch pattern (`tests/unit/test_import_tourneycentral_event.py:1177-1250`),
     patching the HTG module's own bindings. It asserts the literal `"htgsports"` in the CSV `provider`
     column, in the `pending_reviews` filter (through a `_client` double that filters on `provider_id`, so a
     wrong code reads as unsaved), and in the importer argv.
   - A fixture scrub test copies `tests/unit/test_import_demosphere.py:1084-1098`: no phone-number pattern,
     no manager name, and only the placeholder token.
   - Registries: add `htgsports` to the three lists in `tests/unit/test_provider_matcher_dry_run.py` and
     `REGISTRATION_MATCHERS`, and to `_SUBCLASS_PATHS` in `tests/unit/test_birth_year_guard_wiring.py`.
     `tests/unit/test_rematch_game_uid.py` derives from `REMATCH_PROVIDERS`, so it needs nothing.
8. **Docs and backlog.**
   - `CLAUDE.md` Data Providers table: an HTG Sports row (`htgsports`, JSON API with a public page token, one
     event per run via `scripts/import_htgsports_event.py`).
   - `.claude/skills/scraper-patterns/SKILL.md`: an "HTG Sports Pages" section covering the endpoints, the
     token, the field contract, the phone fields to never store, the -1/forfeit/ignore-result flags and the
     no-age division fallback. Update the `:1615-1619` age-rule note to say which drivers turn the fallback
     on.
   - `.claude/skills/merging-duplicate-teams/SKILL.md:179`: add `htgsports` to the operator-run list.
   - `.turbo/improvements.md` IMP-389: add `- **Update (2026-11-09)**:` saying HTG reuses `tc`'s functions
     through provider arguments, and that the other four drivers still keep copies (status stays `open`).
9. **Production provider row and imports** (owner-approved before-merge path). These run after the targeted
   tests and one review pass.
   - Apply step 2's INSERT through `mcp__supabase-write__execute_sql`. Read the row back.
   - Record the ledger with `supabase migration repair --status applied 20261109120000`, run from the
     worktree after copying `C:\PitchRank\supabase\.temp` in.
   - Count `teams`, `team_alias_map` and `games` for provider `htgsports`, and `team_match_review_queue` rows
     with `provider_id = 'htgsports'`, before and after each dry run. They must not move.
   - Dry-run 14130, then 14129, with `--days-back 14`. Show the owner the summary tables, every created team
     outside MO/KS/IA/NE/OK/AR, and every left-out team.
   - On the owner's go, re-run each with `--execute`. Read the rows back: Sporting Columbia's four games are
     stored and linked to its existing PitchRank team.

## Verification

- `python -m pytest tests/unit/test_import_htgsports_event.py tests/unit/test_import_tourneycentral_event.py
  tests/unit/test_provider_matcher_dry_run.py tests/unit/test_birth_year_guard_wiring.py
  tests/unit/test_rematch_game_uid.py -q` passes, and the full gate
  (`python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`) stays green.
- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` is clean.
- Mutation checks. Each mutation must kill a test by name, not merely redden the suite:
  - drop `provider_code` from `pending_reviews` or `build_csv_rows` in the HTG `main` call;
  - put the token on `session.headers`;
  - flip `allow_redirects`;
  - stop skipping forfeits;
  - remove the fallback's single-cohort check;
  - remove the `division_age_fallback=True` argument.
- The production dry run of 14130 lists Sporting Columbia 14/15B Navy as `already_linked` or
  `linked_existing` to its existing PitchRank team, with its four games among "games to import". The before/after counts
  are unchanged.
- After `--execute`: the stored games exist for 2026-11-07 and 11-08 between that team and its four
  opponents, with the right scores. No game for the team is half-matched. The provider's review queue count
  equals the dry run's `review` count.
- Spot-check edge cases in the report CSV: a U14/15 no-age team left out; a forfeit counted, not imported;
  a cross-age game listed in `*_cross_age.csv`.

## Context Files

- `scripts/import_tourneycentral_event.py`: the template whose functions are reused and parameterized.
- `src/models/tourneycentral_matcher.py` and `src/models/demosphere_matcher.py`: the matcher being
  subclassed and the subclass template.
- `scripts/import_soccereventsgroup_event.py:129-230`: the JSON fetch shape.
- `scripts/import_athletes2events_event.py:530-640`: `age_from_name`, `board_cohort`, `split_club` and the
  age reason constants.
- `tests/unit/test_import_tourneycentral_event.py`: fixture, double and `run_main` patterns.
- `tests/unit/test_provider_matcher_dry_run.py`: the registries a new matcher must join.
- `src/etl/enhanced_pipeline.py:380-430`: the provider branch chain.
