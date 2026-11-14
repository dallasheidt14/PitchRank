---
status: done
---

# Plan: Add the Heartland Soccer Premier league as a weekly provider

## Context

Heartland Soccer Association (heartlandsoccer.net) runs the main youth league for Kansas City, with clubs on
both sides of the Kansas/Missouri line. Its league games are not in PitchRank. In Boys U12 Premier
Subdivision 1, each team has about 10 fall league games on the site, while PitchRank holds 3-8 games for each
of those teams, all of them from tournaments. HTG Sports hosts Heartland's tournaments and its futsal league,
but not the outdoor league. The league is published only on Heartland's own CGI pages, so it needs its own
importer.

The owner asked for (2026-11-14):

- Premier only, never Recreational.
- Games dated **2026-08-01 or later**, a fixed floor.
- A scraper and an importer that run weekly on a schedule.
- Decisions the same day:
  - a **new** team, one the matcher would create, whose club's stored teams disagree on state or have none,
    is held for the owner. A team that links to a stored team keeps that team's state;
  - the club-state registry's home (Sporting Blue Valley → KS) decides a new team's state ahead of
    disagreeing clubmates, but only when the home is KS or MO;
  - a name with no age takes its division's age when the division is one cohort;
  - scored games only;
  - the dry run writes its review sheets, as the HTG Sports and Tourney Central importers do.

Measured on 2026-11-14 across every Premier results page:

- **Size:** the driver's walk of every division and subdivisions 1-13 finds 103 subdivisions at U10 and up,
  with 3,762 scored games and 941 teams, dated 2026-08-07 to 2026-10-25. U-9 adds 668 games, which are
  skipped. (A first, stopping walk before the build saw 100 subdivisions, 3,658 games and 915 teams.)
- **Divisions:** every listed game carries a score. Boys Premier stops at U-14/15 in the fall; girls run
  through U-18/19.
- **No age in the name:** about 140 of 941 names state none.
- **Same-day rematches:** none.
- **Club codes:** the site's codes are member organisations, not clubs. `KPSL` alone covers 444 teams across
  dozens of clubs, and 263 teams are "Non Member".
- **Clubs split across the line:** Kansas City Athletics is stored in KS and KC Athletics mostly in MO; Union
  KC 86 KS and 7 MO, with Union KC Soccer Club 60 MO; Sporting City Soccer Club MO and KS.
- **Archives:** season archives keep standings only, so only the current season can be imported.

**Pilot finding (2026-11-14).** A write-guarded production dry run of Boys U-12 alone, under the first
version of step 5, held 64 of 105 teams before matching, so only 21 of 420 games would import:

- 32 "no stored team of this club in KS or MO";
- 17 from registry-curated clubs (Sporting City Soccer Club, KC Legends);
- 15 "club's stored teams disagree".

The Athletes2Events matcher cannot link a team that has no state: `_fuzzy_match_team` returns None when
`state_code` is falsy (`src/models/athletes2events_matcher.py:210`), and `_fetch_candidates` (:184) reads one
state or null. That is why steps 2, 5 and 6 match every team first and hold only a team that would be created.

## Pattern Survey

### Analogous Features

- `scripts/import_demosphere.py` is the skeleton to mirror. It is a weekly league driver with one page per
  division and both teams on each game row (`parse_division_page` :373).
  - It writes held, cross-age and team reports through `_for_spreadsheets`.
  - State comes from stored clubmates within a region: `club_states(supabase, names, region)` (:589).
  - Its own `register_teams` (:723) mirrors Tourney Central's.
  - Conflicts are reported without failing the run.
- `scripts/import_yssl.py`: year inference for year-less dates (`game_date` :332). Its season check
  (`site_season` :309) read a page heading and made the first scheduled run write nothing. Do not copy it.
- `scripts/import_htgsports_event.py` reuses Tourney Central's registration checks and CSV builder, passing
  `provider_code` and `provider_name` at every call.
- `src/models/htgsports_matcher.py` and `src/models/demosphere_matcher.py` both subclass
  `TourneyCentralGameMatcher` (`src/models/tourneycentral_matcher.py:44`). Demosphere's overrides
  `_fuzzy_match_team` and re-returns `{"team_id", "team_name", "confidence"}`, which is the shape to copy.
- `.github/workflows/demosphere-scraper.yml` is the workflow template. It installs `requirements.txt`, not
  `requirements.lock`.

### Reusable Utilities

**From `scripts/import_tourneycentral_event.py`**

