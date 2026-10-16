---
status: draft
---

# Plan: MLS NEXT Kitman importer

## Context

For 2026-27, MLS NEXT's Homegrown Division (HD) and Academy Division (AD) publish schedules and results through Kitman Labs, not Modular11. PitchRank has no MLS NEXT games after 2026-05-31, and the Modular11 spider can no longer get them: HD answers "No data available" and AD holds only placeholder fixtures. Kitman's public JSON files hold about 4,680 played games since 2026-09-05 (about 2,057 HD plus about 2,622 AD), all with scores.

Kitman identifies a team by a numeric squad id, one per club + age + division. The squad label is just the age ("U16") for HD and age plus "AD" ("U16 AD") for AD. Kitman club ids are unrelated to Modular11's, but club names are spelled identically on both sites for the clubs spot-checked.

Decisions made with the owner (2026-10-14):
- **Link existing teams, create the rest.** Do not import everything as new teams: about 17,900 MLS NEXT games from last season are still inside the 365-day ranking window, and duplicate rows would split that history and drop top teams below the 12-game threshold for a published rank.
- **Weekly job**, in addition to the catch-up.
- **New teams are named `Club U16 HD` / `Club U16 AD`**, like the existing 3,200 MLS NEXT rows.
- **States from a club list built up front**, filled by the owner for clubs that cannot be inferred.
- **The site and the rankings database functions treat a Kitman link the same as a Modular11 link** for display.
- **Provider code `mlsnext_kitman`, name `MLS NEXT`.**
- This is an exception to the standing "Modular11 / MLS NEXT is out of scope" rule, opened by the owner on 2026-10-14.

Measured against production on 2026-10-14 (read-only, exact normalised club name via the existing `modular11` aliases): of 2,460 squads, about 1,230 link to an existing team (462 HD, 770 AD), about 335 are at a known club with no team at that age/division, and about 893 are at 121 clubs not in our MLS NEXT data. 37 of those 121 have a near spelling in our data, and several are different clubs (`Los Angeles Sports Club` vs `Los Angeles Soccer Club`, `Roseville` vs `Roswell`, `GFI Academy North/South`), so near-matches go to review and never auto-link. 160 squads belong to a club name that maps to more than one Modular11 club id; those need the branch-safe check. 27 of the unmatched clubs already exist under GotSport. Zero linked rows are deprecated.

## Pattern Survey

Surveyed on `origin/main` @ 6e068b6bb. Nothing there mentions Kitman. The EA pipeline is the closest analog.

### Analogous Features

