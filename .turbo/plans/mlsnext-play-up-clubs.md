---
status: done
---

# Plan: MLS NEXT clubs that play a year up

## As built

- Built as planned except the rename step, which the owner changed on 2026-11-18 (below): `plan_renames`
  accepts a play-up team one board below its squad and names it at its own age, so the plan's "`plan_renames`
  stays exact" (Pattern Survey, Proposed alignment, steps 4 and 6) did not ship. `usable_links` now takes each squad's accepted ages as a tuple. One side effect: a
  link whose key is not a squad this season and whose team is not live used to be kept (`None == None`)
  and is now dropped, which is what the "Dropped N links" message always said. On the 11-16 run it
  changed nothing: `origin/main` dropped 6 links and the branch 2, the 4 Earthquakes squads exactly.
- Mutation checks: every single-guard mutation of the shipped rules failed its own new test by name, including
  a play-up club's team at its squad's own age. (The plan's "renames using the play-up ages" mutation is now the
  shipped behaviour.)
- Live, read-only, under a write guard, against the 11-16 run's files:
  - The builder's import file gains 68 rows (34 games), every one an Earthquakes game. No other row changes,
    and no Earthquakes game is held.
  - The matcher matches the four squads to their real-age teams. `origin/main` rejects all four, and the
    U19 squad matches on both.
  - A `--dry-run` import of the 34 games gives `matched: 34, partial: 0` and finds every game already stored
    by master-id uid, so nothing is stored twice. `origin/main` gives `partial: 34`: the Earthquakes side is
    left empty.
  - Pairing reports are identical (all 2,459 squads already linked), and the rename preview plans 0 renames on both.
- **Rename step (owner, 2026-11-18, "Rename to real age").** It no longer skips a play-up team. It gives it
  the squad's Kitman name at the team's own age (`_name_at_age`), so after an Aug 1 relabel its name follows its
  age instead of keeping last season's. Without this, nothing renames it: the GotSport reconcile leaves the names
  of Kitman-linked teams alone. The live preview still plans 0 renames, because all four Earthquakes names already
  match their ages.
- **Hand-back sheet.** A listed club's held squad reads `needs review: plays a year up`, and the legend explains
  it. The review reason never reached the sheet: `plan_links` writes every review as "needs review". A listed
  club with teams at both ages also gets the ordinary "2 candidates" review.
- **Other providers in the match report.** `run()` also looks up other-provider teams for a listed club's
  squad that has no candidate, at both ages, so its review lists the real-age team.
- **Tests.** An end-to-end test runs builder rows through both CSV loaders, the pipeline's real dedup, perspective
  transform and gender normalisation (schema validation off, as the shared `_import_pipeline` harness runs it) and
  the real Kitman matcher, with the listed club at home and away. The importer test's teams double refuses an
  unknown column, applies filters and selected columns, and answers with one row only for `.single()`, as
  PostgREST does.

## Context