- Fetching: `make_session` (:327), `_encoding` (:335), `_fetch` (:358) and `ScrapeFetchError` (:315).
- Age: `_division_fallback(team_name, age_source, division, listed_ages, event_season, board_season)` (:754),
  which refuses a fallback when a team is listed at more than one age.
- Club: `club_for` (:616).
- Registration: `existing_aliases` (:777), `unsaved_links` (:838), `pending_reviews` (:852),
  `unsaved_reviews` (:868), `shared_links` (:881), `off_board_links` (:903) and `teams_by_id` (:929).
- Output: `build_csv_rows` (:954), `write_csv` (:1046) and `_for_spreadsheets` (:1042).
- Data classes: `Division`, `TeamRow`, `Outcome`, `EventGame` and `Event`.
- **Not reusable:**
  - TC's `build_roster` (:653) sorts ids with `int(tc_team_id)` (:685), which `721A` and `2026fall-7210`
    would crash.
  - TC's `register_teams` (:795) reports an exception and a non-match with the same status, `"error"`
    (:819-822, :833-834).

**From `scripts/import_athletes2events_event.py`**

- `age_from_name` (:552) and `board_cohort` (:613). Not `respell_ages` (:541); see step 5.

**From `src/utils/club_state_registry.py`**

- `home_state` (:625) and `requires_review` (:636).

**From `src/models/athletes2events_matcher.py`**

- The create gate (:313): `if not (self.registration_mode and state_code and team_name and age_group and
  gender)`.
- Review rows suppressed for a no-match in registration mode (`_REVIEW_SUPPRESSED_METHODS` :61, applied at
  :123).

### Convention Anchors

- **Provider registration:** a seed migration like `20261109120000_seed_htgsports_provider.sql`, and a branch
  in `EnhancedETLPipeline._ensure_initialized` with `dry_run=self.dry_run` and no `registration_mode`. Stay out
  of `REMATCH_PROVIDERS` and `SCHEDULE_ID_SUFFIX_PROVIDERS`.
- **The game import calls `_match_team` with no state** for both teams (`src/models/game_matcher.py:675-692`).
  A2E's no-state guard is what keeps that import alias-only.
- **Test registries:**
  - `AUTOCREATING_MATCHERS`, the `test_autocreate_writes_nothing_in_dry_run` list and
    `REGISTRATION_MATCHERS` in `tests/unit/test_provider_matcher_dry_run.py`;
  - `_SUBCLASS_PATHS` in `tests/unit/test_birth_year_guard_wiring.py`. Its
    `test_subclass_fuzzy_match_returns_team_name` (:96) requires an overriding `_fuzzy_match_team`'s own
    source to contain a `"team_name"` literal;
  - `AGE_DERIVING_SCRIPTS` and the known-steps test in `tests/unit/test_age_rollover_freeze_coverage.py`;
  - `WRITER_WORKFLOWS` and `APPLIER_SCRIPTS` in `scripts/team_cleanup/apply_stage.py`;
  - the CLAUDE.md workflow table (`tests/unit/test_agent_doc_references.py`).
- **Doubles:** `_DB` / `_Query` in `tests/unit/test_athletes2events_matcher.py` (:25-141).
  - Records at `execute()` and projects columns.
  - Raises PGRST116 on a zero-row `.single()`.
  - `or_` splits on commas.
  - `fail_candidate_query` makes the candidate read raise.

### Proposed Alignment

- Demosphere's driver skeleton.
- Tourney Central's registration checks and CSV builder.
- The driver's own `build_roster` and `register_teams`.
- A `TourneyCentralGameMatcher` subclass with a registration-only KS/MO candidate search.
- A Demosphere-shaped workflow.
- The usual registries.

## Implementation Steps

0. **Baseline**
   - Work on a branch off `origin/main`. If `origin/main` moves, run `git merge origin/main`; never rebase or
     force-push.
   - The worktree has no `.env`. Load `C:\PitchRank\.env` inside a runner for production dry runs, and never
     copy or edit an env file.

1. **Provider seed migration**
   - `supabase/migrations/20261114120000_seed_heartland_provider.sql` inserts
     `('heartland', 'Heartland Soccer', 'https://heartlandsoccer.net')`, `ON CONFLICT (code) DO NOTHING`.
   - The owner applies it by hand and repairs the ledger.