- **Modular11 Elite Academy (EA) pipeline**, five scripts chained by CSVs in `data/modular11_ea/<age>/` (gitignored by `.gitignore:7`):
  - `scripts/scrape_modular11_ea.py:351-406` `run(...)` writes `teams.csv` (`TEAM_COLUMNS` :41-52) and `games.csv`, never touches the DB, raises `ScrapeError` (:60), and has a roster floor `MIN_ROSTER_TEAMS=1000` (:38). `main` (:409-421) exits 1 on failure and prints `k=v` counts the workflow tees.
  - `scripts/match_modular11_ea_teams.py:470-510` `run(...)` is read-only and writes `match_report.csv` (`REPORT_COLUMNS` :56-68). `classify` (:237-290) buckets `confident` / `review` / `no_match` with a readable reason, and `_hold` (:217-234) lists the per-candidate holds. **`fetch_db_teams` (:322-348) excludes `modular11` rows and HD/AD/MLS NEXT names (:345, `PROTECTED_RE` :41). Kitman needs the opposite: it bridges through those rows.**
  - `scripts/link_modular11_ea_teams.py` is the only writer of `modular11_ea` aliases and teams. `plan_links` (:72-105), `apply_plan` (:193-264), `refuse_unmigrated` (:212), `_usable_target` (:171-190, refuses another age/gender or a deprecated target), `_existing_team` (:108-122), `_create_team` (:125-141). **The alias write is `upsert_team_alias(...)` at :244-253.** Dry run is the default (:430-440, no DB client at all). Each write goes to `link_log_<UTC>.jsonl`, reversed by `--undo` (:275-310). Every run writes `link_plan.csv` and `handback.csv` + `handback_legend.txt` (`write_handback` :319-376).
  - `scripts/build_modular11_ea_games_csv.py`: `build_rows` (:78-121) makes two importer rows per played game whose two keys are both linked and sends the rest to `held_games.csv`. `live_links` (:227-246), `usable_links` (:249-268), `planned_links` (:216-224, `--planned` writes `import_planned.csv`), `unstored_rows` (:147-187) and `impact` (:190-213, uses `GlickoConfig.MIN_GAMES_PROVISIONAL`). It prints `games_added= already_stored= held= teams_touched= crossing_12_games=`. It has no since-date or future-date filter.
  - `src/models/modular11_ea_matcher.py:17-34` `Modular11EaGameMatcher` is alias-only (`_match_team` calls only `_match_by_provider_id`, :30); `PROVIDER_CODE` is defined there (:13).
  - `src/models/modular11_ea_keys.py`: `ea_key(uid, season)` gives `uid:season` (:26-27), `split_ea_key` (:30-34, uses `.isdigit()`), `refuse_raw_keys` (:37-44), `season_start_year` (:47-48), `club_state` raises `UnknownClubError` for an unknown or placeholder club (:51-54), `CLUB_STATES` from `config/modular11_ea_club_states.json`.
  - `.github/workflows/ea-scraper.yml`: cron `'0 5 * * 1'` (:11), dispatch inputs `age` and `execute` (:13-23), `AGE_ROLLOVER_FREEZE: 'false'` (:31), concurrency group no-cancel (:33-35), serial matrix (:41-45), step chain scrape → match report → dry-run plan (`if: env.EXECUTE != 'true'`, :93-103) → link `--execute` (:105-114) → build (:116-125) → `import_games_enhanced.py ... modular11_ea` (:127-137), each write step gated `env.EXECUTE == 'true' && env.AGE_ROLLOVER_FREEZE == 'false'`. Artifacts upload `if: always()` (:139-146) and a `$GITHUB_STEP_SUMMARY` is built from the tee'd counts (:148-159).
  - `supabase/migrations/20261005120000_seed_modular11_ea_provider.sql`: one `INSERT INTO providers (code, name, base_url) ... ON CONFLICT (code) DO NOTHING`.
- **`scripts/import_yssl.py` + `yssl-scraper.yml`**: holds back future-dated games with `earliest <= game_date <= today` (:770), `StaleSeasonError` (:266-272) refuses a site still on last season, and the workflow fails an in-season run that read zero scored games (`yssl-scraper.yml:83-89`).
- **`src/models/modular11_matcher.py`**: how the old ids are built: `_build_aliased_provider_team_id` (:1180-1250) gives base club id + `_U{age}` + `_HD|_AD`; `_create_modular11_alias` (:1478-1574) writes `team_alias_map.division` (:1540); `_create_new_modular11_team` (:1305) sets no `state_code`. The `{m11club}` in these ids is a Modular11 academy id (`modular11_schedule.py:474-488`), not a Kitman id, so bridging has to go through club name.
- **`scripts/scrape_playmetrics_league.py:341-360`** `parse_utc_to_local_date`: the existing pattern for Kitman's `start_time` + `local_timezone`.

### Reusable Utilities

