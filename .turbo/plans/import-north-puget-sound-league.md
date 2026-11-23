---
status: done
---

# Plan: Import the North Puget Sound League (Demosphere site 74274)

## Context

The North Puget Sound League is a Washington youth league on Demosphere ("Elements") whose games PitchRank does
not import. Its teams whose GotSport record carries no games this season hold almost nothing in PitchRank and
cannot be ranked, however many league games they play. Most of the league's teams already exist in PitchRank as
GotSport teams; their league games are missing too.

IMP-191 deferred this until the league published scores. It now does: the BU16 Division 1 schedule page shows
played results (`2-2`, `4-0`, ...) in `td.sch-main-sc`, verified 2026-11-22. `scripts/import_demosphere.py`
already scrapes NCSL (site 80738) by walking outward from a seed club, so NPSL is a second `LEAGUES` row plus the
fixes that let the driver read a site other than NCSL. The outcome is NPSL's Fall 2026 games imported every
Monday alongside NCSL's, and IMP-191 closed.

**Owner decisions (2026-11-22):**
- **Fall 2026 only.** NPSL also runs a Winter 2026-27 season (older girls; season key `116592460`, no games
  played yet). It is a follow-up, built once it has scores. Note it as a new backlog entry.
- **This season only**: games on or after 2026-08-01, the NCSL rule. No back-fill of Spring 2026 or Fall 2025.
- **Label: "North Puget Sound League"**, not "NPSL". The repo's SEO notes use "NPSL" for the adult National
  Premier Soccer League (`.turbo/seo/league-comparison-sources.md:72`), and `League.name` becomes each game's
  `competition` / `event_name` (`scripts/import_demosphere.py:902-904`).

**Decided here (technical):** seed club Northshore Select Club (club key `77067129`, 54 Fall 2026 teams across
BU9-BU19; its `clubs/schedule/` page lists Fall 2026 divisions). Region `states=("WA",)`. No association clubs.
Same `demosphere` provider row and matcher.

**What the live pages showed (2026-11-22, a few polite fetches):**
- Division pages have `table#tblListGames2`, `tr.gm-hdr-5d1h` day rows ("Sun, September 13, 2026"),
  `tr.sch-main-gm` games with `data-gamekey`, `td.schedtm1/2` with `data-tmkey`/`data-cbkey`, and scores in
  `td.sch-main-sc`. Column-header rows are `tr.gm-hdr-5d1ha`, which the parser already skips.
- **No `var tgname`.** The division name is only in `td.hdr` ("BU16 Division 1"). The driver reads the name only
  from `tgname` (`_DIVISION_NAME`, `:198`, used at `:375`), so on NPSL every team would get a blank division. That
  loses the division's age bound and fallback, and its gender, which is the only gender source a team without a
  team code has. Concrete harm: NSC lists `NSC B10A` among its BU9/BU10 teams, so it is a U10 squad. With no division
  bound, `B10` reads as birth year 2010 and the team lands on U16/U17.
- **No team codes.** NPSL team cells carry only the name (`NSC BU16B`), where NCSL's open with a code
  (`NG14107 ...`). `_TEAM_CODE` (`^[A-Z]{1,3}\d+$`, `:197`) strips any first word of that shape, so an NPSL name
  opening with `B10` or `U13` would lose its age.
- Club headers are clean names (`Northshore Select Club`, `Rainier Soccer Alliance`, `Norpoint FC`). Some match
  PitchRank's stored spelling. `Norpoint FC` against GotSport's `Norpoint SC` does not, which is what the
  owner-decided club map settles.
- Club pages list six seasons' teams. Only the season key read from the seed page is walked, which leaves Winter
  out as decided.

## Pattern Survey

Survey of `origin/main` @ a736e9268, 2026-11-22. NPSL page facts above were verified live on top of it.

### Analogous Features

- **The driver is configured per site in `scripts/import_demosphere.py`.**
  - `League(name, state_code, seed_clubs, association_clubs=(), states=(), club_overrides={})` (`:211-218`).
    `:244-246` holds the one row, `"80738": League("NCSL","VA",("15599479",),("15599479",),("VA","MD","DC","WV","DE"),NCSL_CLUBS)`.
  - `NCSL_CLUBS` (`:223-242`) is the owner-decided map from listed club to `(stored club, forced state or None)`.
  - `--site-id` defaults to `"80738"` with `choices=sorted(LEAGUES)` (`:976`), and `league = LEAGUES[args.site_id]`
    (`:1003`).