2. **Matcher: `src/models/heartland_matcher.py`**
   - `HeartlandGameMatcher(TourneyCentralGameMatcher)`, with `REGION = ("KS", "MO")` and a module marker
     `REGION_SEARCH = "KS/MO"`. The marker is a string that equals no stored state and is never a state code.
   - **`_candidate_state_filter(state_code)`**, a hook added to `Athletes2EventsGameMatcher` and read by its
     `_fetch_candidates`, so the paged candidate read stays A2E's own (its default returns the existing
     `state_code.eq.<state>,state_code.is.null`):
     - in `registration_mode`, return `state_code.eq.KS,state_code.eq.MO,state_code.is.null`, whatever
       `state_code` is;
     - outside it, delegate to `super()`.
   - **`_fuzzy_match_team(team_name, age_group, gender, club_name=None, state_code=None)`:**
     - in `registration_mode`, call `super()._fuzzy_match_team(..., state_code or REGION_SEARCH)` and
       re-return `{"team_id": ..., "team_name": ..., "confidence": ...}` as Demosphere's does, so the source
       carries the `"team_name"` literal the guard test reads;
     - outside it, delegate unchanged (A2E returns None with no state, so the game import stays alias-only).
   - **Effect of the marker:**
     - A team with a resolved state keeps its own state's location score and tie-break, so it prefers its own
       state's twin.
     - A stateless team scores every candidate's location the same, and its tie-break is neutral, because the
       marker equals no `state_code` (`game_matcher.py:1647-1651`, `athletes2events_matcher.py:259-262`). Two
       equally good candidates in different states, or one with no state, then tie and go to review at 0.89.
   - **`_match_team` is not overridden.**
     - A stateless team reaches A2E's create gate (:313) with `state_code=None` and is never created.
     - A ≥0.90 match links.
     - A 0.75-0.90 match writes one pending review row on `--execute`.
     - A no-match writes nothing (`_REVIEW_SUPPRESSED_METHODS`).
     - The marker must never be passed to `_match_team`: any truthy state there opens the create gate.

3. **Pipeline branch**
   - Add an `elif self.provider_code.lower() == "heartland":` branch to `EnhancedETLPipeline._ensure_initialized`
     that mirrors `htgsports` exactly: no `registration_mode`, `dry_run=self.dry_run`.

4. **Driver: page fetch and parse (`scripts/import_heartland.py`)**
   - Constants: `PROVIDER_CODE = "heartland"`, `OUTPUT_DIR = Path("data/raw/heartland")` and `RESULTS_URL`.
     - `DIVISIONS` is every age from U-10 to U-18/19 for both genders as the site's form spells them
       (`U-14/15`, `U-18/19`). U-9 is left out.
     - Boys U-15 to U-18/19 return error pages this fall. They are walked anyway, about 52 cheap requests, so
       a spring season that runs them is not silently missed.
   - Fetch only `subdiv_results.cgi`, with `level=Premier`, subdivisions 1-13, pausing a random 1.0-1.8 s.
     - Never build the Recreational form (`level=Recreational`, `b_g1`, `age1`).
     - Never fetch `seedings.cgi`, `team_results.cgi` or the member-clubs page: they list coaches', managers'
       and officers' names, emails and phone numbers.
   - `parse_results_page(html, gender, age, subdivision, season)` returns a `ResultsPage` with two team maps:
     - `teams`: the subdivision's own team list, from `table.text` (a page without one raises `ScrapeFetchError`);
     - `opponents`: teams seen only in its game rows (`table.seasonborder`, `tr.text`).
     - The "Select Subdivision Error" page returns None. A 200 page with neither it nor a results table raises
       `ScrapeFetchError`.
     - Team cells read `<4-char number> <name>` (`^[0-9A-Z]{4}\s+`, ASCII); the number is cut off before name
       parsing.
     - A blank date cell carries the previous one forward. A row of the wrong shape clears it, since it may
       have been the first game of a new day.
     - A row whose two scores are both blank is counted as unscored. A non-digit score, or one blank and one
       not, is a problem.
   - `game_date(label, season)` reads `Aug 9 (Sun)`; the site writes Thursday `Thr`, and `Thu`/`Thur`/`Thurs`
     are accepted.
     - The date's year is the season's year for its month: the start year for August-December, the next year
       for January-July.
     - Failing that, the year before, which covers a site still showing last season after Aug 1.
     - Exactly one of the two must fall on the printed weekday; otherwise the row is unreadable.
     - A fall date never moves into the next season (Aug 9, 2027 is a Monday, so `Aug 9 (Mon)` is unreadable
       in 2026).
   - `half_season(game_dates)` gives `<year>fall` or `<year>spring` from the games themselves. More than one
     half in a run is a problem.
   - Provider team id: `f"{half}-{team_number}"` (`2026fall-7210`).