- `src/tournaments/alias_writer.py:103-125` `upsert_team_alias` (protects approved and curated rows; `METHOD_TIER` :41-49). It does **not** write `team_alias_map.division`.
- `src/models/game_matcher.py:985` `_match_by_provider_id`; `:1154` `_validate_team_age_group` (the import rejects an alias whose team is another age).
- `src/etl/enhanced_pipeline.py:628-646` regenerates `game_uid` as `{provider}:{date}:{masterA}:{masterB}`; `:1558` `_check_duplicates_by_master_ids` catches the same date + team pair + scores stored under another provider.
- `scripts/match_modular11_ea_teams.py`: `club_relation` (:133-149, same/branch/other, branch-safe), `_name_led_by_club` (:118-125), `squad_words` (:152), `schedule_conflict` (:191-209), `_paged` (:351-359).
- `scripts/find_cross_provider_duplicates.py`: `page` (:143), `load_merge_map` (:212), `merged_into` (:254).
- `src/utils/age_group.py:32-50` `normalize_age_group` (returns None for "U17B" / "U16 AD*", so strip first); `src/utils/team_utils.py:8-17` `_soccer_season_year`; `src/utils/provider_ids.py:16-23` `clean_provider_id` / `is_blank_provider_id`; `src/utils/team_name_utils.py:1094` `resolve_distinction`; `src/utils/us_states.py:16` `STATE_CODE_TO_NAME`; `src/utils/placeholder_clubs.py:87` `is_placeholder_club`.
- `scripts/find_queue_matches.py:822-845` `has_protected_division` (AD/HD/EA/"MLS NEXT" tokens stay out of automated matching, so created names ending HD/AD stay protected).
- `scripts/backfill_team_leagues.py:84-90, 168-190`: `teams.league` (`MLS_NEXT_HD` / `MLS_NEXT_AD`) comes from `team_alias_map.division` or a trailing HD/AD in the name. No workflow runs it.
- `src/rankings/constants.py:36-45` `LEAGUE_MULTIPLIER_MALE`: `MLS_NEXT_HD` 1.00, `MLS_NEXT_AD` 0.98, anything else (including NULL) 0.97, applied to opponent strength for U13+ (`src/etl/glicko_engine.py:383, 825-854, 1656-1760`). Currently 824 teams are labelled HD and 2,415 AD in production.

### Convention Anchors

- **Pipeline shape**: scrape → match report → linker (only alias/team writer, `--execute`, log + `--undo`, hand-back CSV) → games CSV builder (two rows per game, held file, impact print) → `import_games_enhanced.py <csv> <code>` with an alias-only matcher. Files are `scripts/<verb>_<provider>_*.py`, `src/models/<provider>_matcher.py`, `src/models/<provider>_keys.py`, with `PROVIDER_CODE` defined once in the matcher module.
- **Season keys** `uid:season` in `teams.provider_team_id`, `team_alias_map.provider_team_id` and the CSV id columns. The importer keeps non-numeric ids as strings (`import_games_enhanced.py:113-129`; pinned by `tests/unit/test_build_modular11_ea_games_csv.py:252-278`). `.claude/rules/data-safety.md` requires an ASCII-bounded regex, not `.isdigit()`, for values that reach writes.
- **Importer column whitelists** (`stream_games_csv` :83-110, `load_games_csv` :156-183) drop anything unlisted. EA's `IMPORT_COLUMNS` (`build_modular11_ea_games_csv.py:45-67`) is checked against both by a derived test (`test_build_modular11_ea_games_csv.py:75-86`).
- **Pipeline provider branch** at `enhanced_pipeline.py:320-329` passes `dry_run=self.dry_run`; the `else` fallback (:377-379) builds `GameHistoryMatcher` without it. A missing `providers` row raises `ValueError("Provider not found")` (:159-174). EA's branch is pinned by `tests/unit/test_modular11_ea_matcher.py:34-37`.
- **Test registries**: an alias-only matcher stays out of `AUTOCREATING_MATCHERS`, the autocreate parametrize, `REGISTRATION_MATCHERS` (`tests/unit/test_provider_matcher_dry_run.py`) and `_SUBCLASS_PATHS` (`tests/unit/test_birth_year_guard_wiring.py:55-67`, which would fail for it).
- **Freeze coverage** (`tests/unit/test_age_rollover_freeze_coverage.py`): the import step is detected automatically; a new linker script must be added by hand to `AGE_DERIVING_SCRIPTS` (:29-36). Gates must contain `env.AGE_ROLLOVER_FREEZE == 'false'` with no top-level `||`, and the workflow must declare the flag. CLAUDE.md's re-arm list names the workflows.
- **Team-cleanup writer registry** (`scripts/team_cleanup/apply_stage.py`): `WRITER_WORKFLOWS` (:170-192), `APPLIER_SCRIPTS` (:197-238) or the test's `EXEMPT_SCRIPTS` (`test_team_cleanup_apply_stage.py:815-829`). `HARD_STOP_AT = (6, 22*60)` (:165) is `ea-scraper.yml`'s 05:00 UTC cron and a test asserts it is the earliest checked-writer cron after the Wednesday propose, so **a new cron must not be earlier than Monday 05:00 UTC**.
- **Docs guard** `tests/unit/test_agent_doc_references.py:387-399`: a scheduled workflow needs a row in CLAUDE.md's workflow table.
- **Club-to-state guard** `tests/unit/test_placeholder_clubs.py:144, 234`: any function in `scripts/`/`src/` named like `state.*from.*club` or `club.*(state|key)` must import `src.utils.placeholder_clubs`.
- **MLS NEXT display flag** is keyed to the literal code `modular11`: `frontend/lib/api.ts:296-314` (`getTeam`), `frontend/lib/matchPredictionService.ts:319-324`, and `has_modular11_alias` in the newest definitions of `get_national_rankings`, `get_national_rankings_count`, `get_state_rankings`, `get_state_rankings_count` (`supabase/migrations/20260603000000_sargable_age_filter_rankings_rpcs.sql`). It drives `composeTeamDisplay` (`frontend/lib/utils.ts`), which keeps the raw team name.
- **Ranking order**: `calculate-rankings.yml` runs Monday `'30 12 * * 1'`; EA relies on its 05:00 cron landing first and is not in `workflow_run`.