- **The walk.** `collect_league` (`:432-470`) fetches `clubs/schedule/<seed_clubs[0]>.html` once. That page proves
  the season is listed (`SeasonNotListedError`) and supplies `season_key` (`:350-353`, the most common key in its
  team links). From there it goes breadth-first: club page, its divisions in that season, each team's `data-cbkey`
  club. There is no division index.
- **Seasons.** `season_start_year` takes `Fall<yr>`/`Spring<yr>` only (`_SEASON_LABEL`, `:204`).
  `current_season_label` (`:485`) treats month 8 or later as Fall, and `season_candidates` (`:491`) tries the current
  season, then the one before.
- **Ids.** The provider team id is `<site>-<season>-<teamkey>` (`:503-504`) and the schedule id is
  `demosphere-<site>-<gamekey>` (`:901`). Both include the site, so two sites cannot collide.
- **Windows.** `--since` defaults to Aug 1 of the season (`:1050`). `--days-forward` defaults to 28 (`:106`), so an
  unscored game inside that window becomes a `U` fixture (`:857-860`).
- **Age.** `team_age` (`:542-563`): the division's U-age (`_DIVISION_AGE` `\b([BG])U(\d{1,2})\b`, `:199`) bounds the
  name and fills in for it. `respell_ages` always runs (`:553`, and in `club_for` at `:532`). `team_cohort`
  (`:566-578`) leaves out anything outside u10-u19 (`:703`).
- **Gender.** `team_gender` (`:581-586`) reads the division, then the team code (`_CODE_GENDER` `^N([BG])\d`,
  `:202`, NCSL codes only).
- **Club.** `club_for` (`:520-539`): the listed club through `stored_club` (`:507-509`) for an ordinary club, and
  the club cut from the name for an association club. Overrides apply in both branches.
- **State.** `club_states` (`:589-622`) finds the single state a club's stored teams agree on, matching `club_name`
  exactly and limited to `League.states` (`:619`). `resolve_state` (`:625-648`): another state's tag in the name is
  held, then the forced state, then the club's agreed state, then the league's.
- **Holds.** `shared_links` (`:762-781`, conflict, reported, not red, `:1118`), `pending_reviews` (`:784-797`),
  `off_board_links` (`:800-823`), and the cross-age file (`:897-898`). `main` runs a dry-run preview, then the
  writer, then the import subprocess (`:1074-1154`).

**NCSL assumptions that misbehave on a second site:**
1. `_TEAM_CODE` (`:197`, `:362-363`) strips a code-shaped first word.
2. `_CODE_GENDER` (`:202`) matches NCSL codes only.
3. `_LISTED_CLUB_SUFFIX` (`:206`) strips NCSL's listing tags (`- Travel`, `- N1`).
4. The association/VISTA logic (`:536`, `:668`, `:681`).
5. `League.states` defaults to `()`, meaning no region, so every state votes.
6. `respell_ages` runs unconditionally. It is meant to be opt-in per provider
   (`import_athletes2events_event.py:563-568`); see Heartland's opt-out (`import_heartland.py:23-28`).
7. NCSL is written into the wording: `:5`, `:38`, `:1138`; the workflow's step name (`:58`) and summary (`:100`);
   `scripts/investigate_missing_game_requests.py:137`; the freeze-test comment
   (`tests/unit/test_age_rollover_freeze_coverage.py:38`); and CLAUDE.md rows.
8. Output files (`{stamp}_games.csv` etc., `:1105-1109`) share `data/raw/demosphere` with no site id.
9. Page shapes were verified on NCSL only (`:342-426`), and a missing score cell reads as unplayed (`_UNPLAYED`,
   `:192`). NPSL verified 2026-11-22 above, except `var tgname`, which NPSL lacks.

