---
status: done
---

# Plan: SincSports league schedules (boys, since 2026-08-01)

## Context

Step (3) of `.turbo/handoff/2026-09-14-sincsports-leagues-and-weekly-tournaments.md`. About 25,000
SincSports boys teams are linked in `team_alias_map`, but most have few or no games, because the
only games imported so far come from tournaments. SincSports also hosts league seasons (Carolina
Champions League, Eastern Carolina Fall League, and others) whose schedules are public. This plan
imports the **boys games played since 2026-08-01** from **competitive youth leagues**, then re-runs
by hand each week while the fall seasons continue.

The earlier attempt parsed 0 games from Carolina Champions League. A browser inventory on
2026-09-14 found why, and found a second defect that would have hit anyway:

1. **A league division URL opens on the Standings tab.** `schedule.aspx?tid=CARCHLEA&div=U12M01`
   renders only `.sched2-stand-tbl`. Adding `&mode=schedule` renders the games in the "sched2"
   layout the handoff documents.
2. **The sched2 games view shows 50 games per page.** `.sched2-pager` carries `"55 games"` in
   `.sched2-pager-info` and `&gpage=N` links. The throwaway parser behind the tournament imports
   (`data/exports/sincsports_session_scripts_20260914/bundle_to_jsonl_s1.py`) never followed
   `gpage`. Checked against the saved captures: 2 of 315 divisions hit the cap, and both belong to
   the league NextGen Birmingham (`ACADLEAG2` U10M01, U12M01), which this plan re-captures. No
   tournament division was cut off.

Owner decisions from 2026-09-14:
- Boys only.
- Competitive youth leagues only: no rec, indoor/futsal, 7v7/small-sided or adult leagues.
- Only games dated on or after 2026-08-01.
- Pages are fetched in a real browser on the owner's machine, and repo code reads the saved files.
  ZenRows is not used.
- Import played games only, and re-run by hand weekly. Scheduling the job belongs to step (4).
- A game whose team is not already linked is held back and its team ID listed, never auto-created.

### What the site does (verified 2026-09-14)

- **League list:** `events.aspx?sinc=Y&leagues=Y`. It is an ASP.NET form, submitted with
  `ctl00_ContentPlaceHolder1_btnSearch` after setting `ctl00_ContentPlaceHolder1_tbFrom`
  (`MM/DD/YYYY`).
  - Unlike the tournament view, a past From Date works.
  - A search returns **at most 30 leagues and no pager**, ordered by start date. The filter seems
    to apply to end date: a 2026-02-01 search still listed leagues that started in Nov 2025.
  - To enumerate, walk the From Date forward until a search adds no new `tid`.
  - Each card has `TTIntro.aspx?tid=X`, `schedule.aspx?tid=X`, the start date, and an age line
    such as `BOYS: U08 - U17 GIRLS: U09 - U17`. Adult leagues read `BOYS: Adult`.
- **Each season has its own `tid`.** `CARCHLES` is Spring 2026 and `CARCHLEA` is Fall 2026, and
  `FRINL`/`FRINL2`/`FRINL3` work the same way. Schedule URLs work without `year`/`stid`.
- **Leagues active on or after 2026-08-01** (from the 2026-09-14 listing):
  - Youth candidates: `CARCHLEA` Carolina Champions League - Fall (starts Aug 15), `ECSA` Eastern
    Carolina Fall League (Aug 20), `ACADLEAG2` NextGen Birmingham - Fall (U08-U12), `PACRSL`
    Pacific Regional Soccer League (Sep 5), `TNKYBCF` TN Borders Classic Fall (Aug 1), `FRINL2`
    Friday Night League Summer 2026 (Jul 24, boys U09-U16; format unconfirmed).
  - Excluded: `TRIANGLF` and `OCASLTF` (adult), `AVRFL` (recreation), `CAMSLF` (U07-U08 only).
  - Not yet checked: leagues that started before Aug 1 and ran past it. The Step 3 From-Date walk
    from 08/01/2026 finds them.