### Proposed Alignment

Follow the EA pipeline closely, deviating where Kitman differs:
- Bridge through the `modular11` aliases and rows instead of excluding them.
- Use YSSL's `game_date <= today` hold-back and in-season zero-games guard.
- Use PlayMetrics' UTC-to-local date conversion.
- Write `team_alias_map.division` and `teams.league` explicitly, since `upsert_team_alias` does not.
- Register the new linker and workflow in the hand-kept registries.

## Implementation Steps

0. **Baseline and local-state hazards (before any edit)**
   - The checkout is on `fix/fixture-score-fill`, 83 commits behind `origin/main`, with uncommitted changes to `.claude/skills/*`, `.turbo/improvements.md` and `scripts/view_teams.py`, plus many untracked `.turbo/` files. Do not build on it and do not stage any of it.
   - Run `git fetch --all --prune`, then branch from `origin/main` with `git checkout -b feat/mlsnext-kitman origin/main` only if the dirty work is first set aside safely. Otherwise use a worktree off `origin/main` per CLAUDE.md's dirty-index exception, and run `npm`/`vitest`/`tsc` in the main checkout (the worktree has no `node_modules`/`.env.local`). Verify with `git diff origin/main --stat` that only intended files differ before the first edit.
   - Note that the new data dir `data/mlsnext_kitman/` is gitignored by `data/*`, so undo logs exist only locally. Copy each run's logs somewhere durable before removing a worktree.

1. **Provider seed migration**
   - Add `supabase/migrations/20261015120000_seed_mlsnext_kitman_provider.sql` modelled on `20261005120000_seed_modular11_ea_provider.sql`: `INSERT INTO providers (code, name, base_url) VALUES ('mlsnext_kitman', 'MLS NEXT', 'https://mls-assist.theintelligenceplatform.com') ON CONFLICT (code) DO NOTHING;`
   - It is applied by hand, then recorded with `supabase migration repair --status applied <version>`. Run `migration-reviewer` on it.