5. **Driver: roster (`build_roster`, the driver's own)**
   - Each team number's division comes from the **roster tables** only.
     - Collect every `(young_age, old_age)` a number is listed at, and pass that set to TC's
       `_division_fallback`, which refuses the fallback for a team listed at two ages.
     - A team seen only in another division's game rows takes no division from them. One listed on no roster
       table is left out with "not on any subdivision's team list".
   - Age: `age_from_name(name, None, event_season)`, then `_division_fallback` for a name with no age (owner,
     2026-11-14). The name is not respelled before `age_from_name`: Heartland writes bare and glued numbers
     (`10B`, `15`) as U-ages as
     often as birth years, and respelled, 5 of 941 fall-2026 names read two to seven boards above their division.
     U-14/15 is two cohorts and U-18/19 is one. A name stating two U-ages is left out (owner, 2026-09-18),
     except two on one board, `U18/19`, which is u19 (owner, 2026-11-14; `one_board_u_ages`). `board_cohort`
     drops anything below U10. Gender is the division's.
   - Club: `club_for_team(name)` takes the longest `HEARTLAND_CLUBS` prefix at a word boundary, case-insensitive,
     and otherwise TC's `club_for("", name, HOST)`.
     - Each `HeartlandClub` entry has `stored`, `spellings` (other stored names of the same club) and an
       optional owner-set `state`.
     - Entries come from stored KS/MO teams' `club_name` (2026-11-14) and are listed for the owner at the
       dry-run review.
   - **`resolve_state(club_name, club, stored)` is the state a team would be created with.** It is not a
     roster filter. In order:
     1. the entry's owner-set state;
     2. `home_state(club_name)`, accepted only when it is KS or MO (owner, 2026-11-14);
     3. `requires_review(club_name)`, which gives None with "the club-state registry asks a person to pick this
        club's state";
     4. the one state the club's stored teams agree on within KS and MO, pooled over `club_name` and every
        spelling. Any disagreement gives None with "the club's stored teams disagree on state";
     5. otherwise None with "no stored team of this club in KS or MO".
   - **No team is left out for its state.**
     - Every team on a team list with an age, a board and a club goes to registration, and `state_code` may
       be None.
     - Left-out reasons are "not on any subdivision's team list", the age reason, "on no U10-U19 board" and
       "no club could be read from the name".

6. **Driver: registration, games CSV and import**
   - The driver's own `register_teams(matcher, provider_id, roster, already)` mirrors TC's, and classifies:
     - an exception gives `error`, which stays red;
     - `created` gives `created`; `relinked` gives `relinked`;
     - `matched` gives `linked_existing` or `already_linked`; `review` gives `review`;
     - a non-match for a row with **no** `state_code` gives **`held`**, with the row's `state_source` as its
       reason;
     - a non-match for a row with a state gives `error` ("unclassified result").
   - Use it for both the dry-run preview and the execute pass, with `shared_links`, `unsaved_links` and
     `unsaved_reviews` called as HTG's driver calls them (`provider_code="heartland"`,
     `provider_name="Heartland Soccer"`).
   - `held` is not in `LINKED_OUTCOMES`, so TC's `build_csv_rows` holds every game with a held team on either
     side.
     - `held_rows` gives each held game its reason: "a team is held for its state: <reason>", "a team is left
       out: <reason>" or "a team is not linked: <status>".
     - The summary table adds a `held` row. Held teams and conflicts are yellow and never fail the run.
   - Games: scored games dated `since` to today, read once per game number. A number listed twice with
     different details is a problem, and neither version is imported.
     - `since` is `max(args.since or date(event_season, 8, 1), MIN_GAME_DATE)`, with
       `MIN_GAME_DATE = date(2026, 8, 1)` (owner, 2026-11-14). A retained spring-2026 page read after Aug 1
       can therefore never import.
     - `schedule_id` is `heartland-<half>-<game no>`, and the competition name is
       "Heartland Soccer Premier League <Fall|Spring> <year>" through TC's `Event`.
   - CSVs are written on dry runs too, through `_for_spreadsheets`: `<half>_<stamp>_games.csv`, `_held.csv`,
     `_cross_age.csv` and `_teams.csv`. The team report has `state_source` and no coach column.
   - The run fails (exit 1) on any of:
     - a fetch failure;
     - an unreadable row or team;
     - a game number listed twice with different details;
     - two halves in one run;
     - a link error;
     - a missing environment or `providers` row.
   - `--execute` runs `import_games_enhanced.py <csv> heartland` and returns its code, or 1 when the run
     failed for one of the reasons above. `Games scraped: N (M
     played)` is printed for the workflow check.

