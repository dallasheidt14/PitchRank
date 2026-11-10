---
status: done
---

# Plan: Hide unplayed GotSport forfeit results

## Context

GotSport records some league results that were never played. The investigation of two Dallas U13
teams (`.turbo/investigations/teams-20261109/aug1-provenance/REPORT.md`, local) found
each team's whole National 1 League schedule stored as 0-3 losses, dated on a placeholder (the
season start 2026-08-01, earlier 2027-01-01), with no field or venue. GotSport sends no forfeit or
status field. PitchRank copies the date and score exactly and counts them as games. Because a
game's identity is date + team pair, each time GotSport moved one of these matches PitchRank saved
another copy, so some teams carry the same forfeit twice (Supra United N1 B2012/13 has 9 losses
counted twice today) and others hold copies dated in 2027 that will start counting when the date
passes.

Owner decision 2026-11-09: "disregard forfeits they shouldn't count". This plan hides the forfeits
that can be recognised, and their leftover copies, by setting `games.is_excluded = true` through a
logged, reversible, dry-run-first script. A lone forfeit entered after its date is
indistinguishable from a real 3-0 and is out of reach. Stopping new ones at import (keep GotSport's
match id, skip administrative results, clear removed results) is a separate later PR.

### Decisions already made

- Forfeits do not count (owner, 2026-11-09).
- Include results scored before their own date, gated on a 40-game GotSport check that finds no
  real game among them (owner, 2026-11-09).
- The importer change is its own PR. A saved tournament seeding that used these results is not
  touched here.

### Scope measured read-only 2026-11-09 (raw ids, last 365 days)

| Group | Rows |
|---|---|
| A. A team's results on one date in one competition: 5 or more, all 3-0/0-3 | 96 (+11 older than a year) |
| B. GotSport 3-0/0-3 whose score was saved before the game's date | 247 (228 not in A) |
| C. Other-date copies of A/B pairings: scored 3-0 / blank | 25 / 44 |

These are SQL approximations on raw ids. The script's merge-resolved, tightened rules (below)
will differ; the dry run gives the real numbers.

## Pattern Survey

(Verbatim from `/survey-patterns`, run against `origin/main` @ 9580209b1.)

### Analogous Features
- `scripts/exclude_rescheduled_fixture_leftovers.py:153-252`: the closest match to target C (a re-dated GotSport match). It is a dry run by default. `--execute` requires `--since` (`:160-162`, because "earlier tournaments broke it"), and `--out` sets the log path. It has no `--limit`. It reads the GotSport provider id with an inline `providers.eq("code","gotsport")` (`:165`). It builds a merge map plus a reverse `absorbed` map (`:166-169`) so a result is found under every id a team was saved under. Rows from the last `MIN_AGE_DAYS=7` are skipped (`:58,171`). Its unscored fetch includes already-excluded rows on purpose, so an earlier run's choice still claims its result and a re-run cannot spend one result twice (`:62-72`, `:137-149`). Each result explains at most one fixture, nearest date first, and two stored copies of one match count once (`:104-150`). It uses `created_at` as the save time (`:96`). Output is plain `print`: the scan count, a by-month breakdown, a "saved under a team since merged away" count, cascade collisions, and 5 sample rows.
- `scripts/exclude_unscored_fixture_twins.py:130-219`: the same-date blank beside a scored row. It has `--execute`, `--since` (optional) and `--out`. It skips `REMATCH_PROVIDERS` rows on both sides (`:139-141,113-127`). It is the home of the family's shared helpers (see below).
- Both scripts above share one write block (`twins:186-219`, `rescheduled:215-251`):
  - It refuses an `--out` that already exists.
  - It writes `{"applied": False, "game_ids": [...]}` **before** the first update.
  - It updates in batches of 100 ids: `update({"is_excluded": True}).in_("id", batch).eq("is_excluded", False).is_("home_score","null").is_("away_score","null")`. That is a guarded update on the old value plus on the shape that qualified the row.
  - It counts `len(res.data)`, which is the RETURNING read-back.
  - In `finally` it rewrites the log with `applied: True, games_excluded: n`.
  - It warns when the planned and written counts differ, and prints "To undo: set is_excluded = false for the game_ids in that log."