- **League root** (`schedule.aspx?tid=X`): a sched2 division picker. Each `.sched2-divcard` links
  `schedule.aspx?tid=X&div=U12M01` and shows `"84 games"`. Codes are `UxxM##` for boys and
  `UxxF##` for girls.
- **Games view** (`&div=CODE&mode=schedule[&gpage=N]`):
  - Days: `.sched2-daygroup` > `.sched2-dayhd-date` (`"Aug 22"`, no year).
  - Games: `.sched2-game` > `.sched2-game-time`, `.sched2-game-num` (`"#876"`), and two
    `.sched2-team` blocks. Each block has `a[data-team]` (SincSports team ID),
    `a.sched2-team-lnk` (name), `.sched2-team-score`, and `a.sched2-ha-h` / `a.sched2-ha-a`
    (home/away) linking `/team/team.aspx?tid=X&year=2026&teamid=ID`.
  - Venue: `.sched2-field-link`. Marks: `.sched2-mark`, whose `title` was `"Counts in standings"`
    on all 100 sampled games. No cancelled or forfeited game was seen, so their markup is unknown.
  - `CARCHLES` U12M01 (a finished season) had 55 games, Feb 14 – Apr 25, all scored. `CARCHLEA`
    U12M01 (in progress) had 50 games on page 1 against 84 on its card, 21 of them scored.
- **Coverage:** all 27 team IDs sampled from `CARCHLES`/`CARCHLEA` U12M01 and U15M01 are
  already in `team_alias_map` under provider `sincsports`. No `games` rows have `competition`
  matching "Carolina Champions", "Eastern Carolina" or "ECSA".

## Pattern Survey

Verified against `origin/main` 3e3f0cf58. No SincSports file differs between that and the
checkout's HEAD.

### Analogous Features
- `src/scrapers/sincsports_schedule.py:107` `parse_division` is a pure BeautifulSoup parser over
  the old `div.form-row.game-row` layout. Its helpers: `_parse_team_block` (`:79`) reads the team ID
  from the `/team/team.aspx…teamid=` link and the name from the `schedule.aspx…team=` link, and
  `_parse_score_col` (`:93`) reads two `style="color:"` divs.
  - Status: `Cancelled` if a red `<font>` is present, `Played` if both scores are present,
    otherwise `Scheduled`.
  - Venue comes from the `TTMap.aspx` link. Cards without team IDs are skipped.
- `src/scrapers/sincsports_schedule.py:60` `TournamentGame`. `date` is raw `MM/DD/YYYY`, and the
  driver normalizes it through `parse_date_iso` (`scripts/scrape_sincsports_tournament_schedule.py:62`).
  The old layout carries a 4-digit year in its text, so no year inference exists anywhere.
- `src/scrapers/sincsports_schedule.py:174` `parse_tournament_index` uses `_DIV_QS_RE`
  (`[?&]div=`, `:53`), so it already reads the sched2 picker's `&div=` links, girls codes included.
- `SincSportsScheduleScraper` (`:184`): `fetch_division_codes` / `fetch_division` build
  `?tid&year&stid&syear[&div]` URLs with no `mode` and no paging. `fetch_tournament` records
  per-division failures on `self.errors` and continues.
- `scripts/scrape_sincsports_tournament_schedule.py` is the driver:
  - Flags: `--tid` (required), `--year`, `--include-cancelled`, `--include-scheduled`,
    `--include-sub-u10`, `--auto-import`, `--dry-run`, `--via-proxy`.
  - Filters: Played only, date present, sub-U10 dropped via `_SUB_U10_CODE_RE` (`:37`).
  - Output: one home-perspective JSONL row per game in `data/raw/`, written through
    `perspective_record` (`:72`). It prints the import command or runs it as a subprocess.
  - Live HTTP only.