7. **Weekly workflow: `.github/workflows/heartland-scraper.yml`**
   - Copy `demosphere-scraper.yml`, keeping its `pip install -r requirements.txt` (not the lock file, unlike
     `ci.yml`).
   - Preserve:
     - `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}`;
     - the `tee run.log`, the step summary, the artifact upload of `data/raw/heartland/` (30 days) and the
       concurrency group;
     - `AGE_ROLLOVER_FREEZE: 'false'` with the `== 'false'` step gate.
   - Inputs: `since` and `dry_run`. Cron `45 8 * * 1` (Monday 08:45 UTC).
   - The zero-games red check covers September, October, April and May.

8. **Registries and docs**
   - The registries listed under Convention Anchors.
   - `CLAUDE.md`:
     - a provider row and a workflow row. They say a **new** team whose club has no settled state is held,
       and that a held team does not turn the run red;
     - the rollover re-arm list;
     - the state-stamping paragraph;
     - the dry-run exception (owner, 2026-11-14).
   - A "Heartland Soccer Pages" section in `.claude/skills/scraper-patterns/SKILL.md` with the same "new team"
     wording.

9. **Tests**
   - **`tests/unit/test_import_heartland.py`** (driver, fixtures under `tests/fixtures/heartland/`; the error
     page's administrator email is replaced by `person@example.com`).
     - Parser: the team number is cut off; `7213 ... 14/15` reads U12; the date carries forward; unscored vs
       unreadable scores; the error page vs a page with no table.
     - Weekday-year cases, including `Oct 15 (Thr)` read in season 2027 as 2026, `Mar 7 (Sun)` in 2026 and in
       2027 as 2027, and `Aug 9 (Mon)` in 2026 as unreadable.
     - Roster:
       - the division fallback, including a U-14/15 no-age name;
       - a team listed at two ages refused the fallback;
       - a game-row-only team gets no division;
       - each `resolve_state` branch, with fixtures violating one condition each, including a non-KS/MO
         registry home refused;
       - a stateless team **in scope**.
     - `register_teams`:
       - a stateless non-match gives `held`;
       - a stated non-match gives `error`;
       - an exception gives `error`;
       - a review stays `review`.
     - `held_rows` reasons, and the floor (a `--since 2025-08-01` run imports nothing before 2026-08-01).
   - **`TestRunMain`** drives `main` with a fake `_fetch` serving fixtures and recording URLs.
     - Its `FakeMatcher` refuses to create when `state_code` is falsy, returning an unmatched result as
       production does.
     - Assert:
       - only `subdiv_results.cgi` with `level=Premier` is fetched;
       - a dry run builds one dry-run matcher and starts no import;
       - `--execute` imports once under `heartland`;
       - a held team's games are held and the run exits 0;
       - conflicts are reported without failing;
       - an unsaved alias, an off-board link, an unreadable page and an unreadable score fail.
   - **`tests/unit/test_heartland_matcher.py`** uses the real `HeartlandGameMatcher` on the A2E `_DB` double,
     which records at `execute()`, in registration mode. It covers:
     - a stateless team with a KS stored twin links, and writes no `teams` row;
     - a stateless no-match writes no `teams`, alias or review rows;
     - a stateless 0.75-0.90 match writes exactly one review row on a non-dry run;
     - a stateless team with equal KS and MO twins goes to review at 0.89;
     - a KS team with equal KS and MO twins links to the KS one;
     - a stated team with no match is created;
     - the candidate read carries the KS/MO/null `or_`;
     - a raising candidate read (`fail_candidate_query`) raises;
     - outside registration mode a stateless team reads no `teams` candidates (alias-only).
   - **One main-level composition test** runs `main` with the real `HeartlandGameMatcher` over the same double
     (Supabase client replaced by `_DB`, `_fetch` serving the U-12 fixture). A stateless team with a stored
     twin is linked and its games reach the CSV; a stateless team with none is `held` and its games are held,
     in both dry-run and `--execute` modes.
   - **Mutations**, one line each, each of which must fail a named new test:
     - restore the pre-match state hold;
     - narrow the `or_` to one state;
     - pass a real state (`"KS"`) in place of the marker;
     - drop the `registration_mode` gate;
     - classify `held` by status;
     - drop `MIN_GAME_DATE`;
     - collapse `listed_ages` to the first division;
     - accept a registry home outside KS/MO.

## Verification

- The CI gate commands, run locally (`python -m ruff check src/ scripts/ config/ tournament_intake.py
  dashboard.py`; `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`).
- **Production dry run, write-guarded.** Run the importer against production with every non-GET request
  refused and recorded. The runner stubs only the `providers` lookup until the seed row exists.
  - Expect 0 refused requests.
  - Expect about 3,762 games in the window and 941 teams.
  - No Recreational or U-9 URL appears.
- **Read the team report.**
  - Count `held` teams by reason. They should now be only teams with no stored twin, far fewer than the
    pilot's 64 of 105.
  - Every `created` row's `state_code` must be KS or MO, from a table entry, a KS/MO registry home or agreeing
    clubmates.
  - Read twenty linked rows beside their stored names, including stateless ones.
- **Near-duplicate check for created rows.** Before `--execute`, compare every `created` row with live teams
  of the same age and gender in KS, MO or null state, at `similarity >= 0.55`, and show the hits to the owner.
- **Double-store check.** For linked games, count stored games from other providers on the same date between
  the same two master teams. Expect 0.
- **Ranking blast radius**, read-only, for the PR: how many games are added, how many teams gain games, and how
  many cross `MIN_GAMES_PROVISIONAL` (10) upward.
- **After the owner applies the seed and approves**, the owner runs `--execute` locally. Confirm from the data:
  - `heartland` games dated 2026-08-01 or later;
  - none half-matched;
  - approved aliases equal linked plus created;
  - held teams have no alias.
- **First GitHub run.** After merge, dispatch `heartland-scraper.yml` with `dry_run=true` to confirm GitHub's
  runners can reach the site. Check the first scheduled Monday run from the data.

## As built (2026-11-14)

- Built as the steps describe.
- **Write-guarded production dry run (2026-11-14),** before review round one's age changes (no
  `respell_ages`; `U18/19` on u19), so a fresh dry run precedes the owner's review sheet. It ran in four
  foreground chunks
  after the system's memory reaper stopped a single background run. Results:
  - 0 non-GET requests across 6,357 reads, and 0 errors;
  - 3,762 scored games in 103 subdivisions, and 941 teams;
  - outcomes: 326 linked, 104 created (86 KS, 18 MO), 122 review, 82 conflict, 274 held and 33 left out.
    Chunking hides conflicts between chunks; the single real run sees them;
  - held reasons: 203 "no stored team of this club in KS or MO", 40 registry-curated (Sporting City 22,
    KC Legends 18) and 31 "stored teams disagree" (Union KC, KC Athletics, KC Surf);
  - 785 of 3,762 games import on a first run, because a game imports only when both teams are placed;
  - reports are under `C:\PitchRank\data\raw\heartland\2026fall_20261114_10*`.