2. **Keys module** `src/models/mlsnext_kitman_keys.py`
   - `PROVIDER_CODE` lives in the matcher (step 4); this module has `kitman_key(squad_id, season)` giving `"{squad_id}:{season}"`, `split_kitman_key` and `refuse_raw_keys`, with an ASCII-bounded regex (`^[0-9]{1,9}:20[0-9]{2}$`) instead of `.isdigit()`.
   - `season_start_year` reuses the Aug-1 rule (same as `modular11_ea_keys.season_start_year`); reuse or import it rather than copying.
   - `club_state(club_name)` reads `config/mlsnext_kitman_club_states.json` and imports `src.utils.placeholder_clubs` (required by `test_placeholder_clubs.py`). It raises an `UnknownClubError` for an unlisted club.

3. **Scraper** `scripts/scrape_mlsnext_kitman.py`
   - GETs the three files with a browser User-Agent and a timeout, no proxy, and a single request each (about 23 MB total, weekly). The feed host answers HTTP 200 with the **web page's HTML** for an unknown file name (the `-25-26` URLs did), so parse the bytes as JSON and fail on anything that is not `{events: [...]}`. Never trust the status alone.
   - Refuse a feed whose `linked_competition_seasons[].key` does not end in the expected season suffix (`26-27`), so a stale or rolled feed fails loudly (YSSL's `StaleSeasonError` pattern). Fail if a file holds fewer than a floor of events (EA's `MIN_ROSTER_TEAMS` pattern; set it from the measured 3,155 / 7,763 / 13,705) and fail an in-season run that read zero scored games.
   - Normalise to `squads.csv` (squad id, season key, club id, club name, age, division HD/AD, competition) and `games.csv` (event id, local date, home/away keys, scores, status). Never touches the DB.
   - Division comes from the file (league and flex files are HD, the academy file is AD), not from the label. Age comes from the `U\d+` prefix of `squad_name`; a label that does not match `^U(13|14|15|16|17|19)( AD)?$` (the "U17B" and "U16 AD*" squads, 3 seen) goes to `held` with a reason and is not guessed.
   - Date: convert `start_time` UTC to local with `local_timezone` (PlayMetrics `parse_utc_to_local_date` pattern). Status `played` only when `completed` is true and both scores are not null; competition "Pro Player Pathway" games count as HD.
   - Prints `k=v` counts for the workflow summary and exits 1 on failure.

4. **Alias-only matcher** `src/models/mlsnext_kitman_matcher.py`
   - Mirror `Modular11EaGameMatcher` exactly (`_match_team` returns `_match_by_provider_id` or `UNMATCHED`; no fuzzy, no create) and define `PROVIDER_CODE = "mlsnext_kitman"` there.
   - Add the provider branch in `src/etl/enhanced_pipeline.py` `_ensure_initialized` next to the EA one (:320-329) with `dry_run=self.dry_run`, and a test pinning it like `test_modular11_ea_matcher.py:34-37`.

5. **Match report** `scripts/match_mlsnext_kitman_teams.py` (read-only)
   - Candidate pool: all non-deprecated teams carrying a `modular11` alias (id `{academy}_U{age}_{HD|AD}`; u19 is parked at `_U18_`, so a Kitman U19 looks up age 19 and 18), resolved through `team_merge_map`. Page with `.order(...)` and a unique column; batch `.in_()` at 100.
   - Bridge by club: Kitman club name → Modular11 club via exact normalised name against the club names on those rows. Use `club_relation` (branch-safe) for same/branch/other. A name that maps to more than one Modular11 club id (160 squads) is `review` unless exactly one candidate fits age + division.
   - Buckets: `confident` (exact club + age + division → one existing team), `review` (near spelling only, branch, ambiguous, or the club also exists under GotSport and the HD/AD team is not already a `modular11` row), `new` (club absent from our MLS NEXT data, or known club with no team at that age/division). Report `candidate_providers` like EA.
   - Never link a near spelling automatically. The measured near-misses include different clubs.