- `data/exports/sincsports_session_scripts_20260914/bundle_to_jsonl_s1.py` (local, gitignored)
  holds a working sched2 draft, `parse_sched2` (`:48-100`), which reads a browser bundle JSON of
  `{events[], divisions[{tid, div, layout, html}]}`. It has three flaws to fix rather than copy:
  - It ignores `gpage`.
  - It appends one fixed year to every date.
  - It regexes mark *text* rather than the `title` attribute.
  - It sets `competition` to `"{event name} - {div}"` (`:121`), which is what the 8,135 imported
    tournament rows carry.
- `scripts/scrape_playmetrics_league.py` is the nearest league driver: `scrape_league` (`:540`)
  loops `scrape_division` (`:431`), with `--dry-run` and `--output-dir`.
- `scripts/scrape_new_gotsport_events.py:462-500` `_find_max_page_number`, with the loop at
  `:549-571`, is the only HTML result-paging pattern in the repo.

### Reusable Utilities
- `TournamentGame`, `perspective_record`, `parse_date_iso` and `_SUB_U10_CODE_RE`, as above.
- `parse_tournament_index` turns picker HTML into division codes.
- `SincSportsClubsScraper` (`src/scrapers/sincsports_clubs.py:114`) supplies the shared session and
  the `SINCSPORTS_DELAY_MIN`/`MAX` throttle to `SincSportsScheduleScraper.__init__`.
- `src/models/game_matcher.py:561` `generate_game_uid` builds
  `{provider}:{date}:{sorted id1}:{sorted id2}`, so the same pair on the same date collapses
  whichever event it came from.
- `src/models/sincsports_matcher.py:549` `_match_team` auto-creates only when `team_name`,
  `age_group` and `gender` are all present (`:593`). Rows from `perspective_record` carry no
  `age_group`/`gender`, so an unlinked team fails to match rather than being created. That
  failure is the owner's chosen behaviour.
- `scripts/discover_sincsports_teams.py` is the team import path for any IDs this run lists.

### Convention Anchors
- Pure `parse_*` functions in `src/scrapers/sincsports_*.py` take HTML and do no network work.
  The live class exposes a swappable `self.session`, and the driver lives in `scripts/`.
- Tests: `tests/unit/test_sincsports_schedule.py` exercises the pure parsers against committed HTML
  in `tests/fixtures/sincsports_events/` (`schedule_puri_u14f01.html`), with no HTTP mocking, and
  spot-checks named games.
- Importer: `python scripts/import_games_enhanced.py <jsonl> sincsports`.
  - `enhanced_pipeline.py:870-876` skips score UPDATEs when
    `source == "sincsports_tournament_schedule"`, so the existing row stays authoritative.
    League rows come from the same `schedule.aspx` route, so they keep that `source` value.
  - `enhanced_pipeline.py:1127-1177`: rows without a score are skipped unless dated in the future.
- Importer defect, confirmed:
  - `enhanced_pipeline.py:456-471` rebuilds the client every 1,000 games
    (`config/settings.py:195`) with `config.settings.SUPABASE_KEY`, the anon key. From then on
    every insert fails RLS and the run still exits 0.
  - Workaround: set `SUPABASE_KEY` to the service-role key in the import process's environment.
  - No backlog entry tracks this defect.

### Proposed Alignment
- **Parser:** add a pure sched2 parser beside `parse_division`, and have `parse_division` dispatch
  on layout so every existing caller gains it.
- **Driver:** extend the existing tournament driver to read a browser bundle instead of adding a
  second driver. Step (4) uses the same path for weekly tournaments.
- **Output:** keep `perspective_record`, the `sincsports` provider and the
  `sincsports_tournament_schedule` source.

## Implementation Steps

0. **Branch setup (local-state hazard)**
   - The checkout sits on `codex/matchbalance-intake-infrastructure`, whose remote is gone and which
     is 10 behind `origin/main`. Its index holds 5 staged frontend files from another session, and
     untracked `probe_*.py` / `pytest-*` folders belong to other sessions. Do not branch in place,
     stash, or stage any of them.
   - Per the worktree exception in the global CLAUDE.md, create a worktree off `origin/main`:
     `git worktree add ../pitchrank-sincsports-leagues -b sincsports-league-schedules origin/main`.
   - Before editing, confirm `git -C ../pitchrank-sincsports-leagues status --short` is empty.
   - Browser bundles and fixture captures write under `C:\PitchRank` (the Playwright MCP's allowed
     root). Copy fixtures into the worktree, and pass bundle paths to the driver as absolute paths.