- **Blast radius**, read-only, with games resolved by master id and no merge folding: the first import adds
  1,222 team-games (a game counts once for each existing team it reaches) to 323 existing teams, and 45 of
  them cross `MIN_GAMES_PROVISIONAL` (10) upward.
- **Owner decision (2026-11-14):** ship as is, then a review sheet of the held clubs. Each club the owner
  marks KS or MO goes into `HEARTLAND_CLUBS` and releases its teams on the next run.

## Context Files

- `scripts/import_demosphere.py`: the skeleton, `club_states`, its own `register_teams` and exit policy.
- `scripts/import_tourneycentral_event.py`: the registration helpers, `_division_fallback` and the CSV builder
  being reused.
- `scripts/import_htgsports_event.py`: provider arguments threaded through the shared helpers.
- `src/models/athletes2events_matcher.py` and `src/models/tourneycentral_matcher.py`: candidate fetch, fuzzy
  match, the create gate and review suppression the override relies on.
- `src/models/demosphere_matcher.py`: the `_fuzzy_match_team` override shape.
- `src/utils/club_state_registry.py`: `home_state` and `requires_review`.
- `tests/unit/test_athletes2events_matcher.py`: the `_DB` double.
- `tests/unit/test_import_demosphere.py`: `TestRunMain` and the fixture privacy tests.
- `.github/workflows/demosphere-scraper.yml`: the workflow template.
- `.claude/skills/scraper-patterns/SKILL.md`: the "HTG Sports Pages", "Demosphere Pages" and near-duplicate
  check sections.