6. **Club → state table** `config/mlsnext_kitman_club_states.json`
   - Build it by script from three sources, in order: the state already on the club's existing MLS NEXT rows, then `config/modular11_ea_club_states.json`, then a blank for the owner to fill. Commit the table with only clubs the owner or the data has settled.
   - Hand the owner a short list of the blank clubs (expected about 80–120) as a checked-in CSV with a legend, per the "approval files need a legend" practice, and wait for it before the first execute. The weekly run **holds** squads of a club missing from the table and lists them in the summary rather than failing the whole run; their games wait and flow once the club is added. (EA raises `UnknownClubError` instead; Kitman differs because an expanding league adds clubs mid-season.)
   - Do not re-enable any of the disabled scheduled state writers. This table feeds team creation only; `fill-team-states-weekly.yml` and `assigning-team-states` handle later corrections.

7. **Linker** `scripts/link_mlsnext_kitman_teams.py` (the only alias/team writer)
   - Mirror `link_modular11_ea_teams.py`: `plan_links`, `apply_plan`, `_usable_target`, `_existing_team`, `_create_team`, `link_log_<UTC>.jsonl` plus `--undo` (remove only teams no game references), `link_plan.csv`, `handback.csv` + legend, `--decisions`, and `--execute` required to write (no DB client at all in a dry run).
   - Alias write through `upsert_team_alias` (mirror :244-253), `match_method`: `fuzzy_auto` for confident, `direct_id` for created, `manual` for owner picks. Key `provider_team_id = "{squad_id}:{season}"`. After the upsert, set `team_alias_map.division` to HD/AD (the helper does not write it) and verify by reading the row back; the base `_create_alias` logs a failed write and returns normally.
   - Created teams: `provider_id` = the new provider, `provider_team_id` = the season key, `team_name` `"{club} U{age} {HD|AD}"`, `club_name` from Kitman's organisation name, `age_group` `u{age}` (lowercase stored form), `gender` `Male` (verify no girls squads are in the feeds; MLS NEXT is boys-only), `state_code` from step 6, `league` `MLS_NEXT_HD` / `MLS_NEXT_AD`. **`league` matters for ranking**: a NULL league applies the 0.97 unaffiliated multiplier instead of 1.00 (HD) or 0.98 (AD) to every opponent-strength figure it touches. Use `resolve_distinction` as the EA/Modular11 creators do.
   - Existing linked teams keep their `modular11` alias; the Kitman alias is added beside it. Never re-point an approved alias: a different target is counted `needs_merge`, as EA does.
   - Refuse a target that is deprecated or of another age/gender (`_usable_target`), and an alias already claimed by another team for the same season.
   - Existing 263 live Modular11 teams have a NULL league; that predates this work, so surface the count in the PR and leave it.

8. **Games builder** `scripts/build_mlsnext_kitman_games_csv.py` (read-only)
   - Mirror `build_modular11_ea_games_csv.py` (`build_rows`, `live_links`, `usable_links`, `planned_links` + `--planned`, `unstored_rows`, `impact`), with `IMPORT_COLUMNS` checked against both importer whitelists by a derived test.
   - Include only games with local date between `2026-08-01` and today (inclusive) and status `played`. A game that is `completed` with a future date goes to `held_games.csv` with the reason `completed_future_dated` (28 seen: they look like rescheduled or placeholder rows). Both teams must be linked and on the same age and gender; a cross-age pair (5 seen) is held, because the importer stamps the home team's age on both rows and would insert the away side half-matched.
   - `unstored_rows` must compare against every provider, so a game already stored under `modular11` is not added a second time.
   - The Kitman event id becomes the game's provider-side id so a re-run is idempotent.
   - Print the impact line (`games_added`, `already_stored`, `held`, `teams_touched`, `crossing_12_games`).

