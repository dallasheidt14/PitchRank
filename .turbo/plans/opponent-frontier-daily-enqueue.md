---
status: done
---

# Plan: Daily opponent-frontier scrape enqueue

## As built (2026-11-23 Arizona, 2026-11-24 UTC)

The 2026-11-24 dates below read as UTC: this plan was written and measured on 2026-11-23 Arizona time,
which is already 2026-11-24 in UTC from 17:00.

- **Skip names.** The game filters count as `home_score_null`, `away_score_null`, `excluded_game`,
  `before_season`, `after_today`, `opponent_master_null` and `opponent_id_blank`. On a day the primary list
  runs, candidates scraped this season count as `scraped_this_season`, so the candidate stage still
  reconciles.
- **`id_not_linked` and `id_malformed` count candidates, not sightings.** A candidate with no linked id counts
  `id_not_linked`; one whose linked ids are all non-numeric counts `id_malformed`. Per-sighting counts would not
  add up to the candidate total.
- **No `httpx` import.** A plain `except Exception` after the `APIError` branch already covers
  `httpx.HTTPError`, so naming it would be an unused import.
- **Production dry run (2026-11-23 23:04 Arizona, behind a guard refusing every non-GET):** exit 0, primary list,
  13 targets of 10,258 candidates (10,245 scraped this season), 17,635 window rows, 798 GET requests, 88.8 s
  (not the 18 s the log read alone took). Zero candidates were held for a recent failure; checked: the 2 failed
  teams in the window's games appear only as the team whose own page was imported. Three targets spot-checked:
  own GotSport id and approved alias, one team each, no own scrape since Aug 1 in the merge group.
- **Mutation run:** 72 mutations, each killed by the test written for it. The first run found one gap: the
  ordering test's team ids sorted the same way as their sighting times, so ordering by team id survived; the
  fixture now sorts them the other way.