1. **Capture test fixtures from the live site**
   - In the Playwright MCP browser on `soccer.sincsports.com`, use same-origin `fetch()` with
     `browser_evaluate` and `filename` to save raw HTML for:
     - `CARCHLES` root (picker)
     - `CARCHLES&div=U12M01&mode=schedule` (page 1, which has the pager)
     - `…&gpage=2` (5 games, the last page)
     - `CARCHLEA&div=U12M01` with no `mode` (Standings only)
   - Unwrap the JSON string into `.html` files under `tests/fixtures/sincsports_events/`, named
     `sched2_carchles_root.html`, `sched2_carchles_u12m01_p1.html`,
     `sched2_carchles_u12m01_p2.html` and `sched2_carchlea_u12m01_standings.html`.
   - If any league in Step 3 shows a cancelled or forfeited game, save that page too, as
     `sched2_<tid>_<div>_cancelled.html`, so status parsing is tested against real markup. If none
     exists, record that in the test module docstring.

2. **Sched2 parsing in `src/scrapers/sincsports_schedule.py`**
   - Add `parse_sched2_division(html, tournament_id, division_code, season_start_year) -> List[TournamentGame]`.
     - Walk `.sched2-daygroup`. For each `.sched2-dayhd-date` (`"Aug 22"`), resolve the year from
       the soccer season: months Aug–Dec take `season_start_year`, and Jan–Jul take
       `season_start_year + 1`. Emit `date` as `MM/DD/YYYY` so `parse_date_iso` still applies.
     - For each `.sched2-game`, the first `.sched2-team` is home (it carries `a.sched2-ha-h`). Take
       the ID from `a[data-team]`, uppercase it, and require the existing SincSports ID shape. Take
       the name from `a.sched2-team-lnk` and the integer score from `.sched2-team-score`, or `None`
       when blank or non-numeric.
     - Take `game_num` from `.sched2-game-num` without the `#`, `time` from `.sched2-game-time`,
       and `venue` from `.sched2-field-link` text.
     - Status: `Cancelled` when a `.sched2-mark` / `.sched2-typechip` title or text matches
       cancel/forfeit/postpone/void, `Played` when both scores are present, and `Scheduled`
       otherwise. Log once per page any mark title outside the known set (`"Counts in
       standings"` plus the cancel family), so unseen markup shows up rather than being guessed at.
     - `division_name`: the `.sched2-select` option marked `selected` when it names the division,
       else `None`.
     - Skip games missing either team ID, as `parse_division` does.
   - Add `parse_sched2_pager(html) -> tuple[Optional[int], int]`. It returns the total from
     `.sched2-pager-info` (`"55 games"`) and the highest `gpage` in the pager links, which is 1
     when no pager exists.
   - In `parse_division`, dispatch to `parse_sched2_division` when the HTML contains `sched2-game`.
     Keep the old-layout path unchanged. Add `season_start_year: int = 2026` to `parse_division` so
     current callers keep working. Do not dispatch on `sched2-page` alone: the Standings-only
     fixture carries that class and has no games.
   - Make `SincSportsScheduleScraper.fetch_division` request `&mode=schedule`. After parsing page 1,
     fetch `&gpage=2..N` from `parse_sched2_pager` with the existing delay between requests.
     Otherwise the new dispatch would bring the 50-game cap into the live path. Keep the
     `year/stid/syear` params as they are.