- `scripts/exclude_none_opponent_games.py:134-247`:
  - Re-run safety is stated in the docstring (`:19-20`): already-excluded rows are skipped and a re-run sweeps stragglers.
  - It refuses `--execute` while there are cascade collisions (`:194-196`).
  - Its log carries the prior state of non-game rows it changes (`prior_review_status`, `:207-220`).
  - It is the only one of these that reads the provider with `.single()` (`:143`).
- `scripts/exclude_merge_duplicate_games.py:265-414`: the most complete write and undo machinery.
  - Flags: `--execute`, `--limit N` (`:274`), `--out`, `--scope merge-clusters|all`, and `--revert <log>` (dry run unless `--execute`).
  - It writes `sent` to the log before each batch, so a batch whose reply was lost is still recorded (`:394-408`). It always uses atomic `write_log`.
  - An `--execute` run that finds nothing still leaves an empty log (`:288-293`).
  - It does not refuse on a collision. It leaves the colliding candidate in place, so every game the run hides is named in its log (`:362-378`).
  - `revert()` (`:229-262`) replays the log through `still_excluded()` (`:216-221`), guards with `.eq("is_excluded", True)`, and stamps `reverted_at` so the log cannot be replayed.
  - Its full-table scan pages by 7-day `game_date` windows rather than deep offsets (`fetch_all_scored_games`, `:142-182`).
- `scripts/reconcile_tgs_scores.py:296-395`: hides a stale scored row one row at a time.
  - The hide is a compare-and-set: `.eq("id").eq("home_score").eq("away_score").eq("is_excluded", False)` (`:374-383`).
  - It re-reads the twin it defers to just before writing (`:363-372`).
  - Each log entry has its own `outcome` (`pending`, `applied` or `skipped`) (`:330-339`).
  - It checks cascades against **every provider's** live games on the hide dates (`fetch_cascade_neighbours` `:123-147`, `split_refused_hides` `:296-313`).
  - `--since` defaults to 45 days back.
  - This is the analog for target D (one specific row, with a guard on its exact score).
- `supabase/migrations/20260325000000_propagate_game_exclusion.sql`:
  - The trigger `trg_propagate_game_exclusion` (`:12-78`) is `AFTER UPDATE OF is_excluded`. It fires only when the flag goes FALSE to TRUE and both master ids are set.
  - It excludes every other non-excluded row with the same `game_date`, the same **raw** unordered master pair and aligned scores, from any provider.
  - Un-excluding cascades to nothing.
  - The same file defines the RPC `exclude_games_for_team_in_range(team, start, end, p_dry_run)` (`:84-138`). It covers scored games only, writes no log, and runs under the 8 s RPC limit. None of the exclude scripts calls it.
  - The trigger was never redefined later.
- `supabase/migrations/20260309000000_restore_ml_bypass_in_immutability_trigger.sql`: this is the newest `prevent_game_updates`. Its Exception 3 lets an `is_excluded`-only UPDATE through on immutable games, so no correction RPC is needed.
- `src/etl/enhanced_pipeline.py:2434-2550`: `_propagate_exclusions_to_new_games` auto-excludes a newly inserted row that matches an excluded row (date, raw pair, scores). `_check_duplicates_by_master_ids` (`~:1848`) treats an excluded row as an existing key. Score corrections skip excluded rows (`:2096`). Together these mean a hidden 3-0 row stays hidden on re-scrape.
- Forfeit detection elsewhere happens only at import, never in GotSport game rows already stored:
  - `scripts/import_htgsports_event.py:156,363` (Forfeit and NoShow flags are not imported)
  - `scripts/import_demosphere.py:193,405`
  - `scripts/scrape_playmetrics_league.py:606` and `scrape_playmetrics_tournament.py:357`
  - `src/tournaments/gotsport_event_structure.py:302`, which maps a status of `forfeit`
  - `GotSportScraper._parse_api_match` (`src/scrapers/gotsport.py:698-818`) reads no status or forfeit field.
