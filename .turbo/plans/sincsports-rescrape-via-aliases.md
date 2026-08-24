---
status: draft
---

# Plan: SincSports Re-Scrape via Team Alias Map

## Context

`scripts/scrape_games.py` sources teams via `teams.provider_id`. After fuzzy-merge — both the runtime auto-link inside the SincSports discovery flow and the weekly `data-hygiene-weekly.yml` Step 3 hygiene merge — the canonical team row keeps its original `provider_id` (typically `gotsport`), while the SincSports linkage moves into `team_alias_map` as a separate row pointing at the canonical `team_id_master`. The current scraper driver never reads `team_alias_map`, so every fuzzy-linked team silently loses its SincSports re-scrape path. The 2026-04-24 u14 Female full-grid discovery alone produced ~666 affected teams; weekly hygiene merges add another ~5–8.

This plan adds a standalone driver `scripts/scrape_sincsports_games_via_aliases.py` that sources teams from `team_alias_map` (`provider_id=sincsports`, `match_method IN ('direct_id','fuzzy_auto')`, `review_status='approved'`, `match_confidence >= 0.90`), joins to `teams` for canonical metadata, then runs the existing per-team SincSports scrape loop. The driver logs to `team_scrape_log` with `provider_id=sincsports` but deliberately does NOT bump `teams.last_scraped_at` — that timestamp stays owned by GotSport's cron so this driver never suppresses a future GotSport scrape. The longer-term refactor of `scrape_games.py` to always read `team_alias_map` is out of scope.

## Pattern Survey

### Analogous Features

- `scripts/scrape_games.py:253-520` — Closest structural analog. Async driver: argparse → dotenv → Supabase client → team-fetch → asyncio+Semaphore concurrent scrape → JSONL emit (with `file_lock`) → bulk `team_scrape_log` insert + `teams.last_scraped_at` bump (deferred via `log_buffer`) → optional `--auto-import` hand-off. CLI defaults at `:524-544`: `--provider`, `--output`, `--limit-teams`, `--skip-teams`, `--null-teams-only`, `--include-recent`, `--since-date`, `--auto-import`, `--concurrency=30`.
- `scripts/scrape_sincsports_tournament_schedule.py:1-212` — SincSports-specific standalone driver, but tournament-id sourced (does NOT consult `team_alias_map` or `teams`). Useful for the dotenv loader (`:53-57`), JSONL output convention (`data/raw/sincsports_games_tournament_<TID>_<ts>.jsonl` at `:191`), and `import_games_enhanced.py` hand-off shape (`:198-205`).
- `scripts/maintain_gotsport_direct_id_aliases.py:60-83` — Existing paginated read from `team_alias_map` filtered by `provider_id`, `review_status='approved'`, `not_.is_("provider_team_id","null")`. Direct template for the new driver's source query.
- `scripts/backfill_missing_club_names.py:178-227` — `fetch_gotsport_ids` is the closest "alias-first, teams-as-fallback" lookup pattern: reads `team_alias_map` filtered by provider + approved + `in_("team_id_master", batch)`. Direct analog for the alias→teams join shape.
- `src/scrapers/base.py:71-122` — `BaseScraper._get_teams_to_scrape()` shows the pre-RPC pattern: `get_teams_to_scrape` RPC → batched `teams.in_("team_id_master", batch)` re-fetch. The new driver inverts the flow (alias-first, then teams batch-fetch) but reuses the batching idiom.

### Reusable Utilities