3. **Browser capture script: `scripts/sincsports_capture_bundle.js`**
   - A self-contained async function for Playwright MCP `browser_evaluate` on a
     `soccer.sincsports.com` page. It returns one JSON bundle, saved with `filename` under
     `data/raw/sincsports_leagues_<YYYYMMDD>/`. The file header states how to run it, the pacing,
     and "never re-fire before the previous response lands".
   - **Mode `leagues`** (input `{mode:'leagues', from:'08/01/2026'}`):
     - Build the search as a form POST by reading every hidden input from a fresh GET of
       `events.aspx?sinc=Y&leagues=Y`, the same form-state idea as
       `src/scrapers/sincsports_clubs.py:191-215` `_extract_form_state`.
     - Walk From Date forward from the last start date returned until a search adds no new `tid`.
     - Return `leagues[] {tid, name, start_date, location, ages_text}`.
   - **Mode `divisions`** (input `{mode:'divisions', tids:[…]}`):
     - For each tid, fetch the root and keep division codes matching `^U\d{2}M`.
     - For each code, fetch `&mode=schedule`, read the pager, and fetch the remaining `gpage`s.
     - Return `events[] {tid, name}` and `divisions[] {tid, div, page, pager_total, html}`.
     - Pace each request at a random 0.6–1.5 s, one worker. Parse with `DOMParser`, never
       `innerHTML`.
   - The script only reads SincSports pages and writes nothing to the repo or database.

4. **Bundle input for `scripts/scrape_sincsports_tournament_schedule.py`**
   - Make `--tid` and a new `--from-bundle PATH` mutually exclusive, with one required.
   - Add `--season-start-year` (default 2026), forwarded to `parse_division`, and `--since
     YYYY-MM-DD`, which drops rows dated before it. The owner's run passes `2026-08-01`.
   - With `--from-bundle`, group `divisions[]` by `(tid, div)`, parse every page through
     `parse_division`, and concatenate. Dedup within a division on `(date, home_id, away_id,
     game_num)`, since overlapping pages would otherwise double-count.
     - Compare the parsed count with `pager_total`, and print a per-division mismatch table.
     - Set `division_name` to `"{event name} - {div}"`, matching the 8,135 rows already imported.
     - Record any division with a mismatch in the summary, and exit non-zero from `--dry-run`
       when a mismatch exists, so truncation cannot pass silently.
   - Keep the existing filters (Played only, date present, sub-U10 dropped) and apply them the same
     way to bundle input. Output goes to
     `data/raw/sincsports_games_bundle_<bundle-stem>_<ts>.jsonl` through `perspective_record`.
   - Add `--check-aliases`, a read-only mode. It queries `team_alias_map` for the `sincsports`
     provider by `provider_team_id` in batches of 100 and writes unlinked IDs, with a sample team
     name and the tids/divisions they appear in, to `…_unlinked_teams.csv` beside the JSONL. Rows
     whose team is unlinked stay out of the JSONL, which is the owner's hold-back decision. Build
     the client the way the entry-point scripts do (`SUPABASE_SERVICE_ROLE_KEY`).
   - Leave `--auto-import` and the `--via-proxy` live path behaviour otherwise unchanged.

5. **Tests: `tests/unit/test_sincsports_schedule.py`**
   - Parse the p1 fixture and assert 50 games, with one game spot-checked by literal values: date,
     both IDs, both names, both scores, game number and venue, read by eye from the fixture.
   - Parse p2 and assert 5 games, and that `parse_sched2_pager` on p1 returns `(55, 2)`.
   - Year rollover: `CARCHLES` Feb dates with `season_start_year=2025` yield `02/14/2026`, and an
     `Aug 22` header with `season_start_year=2026` yields `08/22/2026`. Build the Aug case from a
     minimal inline sched2 snippet so the test cannot pass on one branch of the rule alone.
   - The Standings-only fixture returns `[]` through `parse_division` and does not raise.
   - `parse_tournament_index` on the root fixture includes `U12M01` and a `U..F..` code, and the
     boys filter keeps only `M` codes.
   - Status: one inline-snippet case per branch (both scores → Played, one blank → Scheduled,
     cancel mark with scores → Cancelled). Use the real cancelled fixture if Step 1 found one.
   - Driver bundle path: build a tiny bundle dict in the test from the p1+p2 fixtures, with a
     duplicated page to prove the dedup. Assert 55 unique games, no mismatch, and the
     `--since` cut by a literal count.
   - The existing old-layout tests (`schedule_puri_u14f01.html`) must keep passing unchanged.