- Nothing on origin/main detects administrative 3-0/0-3 slates, scores saved before `game_date`, or stale 3-0 copies. The backlog entry IMP-223 "Future-dated games already carry scores" (`.turbo/improvements.md:959`, status open) is exactly target B's open question, so this work should close it in the same PR.
- Anti-pattern: `scripts/cleanup_dupe_games_by_composite.py` deletes rows and keys on raw ids. `exclude_merge_duplicate_games.py:37-38` already names it as unsafe.

### Reusable Utilities
- `scripts/exclude_unscored_fixture_twins.py:53` — `get_client`. Reads the env vars directly and prefers the service-role key. This family does not use `config.settings`.
- `scripts/exclude_unscored_fixture_twins.py:61` — `_paged(make_query)`. Takes a factory, so each page gets a fresh builder (the skill's `range()` builder-reuse trap). `PAGE=1000`, `ID_BATCH=100` (`:49-50`). The caller must add `.order("id")`.
- `scripts/exclude_unscored_fixture_twins.py:71` — `_linked`. Drops rows that are missing either master id. The trigger never fires on such rows.
- `scripts/exclude_unscored_fixture_twins.py:88` and `exclude_rescheduled_fixture_leftovers.py:75` — `fetch_scored_for`. A batched `.in_("home_team_master_id", ≤100)` over every id a team was saved under, which finds a result whichever side is home.
- `scripts/exclude_merge_duplicate_games.py:103` — `load_merge_map`. Paged and ordered, and it raises on error. Every exclude script imports it.
  - `src/utils/merge_resolver.py:54` `MergeResolver.load_merge_map` **swallows errors into an empty map**, so it fails open. The exclude scripts avoid it.
  - Merges are flattened in the database (`20251230000001_fix_merge_idempotency.sql:107`), so one-hop `merge_map.get(t, t)` is what the twins and rescheduled scripts use.
- `scripts/exclude_none_opponent_games.py:111,124` — `cascade_key` and `cascade_collisions`. A Python mirror of the trigger's match key (raw ids). Imported by four scripts.
- `scripts/reconcile_tgs_scores.py:123` — `fetch_cascade_neighbours`. Fetches every provider's live games on given dates between given teams, which is the full set a hide can cascade into.
- `scripts/apply_vetted_team_merges.py:264,273,280` — `new_log`, `read_log`, `write_log`:
  - `new_log` gives `--out` or a timestamped path, and refuses an existing file.
  - `write_log` writes a `.tmp` file and swaps it in with `os.replace`, so a kill mid-write cannot truncate the log.
  - Open backlog "Share one rollback-log helper across the exclude cleanups" (`.turbo/improvements.md:2646`) says the other five scripts' plain `write_text` should move to this.
- `scripts/exclude_merge_duplicate_games.py:216,229` — `still_excluded` and `revert`. The only `--revert` implementation in the family.
- `src/models/game_matcher.py:476,482` — `REMATCH_PROVIDERS` and `SCHEDULE_ID_SUFFIX_PROVIDERS`. GotSport is not a rematch provider, but it does add a `schedule_id` suffix to the uid on a day the same two teams met twice.
- `src/utils/provider_ids.py` — `is_blank_provider_id`. The `''`, `'None'` and `'null'` placeholder set.

### Convention Anchors
- File, CLI and import shape:
  - One file per cleanup at `scripts/exclude_<shape>.py`, with a long docstring stating the rule, the trigger interaction and the undo.
  - It loads root `.env` then `.env.local` with override, and imports siblings in packaged form (`from scripts.x import ...`).
  - `main() -> int` ends with `raise SystemExit(main())`. `--execute` turns off the default dry run, and `--out` names the rollback log.
  - Exit code 1 means it refused on a collision.
- Dry-run output is plain `print`, not rich: counts, a per-month breakdown, a merged-away count, a collision list, a few sample ids, then `"DRY RUN — nothing written. Re-run with --execute."`. A dry run writes no file (CLAUDE.md Code Quality `:1088-1091`), and any printed undo or next command must come from the run's own mode.
- Log location: the cwd (repo root), named `<script>_<UTC %Y%m%dT%H%M%SZ>.json`. No exclude script defaults to `data/backups/`, which is gitignored via `data/*`. A root-level `*.json` is not ignored, and the repo is public.
- Log format: `{"applied": bool, "game_ids": [...], "games_excluded": n}`. The richer form in `exclude_merge_duplicate_games.py` is `rows` with per-row fields plus `sent`, `confirmed` and `reverted_at`. `reconcile_tgs_scores.py` keeps a per-entry `outcome`.
- Writes:
  - Batch 100 ids with `.in_()` (CLAUDE.md pitfall 7, skill `:372`).
  - Guard on `.eq("is_excluded", False)` plus the qualifying shape (scores, or `.is_(…,"null")`).
  - Count `res.data` with the default `returning='representation'` (skill `:700-718`, compare-and-set).
  - Skill `:492-510`: each newly excluded row makes the trigger scan its whole `game_date`, about 13 ms per row, about 1.5 s per 100-id batch, inside the 8 s budget. Count cascade targets before excluding.
  - Nothing in the import path clears `is_excluded`, so the rollback log is the only way back.
- Game immutability: never UPDATE game data. `is_excluded` is the sanctioned quarantine (CLAUDE.md `:1047,1107`). Score changes go through `game_corrections` and `apply_game_correction`.
- Timeouts:
  - There is no explicit 57014 handling in the family.
  - Scans are filtered (`provider_id`, `game_date` bounds, null or non-null scores), ordered by `id` and paged by 1000.
  - A scan over the whole table pages by date window (`fetch_all_scored_games`).
  - RPCs and MCP SQL get 8 s and a function cannot raise its own limit (skill `:397-430`).
- Date and time traps:
  - `created_at` is a save time only when it is after 2025-11-06 (skill `:69-72`).
  - `scraped_at` is set as naive local `datetime.now().isoformat()` (`gotsport.py:813`).
  - `batch_backfill_null_scores` **overwrites** `scraped_at` with the fill time when it scores a fixture (`20260602000000_add_batch_backfill_null_scores.sql:53`). For a filled fixture, `scraped_at` therefore means when the score arrived.
  - GotSport `competition` = `competition_name or division_name or event_name`, with the "Transfer Competition" placeholder replaced by `event_name` (`gotsport.py:323,788-809`).
  - GotSport's team feed lists played games only since 2026-10-01 (`.turbo/improvements.md:2643`), so no later scrape will drop a stale row.
- Test doubles, by file:
  - `tests/unit/test_exclude_unscored_fixture_twins.py:62-146`: `_Query`/`_DB`. It projects the selected columns, evaluates filters at `execute()`, records `(table, op)` in `db.executed` at `execute()`, and raises on any unmodeled builder method. It has no `or_` or `not_`, no max-rows cap, no `range`-without-`order` refusal, and does **not** model the trigger.
  - `tests/unit/test_exclude_rescheduled_fixture_leftovers.py:143-159` subclasses it, adding `lte` and a 100-id `.in_()` assertion.
  - `tests/unit/test_exclude_merge_duplicate_games.py:26-124` models the trigger. `trigger_key` is read from the migration, not from the code under test, and `propagate_exclusion` applies it. It also models `not_.is_`, refuses `range()` without `order()`, has `IN_BATCH_LIMIT` (from `test_find_cross_provider_duplicates.py:93`), and `update_faults` set to "refused" or "lost".
  - The skill (`:261-317`) also asks for a max-rows cap, fixtures stored out of id order, and checks on filter columns.
- What the tests guard:
  - dry run writes nothing and no log
  - the log exists before the first update (a `_Watching.execute`)
  - an existing log is refused
  - a row scored after selection is not excluded (patches the selector)
  - already-excluded rows are not logged again
  - more than 100 teams are batched
  - merged-away ids on either side
  - other providers are not evidence
  - a cascade into another provider's row is refused
  - `--execute` without `--since` is refused
- CLAUDE.md test rules (`:39-150`): a double records at `execute()`; it refuses what production refuses; a mutation must kill the new test by name; revert each conjunct of a compound guard separately; bind the test at the composition (`main`).

### Proposed Alignment
Follow the exclude family directly:
- Place the script at `scripts/exclude_<shape>.py`, with a dry run by default, `--execute`, `--since` (required for `--execute`, as in the rescheduled script) and `--out`.
- Import `get_client`, `_paged`, `_linked`, `ID_BATCH`, `load_merge_map` and `cascade_key`/`cascade_collisions` rather than re-deriving them.
- Write the log with `new_log`/`write_log`, before the first update, carrying per-row detail and `sent`. Take the `--revert` shape from `exclude_merge_duplicate_games.py`, because that log is the only undo.
- Guard each write on `is_excluded = false` plus the exact 3-0/0-3 (or null) scores that qualified the row, with the per-row compare-and-set from `reconcile_tgs_scores.py` for the single target D row.
- Check trigger cascades against every provider via `fetch_cascade_neighbours`. Either refuse or leave a colliding row in place, so every hidden row appears in the log.
- Test it with a double derived from `test_exclude_merge_duplicate_games.py`, which models the trigger, extended with `or_`, a 100-id cap and an ordered-`range` refusal.

Deviate in one place: targets A, B and C need scored-row scans, and `scraped_at` is the save time B depends on. That makes the scan wider than the unscored-only predecessors, so page it by date window. Close IMP-223 in the same PR.

### Where this plan departs from the survey

- **IMP-223 gets an Update, not a close.** It also covers future-dated rows with ordinary scores
  (460 GotSport rows with a non-3-0 score saved before their date, measured 2026-11-09). This work
  answers only the 3-0 part.
- **Log default under `data/backups/`**, not the repo root: the repo is public and a root `*.json`
  is not ignored. `--out` still overrides.
- **D needs no special case.** The revoked Supra-over-Garcia 3-0 (2027-01-01, saved 2026-09-14)
  meets rule B; a test pins that, so no per-row compare-and-set path is added.
- **`--since` defaults to today − 365 days** (the ranking window) rather than being required:
  rows older than that do not count anywhere, and the rules do not depend on season boundaries.

## Implementation Steps

1. **Set up an isolated worktree off `origin/main`.**
   - The main checkout `C:\PitchRank` is a detached HEAD 193 commits behind `origin/main`, with
     unrelated modified files and many untracked ones. Do not branch in place. Run
     `git fetch --all --prune`, then
     `git worktree add C:\pitchrank-hide-forfeits -b fix/hide-unplayed-gotsport-forfeits origin/main`.
   - Verify with `git -C C:\pitchrank-hide-forfeits status --short` (empty) before any edit.
   - The worktree has no `.env`; load the main checkout's root `.env` into the environment for the
     production dry run without printing any value (agents never echo env values).

2. **Write `scripts/exclude_unplayed_forfeit_games.py`** following the exclude family.
   - Docstring: the three rules, why each is safe, the trigger interaction, and the undo.
   - Load env like the family; import `get_client`, `_paged`, `_linked`, `ID_BATCH`, `PAGE` from
     `scripts.exclude_unscored_fixture_twins`, `load_merge_map` and `still_excluded` from
     `scripts.exclude_merge_duplicate_games`, `cascade_key` from
     `scripts.exclude_none_opponent_games`, `fetch_cascade_neighbours` from
     `scripts.reconcile_tgs_scores`, and `new_log`/`read_log`/`write_log` from
     `scripts.apply_vetted_team_merges` (packaged imports only).
   - CLI: `--execute`, `--since YYYY-MM-DD` (default today − 365), `--out PATH` (default
     `data/backups/exclude_unplayed_forfeit_games_<UTC>.json` via `new_log`), `--show-group A|B|C`
     (print every id in that group, for the GotSport check), `--revert LOG` (dry run unless
     `--execute`).

3. **Fetch.**
   - GotSport provider id inline as the family does.
   - Scored candidates: GotSport rows, `game_date >= since` (future dates included),
     `is_excluded = false`, `home_score in (0,3)`, `away_score in (0,3)`, both master ids set
     (`_linked`), paged by `game_date` window like `fetch_all_scored_games`, ordered by `id`.
     Keep only (3,0)/(0,3) in Python.
   - For rule A's "every result that day" check, fetch all scored GotSport rows on each candidate
     date for the candidate teams under every id they were saved under (batched ≤100 ids).
   - For rule C, fetch other rows (scored and unscored, not excluded) of each candidate pairing
     under every saved id, batched ≤100.
   - Resolve every master id one hop through `load_merge_map`.

4. **Select (pure functions, unit-tested directly and through `main`).** `forfeit` means
   (3,0) or (0,3); `loser` is the side with 0.
   - **A — whole schedule on one date:** a resolved team with 5 or more scored GotSport results on
     one `game_date` in one `competition`, all forfeit-shaped, and that team the loser in every
     one. All those rows are A. Record (team, competition) in a `withdrawn` set.
   - **B — scored before its date:** a forfeit-shaped GotSport row with
     `scraped_at < game_date − 1 day` (the full-day margin absorbs naive-local `scraped_at` and
     time zones).
   - **C — leftover copies:** for each A or B row's resolved pair and competition, any other-date
     row of that pair that is (C1) forfeit-shaped with the same resolved loser, or (C2) unscored,
     but C2 only when one side of the pair is in `withdrawn` for that competition (a pair that is
     not withdrawn may have a genuine second meeting).
   - A row in several groups is listed once, with all its group labels.
   - **Cascade:** `fetch_cascade_neighbours` over the selected rows; a neighbour the trigger would
     hide that is not already selected is added with label `cascade`, so the log names every row
     the run hides.

5. **Report (dry run and execute).**
   - Counts per group and in total; per month; dated today or earlier (counted by rankings now)
     versus future-dated; how many rows sit under merged-away ids; cascade additions; up to 5
     sample rows per group with date, teams, score and competition.
   - Blast radius, as the ranking rule requires: distinct resolved teams with a removed game;
     for each, scored games in the 365-day window dated today or earlier before and after; how
     many fall below `GlickoConfig.MIN_GAMES_PROVISIONAL` (read from `src/etl/glicko_config.py`,
     currently 10) and how many reach 0.
   - The two investigated teams must appear: Supra United FC N1 B2013/14 Black Burciaga (14 A rows
     plus copies) and FC Dallas East N1 B2013/14 Garcia (9 A + 6 at 2027-01-01).
   - Dry run ends `DRY RUN — nothing written. Re-run with --execute.` and writes no file.

6. **Write (`--execute`).**
   - Refuse an existing `--out`. Write the log (per-row id, labels, date, raw and resolved ids,
     scores, competition; `applied: false`) before the first update, with `write_log`.
   - Update in batches of ≤100 ids, one batch shape per guard: `.eq("is_excluded", False)` plus
     `.eq("home_score",3).eq("away_score",0)`, or the reverse, or both scores `.is_("null")`.
     Record `sent` before each batch and `confirmed` from `res.data` after; finish with
     `applied: true`, written count, and a warning if it differs from planned.
   - Print `To undo: python -m scripts.exclude_unplayed_forfeit_games --revert <log> --execute`.

7. **Undo (`--revert`).** Mirror `exclude_merge_duplicate_games.revert`: replay the log through
   `still_excluded`, guard `.eq("is_excluded", True)`, stamp `reverted_at`, refuse a stamped log.

8. **Tests: `tests/unit/test_exclude_unplayed_forfeit_games.py`.**
   - Double derived from `tests/unit/test_exclude_merge_duplicate_games.py`: projects selected
     columns, records at `execute()`, refuses `range()` without `order()`, caps `.in_()` at 100,
     models the trigger from the migration's key, and supports the filters the script uses
     (`gte`, `lt`, `in_`, `eq`, `is_`, `not_.is_`).
   - Fixtures, one row per conjunct so each guard can be mutated alone:
     - A: 5 losses 3-0 on one date (hit); 4 (miss); 5 plus a 2-1 that day in the same competition
       (miss); 5 split across two competitions (miss); 5 forfeit wins (miss); losses saved under
       a merged-away id (hit).
     - B: saved 2 days before its date (hit); 12 hours before (miss); a 2-1 saved early (miss);
       another provider (miss); the revoked Supra-over-Garcia shape (hit).
     - C: same pair, other date, same loser (hit); opposite loser (miss); blank of a withdrawn
       pair (hit); blank of a B-only pair (miss); merged-away ids either side (hit).
     - Cascade: a same-date aligned twin from another provider is logged.
   - Write and undo: dry run writes nothing and no file; the log exists before the first update;
     an existing log is refused; a row whose score changed after selection is not hidden; an
     already-hidden row is not logged; `--revert` restores and stamps; a stamped log is refused.
   - One composition test drives `main()` end to end through the double, which does its own
     fetching.
   - Mutation check: revert each conjunct of rules A, B and C and each write guard on its own, and
     confirm a test in this file fails by name each time.

9. **Backlog and docs.**
   - IMP-223: add `- **Update (YYYY-MM-DD)**:` saying the 3-0 part is answered (GotSport posts
     administrative results ahead of the date; this script hides them) and the non-3-0 part (460
     rows on 2026-11-09) stays open.
   - `/note-improvement` for: the importer change (keep the GotSport match id so a moved match
     replaces its copy; skip administrative results; clear a result GotSport removes; correct the
     `past=true` comment at `gotsport.py:451-454`, which returns unscored past matches too); and
     `.claude/rules/ranking-changes.md` naming 12 games where the live floor is 10.

## Verification

- `python -m pytest tests/unit/test_exclude_unplayed_forfeit_games.py -q` passes; the full CI
  form `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py` and
  `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` pass.
- Production dry run from the worktree: `python -m scripts.exclude_unplayed_forfeit_games`.
  Expect counts near the measured A 96, B 247, C 69, with any gap explained by merge resolution or
  the tightened rules (A requires the team to lose all; C2 only for withdrawn pairs). Both
  investigated teams appear with the rows listed in step 5. Zero writes: re-query a sample of
  listed ids and confirm `is_excluded` is still false.
- GotSport check for B (the owner's gate): from `--show-group B`, take 40 random rows dated today
  or earlier and look each match up in both teams' `/api/v1/teams/{id}/matches?past=true`
  histories (one fetcher, paused, plain requests). A row is a real game if GotSport shows that
  pairing within a day of the stored date with the same score **and** a venue or pitch. Proceed
  only if none of the 40 is a real game; otherwise stop, report, and tighten or drop B.
- Owner approves the dry-run counts and blast radius before `--execute`.
- After `--execute`: the written count equals the planned count; the log's ids read back as
  excluded; a fresh dry run selects 0; the Supra U13 Aug 1 rows and the Supra U14 duplicate pairs
  are hidden.
- After the next Monday ranking run: check from the data, not the run log, that Supra U13's and
  Garcia's counted games no longer include any hidden row and their records drop the forfeit
  losses.

## Context Files

- `.turbo/investigations/teams-20261109/aug1-provenance/REPORT.md` — what these rows are and why
  they are safe to hide (local, gitignored).
- `scripts/exclude_merge_duplicate_games.py` — log, `sent`/`confirmed`, `--revert`, date-window
  paging, the trigger-aware double's counterpart.
- `scripts/exclude_unscored_fixture_twins.py` — the shared helpers and the guarded batch write.
- `scripts/reconcile_tgs_scores.py` — `fetch_cascade_neighbours` and scored-row guards.
- `supabase/migrations/20260325000000_propagate_game_exclusion.sql` — the cascade every hide
  triggers.
- `tests/unit/test_exclude_merge_duplicate_games.py` — the double to derive from.
- `.claude/skills/supabase-pitchrank/SKILL.md` — bulk `is_excluded` cost and the double rules.

## As built

- Script `scripts/exclude_unplayed_forfeit_games.py`; tests `tests/unit/test_exclude_unplayed_forfeit_games.py`
  (83 tests). Every condition of every rule, each write and revert guard, the fetch windows, the report lines and
  the log folder were mutated one at a time; all 65 mutations failed a named test in the new file.
- Groups are named `whole_slate` (A), `early` (B) and `copy` (C). Implementation Steps 2-8 and the Pattern
  Survey describe the first draft; the build differs where these bullets say. In particular a trigger
  neighbour refuses the run rather than joining it (no `cascade` label), one fetch of the source teams'
  GotSport rows serves both the same-day check and the copy rule, the log holds raw ids with `stem`,
  `changed` and `inflight`, and the script prints its own undo command. The survey's "played games only" is
  wrong: the `past=true` feed also returns past-dated unscored matches.
- **Copy rule tightened.** A scored copy must have the same loser *and the same home team* as its source, and
  every copy must fall in the source's season (Aug 1 - Jul 31). A GotSport check of all 25 scored copies in the
  first draft found 15 listed at a venue on their own date with that score, scored after the date, several the
  other leg of a home-and-away pair. The host rule removed 18 of the 25, all 15 of those among them; the 7
  scored copies left are, on GotSport, 4 with no field, 2 moved, 1 no longer listed.
- **The early group's gate failed as written, and the owner kept the group.** 26 of 40 sampled early rows
  appear on GotSport at a venue on that date with the same 3-0. Those scores were entered weeks before kickoff
  (one row was first saved already 3-0 on 2026-09-30 for a 2026-10-24 game) and GotSport still lists 3-0, so
  the venue is the fixture's booked field, not evidence of play. Asked 2026-11-09, the owner chose "Hide them
  anyway". Results: `.turbo/investigations/teams-20261109/aug1-provenance/early_sample_results.json` (local).
- **Changes from the first review round:**
  - "Early" uses the later of `scraped_at` and the row's newest approved score correction, which changes a
    score without touching `scraped_at`. Two rows of the first draft's selection had their 3-0 set by a
    correction after kickoff; both now stay.
  - A whole slate needs 5 *different* opponents, so a match stored twice under a merge counts once.
  - The same-day check reads rows whose opponent has no master id yet.
  - A row the exclusion trigger would also hide refuses `--execute` (as the sibling cleanups do) instead of
    joining the run.
  - `--execute` re-reads and re-selects everything just before writing and refuses if anything changed.
  - The log records the ids each update changed (`changed`) and the batch in flight (`inflight`); `--revert`
    restores only those (plus rows the trigger hid with them), and leaves the log unstamped, exiting 1, when it
    restores fewer than it found. `--execute` exits 1 when the read-back differs.
  - The blast radius counts what the ranking loader reads: scored, linked, dated within
    `GlickoConfig.WINDOW_DAYS + WINDOW_GRACE_DAYS` (365 + 0) up to today, games of `team_ranking_exclusions`
    teams left out, both in the per-team counts and in the games the run removes.
- The revert is the script's own (see the Update on "Share one rollback-log helper" in the backlog).
- The plan's second `/note-improvement` (rule text naming 12 games) was dropped: `origin/main` already says 10.
- Production dry run 2026-11-09 on the final code, under a fail-closed read-only guard: 347 rows to hide
  (whole_slate 90, early 238, copy 38; a row can carry two labels). 224 of them count in rankings today and 99
  are future-dated; 31 are unscored fixtures. 270 teams lose a counted game; 13 fall below 10 games; 2 are left
  with none (N1 G2010/11 TX, Cosmos FC U14G Ricardo, both whole-slate teams); 0 trigger
  collisions. All 23 investigated Aug 1 rows are selected.
- The default log goes to `data/backups/` of the checkout holding the script, so a run from a linked worktree
  needs `--out` pointed at the main checkout: removing the worktree deletes its ignored files.
- `--execute` waits on the owner's approval of the dry-run counts and blast radius.
- Smoke test 2026-11-09 against production, every write recorded and not sent, 5/5 passed: the dry run, the
  `--show-group early` listing, `--execute`, a `--revert` dry run, and `--revert` refusing `--since`. The
  `--execute` path sent 5 guarded batches (100 + 68 at 3-0, 100 + 48 at 0-3, 31 unscored) naming exactly the 347 logged rows; a
  read-only spot check found the sampled rows unchanged.