- **Changed by code review round 1:**
  - **Volume (corrects the Volume design decision and Step 7's CLAUDE.md wording).** `process_missing_games`
    tops a run up from `teams` only when it finds no pending row (`process_all`), so these rows change a run's
    count only through what else is waiting. Beside 40 or more other pending rows they change nothing; beside 1
    to 39 they add scrapes, up to 40, to a run that would have skipped the top-up; with none, they replace the
    top-up, with fewer scrapes when fewer than 40 of them wait. "Adds no ZenRows spend" holds only in the first
    case and the last case's full runs. CLAUDE.md now says so (corrected twice more, by review round 2 and the
    doc pass, which each found the previous wording one-sided).
  - **`is_deprecated` NULL counts as deprecated**, as in `enqueue_yesterday_games` and the SQL selectors
    (`is_deprecated = false`), not "not true". No team row held NULL on 2026-11-24.
  - **The source id must start the URL** (`https://rankings.gotsport.com/teams/<id>/`), so an event schedule
    URL quoting a team page in its query is not read as a team-page import. All 17,644 window rows matched
    that form on 2026-11-24.
  - **The keyset pager is `_keyset` in `scripts/enqueue_helpers.py`**, beside `_paged`, and the script uses
    that module's `PAGE_SIZE`. The timestamp parser stays in the script; the backlog's IMP-255 records the
    copies.
  - **A guard exit logs one line naming the read that stopped it** instead of the reconciling summary, and an
    int-coded `APIError` (postgrest-py's own, for a response it could not read) logs "outcome unknown"
    rather than "refused".
- **Changed by code review round 2:** any failure other than a string-coded `APIError` (a timeout or dropped
  connection included) logs "outcome unknown", the split `definite_refusal` in `scripts/team_cleanup/run_store.py`
  uses; every one still counts `failed` and exits 1. The import test now allows only the standard library, the
  repo's packages and the dependency closure of the packages the workflow's pip line names, instead of refusing
  six named modules. 105 single-guard mutations, each killed by its named test.

## Context

The owner wants the most cost-effective way to keep queueing GotSport teams that have games we do not
have yet. The 2026-11-23 yield study (`data/backups/scrape_yield_study_2026-11-23/REPORT.md`, gitignored)
found the best signal is a team that just appeared as **someone else's opponent**: every newly imported
game names an opponent that played, and teams we never scrape ourselves only hold the games that happened
to show up on other teams' pages.

A live test confirmed it (Clear Queue run 45290599376, 2026-11-23, after PR #1487's window fix): of 1,000
such teams, the 732 **never scraped by us this season** hit 69% and inserted **2.11 new games per scrape**
(109 reached 10 games and became rank-eligible). The 251 previously scraped ones hit 15% / 0.39, no better
than an ordinary scrape. In the same run `yesterday_game` returned 0.99 per scrape counting filled scores and
`active_team` 0.27. Only 12 of the 1,645 new games duplicated a stored game. Supply is small: about 110
never-scraped teams first appear as an opponent per day in November (4 to 498).

Owner decisions (2026-11-23): queue **never-scraped-this-season teams only**; daily cap **1,000**;
**priority 2**; leave every other producer unchanged (revisit `active_team` after about two weeks of this
job's numbers). On 2026-11-24 the owner added a zero-day fallback to recent opponents we have scraped
before, with a 14-day wait (Design decisions). Owner's framing: "if you think the next best step ... is the just appeared as an opponent
then we need to add that to the enqueu daily and make a github action for that most likely". It is an
**extra** daily job; nothing is replaced.

Measured feasibility (read-only, 2026-11-24): GotSport games created in the last 7 days = about 16,000 rows;
11,258 distinct opponent master ids; their `team_scrape_log` success/partial rows since Aug 1 = 64,164 rows in
17.4 s (batches of 100 ids); 423 never scraped before merge resolution and team filters. A first probe read the
games in 1.0 s with keyset paging on `id`, but that was a warm cache: `EXPLAIN` shows the `ORDER BY id` form walks
`games_pkey` and filters every row (about 2 million), and in review round 3 one of three runs of it hit the 8 s
statement timeout (`57014`). Ordered by `created_at, id` the same read uses `idx_games_created_at` (a backward index
scan plus an incremental sort, 75 ms at offset 15,000). So a Python selector fits a daily Action without a new RPC
or migration, provided the games read pages by `created_at` (Design decisions).

## Pattern Survey

All paths are relative to `C:\pitchrank-opponent-frontier` at HEAD dc3d52c5e.

### Analogous Features
- `scripts/enqueue_viewed_teams.py:150-205`: this is the **closest analogue for a selector that reads tables itself**. `select_targets` runs collect → `resolve_merges` → `load_team_rows` → servable filter (an own GotSport row, or `teams_with_gotsport_alias` at L97-116 plus a non-null `teams.provider_id` rule at L174-182) → cooldown on `teams.last_scraped_at` (L119-126) → `teams_with_pending_user_request` → sort and cap at `--limit` (L201-204). It enqueues the team's *own* provider_id and provider_team_id (L141-142) and relies on the drainer's alias fallback. The prototype differs: it passes the GotSport provider plus the GotSport/alias id.
- `scripts/enqueue_yesterday_games.py:86-107`: pages `games` by keyset (`gt("id", after)`, `.order("id").limit(PAGE_SIZE)`) because the filtered set shrinks while the read runs.
  - It counts skips in a `SKIP_REASONS` stats dict (L69-76, L232) and prints a two-line summary (L325-332).
  - `active_request_verdict` reproduces the RPC's reuse/conflict rule in Python (L143-179).
  - It blanks placeholder ids with `is_blank_provider_id` (L54, L259) and takes a UTC date with `datetime.now(timezone.utc)` (L321).
- `scripts/enqueue_user_interest_teams.py:72-74,157-166`: the **only producer that branches on an RPC SQLSTATE**. On `APIError.code == "23505"` it promotes the waiting row instead. It summarises with an outcomes dict (L240-252) and has an optional `--out` JSON (L227-232). No producer handles `55000` or `22023`.
- `scripts/enqueue_active_teams.py:62-84`, `enqueue_discovery_teams.py:57-72`, `enqueue_safety_net.py:58+`: these hand selection to a `find_*` RPC. The Python only de-duplicates; it does no merge, servability or protection logic.
- `scripts/enqueue_stranded_merge_fixtures.py`: the odd one out. It uses `--execute` instead of `--dry-run` (L89), `print` instead of the logger, and returns exit 1 on any failure (L198).
- **Shared skeleton of every scheduled producer:**
  - optional `truststore` inject, `load_dotenv(".env.local")` then `.env`, `sys.path.append(repo)`, `logging.basicConfig`;
  - module constants `GOTSPORT_PROVIDER_CODE`, `PRIORITY_*`, `REQUEST_TYPE`, `DEFAULT_*`;
  - `get_gotsport_provider_id` using `.single()` and raising `RuntimeError`;
  - URL/key env fallbacks with `sys.exit(1)`;
  - dry run logs the first 20 `WOULD ENQUEUE:` lines and a `...(N total)` line;
  - the live loop catches `Exception` per team and ends with `Enqueued N teams at priority P, M failed`. Exit is 0 even with failures. Example: `enqueue_viewed_teams.py:208-258`.

### Reusable Utilities
- `scripts/enqueue_helpers.py:21` — `_paged(query_builder)`: offset paging ordered by `id`, takes a function that builds the query. Its docstring (L29-30) says keyset paging is needed when rows leave the filter mid-read.
- `scripts/enqueue_helpers.py:41` — `_chunks`: batches of 100 for `.in_()`.
- `scripts/enqueue_helpers.py:46` — `resolve_merges`: one hop through `team_merge_map`.
- `scripts/enqueue_helpers.py:66` — `expand_to_aliases`: adds every id merged into a survivor. Use it for reads of `team_scrape_log` and `scrape_requests` that are filed under pre-merge ids.
- `scripts/enqueue_helpers.py:92` — `load_team_rows`: default columns at L18 are `team_id_master,team_name,provider_id,provider_team_id,last_scraped_at`.
- `scripts/enqueue_helpers.py:109` — `teams_with_pending_user_request`: pending priority-1 rows. **Its docstring (L112-114) is stale.** It says the RPC's UPDATE branch rewrites `game_date`, but the newest RPC only applies `least(priority)` (see below). `enqueue_active_teams.py:94-102` is stale the same way, and `enqueue_discovery_teams.py:75-82` gives a stale reason for a still-true outcome.
- `scripts/enqueue_viewed_teams.py:97` — `teams_with_gotsport_alias`: approved GotSport alias, mirroring `process_missing_games.get_gotsport_alias`. It is not in `enqueue_helpers.py`, so the new script would import it from the viewed-teams script or move it.
- `src/utils/provider_ids.py:21` — `is_blank_provider_id`: catches `""`, `none` and `null`.
- `src/utils/placeholder_team_names.py:29` — `is_placeholder_team_name`: the drainer's placeholder rule.
- `src/utils/team_utils.py:8` — `_soccer_season_year(now=None)`: takes a date or datetime.
- `src/utils/team_utils.py:23` — `scrape_excluded_birth_years(today)`: the drainer's birth-year exclusion. This module is stdlib-only, so it imports with just `pip install supabase python-dotenv` (`src/utils/__init__.py:14-21` guards the pandas imports).
- **No reusable function returns the season's Aug 1.**
  - `src/scrapers/gotsport.py:91-101` computes `date(_soccer_season_year(today), 8, 1)` inline. Importing it pulls in `requests` and `bs4` (L21-22), which the enqueue workflows do not install.
  - `scripts/audit_user_interest_teams.py:82-87` has a duplicate `season_start(today)`.
- **No lightweight "board ages" constant.**
  - `config/settings.py:94-95` `AGE_GROUPS` keys u10–u17 and u19, but `config.settings` imports `src.rankings.constants`. That runs `src/rankings/__init__.py`, which imports the calculator and numpy, so it would break under the workflow's pip install.
  - Hardcoded allowlists exist elsewhere: `src/scrapers/gotsport_tier_parser.py:126` `IN_SCOPE_AGES`, `src/scrapers/sincsports_events.py:75`, `scripts/discover_sincsports_teams.py:74`.

### Convention Anchors
- **The enqueue RPC.** The newest definition by name is `supabase/migrations/20261020020000_atomic_matchbalance_refresh.sql`. `enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint)` (L102-138) wraps `enqueue_scrape_request_once` (L21-97).
  - Raises `22023` if the team, provider, provider_team_id (null or blank), game_date or priority is missing, or priority is outside 1–5 (L40-44).
  - Resolves the input to its merge survivor and matches active rows across the whole merge group (L58-70).
  - Inserts when no active row exists (L72-77).
  - A compatible pending row gets **only** `priority = least(priority, p_priority)`. It never rewrites the registration, the date or the FIFO position (L78-85).
  - "Compatible" means same provider_id and provider_team_id, stored game_date on or before p_game_date (except `missing_game`), and within ±90 days.
  - An incompatible row raises `23505` (L116-122).
  - A processing row whose `processed_at` is more than 24h old raises `55000` (L125-128). A fresh compatible processing row returns its id, which reads as success.
  - Granted to service_role only (L132-135).
  - The unique index `idx_scrape_requests_active_team` covers pending and processing rows (L3-5).
  - No migration puts a CHECK on `request_type`. `dashboard.py:5673-5679` `REQUEST_TYPE_LABELS` falls back to the raw string.
- **`find_*` RPC precedent.** Newest definitions are in `supabase/migrations/20261121000400_scrape_eligibility_reads_placeholder_team_name.sql`.
  - `find_recently_active_teams` (L112-161) is SQL, STABLE, security invoker, and returns `TABLE(team_id_master, team_name, provider_team_id)`. It unions the home and away sides, resolves merges with a LEFT JOIN on `team_merge_map`, then applies `is_deprecated = false`, an age **denylist** (`U8,U-8,U9,U-9`), birth years from `extract(year from now() - interval '7 months')`, and the exact placeholder clause.
  - It is granted to `authenticated, service_role` (`20260622000000_find_recently_active_teams.sql:70`).
  - `find_topup_teams` (L255-313) is the SECURITY DEFINER model, with `SET search_path = ''` and `REVOKE … FROM PUBLIC, anon, authenticated` / `GRANT … TO service_role` (L312-313).
- **RPC time budget.** A service-role RPC gets 8 seconds and cannot raise it (`.claude/skills/supabase-pitchrank/SKILL.md:495-520`). The pattern that works is a caller-driven keyset loop, as in `refresh_team_scrape_activity(p_after, p_batch_size)`, which returns `last_team_id` (`20260827100100_refresh_team_scrape_activity.sql:32-52,140-141`).
- **Migration guards a new RPC would hit.**
  - `tests/unit/test_scrape_activity_predicate.py:264-271`: `PLACEHOLDER_FUNCTIONS` is a hand-written list, so a new RPC is not covered unless added.
  - L289 scans every function for the legacy placeholder name.
  - L163-177 fails if a `canonical-eligibility-v1` predicate block appears outside `GATED_FUNCTIONS`.
  - The repo convention is one test file per migration (for example `tests/unit/test_missing_game_clicks_migration.py`, which reuses helpers from `test_matchbalance_leads_migration.py`).
- **Indexes.**
  - `idx_games_created_at ON games(created_at DESC)` (`20251121000001_add_import_stats_indexes.sql:6`), never dropped.
  - **No index on `games.source_url`.**
  - `team_scrape_log` has only single-column indexes on `team_id`, `provider_id` and `scraped_at DESC` (`20240101000000_initial_schema.sql:215-217`); none is composite. Status CHECK is `success/error/partial` (L211).
- **What the drainers accept.**
  - `scripts/drain_queue.py:97-123` `_is_scrapeable_team` rejects placeholder names, U8/U9 (a denylist, so u7 and NULL pass) and the excluded birth years. A rejected claimed row is marked `completed`, `games_found=0` (docstring L109-115).
  - `drain_queue` claims only GotSport-provider rows (L174-191).
  - `scripts/process_missing_games.py` applies **no** scrapeability filter. It reads every pending row (L89-109) and requires a non-null provider_id and provider_team_id (L429-436).
  - It falls back to an approved GotSport alias only when the row's provider has no scraper (L458-472, via `get_gotsport_alias` at L149-195, on the raw `team_id_master`). On a GotSport 404 it retries the other approved aliases (L476-502).
  - Because the producer's allowlist is narrower than the drainer's denylist, it cannot create rows the drainer would reject.
- **How a failed scrape is recorded.**
  - `process_missing_games`:
    - Team not found: `team_scrape_log` status `error`, `last_scraped_at` advanced (L536-542), request `failed`.
    - WAF block: `error`, timestamp not advanced, re-raised (L549-571).
    - Any other failure: `error`, timestamp not advanced (L573-597).
  - The log's `provider_id` is the provider actually scraped (L441-444, L467).
  - `drain_queue` marks error rows `failed` with "Team not found or scrape error" (L380-421).
  - None of these writes a success or partial row. **A team that never scrapes successfully re-qualifies every day** unless the producer also excludes recent `failed` requests or `error` log rows.
  - Seam: `process_missing_games` only began writing `team_scrape_log` on 2026-08-28 (#1047). Its Aug 1–27 scrapes have no log rows.
- **Workflow shape** (`.github/workflows/enqueue-viewed-teams.yml` is the template):
  - `run-name` with `DRY RUN`/`live`; `workflow_dispatch` inputs `dry_run` (boolean) and `limit` (string, blank means the default).
  - Flags built in job `env` as `${{ inputs.limit != '' && format('--limit {0}', inputs.limit) || '' }}`, which keeps raw inputs out of `run:` (the review-workflows skill's `audit_workflows.py:127` shell-injection check).
  - `concurrency: group: <workflow name>, cancel-in-progress: false`; `ubuntu-latest`; `timeout-minutes: 15` (yesterday-games uses 60).
  - `actions/checkout@v5` and `setup-python@v6` with 3.11; unpinned `pip install supabase python-dotenv` (yesterday-games adds `truststore certifi`).
  - Step env maps `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}`; then `export PYTHONPATH`.
  - The cron comment explains the spread minute (`enqueue-active-teams.yml:13-16`).
- **Cron slots already taken:**
  - Daily enqueue jobs: `47 5` viewed, `13 7` yesterday, `28 10` active.
  - Weekly enqueue jobs: `41 14 * * 0` discovery, `56 16 * * 0` safety-net.
  - Other daily slots: `15 4`, `20 6`, `17 13`, `20 17`.
  - Every hour or every few hours: process-missing-games `7,22,37,52`, backfill-unknown `3,18,33,48`, `50 */3`, `37 */4`, `0 */6`.
- **Rollover freeze.** `tests/unit/test_age_rollover_freeze_coverage.py` detects writers by script name only (L29-42, L48-57). No enqueue script is listed and no `enqueue-*.yml` carries `AGE_ROLLOVER_FREEZE`, so an enqueue-only workflow stays ungated and unlisted, like the existing five.
- **Places the new files must be registered:**
  - `tests/unit/test_team_cleanup_apply_stage.py:948-1006` `NOT_A_WRITER` (the enqueue entries at L969-973 read "writes scrape_requests"). `test_every_workflow_is_checked_or_named_as_left_out` (L1039) fails for an unclassified workflow.
  - `tests/unit/test_agent_doc_references.py:387-399` requires a row in CLAUDE.md's `## GitHub Actions Workflows` table. L160 and L225 check that backticked paths exist and that documented flags are registered with argparse.
  - CLAUDE.md:
    - the workflow table (L704-708);
    - the producer table (L924-942) and "That is every caller" (L944);
    - the non-GotSport paragraph (L954-959);
    - Weekly Cycle (L913-921, ~3,840/day drain);
    - volume caps (L988-996).
  - No skill lists the producers. `supabase-pitchrank` SKILL.md:286-291 covers only the merge-group reads.
- **Test doubles.**
  - `tests/unit/test_enqueue_active_teams.py`, `test_enqueue_discovery_teams.py` and `test_enqueue_safety_net.py` use `Mock()` and assert on `supabase.rpc.call_args` (for example active L49, L68). That records at construction, which **does not comply** with the CLAUDE.md rule, and they never drive `main()`.
  - The strict, compliant doubles each live inside their own test file; there is no shared module:
    - `test_enqueue_viewed_teams.py:40-150`: evaluates eq/in_/gte, projects to the selected columns, requires `order()` before `range()`, records RPCs in `execute()` (L118-135), refuses unseeded tables, and tests itself (L440-463).
    - `test_enqueue_yesterday_games.py:39-224`: a fixed `TABLE_COLUMNS` schema with fixture rows checked against it, `in_()` capped at 100 values, `is_()` accepting null only, gt/limit, a page refused without `order()`, `.single()` raising PGRST116 on zero rows, and RPC params passed through `json.dumps`.
    - `test_enqueue_user_interest_teams.py:120-149`: raises `APIError` per team from the RPC.
  - **None supports `not_`, `or_`, `lt` or `like`**, which the prototype's games query uses.
- **Driving `main()` in tests.** Monkeypatch the module's `create_client`, set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, and set `sys.argv` (viewed L393-398, yesterday L829-835).
  - The clock is frozen by patching a `_FrozenDatetime` subclass onto the module's `datetime` (yesterday L819-831).
  - Paging tests patch `PAGE_SIZE` in both modules (L447-448).
  - Summary log lines are asserted through `caplog` (L839-856).

### Proposed Alignment
Superseded by the Design decisions and Implementation Steps below, which are what to build. The survey's
suggestions that still hold are kept there: `select_targets` shape from `enqueue_viewed_teams.py`, keyset paging
and skip stats from `enqueue_yesterday_games.py`, `APIError.code` branching from `enqueue_user_interest_teams.py`,
a strict execute-recording double (extended as Step 6 lists), no `config.settings` import, and registration in
`NOT_A_WRITER` and the CLAUDE.md workflow table. Its RPC alternative and its `not_`/`or_`/`lt` operators are not
used.

## Design decisions (made during planning, revised by plan review rounds 1 and 2)

- **Python selector, no RPC, no migration.** Measured 18 s against production (see Context). A migration
  would need hand-application and a ledger repair for no runtime gain.
- **Candidate window: GotSport games created in the last 7 days** (`--window-days`, default 7, accepted
  1–30). Wider than the daily cadence so a late or skipped GitHub run loses nothing (`enqueue-active-teams.yml:13-16`
  records a run drifting ten hours and one skipped). Re-selecting a team is harmless: once it is scraped it
  leaves the primary pool. The 2026-11-23 test already drained the older backlog (732 of the 749 never-scraped
  teams then in the pool).
- **Where each game filter runs, and how the window is paged.** The PostgREST games query carries only
  `.eq("provider_id", <GotSport>)` and `.gte("created_at", <window start>)`, ordered `.order("created_at")
  .order("id")` and paged by offset with `.range(offset, offset + PAGE_SIZE - 1)`, a fresh builder per page, rows
  de-duplicated by `id`. Not keyset on `id`: that order walks `games_pkey` and timed out (Context). Compute the window
  start once, before the first page, and pass it to every page. Offset paging is then sound because both filter
  columns never change after insert. `created_at` is an import transaction's start time, so an import that commits
  mid-read can land behind the read position: later pages shift and repeat a few rows (dropped by the
  de-duplication), and the late rows are picked up by the next day's run, which the 7-day window covers. Not keyset
  on `created_at` alone either: an import stamps one `now()` on a whole batch, so a page of ties skips or loops. Every other filter runs in Python on the returned rows: both scores non-null,
  `is_excluded` not true, `season_start_date <= game_date <= today` (UTC; a scored row dated in the future is not
  evidence the team played), a non-null opponent master id, and a non-blank opponent provider id. "Raw window rows"
  means the distinct rows the query returned, before any Python filter; the read guard below counts those.
- **The opponent side comes from the game row.** Every GotSport game row carries `home_provider_id`/
  `away_provider_id`, and `source_url` (`https://rankings.gotsport.com/teams/<id>/game-history`) names exactly
  one of them for team-page imports: 8,810 home and 8,723 away of 17,533 rows on 2026-11-24, none neither. The
  other side is the opponent. Parse the source id with an ASCII-bounded pattern (`gotsport\.com/teams/([0-9]{1,12})/`).
  A row whose source names neither side (the event scraper writes schedule URLs, `src/scrapers/gotsport.py:3110`)
  or both sides is skipped and counted as `source_matches_neither` / `source_matches_both`.
- **A game between two registrations of one team is not an opponent sighting.** Resolve merges on both sides
  (`resolve_merges` over the union of both sides' **non-null** master ids: the helper sorts its input,
  `scripts/enqueue_helpers.py:52`, and a `None` beside UUID strings raises `TypeError`) and skip a row whose
  opponent canonical equals its source side's canonical, counted as `self_game`. A source master can be null (both
  master columns are nullable and the unlink RPC clears one side); such a row still counts as a sighting, since there
  is no second team to compare, and is counted as `source_master_null`.
- **Sightings are kept per GotSport id, with every timestamp.** Fold each qualifying row into `(canonical team,
  opponent GotSport id) -> sorted list of created_at`, so a timestamp never detaches from the registration it came
  from, and the fallback can count the sightings after a team's newest own scrape, which is only known later.
  Earliest, newest and count all derive from the list.
- **One merge-group map feeds every per-team read.** After the team filters, build it once as
  `expand_to_aliases(supabase, {t: t for t in candidates})` (raw id -> canonical, covering every id merged into each
  candidate) and pass it to the scrape-log, failed-request and alias reads. Each reads by every id in the map and
  maps each returned row (log `team_id`, request `team_id_master`, alias `team_id_master`) back to its canonical, so
  a row still filed under a predecessor that the game window never names is not lost.
- **"Never scraped this season"** = no `team_scrape_log` row with `provider_id` = GotSport and `status` in
  (`success`, `partial`) and `scraped_at` on or after the season's Aug 1, checked across the merge-group map (the log
  is not repointed by merges). Never `teams.last_scraped_at`, which `_update_team_scrape_dates` stamps on both sides
  of every imported game.
- **Failed teams wait a week.** Skip a team with a GotSport `error` log row on or after `now - 7 days`, or a
  `scrape_requests` row of **any provider** with `status = 'failed'` and `completed_at` on or after `now - 7 days`,
  both across the merge-group map (`ERROR_COOLDOWN_DAYS = 7`). Any provider, because every scrape is a GotSport
  scrape: `process_missing_games` reroutes a row whose provider has no scraper to the team's GotSport alias
  (`process_missing_games.py:457-472`), and `drain_queue` claims GotSport rows only. Both drainers write `error` log
  rows (`drain_queue.py:495-545`, `process_missing_games.py:536-597`) and stamp `completed_at` on a failed request
  (`process_missing_games.py:127-128`, `drain_queue.py:407-411`). The request check covers a lost log write:
  `process_missing_games._flush_scrape_log` only warns when its batch insert fails (`process_missing_games.py:802-810`).
- **Two kinds of season bound.** `season_start_date(today)` returns a `date`, compared with `games.game_date`. The
  scrape log's `scraped_at` is a timestamp, so `season_start_instant(today)` returns the same day at 00:00 UTC,
  timezone-aware; the log read starts at `min(<season instant>, now - 7 days)` (two aware datetimes; a `date`
  against a `datetime` raises `TypeError`), serialized with `.isoformat()`. So on Aug 1 a July 31 error still holds,
  and only log rows at or after the season instant count as "scraped this season". The functions carry the
  `_date`/`_instant` names so a local value never shadows them (`season_start = season_start(today)` raises
  `UnboundLocalError`). Log writers stamp naive `datetime.now()`, which the database reads as UTC; on GitHub's UTC
  runners that is exact.
- **Values from PostgREST are strings.** Parse at the read boundary: `game_date` with `date.fromisoformat`, and
  `created_at`, `scraped_at` and `completed_at` with `datetime.fromisoformat` (after turning a trailing `Z` into
  `+00:00`), treating a naive value as UTC, as `enqueue_viewed_teams.scraped_within_cooldown:119-126` does. Every
  comparison then runs on `date` or aware `datetime` values.
- **Known seam, accepted:** `process_missing_games` wrote no `team_scrape_log` before 2026-08-28 (#1047), so a
  team scraped only by it between Aug 1 and 27 reads as never scraped and gets one extra scrape.
- **Teams already in the queue stay in.** A team holding a pending or processing row is still sent to the RPC.
  The live RPC lowers a compatible pending row's priority number to 2 and keeps its `requested_at`
  (`20261020020000_atomic_matchbalance_refresh.sql:78-85`), and both drainers claim by `priority ASC,
  requested_at ASC`, so a waiting p3/p4 row for one of these high-yield teams jumps the line. Measured 2026-11-24:
  0 of the 422 never-scraped candidates held an active row, so they cost no cap slots. Such a reused row keeps its
  original `request_type`, so it is not counted in the yield measurement below.
- **Which GotSport id to enqueue.** A team's linked ids are its own `provider_team_id` (when `teams.provider_id`
  is GotSport) plus its approved GotSport `team_alias_map` ids. Keep only sightings whose id is linked
  (`id_not_linked` otherwise) and passes `GOTSPORT_ID_RE.fullmatch(value)` with `GOTSPORT_ID_RE = re.compile(r"[0-9]{1,12}")`,
  which is ASCII-only and admits no trailing newline (`id_malformed` otherwise: a non-numeric id
  makes the scraper return nothing before any request, and that scrape is logged `partial`, which would retire the
  team from the primary pool for the season). For a primary target, choose the linked id with the most sightings,
  ties to the smallest string; its `first_seen` is the earliest sighting among its linked ids. For a fallback target,
  choose only among linked ids holding a sighting created after the team's newest own scrape, by the count of those
  later sightings, ties to the smallest string (with the default 7-day window and 14-day wait every in-window sighting
  qualifies; with a longer window, the most-seen id may carry only old sightings). Then check the name against the
  **chosen** id, `is_placeholder_team_name(team_name, chosen_id)`, which is the pair the drainer checks
  (`drain_queue.py:77-79`); skip `placeholder_name`. Enqueue with the **GotSport provider id**, because `drain_queue`
  claims GotSport-provider rows only (`drain_queue.py:174-191`) and `process_missing_games` scrapes a GotSport row
  directly.
- **Team filters** (allowlist, inside the drainer's denylist): live (`is_deprecated` not true), `age_group`
  lower-cased in the board set u10–u17 and u19, `birth_year` not in `scrape_excluded_birth_years(today)`, and
  **not ranking-excluded** (the placeholder-name check runs after the id is chosen, above). The board set is a module constant, because
  `config.settings` cannot be imported under the workflow's install; a unit test pins it to
  `config.settings.AGE_GROUPS`. The ranking exclusion mirrors `src/rankings/data_adapter.py:563-598`, which drops
  every game touching an excluded team, so scraping one adds nothing to any board: map every
  `team_ranking_exclusions.team_id_master` through `resolve_merges` and skip a target whose canonical is in that set
  (`ranking_excluded`). Measured 2026-11-24: 1,265 exclusion rows, covering 5 of the 422 never-scraped candidates.
  This matches the owner-approved backlog entry "Keep excluded teams out of the scheduled scrape queue"
  (`.turbo/improvements.md:2863-2869`), which covers the other producers.
- **No pending-user-request protection.** The live RPC only applies `least(priority)` to a compatible row and
  never rewrites its date (`20261020020000_atomic_matchbalance_refresh.sql:78-85`), so a priority-2 call cannot
  disturb a user's priority-1 row.
- **Order under the cap:** primary targets by `(first_seen, team_id_master)`. With supply around 110 a day and a
  cap of 1,000, the cap rarely binds.
- **Zero-day fallback: recent opponents we have scraped before (owner, 2026-11-24).** Owner: "If there's ever 0
  then can we queue recent opponents", then "Or if you have a more effective idea on what to queue it with", and
  chose a 14-day wait. Rule: **only when the primary list is empty after every filter**, queue up to `--limit`
  teams from the same candidates (same window, team filters, linked-id checks, failure wait) that were scraped this
  season, whose newest own GotSport success/partial scrape is **at least 14 days old** (`--rescrape-after-days`,
  default 14, accepted 1–90), **and** that have a linked sighting created after that newest own scrape (new
  evidence since our last look, which matters when `--window-days` exceeds the wait). Order by
  `(newest own scrape, team_id_master)`, oldest first. They go in at priority 2 as `request_type`
  **`opponent_frontier_rescrape`**, measured apart from the main rule. Why this and not something else: of the
  measured options for previously scraped teams, only the stale 6-9-game rescrape did better (26% hit against
  15%), and it needs every candidate's season game count, too heavy for a daily read; this rule reuses rows the job
  already reads. The 5-day version measured 15% / 0.39 games per scrape; the study's best re-scrape gap was 10-14
  days (21% hit). The fallback pool was 6,181 teams on 2026-11-24, so a fallback day fills its cap.
- **Read guards: two reads can fail silently, and each turns the run red before any enqueue, in a dry run too.**
  - *No raw window rows.* An outage, a wrong provider id or a broken filter returns nothing. This is an alarm,
    not a spend guard: the fallback draws from the same candidates, so an empty read queues nothing either way.
    A normal week holds about 16,000 rows, and on Aug 1 the window still holds July rows, so a healthy rollover
    day does not trip it.
  - *A scrape-log read that comes back empty.* This is the read whose failure inflates volume: every candidate
    would read as never scraped and the main rule would fill its 1,000 cap daily while staying green. Exit 1 when at
    least 100 distinct canonical candidates passed the team filters and the scrape-log read returned **zero rows of
    any status**. The check runs on the count at that stage, before the failure wait, id checks and cap. A healthy
    day reads tens of thousands of rows (66,616 on 2026-11-24), and because the read starts at the earlier of Aug 1
    and seven days ago, early August still reads late-July rows. A share-based test ("more than half never scraped")
    was rejected in review round 2: early in a season most candidates genuinely have not been scraped yet (measured
    read-only with the season start set to 2026-08-28: 99.8% and 84% on days 1 and 2), so it would turn the job red
    exactly when its pool is largest. A short but non-empty read is left to the keyset paging and its test.
- **RPC outcomes and exit status.** Success counts `enqueued` (a reused row reads the same). `APIError` code
  `23505` counts `already_queued` (a conflicting registration or date already waits). `55000` counts
  `stuck_processing` (the team's row has sat in `processing` over 24 h; `scripts/retire_stranded_scrape_requests.py`,
  operator-run, clears it). Any other `APIError` (including `22023`), `httpx.HTTPError` or other exception counts
  `failed`. The loop always continues to the next target after a failure. **Exit 1 when any attempt ends `failed`
  or `stuck_processing`**; `23505` never reddens. The summary
  names the retire script when `stuck_processing > 0`. Measured: 16 recent runs of the three daily producers made
  about 25,000 RPC calls, whose only failures were `23505`, so this rule would have reddened none of them.
- **Public logs.** This repo is public, so a workflow step's output is published (CLAUDE.md, Code Quality). Set
  `logging.getLogger("httpx").setLevel(logging.WARNING)` (as `scripts/train_point_in_time_match_model.py:49` does),
  because httpx logs every PostgREST URL at INFO, team ids included. Every run inside GitHub Actions, live or dry,
  logs counts only. GotSport ids are not public data here: the browser roles were refused `teams.provider_team_id`
  and the games' provider-id columns on purpose (`supabase/migrations/20261121000100_hide_provider_ids_from_public_reads.sql:1-11`),
  and a dispatched dry run's output is as public as a scheduled one. So the detailed preview (the first 20 targets'
  GotSport id and team name) is printed only when the `GITHUB_ACTIONS` environment variable is not `"true"`, which
  is a local run such as the Verification dry run; inside Actions the dry run prints the same counts as a live run.
- **Schedule: daily 08:43 UTC** (01:43 Arizona). Both drainers claim by `priority ASC, requested_at ASC`
  (`process_missing_games.py:100-101`, `20260526100000_claim_queue_items.sql:34`), so within priority 2 the enqueue
  time sets the order: after `yesterday_game` (07:13) and ahead of `active_team` (10:28). GitHub's start times
  drift by hours, so this ordering is best effort. Minute 43 collides with no listed slot.
- **Volume: this job changes which teams get scraped, not how many.** `process_missing_games` scrapes top-up
  teams from the `teams` table whenever it finds no pending row (`scripts/process_missing_games.py:610-613`), and
  Clear Queue tops up to its own limit, so a new row takes the place of a top-up scrape (0.20 games per scrape in
  the study) or waits behind other rows; it adds no ZenRows spend. The main rule is supply-limited (about 110 rows
  a day). A fallback day queues the full `--limit`: 1,000 rows is 25 drainer runs, about 6 h of the 15-minute
  drainer, against priority-2 inflow of about 3,100 a day (1,842 `active_team`, 1,200 `yesterday_game`, 58
  `viewed_team` in the 24 h to 2026-11-24) and a drain of about 3,840, so other priority-2 rows wait longer that day.
- **Workflow install pinned to what CI tests.** `pip install supabase python-dotenv -c requirements.lock`: the lock
  carries no hashes, so it works as a constraints file, and pins `supabase==2.18.1` and `python-dotenv==1.1.1`,
  which CI installs (`supabase==2.18.1` in turn pins postgrest 1.1.1, per the `supabase-pitchrank` skill). This
  departs from the five sibling enqueue workflows on purpose; the backlog entry "Install the pinned Supabase client
  in the scheduled queue workflows" covers those.
- **Not on the `AGE_ROLLOVER_FREEZE` list.** The job writes `scrape_requests` only, like the five existing enqueue
  workflows (`tests/unit/test_age_rollover_freeze_coverage.py:29-57` detects writers by script name).
- **Where this plan departs from the survey's Proposed Alignment.** No `not_`/`or_`/`lt` in production queries
  (filters run in Python, above), so the copied double is extended as Step 6 lists; `22023` gets no branch of
  its own and counts `failed`; and `team_ranking_exclusions` has no `id` column (its key is `team_id_master`), so
  `enqueue_helpers._paged`, which orders by `id`, cannot read it.
- **Service-role key required.** Unlike the viewed-teams skeleton, do not fall back to `SUPABASE_KEY`: that is the
  anon key, and `team_ranking_exclusions` revokes access from anon and authenticated
  (`supabase/migrations/20260917120000_add_team_ranking_exclusions.sql:46-58`). Exit 1 before building a client when
  `SUPABASE_SERVICE_ROLE_KEY` is missing, dry run included.
- **Skipped in review round 1, with reasons:** a daily budget shared across same-day runs (one operator dispatches
  by hand, and drain capacity is fixed, so a second run changes composition, not spend); paging the reverse-merge
  and alias lookups inside each 100-id batch (the hosted project returns up to 200,000 rows per request); excluding
  already-queued teams (above).
- **Skipped in review round 2, with reasons:** quoting each workflow input into a shell array (only the owner can
  dispatch, which needs repo write access, and the five sibling enqueue workflows build flags the same way; the
  numeric bounds are tested instead); treating a failed request under a non-GotSport provider as no failure (every
  scrape is a GotSport scrape, above); reading back each returned request id to tell inserts from reuses (the
  first-live-run check allows for reuse instead, Verification).

## Implementation Steps

0. **Setup (local-state hazard).** Work only in the worktree `C:\pitchrank-opponent-frontier`, branch
   `feat/opponent-frontier-enqueue`, created off `origin/main` dc3d52c5e. Do **not** use `C:\PitchRank`: it sits on
   `chore/carry-forward-local-notes`, 50+ commits behind, with another session's uncommitted files. Before editing,
   run `git fetch origin && git status --short` in the worktree (expect only this plan file untracked) and
   `git log -1 origin/main`; if `origin/main` moved, `git merge origin/main` (never rebase: the guard blocks
   force-push). The worktree has no `.env`; run the production dry run from `C:\PitchRank` as the cwd, pointing at
   the worktree's script (Verification), so `load_dotenv(".env")` finds the root file while `sys.path` still
   resolves the worktree's `scripts` and `src`.

1. **Create `scripts/enqueue_opponent_frontier.py`** on the shared producer skeleton
   (`scripts/enqueue_viewed_teams.py:1-60, 208-258`): truststore inject, `load_dotenv(".env.local")` then `.env`,
   `sys.path.append(repo)`, `logging.basicConfig(level=INFO)` plus `logging.getLogger("httpx").setLevel(logging.WARNING)`.
   Constants: `GOTSPORT_PROVIDER_CODE = "gotsport"`, `PRIORITY_OPPONENT_FRONTIER = 2`,
   `REQUEST_TYPE = "opponent_frontier"`, `RESCRAPE_REQUEST_TYPE = "opponent_frontier_rescrape"`,
   `DEFAULT_LIMIT = 1000`, `DEFAULT_WINDOW_DAYS = 7`, `DEFAULT_RESCRAPE_AFTER_DAYS = 14`, `ERROR_COOLDOWN_DAYS = 7`,
   `BOARD_AGE_GROUPS = frozenset({"u10", ..., "u17", "u19"})`, `PAGE_SIZE = 1000`, `MIN_CANDIDATES_FOR_LOG_GUARD = 100`,
   `SOURCE_ID_RE` and `GOTSPORT_ID_RE` (both ASCII `[0-9]{1,12}`). `get_gotsport_provider_id` as in viewed-teams.
   Imports: `scripts.enqueue_helpers` (`_chunks`, `resolve_merges`, `expand_to_aliases`, `load_team_rows`),
   `src.utils.team_utils` (`_soccer_season_year`, `scrape_excluded_birth_years`), `src.utils.provider_ids`
   (`is_blank_provider_id`), `src.utils.placeholder_team_names` (`is_placeholder_team_name`),
   `postgrest.exceptions.APIError`, `httpx`. Nothing that imports `config.settings`, pandas, requests or bs4.
   Packaged imports only (`from scripts.x import ...`).

2. **Selection functions.** Each is single-purpose so tests can drive it; `select_targets(supabase, provider_id,
   now, window_days, rescrape_after_days, limit)` composes them and returns a result holding the target list, which
   list it is (`primary` or `rescrape`), the raw window row count, the guard verdicts and a `stats` Counter of every
   skip reason.
   In this order:
   - `season_start_date(today) -> date`: `date(_soccer_season_year(today), 8, 1)`, and
     `season_start_instant(today) -> datetime`: the same day at 00:00 UTC, timezone-aware. Locals holding their
     values use other names (`season_day`, `season_at`).
   - `fetch_window_games(supabase, provider_id, since_iso)`: offset pages over `games` with only the two filters named
     in the Design decisions, `.order("created_at").order("id").range(...)`, a fresh builder per page, stopping on a
     short page, rows de-duplicated by `id`. Columns: `id, game_date, created_at, home_team_master_id,
     away_team_master_id, home_provider_id, away_provider_id, home_score, away_score, is_excluded, source_url`. The
     number of distinct rows is `raw_rows`; when it is 0, stop with the `no_games_read` verdict.
   - `opponent_sightings(games, season_day, today)`: parse each row's strings, apply the Python game filters and the
     source-side rule, and return `(opponent master, source master or None, opponent GotSport id, created_at)` tuples
     and the skip counts (`source_matches_neither`, `source_matches_both`, and one per game filter).
   - Resolve the non-null masters of both sides with `resolve_merges`, drop `self_game` rows, count
     `source_master_null`, and fold sightings per `(canonical, GotSport id)` into a sorted list of `created_at`.
   - `load_team_rows(columns="team_id_master,team_name,provider_id,provider_team_id,age_group,birth_year,is_deprecated")`
     on the canonical ids, then the team filters (`no_team_row`, `deprecated`, `not_on_board`,
     `excluded_birth_year`).
   - `ranking_excluded_canonicals(supabase)`: page `team_ranking_exclusions` by keyset on `team_id_master`
     (`.select("team_id_master").order("team_id_master").limit(PAGE_SIZE)` with `.gt("team_id_master", last)`), map
     through `resolve_merges`, return the canonical set; skip `ranking_excluded`. The teams left are the
     **candidates**.
   - Build the merge-group map once: `group = expand_to_aliases(supabase, {t: t for t in candidates})`.
   - `own_scrape_status(supabase, provider_id, group, season_at, cooldown_start)`: read `team_scrape_log` in
     batches of 100 of the map's raw ids (`.select("id,team_id,status,scraped_at").eq("provider_id", gs)
     .in_("team_id", batch).gte("scraped_at", min(season_at, cooldown_start).isoformat())`, keyset on `id` within each
     batch, the cursor reset for the next batch), map each row through `group`, and return per candidate: scraped this
     season (success/partial at or after `season_at`), the newest such `scraped_at`, and whether an `error` row sits at
     or after `cooldown_start`;
     also the number of log rows read. When there are at least `MIN_CANDIDATES_FOR_LOG_GUARD` candidates and that
     number is 0, stop with the `scrape_log_empty` verdict.
   - `recently_failed(supabase, group, cooldown_start)`: `scrape_requests` in batches of 100 of the map's raw ids
     (`.select("id,team_id_master").eq("status", "failed").gte("completed_at", cooldown_start.isoformat())
     .in_("team_id_master", batch)`, keyset on `id` within each batch, **no provider filter**; a null `completed_at`
     never matches), mapped through `group`. Skip
     `recent_error` for either this or an `error` log row.
   - `linked_gotsport_ids(supabase, provider_id, team_rows, group)`: each candidate's own GotSport id plus the
     approved GotSport aliases read in batches of 100 of the map's raw ids (`eq provider_id`, `eq review_status
     approved`, `in_ team_id_master`), owners mapped through `group`; keep sightings whose id is linked and numeric
     (`id_not_linked`, `id_malformed`).
   - Primary list: candidates not scraped this season. Choose each one's id and `first_seen` as in the Design
     decisions, apply `is_placeholder_team_name(team_name, chosen_id)` (`placeholder_name`), sort, and cap
     (`over_limit`).
   - Fallback list, built only when the primary list is empty: candidates scraped this season whose newest own scrape
     is at least `rescrape_after_days` old and that hold a linked sighting created after it (`rescrape_too_recent`,
     `rescrape_no_new_sighting`). For each, count every linked id's sightings after the newest own scrape from its
     timestamp list, choose the id with the most such sightings (ties to the smallest string), apply the same
     placeholder check, sort, and cap. "Primary list empty" is judged after every primary filter, the placeholder
     check included, so a day whose last never-scraped team fails that check still runs the fallback.
   - Either guard verdict (`no_games_read`, `scrape_log_empty`) stops `main()` with exit 1 before any enqueue, dry run
     included.

3. **`enqueue_team(supabase, target, provider_id, today_iso, dry_run)`**: returns without calling anything when
   `dry_run` is true (the writer carries its own guard, per CLAUDE.md Code Quality); otherwise calls
   `enqueue_scrape_request` with exactly `p_team_id_master`, `p_team_name`, `p_provider_id` (GotSport),
   `p_provider_team_id` (the chosen id), `p_game_date` (today's UTC date as an ISO string, never a `date` object),
   `p_request_type` (`"opponent_frontier"`, or `"opponent_frontier_rescrape"` for a fallback target) and
   `p_priority` 2, then `.execute()`, and classifies the outcome as in the Design decisions (in a dry run it returns
   `would_enqueue`). `main()` sends **every** target through `enqueue_team` in both modes, passing `dry_run`, so the
   writer's own guard is on the dry-run path, and continues past a failed target. It logs one summary line naming the
   list that ran, with counts grouped by the stage that produces them, so each group reconciles on its own:
   game rows (`raw_rows` = rows kept as sightings + each game-filter and source-side skip; `source_master_null` counts
   kept rows and is reported beside them, not subtracted), canonical teams (folded teams = candidates + each team-filter
   skip; candidates = targets + each later skip + `over_limit`), and writer outcomes (targets = `enqueued` +
   `already_queued` + `stuck_processing` + `failed`, or `would_enqueue` in a dry run). It exits 1 on a guard verdict or
   on any `failed` / `stuck_processing` outcome, and names `scripts/retire_stranded_scrape_requests.py` when
   `stuck_processing > 0`.

4. **CLI and dry run.** argparse flags `--dry-run`, `--limit` (default 1000, accepted 1–5000),
   `--window-days` (default 7, 1–30), `--rescrape-after-days` (default 14, 1–90); a value outside its range is an
   argparse error. A dry run performs every read and guard with the exit status a live run would give, logs the
   summary, and executes no RPC. Outside GitHub Actions (`GITHUB_ACTIONS` is not `"true"`) it also logs the first 20
   `WOULD ENQUEUE:` lines with each target's team name and chosen GotSport id; inside Actions it logs counts only
   (Design decisions, Public logs). It writes no file. Env: `SUPABASE_URL` (or `NEXT_PUBLIC_SUPABASE_URL`, as in viewed-teams) and `SUPABASE_SERVICE_ROLE_KEY` only,
   with no `SUPABASE_KEY` fallback; exit 1 before building a client if either is missing. The clock comes from
   `datetime.now(timezone.utc)` through the module's `datetime` name, so tests can freeze it.

5. **Create `.github/workflows/enqueue-opponent-frontier.yml`** from `enqueue-viewed-teams.yml` (preserve its shape:
   `run-name` with DRY RUN/live, a `concurrency` group named for the workflow with `cancel-in-progress: false`,
   `timeout-minutes: 15`, checkout@v5, setup-python@v6 3.11, step env `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}`, `export PYTHONPATH`). The install line becomes
   `pip install supabase python-dotenv -c requirements.lock`. Cron `'43 8 * * *'` with a comment giving the slot's
   reason (after yesterday-games, ahead of active-teams, FIFO within a priority) and the spread-minute note.
   `workflow_dispatch` inputs `dry_run`, `limit`, `window_days`, `rescrape_after_days`, each turned into a flag in
   job `env` via `format()` so no raw input reaches `run:`.

6. **Tests: `tests/unit/test_enqueue_opponent_frontier.py`.** Copy the strict double from
   `tests/unit/test_enqueue_yesterday_games.py:39-224` (there is no shared double module) and extend it:
   - add `gte` with SQL null semantics (a null column value never matches), a multi-key `order()` (the games read
     orders by `created_at` then `id`), and `TABLE_COLUMNS` for `providers`, `games`, `teams`, `team_merge_map`,
     `team_alias_map`, `team_scrape_log`, `scrape_requests`, `team_ranking_exclusions` (the copied double has `eq`,
     `in_`, `gt`, `limit`, `is_`, `order`, `single`, `range`);
   - seed every date and timestamp as the ISO string PostgREST returns (`"2026-11-20"`,
     `"2026-11-23T14:01:52.094868+00:00"`), so the code must parse at the read boundary;
   - project to the selected columns, cap `in_()` at 100, refuse a page without `order()`, store fixture rows out of
     id order, and record each executed table query's filters (column, operator, value) and order so a test can
     assert what reached PostgREST;
   - make the RPC builder enforce the endpoint at `execute()`: refuse any name other than `enqueue_scrape_request` and
     any parameter set other than exactly the seven `p_*` keys, `json.dumps` the params, record `(name, params)`, and
     return a UUID-shaped string on success (the live wrapper returns the request id,
     `20261020020000_atomic_matchbalance_refresh.sql:102-106`); inject a per-team `APIError` like
     `test_enqueue_user_interest_teams.py:120-149`;
   - give the double a `max_rows` (default 1,000, the local PostgREST cap). The paging test sets `max_rows=3` and
     patches `PAGE_SIZE` to 2 in every module that reads it, with at most 3 rows behind any unpaged 100-id batch read.
     For each paged reader (games, scrape log, failed requests, ranking exclusions) it places a **deciding** row past
     the first page of one filtered query, so only a second page changes the result, and asserts that result (a
     target present, or excluded). The scrape-log and failed-request fixtures span two 100-id batches, the second
     starting with a lower row id than the first ended on, so a keyset cursor carried across batches loses a row and
     fails the test.

   Drive `main()` as in `test_enqueue_yesterday_games.py:819-856` (frozen clock, patched `create_client`,
   `sys.argv`, `caplog`). Each case gives literal expected values and, where a guard has several parts, one fixture
   row per part:
   - opponent side for a home and an away source; a source naming neither side (`source_matches_neither`); a row
     whose two sides carry the same provider id but distinct canonical masters (`source_matches_both`, so the self-game
     check cannot be what drops it); a self-game between two registrations merged into one team (`self_game`); a row
     whose source master is null, beside a valid target, still yields its opponent and the run finishes;
   - the games query: the recorded filters for the `games` read are exactly `provider_id eq <GotSport>` and
     `created_at gte <window start>`, ordered by `created_at` then `id`; a row created just before the window start and
     a row from another provider, each otherwise eligible, produce no candidate;
   - each Python game filter on its own row (home score null, away score null, `is_excluded` true, `game_date`
     before Aug 1, `game_date` after today), each naming a distinct opponent that would otherwise be queued, beside one
     valid control row: assert the exact set of target ids (the control only), each filter's own skip count, and that
     `raw_rows` counts all six;
   - the "never scraped" rule: a `success` row since Aug 1 excludes; a `partial` row excludes; a `success` row before
     Aug 1 does not; with the clock frozen at 2026-08-03, a 2026-07-30 `success` row (inside the read, before the
     season) still leaves the team never scraped; a log row under another provider does not exclude;
   - the failure wait: an `error` row inside 7 days excludes and one older does not; a `failed` request completed
     inside 7 days with no log row excludes, under GotSport and under another provider alike; one completed 8 days ago
     does not; one requested 8 days ago and completed yesterday does; a recent `completed` request does not; a
     `pending` request with a null `completed_at` does not; with the clock frozen at 2026-08-01 08:43 UTC, a
     2026-07-31 error excludes and a 2026-07-24 error does not;
   - merges: a game side under a deprecated id is queued under the canonical; a `success` row, a recent `failed`
     request and the only approved alias, each filed under a predecessor id the window never names, each act for the
     canonical;
   - each team filter on its own row (deprecated, u9, excluded birth year) and a ranking exclusion stored under a
     deprecated id; placeholder names against the chosen id: `unknown_123` whose chosen alias is `123` is skipped, and
     `unknown_555` whose chosen id is `123` is kept;
   - ids: the game id equals the team's own GotSport id; the game id via an approved alias; a pending alias and an
     unrelated id skip as `id_not_linked`; a game id that equals this team's approved alias under **another**
     provider (a TGS row with the same number) and no GotSport row skips as `id_not_linked`; approved aliases `"12a4"`, a 13-digit id, `"１２３"`
     (full-width digits) and `"123\n"` skip as `id_malformed`, while a 12-digit id is kept;
   - primary id choice with competing registrations: one team whose own id has 1 sighting (the earliest) and whose
     alias has 3 sends the alias, and its `first_seen` is the own id's earlier sighting; two ids with equal counts send
     the smaller string; under `--limit 1` against a second team first seen in between, the first team still wins on
     its earliest linked sighting;
   - a team already holding a compatible pending priority-4 row is still sent to the RPC;
   - the RPC call recorded at `execute()` equals a literal `("enqueue_scrape_request", {...})` pair
     (`"p_request_type": "opponent_frontier"`, `"p_priority": 2`, `"p_game_date": "2026-11-24"`, the GotSport
     provider id literal, the chosen id);
   - order and cap: three targets with `--limit 2` queue the two oldest by first sighting;
   - argument bounds: `--limit` 0 and 5001, `--window-days` 0 and 31, `--rescrape-after-days` 0 and 91 each exit with
     an argparse error, and 1 / 5000, 1 / 30, 1 / 90 are accepted;
   - fallback: with no primary target, a team last scraped 15 days ago is queued as `opponent_frontier_rescrape` and
     one last scraped 13 days ago is not; oldest own scrape first; with one primary target present, no rescrape target
     is queued; with `--window-days 30`, a team scraped 15 days ago whose only sighting is 20 days old is not queued;
     with `--window-days 30`, registration A holding nine sightings before the team's own scrape and one after, and
     registration B holding two after, sends B; when the last never-scraped candidate fails the chosen-id placeholder
     check and an eligible rescrape candidate exists, the rescrape is queued;
   - guards: zero raw rows exits 1; a window holding only July rows on a clock frozen at 2026-08-01 exits 0 with no
     target; 99 candidates with zero log rows exit 0; 100 candidates with zero log rows exit 1, including when one of
     them would later fail the id check (the guard runs at the candidate stage); 100 candidates whose only log row is
     an `error` row exit 0; with the clock frozen at 2026-08-02, 100 candidates with no success row since Aug 1 but July
     log rows present exit 0 and queue up to `--limit 5`; every exit-1 case asserts zero recorded RPC calls, in a live
     run and in a dry run;
   - outcomes: one `23505` followed by a success exits 0 with `already_queued` 1 and `enqueued` 1; one `55000`
     followed by a success exits 1 with `stuck_processing` 1, `enqueued` 1 and the retire-script line in the log; an
     unexpected error followed by a success exits 1 with `failed` 1, `enqueued` 1 and the second target's call
     recorded;
   - the writer: `enqueue_team(..., dry_run=True)` records no RPC and `dry_run=False` records exactly one; a dry run of
     `main()` on the primary list and on the fallback list, with `enqueue_team` wrapped by a recording spy, calls it
     once per target with `dry_run=True` and the expected target ids, records no RPC, and leaves its working directory
     (a `tmp_path` it is run from) empty;
   - public output: a dry run with `GITHUB_ACTIONS=true` logs no fixture GotSport id or team name (assert a
     recognisable fixture id such as `"7654321"` is absent from `caplog` and stdout), and with `GITHUB_ACTIONS` unset
     the same run logs it in a `WOULD ENQUEUE` line;
   - env: with `SUPABASE_URL` and `SUPABASE_KEY` set and `SUPABASE_SERVICE_ROLE_KEY` removed after the harness sets it
     up, the run exits 1 and the patched `create_client` is never called, dry run included;
   - summary counters: on a fixture with a null-source row, a merged pair and a capped target, each stage's counts
     reconcile as step 3 defines them;
   - season start: frozen 2026-11-24, 2027-07-15 and 2026-08-01 all give 2026-08-01;
   - `BOARD_AGE_GROUPS == set(config.settings.AGE_GROUPS)` (the test environment has the full install).

7. **Register the workflow and document the producer.**
   - `tests/unit/test_team_cleanup_apply_stage.py` `NOT_A_WRITER`: add
     `"enqueue-opponent-frontier.yml": "writes scrape_requests"` beside the other enqueue entries (~L969-973).
   - CLAUDE.md `## GitHub Actions Workflows` table: a row after `enqueue-yesterday-games.yml`,
     `Daily 08:43 UTC | Queue teams that just appeared as an opponent and that we have never scraped this season (priority 2)`.
   - CLAUDE.md producer table under "Scraping is queue-driven": a row for `enqueue_opponent_frontier.py` (Daily, 2,
     "GotSport teams that appeared as an opponent in a game saved in the last 7 days and have no scrape of their own
     this season (team_scrape_log success/partial since Aug 1); ranking-excluded teams are skipped and teams that
     failed in the last 7 days wait a week; on a day with none, up to the same cap of those teams we last scraped
     14+ days ago, as `opponent_frontier_rescrape`").
   - CLAUDE.md "Scrape volume is capped by limits": name the new default (1,000) and state both behaviours from the
     Design decisions' Volume bullet: the main rule is supply-limited (about 110 a day) and a fallback day fills the
     cap, and either way the rows replace top-up scrapes rather than adding to the drainer's fixed 40 a run.
   - Every flag CLAUDE.md names for the script must exist in its argparse (`test_agent_doc_references.py:225`). Do not
     backtick a slash-joined token such as `success/partial` in these rows: the path check reads it as a path.

8. **Backlog.** Extend, rather than duplicate, the two existing entries on the stale explanation:
   `### Correct teams_with_pending_user_request's reason for skipping a user's row` (`.turbo/improvements.md:3246`)
   and `### Correct two queue-job docstrings that still say enqueue_scrape_request re-dates a row`
   (`.turbo/improvements.md:2573`). Add, as `- **Update (YYYY-MM-DD)**:` lines, the precise active-teams location
   (`scripts/enqueue_active_teams.py:94-102`) and a third docstring, `scripts/enqueue_discovery_teams.py:75-82`, which
   reaches the right outcome (a waiting row keeps its date) for a stale reason (it credits `COALESCE` in an UPDATE
   branch the live RPC no longer has). Note two new entries with
   `/note-improvement`: a dashboard label for `opponent_frontier` / `opponent_frontier_rescrape` in
   `dashboard.py:5673-5679`, and the stale docstring in `scripts/retire_stranded_scrape_requests.py` (it says a
   processing row does not block a new pending one, but `idx_scrape_requests_active_team` covers processing). Do not
   fix any of them in this PR.

## Verification

- Stage the new and changed files by path first (`git add scripts/enqueue_opponent_frontier.py
  scripts/enqueue_helpers.py .github/workflows/enqueue-opponent-frontier.yml tests/unit/test_enqueue_opponent_frontier.py
  tests/unit/test_enqueue_helpers.py CLAUDE.md tests/unit/test_team_cleanup_apply_stage.py .turbo/improvements.md
  .turbo/plans/opponent-frontier-daily-enqueue.md .claude/skills/supabase-pitchrank/SKILL.md`), then confirm
  `git diff --cached --stat` lists all ten (the two `enqueue_helpers` files joined when review moved `_keyset` there), including
  step 8's backlog edits and the planning session's lesson edits already in the worktree (a pagination paragraph in
  the `supabase-pitchrank` skill and a provider-id sentence in CLAUDE.md's Code Quality public-output bullet):
  `test_documented_paths_exist` resolves backticked paths against the tracked-file index
  (`tests/unit/test_agent_doc_references.py:126-135`), so it fails for an unstaged new file even though it is on disk.
- `python -m pytest tests/unit/test_enqueue_opponent_frontier.py tests/unit/test_team_cleanup_apply_stage.py tests/unit/test_agent_doc_references.py tests/unit/test_age_rollover_freeze_coverage.py -q`: all pass.
- CI form: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` and
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py` (the worktree's known environment-only failures
  are listed in memory `fresh-worktree-setup-on-pitchrank`; compare failing test names with a baseline run, not the
  count).
- Mutation checks, one guard at a time, confirming the **new test's name** is among the failures: drop the
  `created_at` filter; drop the provider filter; move a Python game filter into the PostgREST query; drop the
  source-side exclusion; drop the both-sides check; drop the self-game check; pass a `None` master to
  `resolve_merges`; drop each score check separately; drop the `is_excluded` check; drop each `game_date` bound
  separately; drop the success/partial check; drop the `partial` status; drop the in-Python season bound on
  success rows; drop the error-log cooldown; drop the failed-request `status` filter; drop its `completed_at` bound;
  add a provider filter to it; start the log read at Aug 1 instead of the earlier bound; drop the merge-group map
  from each of the three reads in turn; drop each team filter; drop the ranking exclusion; check the placeholder name
  against the team's own id instead of the chosen one; accept unlinked ids; drop the numeric id check; run the
  fallback when primary targets exist; drop the 14-day check; drop the sighting-after-scrape check; choose the
  fallback id by total sightings; page the games read by `id`; carry a keyset cursor across 100-id batches; print
  the preview inside Actions; drop the de-duplication by `id`; use `match` instead of `fullmatch` for ids; drop each read guard; trip the log guard at 99 candidates; let a dry run skip a
  guard; exit 0 on `55000`; stop the loop at the first failure; change priority to 3; pass a `date` object; drop
  `.execute()`; drop `enqueue_team`'s own dry-run return; fall back to `SUPABASE_KEY`; ignore `--limit`.
- Read-only production dry run, from `C:\PitchRank` as cwd:
  `python C:\pitchrank-opponent-frontier\scripts\enqueue_opponent_frontier.py --dry-run`. Expect exit 0, a summary
  naming which list ran, skip counts that add up, and `WOULD ENQUEUE` lines naming GotSport ids. On 2026-11-24 a
  read-only probe of the round-1 rule (after merge resolution and the team filters, before the ranking exclusion and
  the any-provider failure wait) found 12 primary targets of 10,423 candidates and a fallback pool of 6,181, so expect
  a primary list of tens to a few hundred. Spot-check three targets against the list that ran: for `primary`, no GotSport
  success/partial `team_scrape_log` row since 2026-08-01 under any id in the merge group; for `rescrape`, a newest own
  scrape at least 14 days old and a linked sighting saved after it. Either way the chosen id is the team's own GotSport
  id or an approved GotSport alias.
- After merge: dispatch the workflow once with `dry_run: true` and read its summary line, then let the 08:43 UTC
  schedule run. Confirm the first live run's rows exist: count `scrape_requests` rows with `request_type` in
  (`opponent_frontier`, `opponent_frontier_rescrape`) and `requested_at` after the run started, and compare it
  with the summary's `enqueued`. A reused waiting row keeps its own `request_type` and `requested_at`, so it is
  not in that count, and the script keeps none of the request ids the RPC returns, so a shortfall cannot be matched
  row by row. Spot-check it instead: a local `--dry-run` just before the scheduled run lists up to 20 targets, and
  for each of those with no new row, look for a pending or processing row under its merge group that was already
  active when the run started, with the same GotSport id and a `game_date` on or up to 90 days before the run's
  date, the rows the RPC reuses (`20261020020000_atomic_matchbalance_refresh.sql:78-85`). Report the
  rest of any shortfall as unverified, since the live run may also have chosen differently as scrapes landed in
  between. A count of zero against a positive `enqueued` is reconciled the same way, after confirming the query ran
  against the production project.
- About a week later, measure yield with the method of the 2026-11-23 test
  (`data/backups/opponent_frontier_test_2026-11-23/measure_hit_rate.py`: games whose `source_url` names the scraped
  GotSport id, saved after the request), applied to this job's queue rows. Design the exact counting rules when that
  measurement runs (owner, 2026-11-24, after three review rounds kept refining them here), and report any rows that
  cannot be credited to one scrape separately from the hit rate. Compare against the test's 69% / 2.11 for the
  primary list, read the pending age of other priority-2 rows on any fallback day, and bring the numbers to the owner
  with the `active_team` question.
- **When the pool dries up.** The owner noted (2026-11-24) "at some point there will be no new teams left and this
  will turn up zero teams". The built-in fallback covers a zero day. November's weekly new arrivals were 1,095, 595
  and 655, levelling near 90 a day, and the "this season" rule resets every Aug 1. On the first days the fallback runs,
  measure `opponent_frontier_rescrape` rows the same way and bring the numbers to the owner; if it does no better than
  `active_team` (0.27 games per scrape), say so.

## Context Files

- `data/backups/opponent_frontier_test_2026-11-23/enqueue_opponent_frontier.py` (in `C:\PitchRank`, gitignored) — the prototype rule this job productionises.
- `scripts/enqueue_viewed_teams.py` — closest table-reading producer; skeleton, filters, `select_targets` shape.
- `scripts/enqueue_yesterday_games.py` — keyset paging over `games`, skip stats, summary lines.
- `scripts/enqueue_helpers.py` — `_chunks`, `resolve_merges`, `expand_to_aliases`, `load_team_rows`.
- `scripts/enqueue_user_interest_teams.py:157-166` — `APIError.code` branching on the enqueue RPC.
- `tests/unit/test_enqueue_yesterday_games.py` — the strict double and `main()` harness to copy.
- `.github/workflows/enqueue-viewed-teams.yml` — workflow template.
- `supabase/migrations/20261020020000_atomic_matchbalance_refresh.sql:21-138` — the live enqueue RPC contract.
- `scripts/drain_queue.py:97-191, 380-545` and `scripts/process_missing_games.py:89-132, 429-613, 795-812` — what the drainers claim, accept, log and top up.
- `src/rankings/data_adapter.py:134-160, 563-598` — how rankings read and apply `team_ranking_exclusions`.