- `src/etl/bulk_ops.py:32-63` — `call_rpc_with_fallback(supabase, fn_name, params, *, fallback, limit, log_msg)`. Not strictly required for this driver (alias query is direct, not RPC).
- `src/etl/bulk_ops.py:66-131` — `bulk_update_last_scraped_at(supabase, updates, *, chunk_size=2000, on_missing_function=None)`. **Intentionally NOT used** in this driver — coordination decision: log only, don't bump timestamp.
- `src/scrapers/sincsports.py:22-188` — `SincSportsScraper(supabase_client, provider_code='sincsports')`. Per-team entry point: `scrape_team_games(team_id: str, since_date: Optional[datetime]=None, days_back: Optional[int]=None) -> List[GameData]` at `:114-188`. Returns via `_game_data_to_dict()` at `:535-542`. Throttle envs `SINCSPORTS_DELAY_MIN/MAX/MAX_RETRIES/TIMEOUT/RETRY_DELAY` at `:31-35`. Single `requests.Session` (`:38`) with `HTTPAdapter(pool_connections=10, pool_maxsize=10)` at `:90-94` — bounds safe per-instance concurrency. **404 returns `[]` rather than raising** (`:162-165`), so `TeamNotFoundError`-style handling from `scrape_games.py` does NOT apply.
- `src/etl/pipeline.py:91-94` — `ETLPipeline._get_provider_id()` resolves `providers.code → UUID`. Inherited by `SincSportsScraper`. Use as `scraper._get_provider_id()` for `team_scrape_log.provider_id`.
- `scripts/scrape_games.py:50-58` — `_is_placeholder_unknown_team(team)` filters `team_name == f"unknown_{provider_team_id}"`. Reusable; apply to the joined `teams` row using the alias's `provider_team_id` (not the canonical's).
- `scripts/scrape_games.py:61-101` — `_bulk_log_team_scrapes` writes to `team_scrape_log` AND calls `bulk_update_last_scraped_at`. **Will be cloned but with the timestamp bump removed** per coordination decision.
- `scripts/scrape_games.py:153-250` — `_scrape_team_concurrent(semaphore, scraper, team, ...)` wraps the sync scraper in `asyncio.to_thread`, with `file_lock` for JSONL writes and a `log_buffer` for deferred logging. **`TeamNotFoundError` handling at `:224-244` is GotSport-specific** — drop or replace for SincSports.

### Convention Anchors

- **dotenv loader** (`scrape_games.py:32-47`): `load_dotenv()`, then `.env.local` with `override=True` if it exists, then `logger.info("Loaded .env.local"|"Loaded .env")`. Same idiom in `scrape_sincsports_tournament_schedule.py:53-57`. Not yet consolidated into a helper.
- **Supabase client init** (`scrape_games.py:283`): `create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))`.
- **CLI shape**: `argparse.ArgumentParser` → `asyncio.run(main())` → `KeyboardInterrupt`→`sys.exit(130)`, generic `Exception`→`logger.exception` + `sys.exit(1)` (`scrape_games.py:523-577`).
- **JSONL output** convention: `data/raw/scraped_games_{ts}.jsonl` (gotsport) / `data/raw/sincsports_games_tournament_<TID>_<ts>.jsonl`. New driver: `data/raw/sincsports_games_via_aliases_<ts>.jsonl`.
- **Importer hand-off**: `python scripts/import_games_enhanced.py <out> <provider> --stream --batch-size 1000` (`scrape_games.py:499-510`). Pass `sincsports` as the provider arg.
- **`team_alias_map` schema** (`supabase/migrations/20240101000000_initial_schema.sql:106-117`): `provider_id UUID FK→providers.id`, `provider_team_id TEXT NOT NULL`, `team_id_master UUID FK→teams.team_id_master`, `match_confidence FLOAT`, `match_method TEXT`, `review_status TEXT CHECK IN ('pending','approved','rejected','new_team')`. Locked vocabulary for `match_method`: `direct_id`, `fuzzy_auto`, `fuzzy_review`, `import`, `manual` (per memory `gotcha_match_method_vocabulary`).
- **Merge cascade behavior** (`supabase/migrations/20251230000001_fix_merge_idempotency.sql:178-180`): `execute_team_merge` does `UPDATE team_alias_map SET team_id_master=canonical WHERE team_id_master=deprecated`; canonical's `teams.provider_id` unchanged. **This is the bug the new driver fixes.**
- **`team_scrape_log` schema** (`supabase/migrations/20240101000000_initial_schema.sql:206-217`): `team_id UUID FK→teams.team_id_master`, `provider_id UUID FK→providers.id`, `scraped_at TIMESTAMPTZ`, `games_found INT`, `status TEXT CHECK IN ('success','error','partial')`.
- **No existing SincSports games-scrape workflow**: `.github/workflows/sincsports-team-discovery.yml` is discovery-only. `scrape-games.yml` hard-codes `--provider gotsport`. Workflow integration is explicitly out of scope here; the new script is operator-runnable + manual-dispatchable as a future workflow.