- **Workflow (`.github/workflows/demosphere-scraper.yml`).**
  - One job and one writing step (`:58-93`), gated by `if: ${{ env.AGE_ROLLOVER_FREEZE == 'false' }}`.
  - It passes no `--site-id`, runs under `set -euo pipefail`, and `tee` overwrites `run.log`.
  - The zero-played check (`:88-93`) greps one `Games scraped:` line.
  - The summary `sed`s from `(Demosphere)` (`:102`). Artifact `demosphere-${{ github.run_id }}` (`:107-114`), concurrency
    group `demosphere-scraper`, cron `23 5 * * 1`, timeout 120 minutes.
- **Matcher and import routing.**
  - `src/models/demosphere_matcher.py:29-45` subclasses `TourneyCentralGameMatcher` and adds only `expand_club_code`
    (NCSL club codes such as `HERN`).
  - Team creation is in `src/models/tourneycentral_matcher.py:74-118` and is gated on `dry_run`. Alias and review
    writes are gated on `dry_run` too (`game_matcher.py:1706`, `:1778`).
  - `enhanced_pipeline.py:416-426` routes `demosphere` and passes `dry_run`. The seed migration
    `20261029120000_seed_demosphere_provider.sql` makes one provider row for every Demosphere site.
- **Several leagues through one driver.**
  - Affinity OR/UT/HI/GA give each state its own provider, matcher and workflow. That does not fit here, since the
    provider is the same across sites.
  - PlayMetrics loops a league list in one step with per-league failure counts (`playmetrics-scrape-import.yml:66-130`).
  - EA runs the same scripts per age as a matrix with `fail-fast: false, max-parallel: 1` (`ea-scraper.yml:41-48`),
    with its writing steps freeze-gated.
  - Heartland imports `club_states` from this driver (`scripts/import_heartland.py:73`), so a change to that
    function's signature reaches Heartland.

### Reusable Utilities

- `scripts/import_athletes2events_event.py`:
  - `age_from_name` (`:574-632`), `board_cohort` (`:635-644`), `split_club` (`:647-662`), `respell_ages` (`:563`);
  - the roster helpers `existing_aliases`, `unsaved_links`, `unsaved_reviews`, `teams_by_id` and `write_csv`.
- `scripts/import_tourneycentral_event.py`: `pending_reviews`, `shared_links` and `build_csv_rows`, which take
  provider arguments.
- `src/utils/team_utils.py`: `calculate_age_group_from_band`, `calculate_age_group_from_birth_year`.
- `src/utils/placeholder_clubs.py`: `is_placeholder_club`, already used by `club_states`.
- The club gate: `src/models/squad_name_gates.py` `is_same_club`, which calls `src/utils/club_normalizer.py`
  `are_same_club`.

### Convention Anchors

- **Driver tests.** `tests/unit/test_import_demosphere.py` (1,812 lines) covers parsing, the walk, the
  club/age/gender/state rules, CSV rows, the holds and `main` end to end through `run_main`. Its fakes are NCSL-bound:
  `pages()` is keyed on seed `15599479` (`:1148-1159`), `_roster` hardcodes `"80738"`/`"VA"` (`:434-449`), and
  `NCSL_CLUBS` is pinned exactly (`:1780-1799`).
- **Fixtures.** `tests/fixtures/demosphere/` scrubs contact names, emails and phones to placeholders, and a test
  enforces it.
- **Freeze test.** `test_age_rollover_freeze_coverage.py` detects writing steps by `import_demosphere.py` plus
  `--execute` (`:39`, `:61`). A matrix step for the same script is picked up automatically, but must carry the gate
  with no top-level `||`.
- **Team-cleanup apply stage.** `scripts/team_cleanup/apply_stage.py` lists `demosphere-scraper.yml` (`:221`) and
  `import_demosphere.py` (`:269`), and fixes `HARD_STOP_AT` at `:198`. Staying in this workflow and cron keeps both
  correct.
- **Docs that change together:** CLAUDE.md (Data Providers row, workflow table row) and
  `.claude/skills/scraper-patterns/SKILL.md`, section "Demosphere Pages".
- **Closing IMP-191** in the same PR: set `done`, add `Refs`, and cut the entry into `.turbo/improvements-archive.md`
  by hand. Do not run the sweep script.

### Proposed Alignment

- Add one `LEAGUES` row for `74274` with its own seed club, `states=("WA",)` and an owner-decided `NPSL_CLUBS` map.
  Keep the single `demosphere` provider and matcher.