6. **Operator run (after merge, from `C:\PitchRank` on the owner's machine)**
   - Run capture mode `leagues` from `08/01/2026`. Pick the keep list: boys youth leagues with
     games since Aug 1, excluding names or age lines containing Adult, Rec/Recreation, Futsal,
     Indoor, 3v3/5v5/7v7, or ages only below U10. Show the owner the keep list and the excluded
     list before capturing divisions. Settle `FRINL2`'s format there.
   - Run capture mode `divisions` with the keep list, then the driver with `--from-bundle <abs path>
     --since 2026-08-01 --dry-run`. Expect zero pager mismatches.
   - Run with `--check-aliases`. If unlinked IDs exist, route them through
     `scripts/discover_sincsports_teams.py` (dry run first) and re-run the driver.
   - Import the JSONL:
     `SUPABASE_KEY=<service role key> python scripts/import_games_enhanced.py <jsonl> sincsports`.
     Run the importer's dry run first if it has one, else a small slice.
   - Weekly while the fall seasons run: repeat the `divisions` capture for the same tids and
     re-import. Same-date, same-pair games collapse on `game_uid`, and the source gate keeps
     existing scores.

## Verification

- `python -m pytest tests/unit/test_sincsports_schedule.py -v`: all new and existing cases pass.
- Mutation checks on a scratch copy, one at a time, clearing `__pycache__` between runs:
  - Drop the `gpage` follow in `fetch_division` / the driver's page grouping, and expect the 55-count
    and mismatch tests to fail.
  - Hard-code the year, and expect the rollover test to fail.
  - Swap the home/away team order, and expect the literal spot-check to fail.
  - Remove the `sched2-game` dispatch, and expect the p1 test to fail.
  - Make the dispatch key on `sched2-page`, and expect the Standings test to fail.
- CI gate lines from `CLAUDE.md`, Python half:
  `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` and
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.
- Driver `--dry-run` on the real bundle: per-league and per-division totals, zero pager
  mismatches, and the boys-only and `--since` filters visible in the summary counts.
  `ACADLEAG2` U10M01 and U12M01 should each now parse more than 50 games. Both are U10+, so the
  sub-U10 filter keeps them.
- Before import:
  - Query `games` for `competition ILIKE` each kept league name (`ECSA` and `ACADLEAG2` have
    capture files from the prior session), and note any existing rows. `game_uid` should collapse
    them rather than insert duplicates.
  - Confirm the JSONL row count is under 1,000, or that the service-role `SUPABASE_KEY` is set.
- After import:
  - Re-derive the inserted count from the database: `games` rows with `provider` sincsports and
    `competition` starting with each league name, dated ≥ 2026-08-01. Compare it with the
    JSONL rows minus reported duplicates, and do not rely on the importer's summary alone.
  - Fused-team check from the handoff: no master team with two SincSports IDs playing different
    opponents on the same date.
  - Confirm no RLS `42501` lines in the import log.

## Context Files

- `.turbo/handoff/2026-09-14-sincsports-leagues-and-weekly-tournaments.md`: site behaviour,
  access constraints, importer gotchas and open merge follow-ups.
- `src/scrapers/sincsports_schedule.py`: the parser and live fetcher being extended.
- `scripts/scrape_sincsports_tournament_schedule.py`: the driver gaining bundle input, and
  `perspective_record`.
- `tests/unit/test_sincsports_schedule.py`: fixture-test style to mirror.
- `data/exports/sincsports_session_scripts_20260914/bundle_to_jsonl_s1.py`: working sched2 draft
  and bundle shape (local only). Port the selectors, not its year/paging/mark handling.
- `src/scrapers/sincsports_clubs.py:191-268`: ASP.NET hidden-field form state, the model for the
  league-list POST.
- `src/etl/enhanced_pipeline.py:456-471` and `:860-890`: the anon-key refresh defect and the
  `sincsports_tournament_schedule` score-update gate.