9. **Workflow** `.github/workflows/mlsnext-kitman-scraper.yml`
   - Clone `ea-scraper.yml`: cron `'45 5 * * 1'` (Monday 05:45 UTC, after the 05:00 hard stop and well before the 12:30 rankings run), dispatch input `execute` (default false), `AGE_ROLLOVER_FREEZE: 'false'`, concurrency group without cancel, secrets as in EA (`SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}`; the import step also sets `SUPABASE_KEY`). No matrix (the three files hold every age).
   - Steps: scrape → match report → dry-run plan (`if: env.EXECUTE != 'true'`) → link `--execute` → build → `import_games_enhanced.py data/mlsnext_kitman/import.csv mlsnext_kitman`. Each write step gated `env.EXECUTE == 'true' && env.AGE_ROLLOVER_FREEZE == 'false'` with no top-level `||`. Artifacts `if: always()`. Step summary lists new/held clubs (a club missing from the state table) and held games.
   - Register it: add the linker to `AGE_DERIVING_SCRIPTS` (freeze test), the workflow to `WRITER_WORKFLOWS` and the linker to `APPLIER_SCRIPTS` and the scraper, report and builder to `EXEMPT_SCRIPTS` (`apply_stage.py`), a row in CLAUDE.md's workflow table, a row in its Data Providers table, and update its "re-arm" list and count.
   - The workflow is not added to `calculate-rankings.yml`'s `workflow_run` list; like EA, it relies on landing earlier on Monday.

10. **Display flag** (website and database functions)
    - `frontend/lib/api.ts` `getTeam` (:296-314) and `frontend/lib/matchPredictionService.ts` (:319-324): count an alias from either `modular11` or `mlsnext_kitman` (`.in('providers.code', [...])`). Keep the existing property name `has_modular11_alias` rather than renaming it across the frontend (IMP-119 covers removing the flag).
    - New migration redefining `get_national_rankings`, `get_national_rankings_count`, `get_state_rankings`, `get_state_rankings_count` so `has_modular11_alias` also matches the new code. **Take each function's newest definition across all migrations (`20260603000000_sargable_age_filter_rankings_rpcs.sql` today) and keep the argument lists identical**: a changed signature creates an overload, every call then fails with "function is not unique", and dropping the old one wipes its GRANTs. Re-issue ACLs only if a DROP is unavoidable. Run `migration-reviewer`.
    - Add the Vitest cases the existing flag tests use for the new code; run `npm run typecheck`, `npm run test`, `npx eslint .`, `npx prettier --check .` in `frontend/`.