- Make the NCSL-only behaviour per-league: team codes, code gender and listing suffixes.
- Read the division name from `td.hdr` when `var tgname` is absent.
- Run the second site inside `demosphere-scraper.yml` as an EA-style matrix, so each site gets its own log,
  zero-played check, summary and artifact.

## Implementation Steps

0. **Branch from `origin/main` in a worktree.**
   - `C:\PitchRank` sits on an unrelated branch, 48 commits behind `origin/main` as of 2026-11-22. It holds staged and
     unstaged unrelated edits to `.turbo/improvements.md`, a file this change must edit to close IMP-191.
   - That is CLAUDE.md's worktree exception, so create a worktree off `origin/main`. Never stash or unstage that work.
   - Before editing, confirm with `git -C <worktree> diff --stat origin/main` that the worktree is clean.
   - The worktree has no `.env`, so run the production dry run (step 7) from it with the main checkout's root `.env`
     supplied by path.

1. **Read the division name from `td.hdr` as a fallback** (`scripts/import_demosphere.py` `parse_division_page`,
   `:373`).
   - Keep `_DIVISION_NAME` (`var tgname`) first. Fall back to the first `td.hdr` text, cleaned with `_clean_name`
     (`&nbsp;` and runs of whitespace collapsed).
   - A division page yielding neither should add a page problem rather than pass a blank name silently. A blank
     division drops the age bound and gender for every team on the page.

2. **Make the NCSL-specific readers per-league.**
   - Add `League` fields with NCSL's current behaviour as the NCSL row's values: `team_codes: bool` and
     `listed_club_suffix: Optional[Pattern]`.
   - `_team_stub` (`:355-370`) strips a code only when the league has team codes. `team_gender` (`:581-586`) uses
     `_CODE_GENDER` only then.
   - Thread the league into `parse_division_page` / `_team_stub` the way `collect_league` already receives it. Keep
     every existing NCSL test passing unchanged; that is the check nothing moved for NCSL.

3. **Add the NPSL row** (`scripts/import_demosphere.py:244-246`).
   - `"74274": League("North Puget Sound League", "WA", ("77067129",), (), ("WA",), NPSL_CLUBS, team_codes=False, listed_club_suffix=None)`.
   - Start with an empty `NPSL_CLUBS`, filled in step 8 from the owner's decisions, the same way `NCSL_CLUBS` was on
     2026-10-30.
   - Generalise the NCSL wording at `:5`, `:38` and `:1138` ("another squad from this league") and in the docstring
     usage line.

4. **Name output files per site** (`:1105-1109`): put the site id in the stamp (`{stamp}_{site}_games.csv` etc.) so a
   local run of both sites cannot read the wrong CSV. Check every reader of these names, the workflow's `run.log`
   included.

5. **Run both sites from `demosphere-scraper.yml`.**
   - Turn the job into a matrix over `site: ["80738", "74274"]` with `fail-fast: false, max-parallel: 1`, as in
     `ea-scraper.yml:41-48`.
   - Pass `--site-id "${{ matrix.site }}"`.
   - Write `run-${{ matrix.site }}.log`, name the artifact `demosphere-${{ matrix.site }}-${{ github.run_id }}`, and
     make the summary heading say which league.
   - Keep the per-leg zero-played check as it is, now reading its own leg's log.
   - **Preserve from the current file:** the cron and its comment, `workflow_dispatch` inputs (`season`, `since`,
     `dry_run`), the `AGE_ROLLOVER_FREEZE` env, its comment and the step gate (no top-level `||`), the concurrency
     group, `timeout-minutes: 120`, the env secrets block, `set -euo pipefail`, the season-to-date comment and
     `mkdir -p data/raw/demosphere`.
   - Rename the step from "Scrape NCSL ..." to one naming the matrix site.
   - Max-parallel 1 keeps the two sites from writing at once, and the apply stage's writer list needs no change since
     the file name stays.