### Proposed Alignment

Mirror `scripts/scrape_games.py` for the script's overall shape (argparse, dotenv pattern, asyncio+Semaphore, JSONL emit, `_bulk_log_team_scrapes` pattern). Mirror `scripts/backfill_missing_club_names.py:fetch_gotsport_ids` for the `team_alias_map` paginated source query, then a batched `teams.in_("team_id_master", batch)` join to fetch `team_name`, `age_group`, `birth_year`, `is_deprecated`. The single non-obvious deviation: drop the `teams.last_scraped_at` bump from the cloned `_bulk_log_team_scrapes` helper (coordination decision — see Context). SincSports-specific behaviors honored: (a) drop GotSport-only `TeamNotFoundError` handling since `SincSportsScraper.scrape_team_games` returns `[]` on 404; (b) default `--concurrency=8` to stay under SincSports `pool_maxsize=10`; (c) skip rows where `teams.is_deprecated=true`; (d) apply `_is_placeholder_unknown_team` against the alias's `provider_team_id`.

## Implementation Steps

1. **Create driver scaffolding and dotenv/Supabase init**
   - New file: `scripts/scrape_sincsports_games_via_aliases.py`.
   - Mirror `scripts/scrape_games.py:1-47` for shebang, module docstring, imports, dotenv `.env.local`→`.env` fallback, `logging.basicConfig`, `Console` instance.
   - Imports include `from src.etl.bulk_ops import call_rpc_with_fallback` (kept for symmetry/future use, even if not invoked) and `from src.scrapers.sincsports import SincSportsScraper`.
   - Module-level constants: `DEFAULT_CONCURRENCY = 8`, `DEFAULT_BATCH_SIZE = 500` (matches `scrape_games.py` log-buffer batch), `ALIAS_PAGE_SIZE = 1000`.

2. **Port `_is_placeholder_unknown_team` and add `_should_skip_team` helper**
   - Copy `scripts/scrape_games.py:50-58` `_is_placeholder_unknown_team(team)` verbatim. Document at top of helper that it operates on a dict with `team_name` and `provider_team_id` — the new driver populates `provider_team_id` from the alias row, not the canonical team's column.
   - Add `_should_skip_team(team, alias) -> Optional[str]` returning a skip reason string or `None`. Skip cases:
     - `alias["provider_team_id"]` is null/empty → `"no_provider_team_id"`.
     - `team.get("is_deprecated") is True` → `"deprecated"` (defense in depth — query already filters, but the row could be stale if it raced with a merge).
     - `_is_placeholder_unknown_team({"team_name": team["team_name"], "provider_team_id": alias["provider_team_id"]})` → `"placeholder_unknown"`.
   - Logger emits a per-skip `logger.info("Skipping %s (%s): %s", team_id_master, team_name, reason)` so operator can audit skip churn.