11. **Catch-up run** (operator, in order, with the owner's yes before each write)
    - Scrape; match report; owner reviews `review` rows and fills the blank clubs; link dry run; `build --planned` for the impact figures; then link `--execute`, build, import dry run, import.
    - Confirm from the database, not the run log: re-count Kitman-keyed aliases, teams created, games imported, and compare with the report's counts.

## Verification

- **Unit tests** (new files under `tests/unit/`, serial `python -m pytest tests/unit/test_*mlsnext_kitman* -p no:xdist`; full gate `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`, serially because xdist exhausts the paging file):
  - Keys: valid and invalid season keys, including a Unicode-digit string, an over-long string and a raw id.
  - Scraper: an HTML 200 body for a feed fails; a stale-season feed fails; "U17B" and "U16 AD*" are held; a `completed` row with a future date is held; the UTC-to-local date crosses midnight correctly for a late-evening Pacific game; zero scored games in season fails.
  - Match report: exact club + age + division confident; each near-miss the measurement found (`Los Angeles Sports Club`, `Roseville`, `GFI Academy North`) lands in `review`, never `confident`; a u19 squad resolves through an `_U18_` alias; a club also under GotSport is `review`.
  - Linker: dry run opens no DB client; `--execute` writes the alias, then `division`, then reads both back; a created team carries `league`, `state_code`, `age_group` in lowercase u-form and name `Club U16 HD`; an approved alias is never re-pointed; `--undo` removes only teams with no games.
  - Builder: both teams must be linked and same-age; cross-age and future-dated are held; `IMPORT_COLUMNS` is derived-checked against both importer whitelists; a game already stored under `modular11` is not added.
  - Pipeline: `enhanced_pipeline._ensure_initialized` builds the Kitman matcher with `dry_run` set.
  - Registries: the freeze, team-cleanup and docs-reference tests pass with the new workflow and linker registered.
- **Doubles must refuse what production refuses**: use a double whose zero-row `.single()` raises (`tests/unit/test_athletes2events_matcher.py`), records at `execute()`, returns only the selected columns, and honours `.range()` paging. Do not copy the permissive doubles named in the supabase-pitchrank skill.
- **Mutation checks**: for each multi-part guard (age check, gender check, deprecated check, the two score tests, the date window's two bounds, the cross-age hold), revert one conjunct at a time on a scratch copy and collect the failing test **names**; the new test must be among them. Delete stale `.pyc` after each restore.
- **Dry-run output beats code review**: run the match report and `link_plan` against production and read real rows; spot-check 30 `confident` links by hand, every `review` reason class, and the created-team names and states.
- **Impact, put in the PR** (ranking rule): `games_added`, how many teams on the other side of those games are affected, and `crossing_12_games` in both directions. Expect most existing HD/AD teams to sit well above 12 games from last season. Report any team that ends at zero games.
- **After execution, from the database**: Kitman-keyed alias count per division, created teams per division with non-NULL `league` and `state_code`, no created team in a state the club table did not give, games imported by month (all since 2026-08-01, none future-dated), no game inserted half-matched (both master ids set), and no duplicate of a game already stored under another provider.
- **Weekly job**: the first scheduled run's summary must show new game counts; confirm from the data (games for the week) rather than a green run, as a green run can follow a swallowed failure.
- **Site check**: open one linked and one created MLS NEXT team on `www.pitchrank.io` after deploy and confirm the full registered name shows for both.
- Run `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` before committing, and a code review (`/review-code`) before pushing, since the games feed the Monday ranking run.

## Context Files

- `scripts/link_modular11_ea_teams.py` — the linker to mirror; read `plan_links`, `apply_plan`, `_usable_target`, `_create_team`, `undo`, `write_handback`.
- `scripts/match_modular11_ea_teams.py` — match-report structure, `classify`, `_hold`, `club_relation`; note `fetch_db_teams` excludes the rows Kitman must include.
- `scripts/build_modular11_ea_games_csv.py` — builder, `unstored_rows`, `impact`, `IMPORT_COLUMNS`.
- `scripts/scrape_modular11_ea.py` — scraper shape, counts output, roster floor.
- `src/models/modular11_ea_matcher.py` and `src/models/modular11_ea_keys.py` — the alias-only matcher and key helpers to mirror.
- `.github/workflows/ea-scraper.yml` — workflow to clone, with the freeze gates and summary.
- `src/models/modular11_matcher.py:1145-1250, 1478-1574` — how the old MLS NEXT ids, divisions and names were built.
- `src/etl/enhanced_pipeline.py:159-174, 320-329, 377-379, 628-646, 1558` — provider branch, `ValueError`, `game_uid`, cross-provider duplicate check.
- `scripts/import_games_enhanced.py:83-110, 156-183` — column whitelists.
- `src/tournaments/alias_writer.py` — `upsert_team_alias` and its protections.
- `src/rankings/constants.py:36-90` and `scripts/backfill_team_leagues.py` — why created teams need `league` set.
- `tests/unit/test_age_rollover_freeze_coverage.py`, `tests/unit/test_team_cleanup_apply_stage.py`, `scripts/team_cleanup/apply_stage.py:165-238` — registries and the 05:00 UTC hard stop.
- `frontend/lib/api.ts:296-320`, `frontend/lib/matchPredictionService.ts:312-328`, `frontend/lib/utils.ts` (`composeTeamDisplay`), `supabase/migrations/20260603000000_sargable_age_filter_rankings_rpcs.sql` — the display flag.
- `.turbo/plans/modular11-ea-*.md` and `.turbo/specs/modular11-ea-*.md` — the EA design decisions this plan follows.