The owner files teams by real age even when they play up (2026-09-18: "it doesn't matter that they play
up we need to get their actual age group correct"). On 2026-11-17 the owner confirmed from app screenshots
that San Jose Earthquakes field every MLS NEXT squad one division up, and moved four teams to their real age
("Move now, fix import later"):

| Team (team_id_master) | Stored | Kitman squad |
|---|---|---|
| San Jose Earthquakes U13 HD (e311dd41-dee8-41e2-b134-e90998598059) | u13 | 6015:2026 (U14) |
| San Jose Earthquakes U14 HD (05d07d97-804c-4c3a-8f0f-ff23b98c26b7) | u14 | 6016:2026 (U15) |
| San Jose Earthquakes U15 HD (466cd0a9-2c68-4f4f-8469-83637ffd78df) | u15 | 7208:2026 (U16) |
| San Jose Earthquakes U16 HD (3abca5c1-a9d0-4507-8612-d9b91763fb0c) | u16 | 6017:2026 (U17) |

Every stage of the Kitman pipeline refuses a link whose team's stored age differs from its squad's, so from
the Mon 2026-11-23 run these four teams' new games would be held every week. Measured 2026-11-18 against the
11-16 run's `squads.csv` and the live aliases: of 2,459 linked live boys teams, 2,455 match their squad's age
exactly and these four are the only ones off, each by exactly one board.

Owner decisions (2026-11-18):
- **A list of clubs**, not a general one-year allowance. A club on the list may have its squads carried by a
  team one board younger; every other club keeps the exact-age rule, which is what caught Austin FC U13 and
  Downtown Las Vegas U14 AD (both stored at the wrong age) on 2026-11-17.
- **A play-up team keeps its real-age name.** The weekly "Apply Kitman names" step does not rename it to the
  division's name.
- **Fix the pairing step too.** `classify` pairs a new squad with a team by exact age, so at next season's
  new squad ids a play-up club's squads would each be paired with the next-older team, silently. A listed
  club's unlinked squad goes to review instead.
- Short plan, not `/turboplan`.

Implementer's call (owner may revise at approval): a `your pick: new` decision for a listed club's squad still
creates the team at the squad's age. The review reason says so; picking the existing team is the normal path.

## Pattern Survey

**Where the age rule lives today (baseline `cad0ddbf2`).**
- `scripts/build_mlsnext_kitman_games_csv.py:208-227` `usable_links(sb, links, ages)` keeps a link only when
  `team.age_group.lower() == ages[key]`; `main` builds `ages` from `squads.csv` at :267 (rows also carry
  `club_name`). `--planned` skips it. `build_rows:140` stamps both importer rows with the home squad's age;
  `club_name`/`opponent_club_name` at :135/:139.
- `src/models/mlsnext_kitman_matcher.py:17-34` `_match_team` ignores its `club_name` argument and calls
  `GameHistoryMatcher._match_by_provider_id(provider_id, key, age_group, gender)` (`game_matcher.py:993-1140`),
  which runs `_validate_team_age_group` (`:1162-1206`) on every tier (cache, direct id, semicolon, fallback).
  **If only the builder changes, the importer still rejects the Earthquakes side and the game is inserted with
  that side NULL** (`game_matcher.py:760-762`, `enhanced_pipeline.py:748-753`), so builder and matcher change
  together.
- `scripts/link_mlsnext_kitman_teams.py:208-231` `_usable_target` -> `_fits_squad(team, age_group)` (exact
  age, Male, not deprecated). Callers: `apply_plan:281` (has `action.club_name`) and `plan_renames:352`, which
  must stay exact, so the helper's age input has to be split.
- `scripts/match_mlsnext_kitman_teams.py:92-174` `classify`: candidate pool exact age + division + suffix
  (:119-125); buckets `confident` :141, `review` :133-145, `new` :147-160; already-linked squads (:111-117) are
  not age-checked.
- The pipeline's home/away transform fills `home_club_name`/`away_club_name` from `club_name`/
  `opponent_club_name` by `home_away` (`enhanced_pipeline.py:1545-1556`), and both CSV loaders keep both columns
  (`import_games_enhanced.py:88,92,161,165`), so the matcher sees each side's Kitman club.
- Nothing else on the path checks team age against squad age: score/provider-id correction key on ids, and
  `enhanced_validators.py:70-72` only checks the row's age is a board.

**Reusable utilities.**
- `src/models/mlsnext_kitman_keys.py:32-34,55-56` — `CLUB_STATES` loaded at import from
  `config/mlsnext_kitman_club_states.json`; `club_state_or_blank` checks `is_placeholder_club` first, then an
  exact `.get(club_name)` (Kitman spelling, no `normalize`). `"San Jose Earthquakes": "CA"` at :240 of the
  JSON confirms the spelling.
- `src/utils/age_group.py:23` — ASCII-bounded `^u([0-9]{1,2})$` (the data-safety rule). No existing helper
  steps exactly one board down; `src/tournaments/triage.py:156-170` `_is_play_up` is looser and uses `int()` on
  unbounded input, so it is not reused. Kitman squads are only u13-u17 and u19 (`scrape_mlsnext_kitman.py:42`),
  and PitchRank keeps no u18 board, so the board below u19 is u17.

**Convention anchors.**
- Tests patch the shared config object in place (`monkeypatch.setitem(keys.CLUB_STATES, ...)`,
  `test_link_mlsnext_kitman_teams.py:188-191`), so the new config is a dict, read through a function at call
  time.
- Builder doubles: `_Db`/`_Query` (`test_build_mlsnext_kitman_games_csv.py:321-396`) filter at `execute()`,
  cap `in_` at 100, and return only selected columns; `_live_run` (:461-480) drives `main`;
  `test_a_live_link_to_a_team_on_another_board_holds_that_squads_games` (:565-575) is the unlisted-club case.
- Linker double `_Query` (`test_link_mlsnext_kitman_teams.py:37-114`) logs at `execute()` and makes
  `.single()` raise PGRST116 like postgrest.
- Matcher test (`test_mlsnext_kitman_matcher.py:12-15`) stubs `_validate_team_age_group` to `True`, so it never
  exercises the age check. The real-validator precedent is `_TeamsTable`
  (`test_import_soccereventsgroup_event.py:648-671`), whose `execute()` raises on a missing row.
- `classify` tests call it directly (`test_match_mlsnext_kitman_teams.py:10-53`).
- The Kitman rules are documented in `.claude/skills/scraper-patterns/SKILL.md:723-733`.

**Proposed alignment.** One rule in `mlsnext_kitman_keys.py`, beside `CLUB_STATES`, read by all four stages;
`plan_renames` keeps the exact check explicitly.

## Implementation Steps

Branch `feat/mlsnext-play-up-clubs` in worktree `C:/pitchrank-kitman-play-up`, cut from `origin/main` at
`cad0ddbf2`. The main checkout `C:\PitchRank` is on another branch with unrelated staged work: do not edit or
stage there. Before editing, `git -C C:/pitchrank-kitman-play-up status --short` must show only this plan.

1. **The club list and the shared rule** (`config/`, `src/models/mlsnext_kitman_keys.py`)
   - New `config/mlsnext_kitman_play_up_clubs.json`: a dict of Kitman club name -> the owner's evidence, starting
     with `"San Jose Earthquakes"` (owner 2026-11-17, app screenshots, every squad one division up). Written
     `indent=2, sort_keys=True`, trailing newline, like the states table.
   - In `mlsnext_kitman_keys.py`: load it at import as `PLAY_UP_CLUBS` (mirror `CLUB_STATES`, :32-34) and add to
     `__all__`; add `plays_up(club_name)` (placeholder guard first, then exact membership, mirroring
     `club_state_or_blank`); add `team_ages_for_squad(squad_age, club_name) -> tuple[str, ...]`: the squad's own
     age, plus one board younger when `plays_up` (`u19` -> `u17`, otherwise `u<n-1>`), parsing the age with an
     ASCII-bounded `u[0-9]{1,2}` fullmatch and returning the age alone when it does not parse. Update the module
     docstring with one paragraph on the list.
2. **Game builder** (`scripts/build_mlsnext_kitman_games_csv.py`)
   - `usable_links` takes `{key: accepted ages}` and keeps a link when the team's stored age is one of them;
     `main` (:267) builds it with `team_ages_for_squad(s["age_group"], s["club_name"])`. Update the module
     docstring sentence on dropped links to name the play-up list.
3. **Importer** (`src/models/mlsnext_kitman_matcher.py`)
   - `_match_team` tries `_match_by_provider_id` with each age from `team_ages_for_squad(age_group, club_name)`
     in order and takes the first alias found; a missing `age_group` keeps today's single call. Nothing in
     `game_matcher.py` changes. Docstring names the list.
4. **Linker and rename step** (`scripts/link_mlsnext_kitman_teams.py`)
   - `_fits_squad(team, ages)` takes the accepted ages. `_usable_target(sb, team_id_master, age_group, club_name)`
     passes `team_ages_for_squad(...)`; `apply_plan:281` passes `action.club_name`.
   - `plan_renames` passes only the squad's own age, with a comment citing the owner's 2026-11-18 decision, so a
     play-up team keeps its real-age name. Its docstring's "fits its squad" becomes "is in its squad's own age".
5. **Pairing step** (`scripts/match_mlsnext_kitman_teams.py` `classify`)
   - Build the candidate pool from `team_ages_for_squad(squad["age_group"], squad["club_name"])` instead of the
     exact age, so a review row lists the real-age team.
   - After bucketing, a listed club's squad tagged `confident` or `new` becomes `review` with its candidates kept
     and the reason "its club plays a year up: pick its team by real age ('new' files it at this age)".
     Already-linked squads are untouched. Unlisted clubs classify exactly as today.
6. **Tests** (one per guard, each killed by its own mutation)
   - `tests/unit/test_mlsnext_kitman_keys.py`: the committed list loads, every listed club is a key of
     `CLUB_STATES` (catches a misspelling, which would otherwise do nothing silently); `team_ages_for_squad`
     literals for a listed club (`u14` -> `("u14", "u13")`, `u19` -> `("u19", "u17")`), an unlisted club
     (`("u14",)`), a placeholder club, and refused shapes (`"u١٤"`, `"u123"`, `""`) returning the input alone.
   - Builder: through `_live_run`/`main`, a listed club's squad linked to a team one board younger imports its
     games (rows in `import.csv`, none held); one two boards younger is still held; the existing unlisted-club
     test stays. Freeze `date` in any new `main` test.
   - Matcher: a new test running the real `_validate_team_age_group` through a `_TeamsTable`-style double (raises
     on a missing row like `.single()`): a listed club's u13 team matches a u14 game; the same for an unlisted
     club does not; a two-boards-younger team does not.
   - Linker: `apply_plan` writes the alias for a listed club's link to a one-younger team and rejects it for an
     unlisted club (`links_rejected`); `plan_renames` does not rename a listed club's one-younger team.
   - `classify`: a listed club's squad with only a one-younger candidate is `review` with that candidate; with an
     exact-age candidate it is `review` (not `confident`); with none it is `review` (not `new`); an unlisted club
     is unchanged.
   - Mutation checks, one at a time, each failing the new test by name: drop the club from the list; make
     `team_ages_for_squad` return the own age only; revert the matcher to a single call; revert `usable_links`'
     membership test; make `plan_renames` use the play-up ages; drop the `classify` review override; widen the
     younger step to two boards.
7. **Docs**
   - `.claude/skills/scraper-patterns/SKILL.md` (Kitman pipeline bullets, :723-733): one bullet on
     `config/mlsnext_kitman_play_up_clubs.json`: who is on it, that it is edited by hand on the owner's word,
     what each stage does for a listed club, and that its teams keep their real-age names.

## Verification

- The touched test files, then the CI gate commands from CLAUDE.md (ruff on the lint paths, the full pytest
  line, the Windows-focused line is unaffected but run per CI).
- Mutation checks in step 6, collecting failing test names, not just the exit code.
- **Live, read-only, branch vs `origin/main`:** run `build_mlsnext_kitman_games_csv.py --in-dir <scratch copy
  of the 11-16 run's games.csv + squads.csv>` with the env from `C:/PitchRank/.env`. On `origin/main` the
  "Dropped N links" count includes the four Earthquakes squads; on the branch it is four lower and
  `import.csv` carries their played games. No other link changes (measured: the four are the only age gaps).
- **Importer, read-only:** call `MlsNextKitmanGameMatcher._match_team` against the live database with
  `dry_run=True` for `6015:2026` at `u14`, club "San Jose Earthquakes": matched to e311dd41 on the branch,
  unmatched on `origin/main`. Then a `--dry-run` import of the branch's `import.csv` under a fail-closed write
  guard (the smoke-test method in auto memory), comparing matched/partial counts with `origin/main`.
- **Pairing, read-only:** `match_mlsnext_kitman_teams.py` against the 11-16 `squads.csv`: the report is
  identical to `origin/main`'s (all Earthquakes squads are already linked).
- **Rename preview:** `link_mlsnext_kitman_teams.py --names` (read-only) lists no Earthquakes team.

## Context Files

- `src/models/mlsnext_kitman_keys.py` — where the list and rule go; mirror `CLUB_STATES`.
- `scripts/build_mlsnext_kitman_games_csv.py` — `usable_links`, `main`.
- `src/models/mlsnext_kitman_matcher.py` and `src/models/game_matcher.py:993-1206` — the importer's age check.
- `scripts/link_mlsnext_kitman_teams.py:200-370` — `_usable_target`, `_fits_squad`, `apply_plan`, `plan_renames`.
- `scripts/match_mlsnext_kitman_teams.py:92-174` — `classify`.
- `tests/unit/test_build_mlsnext_kitman_games_csv.py`, `test_link_mlsnext_kitman_teams.py`,
  `test_match_mlsnext_kitman_teams.py`, `test_mlsnext_kitman_matcher.py`, `test_mlsnext_kitman_keys.py`,
  and `test_import_soccereventsgroup_event.py:648-671` (real-validator double).