3. **Implement `_fetch_aliases_to_scrape(supabase) -> List[Dict]`**
   - Resolve `provider_id` for `'sincsports'` once via a `providers.select("id").eq("code","sincsports").single()` call.
   - Paginate `team_alias_map` filtered by:
     - `.eq("provider_id", sincsports_provider_id)`
     - `.in_("match_method", ["direct_id", "fuzzy_auto"])`
     - `.eq("review_status", "approved")`
     - `.gte("match_confidence", 0.90)`
     - `.not_.is_("provider_team_id", "null")`
   - Use `.range(offset, offset+ALIAS_PAGE_SIZE-1)` until empty page (mirror `maintain_gotsport_direct_id_aliases.py:60-83`).
   - Select columns: `id, provider_team_id, team_id_master, match_method, match_confidence, review_status`.
   - Return list of alias dicts. Log total count.

4. **Implement `_fetch_canonical_teams(supabase, team_id_masters) -> Dict[str, Dict]`**
   - Batched `teams.select("team_id_master, team_name, age_group, birth_year, is_deprecated").in_("team_id_master", batch)` reads, batch size 150 to stay under URL-length cap (per `supabase-pitchrank` skill).
   - Filter out rows with `is_deprecated=True` here (belt-and-suspenders alongside Step 5's per-team skip).
   - Return `{team_id_master: team_dict}` map.

5. **Implement `_join_aliases_to_teams(aliases, teams_by_master) -> List[Dict]`**
   - For each alias, look up canonical team by `team_id_master`. Drop aliases whose canonical row is missing (deprecated/deleted) or missing key fields.
   - Return list of "scrape work units": `{team_id_master, team_name, age_group, birth_year, is_deprecated, provider_team_id, alias_id, match_method, match_confidence}`.
   - Log: total aliases → joinable units → after `_should_skip_team` filtering. (Defer the `_should_skip_team` filter to the actual scrape loop so skips are logged per-team alongside scrape outcomes.)

6. **Clone `_scrape_team_concurrent` adapted for SincSports**
   - Copy `scripts/scrape_games.py:153-250` as `_scrape_team_concurrent_sincsports`.
   - Take `(semaphore, scraper, work_unit, output_path, file_lock, log_buffer, since_date)`.
   - Inside the semaphore: call `_should_skip_team(work_unit, work_unit)` first; if reason → append `{status:'skipped', games_found:0, skip_reason}` to `log_buffer` and return.
   - Wrap `scraper.scrape_team_games(work_unit["provider_team_id"], since_date=since_date)` in `asyncio.to_thread`.
   - **Drop `TeamNotFoundError` handling** — SincSports returns `[]` on 404. Treat empty list as `status='success', games_found=0` (consistent with `scrape_games.py`'s "no games" path).
   - Generic `Exception` handler logs and appends `{status:'error', games_found:0}` to `log_buffer` so the team gets a row in `team_scrape_log` with status='error'.
   - Convert each `GameData` via `scraper._game_data_to_dict(game, team_id_master)` and append a JSONL line under `file_lock`.
   - Append `{team_id_master, games_found, status}` to `log_buffer`.

7. **Clone `_bulk_log_team_scrapes` WITHOUT the `last_scraped_at` bump**
   - Copy `scripts/scrape_games.py:61-101` as `_bulk_log_team_scrapes_no_timestamp`.
   - Keep the batched `team_scrape_log` insert (chunked at `DEFAULT_BATCH_SIZE=500`) — write `team_id, provider_id, scraped_at, games_found, status` rows, where `provider_id` is the SincSports provider UUID and `team_id` is `team_id_master`.
   - **Remove** the `bulk_update_last_scraped_at(supabase, update_payload)` call entirely. Add a top-of-function comment: `"# Coordination: this driver intentionally does NOT bump teams.last_scraped_at. That timestamp is owned by GotSport's cron so this driver doesn't suppress next GotSport scrape."`
   - Skipped/error rows still get logged (status `'partial'` for skipped, `'error'` for exceptions) so operators can see skip/error churn in `team_scrape_log` queries.

8. **Implement `main()` and CLI**
   - Mirror `scripts/scrape_games.py:524-577` for argparse shape and `asyncio.run` wiring.
   - CLI flags:
     - `--output` (default: `data/raw/sincsports_games_via_aliases_<timestamp>.jsonl`)
     - `--limit-teams INT` — cap team count after fetch (for testing)
     - `--skip-teams INT` — skip first N teams (resume aid)
     - `--concurrency INT` (default `DEFAULT_CONCURRENCY=8`)
     - `--since-date YYYY-MM-DD` — pass through to `scraper.scrape_team_games`
     - `--auto-import` — bool flag; when set, run `python scripts/import_games_enhanced.py <out> sincsports --stream --batch-size 1000` after the scrape (mirror `scrape_games.py:499-510`)
     - `--dry-run` — fetch & filter only; do not call the scraper or write JSONL/log rows
   - Provider is hard-coded `sincsports` — there is no `--provider` flag.
   - **NO `--include-recent` / staleness flag** per coordination decision: every run scrapes every alias.
   - Exit codes: `KeyboardInterrupt`→`130`, generic `Exception`→`logger.exception`+`1`.
   - Summary console output at end: total aliases fetched, total scraped, total games, skip-reason histogram, error count, output path, optional auto-import status.

9. **Wire main flow in `async def run(args)`**
   - Steps inside `run()`:
     1. Init `supabase = create_client(...)` and `scraper = SincSportsScraper(supabase, provider_code='sincsports')`.
     2. Resolve `provider_id` once via `scraper._get_provider_id()`. Pass to `_bulk_log_team_scrapes_no_timestamp`.
     3. `aliases = _fetch_aliases_to_scrape(supabase)`.
     4. Apply `--skip-teams` / `--limit-teams` to the alias list (in that order).
     5. `teams_by_master = _fetch_canonical_teams(supabase, [a["team_id_master"] for a in aliases])`.
     6. `work_units = _join_aliases_to_teams(aliases, teams_by_master)`.
     7. If `--dry-run`: print stats, exit 0.
     8. Open `output_path` for append; create `asyncio.Lock()` for file writes; create `Semaphore(args.concurrency)`; create `log_buffer = []`.
     9. `await asyncio.gather(*[_scrape_team_concurrent_sincsports(...) for unit in work_units])` with periodic `_bulk_log_team_scrapes_no_timestamp` flushes (mirror `scrape_games.py:472` flush cadence — every 500 entries).
     10. Final flush after `gather` returns.
     11. If `--auto-import`: `subprocess.run(["python", "scripts/import_games_enhanced.py", out, "sincsports", "--stream", "--batch-size", "1000"], check=True)`.
     12. Print summary and return.

10. **Add unit tests for pure logic**
    - New file: `tests/test_scrape_sincsports_games_via_aliases.py`.
    - `test_should_skip_team_*` covering: empty `provider_team_id`, deprecated row, `unknown_<id>` placeholder, well-formed row (passes through).
    - `test_join_aliases_to_teams_drops_missing_canonical` — alias whose `team_id_master` is missing from `teams_by_master` is dropped.
    - `test_join_aliases_to_teams_drops_deprecated` — `is_deprecated=True` row is dropped at join time.
    - `test_fetch_aliases_to_scrape_query_shape` — `unittest.mock.MagicMock` Supabase client; assert the chained filter calls (`.eq("provider_id",...)`, `.in_("match_method",["direct_id","fuzzy_auto"])`, `.eq("review_status","approved")`, `.gte("match_confidence",0.90)`, `.not_.is_("provider_team_id","null")`) all fire in the expected order.
    - Do NOT add a live HTTP integration test; that's what the manual operator dry-run is for.

## Verification

- **Pure unit tests**: `cd C:/PitchRank && pytest tests/test_scrape_sincsports_games_via_aliases.py -v`. Expect all green.
- **Dry-run smoke test (operator-local, no scrape)**:
  ```bash
  cd C:/PitchRank && python scripts/scrape_sincsports_games_via_aliases.py --dry-run --limit-teams 10
  ```
  Expected: prints alias count (>0), shows 10 work units, lists provider_team_id + canonical team_name for each, exits 0. No JSONL written, no `team_scrape_log` rows.
- **Live scrape smoke test (operator-local, real network)**:
  ```bash
  cd C:/PitchRank && python scripts/scrape_sincsports_games_via_aliases.py --limit-teams 5 --concurrency 2
  ```
  Expected: emits `data/raw/sincsports_games_via_aliases_<ts>.jsonl` with games for the 5 teams, writes 5 rows to `team_scrape_log` with `provider_id=<sincsports UUID>`, `teams.last_scraped_at` UNCHANGED for those 5 canonical rows.
- **Coordination check (manual SQL after live smoke)**:
  ```sql
  SELECT team_id, provider_id, scraped_at, games_found, status
  FROM team_scrape_log
  WHERE scraped_at > now() - interval '10 minutes'
  ORDER BY scraped_at DESC LIMIT 20;
  ```
  Confirm rows have the SincSports provider_id (not GotSport's). Then:
  ```sql
  SELECT team_id_master, last_scraped_at FROM teams
  WHERE team_id_master IN (<5 ids from JSONL>);
  ```
  Confirm `last_scraped_at` values pre-date the smoke test (proving the driver did NOT bump them).
- **Bug-fix verification (the actual point)**: Pick 3 teams from the 2026-04-24 u14 Female fuzzy_auto-linked set whose `teams.provider_id != 'sincsports'`. Confirm they appear in the dry-run alias list. (Without this fix they are invisible to `scrape_games.py --provider sincsports`.)
  ```sql
  SELECT t.team_id_master, t.team_name, t.provider_id, m.provider_team_id, m.match_method
  FROM team_alias_map m
  JOIN teams t ON t.team_id_master = m.team_id_master
  JOIN providers p ON p.id = m.provider_id
  WHERE p.code = 'sincsports'
    AND m.match_method = 'fuzzy_auto'
    AND m.review_status = 'approved'
    AND m.match_confidence >= 0.90
    AND t.is_deprecated = false
  LIMIT 3;
  ```

## Context Files

- `scripts/scrape_games.py` — Master template for argparse, dotenv, asyncio loop, JSONL emit, `_bulk_log_team_scrapes` pattern. Read in full.
- `scripts/scrape_sincsports_tournament_schedule.py` — Existing SincSports-specific driver shape; importer hand-off pattern.
- `scripts/maintain_gotsport_direct_id_aliases.py` — Paginated `team_alias_map` read template (lines 60-83).
- `scripts/backfill_missing_club_names.py` — Alias→teams join template (`fetch_gotsport_ids` at lines 178-227).
- `src/scrapers/sincsports.py` — `SincSportsScraper.scrape_team_games` interface, `pool_maxsize=10` constraint, 404→`[]` semantics.
- `src/scrapers/base.py` — `_get_provider_id`, `_log_team_scrape` (deprecated, shows the per-row pattern), batched-fetch idiom.
- `src/etl/bulk_ops.py` — `call_rpc_with_fallback`, `bulk_update_last_scraped_at` signatures (the latter is intentionally unused).
- `supabase/migrations/20240101000000_initial_schema.sql` — `team_alias_map` (lines 106-117) and `team_scrape_log` (lines 206-217) schemas.
- `supabase/migrations/20251230000001_fix_merge_idempotency.sql` — `execute_team_merge` cascade behavior (lines 178-180); confirms why the bug exists.
- `.turbo/improvements.md` (line 189-194) — Original improvement entry. Note: the entry's "filter on `match_method = direct_id`" is corrected to `direct_id` + `fuzzy_auto` here per Step 5 deep-dive (the 666 affected teams are `fuzzy_auto`-linked).