6. **Tests** (`tests/unit/test_import_demosphere.py`, `tests/fixtures/demosphere/`).
   - Capture an NPSL division page (BU16 Division 1, `116590805`), the seed club page and its `clubs/schedule/` page
     as fixtures. Scrub every contact name, email and phone to the existing placeholders; the existing test enforces
     this.
   - Pin with literal expected values:
     - the division name read from `td.hdr`;
     - a name not losing a code-shaped first word on NPSL while NCSL still strips one;
     - gender from the division on NPSL;
     - `NSC B10A` in a BU10 division filed U10;
     - a bare `B10` in a BU16 division filed U16;
     - the NPSL `LEAGUES` row's literal fields.
   - Parametrize the NCSL-bound fakes (`pages()`, `_roster`) by site rather than duplicating them.
   - Each new test must fail when its half of the change is reverted on its own: revert the `td.hdr` fallback and the
     per-league team-code switch separately.

7. **Production dry run, NPSL only, writing nothing.**
   - Run `python scripts/import_demosphere.py --site-id 74274` (no `--execute`). Run it the way
     `smoke-test-importer-dry-run-against-production` describes: write guard on, beside an `origin/main` control.
   - Count `teams`, `team_alias_map`, `team_match_review_queue` and `games` rows for provider `demosphere` before and
     after, and show zero writes.
   - Read the team report as a person would: linked, created, held and left-out counts, and the created teams' ages,
     genders and states, with the matcher's create payload printed rather than trusting the count.
   - Run the near-duplicate query from scraper-patterns ("Check a roster pass's new teams for near-duplicates before
     `--execute`") over the would-create list.
   - Note any link to an `affinity_wa` row whose `club_name` is a squad name ("Norpoint Road Warriors BU14").

8. **Owner settles the clubs, then the map is written.**
   - Give the owner a numbered list of NPSL teams that did not link, grouped by listed club, with the candidate
     PitchRank team beside each. That is the format the owner settles clubs in, not a club quiz.
   - Include listed clubs whose name differs from the stored WA spelling (`Norpoint FC` against `Norpoint SC`).
   - Write the answers into `NPSL_CLUBS`, and any per-team links the owner names as approved aliases. Re-run step 7
     until the report shows only intended creates.

9. **Docs and backlog, in the same PR.**
   - CLAUDE.md: the Demosphere provider row (add North Puget Sound League, site 74274) and the workflow table row
     (both sites).
   - `.claude/skills/scraper-patterns/SKILL.md` "Demosphere Pages": the `td.hdr` division name, no team codes on
     NPSL, the Winter season key, and the seed club.
   - Update `scripts/investigate_missing_game_requests.py:137` wording.
   - Close IMP-191 (`done`, `Refs`, moved to the archive by hand).
   - Add a new entry for the NPSL Winter season through `/note-improvement`, triggered once Winter games are scored
     (added as IMP-408).

10. **First real run, then confirm from the data.**
    - After merge, dispatch the workflow once (dry run, then real), or let Monday's cron run it.
    - Confirm from `games`, not the run log: NPSL games dated on or after 2026-08-01 exist under provider
      `demosphere` with `schedule_id` prefix `demosphere-74274-`; no game has a NULL side; and the teams that held
      fewer than 10 games this season before the import now hold their league games against teams in scope (a
      scored game against a left-out team is held by design and listed in the run's held CSV; an unscored fixture
      against one is dropped).

## Verification

- `python -m pytest tests/unit/test_import_demosphere.py tests/unit/test_age_rollover_freeze_coverage.py tests/unit/test_team_cleanup_apply_stage.py tests/unit/test_provider_matcher_dry_run.py`.
  All pass, every existing NCSL assertion unchanged.
- Mutation checks, collecting the failing test names: revert the `td.hdr` fallback alone, then the per-league
  team-code switch alone. Each must redden a new NPSL test by name, not only a pre-existing one.
- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`, then the full CI pytest line.
- Step 7's dry run reports zero writes by row counts before and after. Its created teams' printed payload shows WA
  states, sensible ages (no U10 squad on U16) and genders.
- Spot-check ages on the dry run's roster: `NSC B10A` reads U10, `Seattle United NW B10 Blue` reads U16, and every
  `BU16 Division 1` team reads u16 male.
- After the first real run: an NCSL leg and an NPSL leg in the same workflow run, each with its own green
  zero-played check, summary and artifact. The NCSL leg's counts are in line with the week before (no NCSL
  regression).
- From the database, how many NPSL teams reach 10 games this season and appear in the first Monday ranking run
  after import.

## Context Files

- `scripts/import_demosphere.py` — the whole driver; every step edits it.
- `.github/workflows/demosphere-scraper.yml` — the step-5 rewrite target; preserve list above.
- `.github/workflows/ea-scraper.yml` — the matrix pattern to mirror (`:38-48`).
- `tests/unit/test_import_demosphere.py` — fakes to parametrize, assertions that must stay green.
- `src/models/demosphere_matcher.py` and `src/models/tourneycentral_matcher.py` — what a created team is stamped with.
- `.claude/skills/scraper-patterns/SKILL.md` ("Demosphere Pages", "Check a roster pass's new teams for
  near-duplicates") — the rules the dry run is read against.
- `.turbo/plans/add-demosphere-ncsl-provider.md` (working tree of `C:\PitchRank` only) — how NCSL's owner decisions
  were gathered.

## As built (2026-11-23)

Steps 0-9 are done; step 10 runs after merge. Two step details changed: only the division page was captured as
a fixture (the tests build the seed club and its schedule page inline), and the seed club is recorded in the
`LEAGUES` row rather than in the skill.

- **League fields.** Only `team_codes` was added. `listed_club_suffix` was not: the shared `- Travel`/`- N1`
  strip matches no NPSL listed club (checked against the dry run's 38 listed clubs), so it stays shared.
  `_CODE_GENDER` reads only a team code, which NPSL never has, so gender comes from the division unchanged.
- **Differences NPSL showed beyond the plan, each fixed with a test that fails when its half is reverted:**
  - Some divisions a club page lists have no schedule page: Demosphere's spelling corrector answers HTTP 300.
    A 404 and the corrector's 301 are treated the same, and the 301 is never followed, because it sends a missing
    division to a near-named one whose games would then be read twice. `PageNotFoundError` is noted in the run
    summary and the walk goes on. Any other status still fails the run, any other redirect included, as do a club
    or seed page with no page at its address, a walk that finds no division of the season, and a walk in which no
    division has a schedule page. On 2026-11-22 three divisions answered 300. A fourth, found on 2026-11-23,
    answers a 301 to BU12 Division 4; the dry runs before the fix followed it and read that division's 76 games
    (64 played, 12 upcoming) twice. Refusing it took the games to import from 1,917 played and 285 upcoming to 1,854 and
    273: 75 fewer rather than 76, because one new score was posted between the two runs.
  - Empty placeholder slots (no team on either side, no score) are skipped, not reported as unreadable rows.
  - Pages declare no charset and carry a windows-1252 non-breaking space inside some team names
    (`CFSC GU11 Torgison`), which the forced UTF-8 read as U+FFFD. `_undeclared_encoding` reads UTF-8 when the
    bytes are UTF-8, else windows-1252.
- **Step 8 (owner decisions).** 19 listed-club spellings are mapped in `NPSL_CLUBS`, pinned by a literal test. The
  owner reviewed 107 teams on a review page (13 that shared a match with another NPSL squad, 38 likely copies, 56
  the matcher was unsure of) and ruled all of them new teams. The 38 are created by the first run. 68 of the other 69 were
  created before merge through the Demosphere matcher's own create helper plus an approved `direct_id` alias, so
  the run reads them as already linked. The 69th, NSC BU14A, one of the 13 shared, was left to link: a GotSport
  team was renamed to that exact name after the review page was built, which is why the next dry run shows 12
  conflicts. Once the 68 existed, two other squads fuzzy-matched them and were held
  as shared (one a sibling in the same division), so those two were created the same way. A real run cannot do
  this to itself: the matcher skips teams created earlier in the same run.
- **Dry runs** were all under a write guard, with row counts before and after. The last before the 68 creates: 178 linked,
  141 to create, 56 review, 12 conflict, 50 left out (mostly U9), 1,310 played games and 188 upcoming to import,
  3 divisions with no schedule page, 0 problems. After both batches and with redirects refused (2026-11-23): 70
  already linked, 177 linked, 140 to create, 0 review, 0 conflict, 0 errors, 1,854 played and 273 upcoming games
  to import, 290 held (every one against a left-out team), 4 divisions with no schedule page, 0 problems. The
  figures before the 68 creates (1,310 played, 188 upcoming) include the twice-read division. NCSL's dry run is identical to `origin/main`'s, row for
  row.
