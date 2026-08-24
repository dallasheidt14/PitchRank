---
type: plan
status: done
---

# Plan: Scrape Games Workflow Performance Optimization

## Context

The Scrape Games GitHub Actions workflow currently takes ~2 h for a 5,000-team manual run and ~4–5 h for the two scheduled 25,000-team Monday runs (brushing the 6 h GitHub timeout). Diagnostics on run 24748419627 isolate the cost to four serializable bottlenecks: per-row `UPDATE` statements (one in `scripts/scrape_games.py::_bulk_log_team_scrapes`, one in `src/etl/enhanced_pipeline.py::_update_team_scrape_dates`), an 84-page paginated alias preload in `src/etl/enhanced_pipeline.py:159-208`, a 130K-row paginated team fetch + Python-side sort in `scripts/scrape_games.py:355-396`, and conservative scrape concurrency that lacks any 429 retry path. Scheduled runs additionally lack any sharding — both 25K batches run as single jobs back-to-back.

Goals: 5K manual run under 1 h, 25K scheduled runs under 2.5 h, no behavior changes (same dedup, same matching tiers, same prioritization at the population level). Out of scope: rewriting the scraper, switching providers, touching ranking/DB code unrelated to scrape-games.

## Pattern Survey

### Analogous Features

- `scripts/restore_rankings_from_history.py:180` — only `psycopg2.execute_values` exemplar in the repo. Outage-recovery script; not the production-write convention.
- `src/rankings/calculator.py:1146-1188` — `batch_update_ml_overperformance(updates JSONB)` RPC pattern. Production-write convention for bulk updates: wrap in a Postgres function taking a JSONB array, call via `supabase.rpc(...).execute()`. Defined in `supabase/migrations/20251125000000_add_batch_update_ml_overperformance.sql:33`.
- `src/rankings/calculator.py:164` — `batch_upsert_game_explainability` follows the same JSONB-array RPC idiom.
- `scripts/scrape_games.py:60-99` — `_bulk_fetch_scrape_dates`: existing batched-IN read pattern (batch_size=100 due to URL length).
- `scripts/scrape_games.py:102-157` — `_bulk_log_team_scrapes`: batches `team_scrape_log` inserts at 500/page but **falls back to per-row `UPDATE` for `teams.last_scraped_at`** with the comment "Supabase doesn't support bulk UPDATE with different values easily." Primary bottleneck #1.
- `src/etl/enhanced_pipeline.py:2213-2232` — `_update_team_scrape_dates`: same per-row `UPDATE` pattern, called once per import batch (~500–800 sequential REST calls per 1000 games). Primary bottleneck #2 (the post-insert gap).
- `src/etl/enhanced_pipeline.py:159-208` — alias preload via `.range(offset, offset+999)` loop, ~84 paginated GETs at 1000 rows each per pipeline init. Primary bottleneck #3.
- `src/etl/enhanced_pipeline.py:1715` — `_bulk_insert_games` exemplar for adaptive chunk halving on SSL/413 errors. Template for the new bulk RPC's adaptive retry.
- `src/scrapers/base.py:71-122` — `_get_teams_to_scrape()` calls existing RPC `get_teams_to_scrape(p_provider_id)` — no `LIMIT` parameter, returns all eligible teams. **Remains untouched** by this plan.
- `supabase/migrations/20260126000000_fix_get_teams_to_scrape_provider_filter.sql:12` — existing `get_teams_to_scrape` RPC. **Do not modify**; add a new function alongside it.
- `src/scrapers/gotsport.py:50-54` — provider throttle env vars (`GOTSPORT_DELAY_MIN=1.5`, `GOTSPORT_DELAY_MAX=2.5`, `GOTSPORT_MAX_RETRIES=3`).
- `src/scrapers/gotsport.py:89-99` — `HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500,502,503,504]))`. **`status_forcelist` does NOT include 429** — no rate-limit retry.
- `src/scrapers/gotsport.py:293-294` — per-team `time.sleep(random.uniform(delay_min, delay_max))` runs **inside the worker after the HTTP response**, not as an inter-request gap. At concurrency N this gives `N / (request_time + sleep)` throughput — raising N does not scale throughput linearly.
- `.github/workflows/scrape-games.yml:6-12` — two cron schedules + `concurrency: { group: game-scraping, cancel-in-progress: false }` to serialize separate workflow runs. **No matrix pattern in any workflow** — sharding will be a new pattern for the repo.

### Reusable Utilities

- `supabase.rpc(name, payload).execute()` — standard JSONB-array RPC call shape (used 4+ places).
- `_bulk_fetch_scrape_dates` — keep as-is; not a bottleneck.
- `EnhancedETLPipeline._bulk_insert_games` (`src/etl/enhanced_pipeline.py:1715`) — adaptive chunk halving on 413/SSL errors. Mirror this pattern in the new bulk-update RPC caller.
- `asyncio.Semaphore` + `asyncio.gather(*tasks, return_exceptions=True)` (`scripts/scrape_games.py:483, 513`) — keep concurrency idiom; only the default value changes.

### Convention Anchors

- **Bulk-write client**: production write paths use Supabase REST + JSONB-array RPC. psycopg2 is reserved for outage tools (one exemplar). New bulk updates here MUST follow the RPC convention.
- **Migration naming**: `supabase/migrations/YYYYMMDDHHMMSS_add_<thing>.sql`.
- **RPC functions**: `LANGUAGE sql` for pure queries, `LANGUAGE plpgsql` for functions with conditional logic. `SECURITY INVOKER` (default) — service_role bypasses RLS, so `SECURITY DEFINER` is unneeded and a privilege-escalation risk. `SET search_path = public, pg_temp` on all functions (Supabase Postgres is PG15+, supports `SET` on SQL functions). No explicit `GRANT` clauses needed: service_role has full access by default, and these RPCs are not exposed to `authenticated` callers.
- **Pagination**: standard `page_size = 1000`, `.range(offset, offset+999)`, break on empty/short. Keep as fallback when RPC fails.
- **Async concurrency**: `Semaphore(N)` + `asyncio.gather`. Existing defaults: 30 (scrape), 8 (backtest), 4 (import).
- **Workflow scaling**: previously achieved by splitting into separate cron triggers, not matrix jobs. Adding matrix is a deliberate new pattern; document the semantics in the workflow file.

### Proposed Alignment

Add three Postgres RPCs **alongside** existing functions (do not modify `get_teams_to_scrape`) and two supporting indexes. Replace the four bottleneck call sites (one in `scrape_games.py`, three in `enhanced_pipeline.py`) with RPC calls, keeping the existing paginated `.range()` fallback only for the specific "function does not exist" error (SQLSTATE `42883`). Add 429 to the gotsport `Retry.status_forcelist`, instrument retry counts via `Retry.history`, and bump scrape concurrency adaptively based on shard count. Restructure the workflow into a two-stage job graph: a single `prepare` job that runs the alias-maintenance script once, followed by a 5-shard matrix that scrapes + auto-imports in parallel. Sharding is done by **hash of `team_id_master`** (not OFFSET), so shards are deterministically disjoint even while other shards mutate `last_scraped_at` mid-run.

## Implementation Steps

### Phase A — Database (migrations)

*Use three sequential `YYYYMMDDHHMMSS` timestamps matching repo convention. Order is **not** load-bearing — the three new functions don't reference each other. Each migration is purely additive; none drops or modifies an existing object.*

1. **Add `bulk_update_last_scraped_at(updates JSONB) RETURNS int` RPC**
   - New file: `supabase/migrations/<TS_A>_add_bulk_update_last_scraped_at.sql`
   - Payload shape: `[{"team_id_master": "<uuid>", "last_scraped_at": "<iso8601>"}, ...]`
   - `LANGUAGE plpgsql`, `SECURITY INVOKER`, `SET search_path = public, pg_temp`. No explicit `GRANT`.
   - Mirror style of `supabase/migrations/20251125000000_add_batch_update_ml_overperformance.sql`.
   - Body shape:
     ```sql
     create or replace function public.bulk_update_last_scraped_at(updates jsonb)
     returns int
     language plpgsql
     security invoker
     set search_path = public, pg_temp
     as $$
     declare
       affected int;
     begin
       if updates is null or jsonb_array_length(updates) = 0 then
         return 0;
       end if;

       update public.teams t
          set last_scraped_at = u.last_scraped_at
         from jsonb_to_recordset(updates) as u(
           team_id_master uuid,
           last_scraped_at timestamptz
         )
        where t.team_id_master = u.team_id_master;

       get diagnostics affected = row_count;
       return affected;
     end;
     $$;
     ```
   - **Behavioral contract** (document in the migration file as SQL comments):
     - Empty/null `updates` → returns 0 immediately.
     - Duplicate `team_id_master` keys → last value wins (UPDATE…FROM picks one arbitrarily; acceptable because callers produce unique keys by construction).
     - Missing `team_id_master` (no matching row in `teams`) → silently skipped. Returned rowcount reflects **actual updates**, not input length. Callers must handle `rowcount < len(payload)` as a warning, not an error.
     - Malformed timestamp strings → cast error raised loudly; do not mask.

2. **Add `get_approved_aliases(p_provider_id UUID)` RPC + covering partial index**
   - New file: `supabase/migrations/<TS_B>_add_get_approved_aliases.sql`
   - `LANGUAGE sql`, `STABLE`, `SECURITY INVOKER`, `SET search_path = public, pg_temp`. No `GRANT`.
   - Returns `TABLE (provider_team_id text, team_id_master uuid, match_method text)` filtered by `provider_id = p_provider_id AND review_status = 'approved'`.
   - Same migration adds covering partial index:
     ```sql
     create index if not exists team_alias_map_provider_approved_idx
       on public.team_alias_map (provider_id)
       include (provider_team_id, team_id_master, match_method)
       where review_status = 'approved';
     ```
   - Migration body comment: "service_role-only RPC; no GRANT needed. Additive — does not modify existing alias tables or functions."

3. **Add `get_teams_to_scrape_limited(...)` RPC alongside existing `get_teams_to_scrape` + composite index**
   - New file: `supabase/migrations/<TS_C>_add_get_teams_to_scrape_limited.sql`
   - Migration body comment: **"This migration is purely additive. The existing `get_teams_to_scrape(p_provider_id)` function used by `src/scrapers/base.py` is NOT modified or dropped."**
   - Signature:
     ```sql
     create or replace function public.get_teams_to_scrape_limited(
       p_provider_id  uuid,
       p_limit        int     default null,           -- null = no limit
       p_shard_index  int     default 0,              -- 0-based
       p_shard_count  int     default 1,              -- 1 = no sharding
       p_include_recent boolean default false,        -- bypass 7-day filter
       p_null_only      boolean default false         -- only last_scraped_at IS NULL
     )
     returns setof public.teams
     language sql
     stable
     security invoker
     set search_path = public, pg_temp
     as $$
       with current_year as (
         select extract(year from now())::int as yr
       )
       select t.*
       from public.teams t, current_year c
       where t.provider_id = p_provider_id

         -- Hash sharding: mutation-safe, independent of last_scraped_at
         and (p_shard_count <= 1 or (hashtext(t.team_id_master::text) % p_shard_count) = p_shard_index)

         -- Staleness / null / include-recent gating
         and (p_include_recent
              or t.last_scraped_at is null
              or t.last_scraped_at < now() - interval '7 days')
         and (not p_null_only or t.last_scraped_at is null)

         -- Age-group filter (PitchRank supports U10–U19 only) — dynamic per current year
         and (t.age_group is null
              or upper(trim(t.age_group)) not in ('U8','U-8','U9','U-9'))
         -- Birth-year exclusion: mirrors scripts/scrape_games.py:425 [2005,2006,2017,2018,2019]
         -- dynamically. Excludes U7 (c.yr-7), U8 (c.yr-8), U9 (c.yr-9) on the young end;
         -- U20 (c.yr-20), U21 (c.yr-21) on the old end. Five values — must match Python list exactly.
         and (t.birth_year is null
              or t.birth_year not in (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))

         -- Placeholder unknown filter
         and not (t.team_name = 'unknown_' || t.provider_team_id)

       order by t.last_scraped_at asc nulls first
       limit coalesce(p_limit, 2147483647);
     $$;
     ```
   - Same migration adds composite index:
     ```sql
     create index if not exists teams_provider_scrape_priority_idx
       on public.teams (provider_id, last_scraped_at asc nulls first);
     ```
   - Note `hashtext()` is deterministic within a Postgres major version. If PG major version changes, shards reshuffle — acceptable, one-time rescrape of some teams.
   - **Tech-debt flag (critical follow-up)**: the Python list at `scripts/scrape_games.py:425` is hardcoded `[2005, 2006, 2017, 2018, 2019]` and will silently drift out of sync with this dynamic RPC as the calendar year rolls over. The plan keeps the Python post-filter as defense-in-depth (step 5) but REQUIRES the two filters to agree. Follow-up: refactor both call sites to a shared helper (either a Python function that calls `EXTRACT(YEAR FROM NOW())` on the DB, or a Python-side `datetime.now().year` computation mirroring the SQL). Do not delay this past the next calendar year rollover.

### Phase B — `scripts/scrape_games.py`

4. **Replace per-row `UPDATE` in `_bulk_log_team_scrapes`** (lines 102-157)
   - Keep `team_scrape_log` insert batching as-is.
   - Replace the per-team `teams.last_scraped_at` UPDATE loop with `supabase.rpc("bulk_update_last_scraped_at", {"updates": chunk}).execute()`, **chunked at 2,000 rows per call** (~240 KB JSON; safely under PostgREST 1 MB body limit).
   - Implement adaptive chunk halving on HTTP 413: mirror `_bulk_insert_games` pattern at `src/etl/enhanced_pipeline.py:1715`. On 413 response, halve chunk size and retry; give up below 125 rows.
   - Log a warning if returned rowcount < chunk length: `logger.warning("bulk_update_last_scraped_at: %d of %d rows updated", returned, len(chunk))`.
   - Remove the obsolete comment ("Supabase doesn't support bulk UPDATE…").

5. **Replace 130K-team fetch + Python sort in `--limit-teams` / `--null-teams-only` / `--include-recent` branches** (lines 297-396)
   - **Refactor prep**: First extract the existing three paginated branches at `scripts/scrape_games.py:297-396` (`null_teams_only`, `include_recent`, `limit_teams`) into a single private helper `_legacy_paginated_team_fetch(supabase, provider_id, limit_teams, null_teams_only, include_recent)` that preserves the original `while True: .range()` loop and the Python-side sort. The fallback path will call this helper with the same arguments the RPC receives. Rationale: avoids duplicating the paginated loop inside the fallback branch, and keeps the fallback path identical to today's behavior.
   - **Insertion point**: replace the entire branch-selection block at lines 297-396 with: (1) the new RPC call wrapped in the canonical `try/except APIError` (snippet below); (2) the existing Python post-filter for placeholders/age/birth_year, relocated OUT of the per-branch conditionals to run once against the RPC result (or against the fallback helper's result).
   - Collapse all three branches into a single `supabase.rpc("get_teams_to_scrape_limited", params).execute()` call.
   - Parameter derivation:
     - `p_provider_id` from scraper.
     - `p_limit = limit_teams` if set, else `None` (serialized as SQL `NULL`).
     - `p_shard_index = int(os.getenv("SCRAPE_SHARD_INDEX", "0"))`.
     - `p_shard_count = int(os.getenv("SCRAPE_SHARD_COUNT", "1"))`.
     - `p_include_recent = include_recent` (from arg).
     - `p_null_only = null_teams_only` (from arg).
   - **Remove the previous `limit_teams * 1.1` buffer** — filters are now in SQL, so `LIMIT N` returns exactly N eligible teams (no post-filter shortfall).
   - Keep the **Python post-filter** for placeholders / age / birth-year as defense-in-depth (also catches any newly-added edge cases before they hit the scraper).
   - **Fallback**: wrap the RPC call in `try/except` that catches only `postgrest.exceptions.APIError` with SQLSTATE `42883` (function does not exist). On that specific error, log a PERF REGRESSION line and fall through to the existing paginated loop. Re-raise all other exceptions.
   - **Canonical SQLSTATE-42883 fallback snippet** (reused verbatim by steps 7 and 8; adapt the fallback body per site):
     ```python
     from postgrest.exceptions import APIError
     try:
         res = supabase.rpc("get_teams_to_scrape_limited", params).execute()
         teams = res.data or []
     except APIError as err:
         if getattr(err, "code", None) == "42883":  # function does not exist
             logger.error("PERF REGRESSION: Falling back to paginated team fetch: %s", err)
             teams = _legacy_paginated_team_fetch(
                 supabase, provider_id, limit_teams, null_teams_only, include_recent
             )
         else:
             raise  # re-raise timeouts, auth, permission, constraint errors, etc.
     ```
   - **Semantic preservation**: when `null_teams_only=True` with no `limit_teams`, caller passes `p_limit=None` → RPC returns all NULL teams (matches prior behavior). When `limit_teams` is set, RPC returns top-N among those matching the shard filter (matches prior "take top N after sort" behavior at the population level; within a shard, it is top-N of that shard's hash bucket).

6. **No change to `_bulk_fetch_scrape_dates`** (lines 60-99) — not a bottleneck.

### Phase C — `src/etl/enhanced_pipeline.py`

7. **Replace alias preload in `EnhancedETLPipeline._ensure_initialized`** (lines 159-208)
   - Replace the paginated `.range()` loop with one `supabase.rpc("get_approved_aliases", {"p_provider_id": provider_id}).execute()` call.
   - **Fallback**: same `try/except APIError` pattern as step 5 (`code == "42883"` → fallback + PERF REGRESSION log; all other `APIError` → re-raise). Adapt the fallback body to call the existing paginated alias preload. Log line: `"PERF REGRESSION: Falling back to paginated alias preload: %s"`.
   - Preserve all downstream cache-population logic — only the data-load mechanism changes.
   - Update log message currently reporting `pages` count to report `rows` count.

8. **Replace per-team `UPDATE` in `_update_team_scrape_dates`** (lines 2213-2232)
   - **Refactor prep**: First extract the existing per-team UPDATE loop at `src/etl/enhanced_pipeline.py:2213-2232` into a private helper `_legacy_update_team_scrape_dates_per_team(team_scrape_dates)` that preserves the original loop verbatim. The fallback path (triggered on SQLSTATE `42883`) calls this helper. Rationale: keeps the fallback path identical to today's behavior and gives the new RPC call a single concise call site.
   - Replace per-team UPDATE loop with `supabase.rpc("bulk_update_last_scraped_at", {"updates": [...]}).execute()` (same RPC as step 4), chunked at 2,000.
   - Build JSONB payload from the same `(team_id_master, last_scraped_at)` pairs the current loop builds.
   - Keep existing per-batch invocation point in import flow — no change to *when* called, only *how*.
   - Same `try/except APIError` pattern as step 5 (`code == "42883"` → fallback + PERF REGRESSION log; all other `APIError` → re-raise). Fallback body calls the extracted `_legacy_update_team_scrape_dates_per_team(team_scrape_dates)` helper. Log line: `"PERF REGRESSION: Falling back to per-team UPDATE in _update_team_scrape_dates: %s"`.
   - Same "rowcount < input" warning logic as step 4.

9. **No changes to `_propagate_exclusions_to_new_games` or `_process_team_matching_stats`** — out of scope per user decision; they contribute to the post-insert gap but each is a smaller win and would expand blast radius.

### Phase D — `src/scrapers/gotsport.py`

10. **Add 429 to `Retry.status_forcelist` + Retry-After respect + surfaced instrumentation** (lines 89-99)
    - Change `status_forcelist=[500, 502, 503, 504]` → `status_forcelist=[429, 500, 502, 503, 504]`.
    - Change `backoff_factor=0.3` → `backoff_factor=1.0` (429 retries wait 1s, 2s, 4s).
    - Keep `total=3`.
    - Add `respect_retry_after_header=True` so we honor any `Retry-After` header GotSport returns.
    - **Surface transparent retries** — add null-safe instrumentation around the primary team-games `session.get(...)` call so both successful retries and retry-exhaustion are logged. urllib3 retries 429s transparently inside the adapter, so without this instrumentation, 429s either succeed silently (wins) or raise `RetryError` (exhaustion) — neither case is currently logged.
    - **Wrap only the primary team-games request** at `src/scrapers/gotsport.py:181`. Do NOT wrap club-name fetches at line 318 or opponent-club fetches at line 438 — those are best-effort cache misses that fall through cleanly without retry instrumentation.
    - **Local variable names**: the in-scope variables at line 181 are `normalized_team_id` (bound at line 135) and `api_url` (bound at line 157). Existing log lines (195, 217, 237, 296) use `normalized_team_id`; match that for log-style consistency.
    - **Exception ordering**: place the new `except requests.exceptions.RetryError` handler BEFORE any existing `except requests.exceptions.RequestException` chain — `RetryError` is a `RequestException` subclass, so a broader catch higher in the chain would otherwise swallow it and silence the retry-exhaustion marker.
    - Canonical snippet (with corrected variable names):
      ```python
      try:
          response = session.get(api_url, timeout=timeout)
          # Null-safe inspection: retries_obj may be None on responses that never triggered the retry machinery
          retries_obj = getattr(response.raw, "retries", None)
          history = getattr(retries_obj, "history", ()) or ()
          n429 = sum(1 for h in history if getattr(h, "status", None) == 429)
          if n429:
              logger.warning("gotsport 429 retries: team=%s count=%d url=%s", normalized_team_id, n429, api_url)
          response.raise_for_status()
      except requests.exceptions.RetryError as e:
          # urllib3 exhausted all retries (total=3) — separate marker for verification grep
          logger.error("gotsport 429 retry-exhausted: team=%s url=%s err=%s", normalized_team_id, api_url, e)
          raise
      # ...existing `except requests.exceptions.RequestException` handler continues after this block
      ```
      This makes verification items (d1) retry-exhausted count and (d2) successful-retry count measurable via log grep.

### Phase E — `.github/workflows/scrape-games.yml`

11. **Restructure into two-stage job graph: `prepare` → matrix `scrape-and-import`**
    - The `prepare` job computes the shard gate via shell (regex-validating `inputs.limit_teams` and treating schedule events specially), exposes `should_shard` and `shard_count` as **job outputs**, and runs the best-effort alias maintenance script. The matrix job reads those outputs via `needs.prepare.outputs.*` — both as its `if:` gate and as its job-level `env:` for `SCRAPE_SHARD_COUNT`. This replaces the earlier `fromJSON(inputs.limit_teams)` expression (crashes on non-numeric input) and the step-level `env: { SCRAPE_SHARD_COUNT: 5 }` literals that would override any `$GITHUB_ENV` write (GHA env precedence: step-level `env:` wins over `$GITHUB_ENV`, so the prior approach was a silent-failure trap).
    - **MUST preserve from existing workflow** (not shown in canonical YAML below — these live OUTSIDE the `jobs:` block or as tail steps within `scrape-and-import`). A naive rewrite from the canonical YAML alone would silently drop them, with real operational consequences:
      - **Workflow-level `concurrency:`**: keep the existing top-of-file block:
        ```yaml
        concurrency:
          group: game-scraping
          cancel-in-progress: false
        ```
        This serializes the Mon 06:00 UTC and Mon 11:15 UTC cron runs. Without it, cron runs overlap and cause duplicate inserts + stale alias cache — the exact bug it was originally added to prevent.
      - **`Upload logs` tail step** on each matrix shard:
        ```yaml
        - name: Upload logs
          if: always()
          uses: actions/upload-artifact@v5
          with:
            name: scrape-logs-${{ github.run_number }}-shard-${{ matrix.shard }}
            path: logs/*.log
            retention-days: 30
            if-no-files-found: ignore
        ```
        Required for verification items (d1), (d2), and (f) — log artifacts are grepped offline; without them, verification can only be done through the Actions UI, which truncates long logs and doesn't support grep.
      - **`Report results` tail step** on each matrix shard — echoes shard inputs, concurrency, scheduled-vs-manual context. Useful for post-mortem.
      - **`PYTHONPATH: ${{ github.workspace }}` env var**: on both the `Maintain GotSport direct ID aliases` step (in `prepare`) and the `Run scrape + auto-import` step (in `scrape-and-import`). Both scripts self-append `sys.path`, but the env var is cheap insurance against ordering changes in `__init__.py` imports.
    - Canonical workflow shape:
      ```yaml
      jobs:
        prepare:
          runs-on: ubuntu-latest
          # Job-level timeout is a hard ceiling (kills job regardless of step-level timeouts).
          # Sized to accommodate the maintain step's 25-min worst case + 5 min overhead for gate/checkout/install.
          timeout-minutes: 30
          outputs:
            should_shard: ${{ steps.gate.outputs.should_shard }}
            shard_count:  ${{ steps.gate.outputs.shard_count }}
          steps:
            - uses: actions/checkout@v5
            - uses: actions/setup-python@v6
              with: { python-version: '3.11', cache: 'pip' }
            - name: Install dependencies
              run: pip install -r requirements.txt

            - name: Compute shard gate
              id: gate
              # Shell-level validation: regex-match inputs.limit_teams to catch non-numeric input ("abc", "5k")
              # that would crash a fromJSON-based expression. Schedule events always shard.
              run: |
                if [ "${{ github.event_name }}" = "schedule" ]; then
                  echo "should_shard=true"  >> "$GITHUB_OUTPUT"
                  echo "shard_count=5"       >> "$GITHUB_OUTPUT"
                elif [[ "${{ inputs.limit_teams }}" =~ ^[0-9]+$ ]] && [ "${{ inputs.limit_teams }}" -ge 5000 ]; then
                  echo "should_shard=true"  >> "$GITHUB_OUTPUT"
                  echo "shard_count=5"       >> "$GITHUB_OUTPUT"
                else
                  # Small or no-arg manual run: only shard 0 executes;
                  # RPC's hash filter collapses to no-op when p_shard_count <= 1.
                  echo "should_shard=false" >> "$GITHUB_OUTPUT"
                  echo "shard_count=1"       >> "$GITHUB_OUTPUT"
                fi

            - name: Maintain GotSport direct ID aliases
              # Best-effort Tier 1 import-matching optimization. NOT a scraping correctness requirement.
              # continue-on-error prevents a transient Supabase blip from cascading through `needs: prepare`
              # and skipping all 5 scrape shards (wasted weekly window).
              # Step-level timeout-minutes (25) prevents the whole prepare JOB from being cancelled when
              # the per-row UPDATE loop hits its worst case (~5K aliases × ~300ms ≈ 25 min). The job-level
              # timeout is 10 min; without this step-level override, a cold-start run would cancel the job
              # and `needs.prepare.outputs.*` would not propagate, skipping all matrix shards.
              # The checkout/install/gate steps above must NOT use continue-on-error — they produce outputs
              # every downstream shard depends on.
              continue-on-error: true
              timeout-minutes: 25
              env:
                SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
                SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
                PYTHONPATH: ${{ github.workspace }}
              run: python scripts/maintain_gotsport_direct_id_aliases.py

        scrape-and-import:
          needs: prepare
          runs-on: ubuntu-latest
          timeout-minutes: 120
          strategy:
            fail-fast: false
            matrix:
              shard: [0, 1, 2, 3, 4]
          # Shard 0 always runs (covers the small-run case). Shards 1-4 run only when sharding is warranted.
          if: ${{ matrix.shard == 0 || needs.prepare.outputs.should_shard == 'true' }}
          # JOB-LEVEL env: consistent for all steps. Do NOT put SCRAPE_SHARD_COUNT on any step-level env block —
          # step-level env overrides job-level env and would silently break the small-run override.
          env:
            SCRAPE_SHARD_INDEX: ${{ matrix.shard }}
            SCRAPE_SHARD_COUNT: ${{ needs.prepare.outputs.shard_count }}
          steps:
            - uses: actions/checkout@v5
            - uses: actions/setup-python@v6
              with: { python-version: '3.11', cache: 'pip' }
            - name: Install dependencies
              run: pip install -r requirements.txt
            - name: Build scrape command
              id: build-command
              # Reads $SCRAPE_SHARD_COUNT from job env (= needs.prepare.outputs.shard_count).
              # Computes per-shard --limit-teams and --concurrency per step 12.
              run: |
                # ... (see step 12 for exact computation)
            - name: Run scrape + auto-import
              env:
                SUPABASE_URL:              ${{ secrets.SUPABASE_URL }}
                SUPABASE_SERVICE_KEY:      ${{ secrets.SUPABASE_SERVICE_KEY }}
                SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
                NEXT_PUBLIC_SUPABASE_URL:  ${{ secrets.SUPABASE_URL }}
                PYTHONPATH:                ${{ github.workspace }}
              run: ${{ steps.build-command.outputs.command }}
            - uses: actions/upload-artifact@v5
              if: always()
              with:
                name: scraped-games-${{ github.run_number }}-shard-${{ matrix.shard }}
                path: data/raw/scraped_games_*.jsonl
                retention-days: 7
                if-no-files-found: ignore
      ```
    - **Env placement rule** (call this out explicitly in a PR review checklist): `SCRAPE_SHARD_COUNT` lives at **job-level `env:`** only. Do not add a step-level `env:` block for it on any step inside `scrape-and-import` — step-level `env:` wins over job-level and would freeze `SCRAPE_SHARD_COUNT` to a stale literal. `SCRAPE_SHARD_INDEX` is also job-level since `matrix.shard` is stable for the whole job.
    - **Move the alias-preload stagger from YAML into Python**: the earlier draft had a `sleep $((matrix.shard * 5))` as the first step under `scrape-and-import`. That's been removed in the canonical YAML above. Instead, add the stagger at the Python alias-preload entry point in `EnhancedETLPipeline._ensure_initialized()` (the function modified in step 7), immediately before the `get_approved_aliases` RPC call:
      ```python
      import os, time
      shard_idx = int(os.getenv("SCRAPE_SHARD_INDEX", "0"))
      if shard_idx > 0:
          time.sleep(shard_idx * 2)  # Stagger 5 concurrent alias-load RPCs to PostgREST
      ```
      Rationale: YAML-level `sleep` (0/5/10/15/20s before checkout/install) is dwarfed by natural variance in pip-cache hits and setup-python timing — it rarely actually staggers the alias-load moment, and it wastes wall-clock on every shard. In-Python stagger is precise (fires right before the actual RPC) and scales with shard count. Max wall-cost is `(shard_count - 1) * 2 = 8s` on shard 4; 2s/shard gap is ample for PostgREST to stream each ~13MB response before the next one arrives.
    - Per-shard `--limit-teams` (computed in "Build scrape command" step with shell guards — empty-input safety is critical, bare `--limit-teams ` flag would crash the CLI):
      ```bash
      LIMIT_FLAG=""
      if [ "${{ github.event_name }}" = "schedule" ]; then
        LIMIT_FLAG="--limit-teams 5000"  # total 25000 across 5 shards
      elif [ -n "${{ inputs.limit_teams }}" ] && [ "${{ inputs.limit_teams }}" -ge 5000 ]; then
        LIMIT_FLAG="--limit-teams $(( ${{ inputs.limit_teams }} / 5 ))"
      elif [ -n "${{ inputs.limit_teams }}" ]; then
        LIMIT_FLAG="--limit-teams ${{ inputs.limit_teams }}"  # shard 0 only; SCRAPE_SHARD_COUNT=1 → hash filter no-op
      fi
      # If LIMIT_FLAG is empty, the CLI invocation omits --limit-teams entirely, and Python
      # falls through to incremental mode (7-day stale filter). This is the desired behavior
      # for manual dispatch with no inputs — matches the existing workflow's semantics.
      ```
      Then embed `$LIMIT_FLAG` (unquoted, so empty string expands to nothing) in the CLI invocation. Note: per-shard integer division may lose 1–4 teams on `inputs.limit_teams` not divisible by 5 (e.g., 5001/5=1000, total=5000); acceptable at scraping scale.
    - **Concurrency-group semantics** (workflow-top comment):
      > Workflow-level `concurrency: { group: game-scraping, cancel-in-progress: false }` serializes **separate workflow runs** (Mon 06:00 UTC vs Mon 11:15 UTC queue correctly). It does NOT serialize the 5 matrix shards within a single run — parallelism across shards is intentional and required to hit the 2.5 h target. **DO NOT add a job-level `concurrency:` key inside `scrape-and-import`** — doing so would serialize the matrix and kill the speedup.

12. **Adaptive scrape concurrency based on `SCRAPE_SHARD_COUNT`**
    - When `SCRAPE_SHARD_COUNT == 1`: pass `--concurrency 50` (single shard, full pool budget).
    - When `SCRAPE_SHARD_COUNT > 1`: pass `--concurrency 20` per shard → 20 × 5 = 100 in-flight, matches `pool_maxsize=100` at `src/scrapers/gotsport.py:90` and keeps aggregate load on GotSport comparable to the prior single-job/concurrency=30 baseline.
    - Build in the "Build scrape command" step:
      ```bash
      if [ "${SCRAPE_SHARD_COUNT}" = "1" ]; then
        CONCURRENCY=50
      else
        CONCURRENCY=20
      fi
      ```
    - **Keep** `inputs.concurrency` default in the YAML at `'30'` (unchanged). The adaptive values (20 sharded / 50 single) are computed at workflow level via the build-command step and passed explicitly to the Python CLI, bypassing the input default. Manual overrides via the `concurrency` input still win if set. Keeping the YAML default low protects against accidentally shipping high concurrency if the build-command logic is ever bypassed.
    - **Realistic expectation** (document in PR description and workflow comment): concurrency raise on a single shard yields ~30–40% scrape-phase improvement, not linear scaling. The per-team random sleep at `gotsport.py:293-294` runs inside workers after the HTTP response, so throughput is `N / (request_time + sleep)` — raising N from 30→50 lifts throughput modestly. The under-1h goal for 5K manual runs depends on **all** fixes landing (bulk RPCs + concurrency + alias preload), not the concurrency lever alone. The under-2.5h goal for 25K scheduled runs depends primarily on hash sharding giving ~5× parallelism.

13. **Per-matrix-job `timeout-minutes: 120`** (reduced from 360). Each shard does ~1/5 the work; a 2h budget is generous. Protects against cost-runaway on a stuck shard.

### Phase F — Coordination

14. **Keep Python defaults at 30** — do NOT change `scripts/scrape_games.py` argparse CLI default (line 605) or the `scrape_games()` function default (lines 269, 288). The workflow's "Build scrape command" step computes concurrency adaptively (20 when sharded, 50 when single-shard) and passes it explicitly as `--concurrency N`, so the Python default never applies in CI. Keeping the local default at 30 protects developers running `python scripts/scrape_games.py --limit-teams 100` from a single IP against GotSport — production uses 5 distributed GitHub Actions IPs at concurrency 20 each; a dev box at 50 against one IP could trigger rate-limit bans that poison subsequent runs. Verified via grep: no external importers of `scrape_games.scrape_games()` outside tests + docs, so the function default change is unnecessary.

15. **Verify no callers of `_bulk_log_team_scrapes` or `_update_team_scrape_dates`** outside the patched paths via grep in `scripts/` and `src/` before declaring done.

## Verification

Before running verification, on Windows bash:
```bash
export DATABASE_URL=$(grep '^DATABASE_URL=' C:/PitchRank/.env | cut -d= -f2-)
# Confirm the export worked:
psql "$DATABASE_URL" -c "select version();"
```

Per-step verification:

- **Migrations apply cleanly**: `cd C:/PitchRank && supabase db diff --linked --schema public` (shows pending migrations without applying — not a real `--dry-run` on `db push`). Then apply with `supabase db push --debug`. After apply, confirm function signatures:
  ```bash
  psql "$DATABASE_URL" -c "\df public.get_teams_to_scrape_limited"
  psql "$DATABASE_URL" -c "\df public.get_approved_aliases"
  psql "$DATABASE_URL" -c "\df public.bulk_update_last_scraped_at"
  ```
  All three should return signatures; `get_teams_to_scrape` (without `_limited`) must still exist unchanged.
- **Indexes exist and are picked up**:
  ```bash
  psql "$DATABASE_URL" -c "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM get_teams_to_scrape_limited('<provider_uuid>'::uuid, 5000, 0, 5, false, false);"
  ```
  Expect Index Scan using `teams_provider_scrape_priority_idx` for the `provider_id` predicate, with a filter step for the hash-shard predicate (the `hashtext()` expression is not indexable). Total time **< 1 s** on 130K teams; typical is 200–500 ms. For a tighter bound on pure index access, also run the query with `p_shard_count=1` (collapses the hash filter to a no-op) — should complete in **< 100 ms**.
- **Hash-shard disjointness**: *Note*: these queries pass `p_include_recent=true` to test partition correctness over the full team universe (independent of `last_scraped_at` state). Production callers use `p_include_recent=false`; partition correctness at `true` implies correctness at `false` because any subset of a disjoint partition remains disjoint.
  ```sql
  -- Sum across 5 shards should equal total eligible teams; no duplicates
  select count(*) from (
    select team_id_master from get_teams_to_scrape_limited('<uuid>'::uuid, null, 0, 5, true, false)
    union all
    select team_id_master from get_teams_to_scrape_limited('<uuid>'::uuid, null, 1, 5, true, false)
    union all
    select team_id_master from get_teams_to_scrape_limited('<uuid>'::uuid, null, 2, 5, true, false)
    union all
    select team_id_master from get_teams_to_scrape_limited('<uuid>'::uuid, null, 3, 5, true, false)
    union all
    select team_id_master from get_teams_to_scrape_limited('<uuid>'::uuid, null, 4, 5, true, false)
  ) u;
  -- Should equal: select count(*) from get_teams_to_scrape_limited('<uuid>'::uuid, null, 0, 1, true, false);
  -- And: select team_id_master, count(*) from (...) group by 1 having count(*) > 1; -- should return zero rows
  ```
- **Bulk RPC behavioral parity**:
  - Write a one-off script that: reads current `last_scraped_at` for 100 teams; calls `bulk_update_last_scraped_at` with new timestamps for those 100; re-reads; asserts all 100 now match new values.
  - Test empty-array case: `bulk_update_last_scraped_at('[]'::jsonb)` returns 0.
  - Test missing-team case: include one non-existent UUID in payload; assert `returned_count == len(payload) - 1` AND caller logs a warning.
  - Measure serialized payload size for 2,000-row call — confirm < 300 KB.
- **Alias RPC behavioral parity**: compare row count and a random sample of 100 rows between the new RPC and the old paginated load for `provider_id = <gotsport_uuid>`. Counts must match exactly.
- **End-to-end manual run (5K)**: trigger `gh workflow run scrape-games.yml -f limit_teams=5000` and verify:
  - (a) all 5 matrix shards complete (each ~1000 teams)
  - (b) total wall time under 1 h (currently ~2 h)
  - (c) total games inserted within ±5% of a baseline run on the same team set
  - (d1) **Retry-exhaustion count == 0**: `grep 'gotsport 429 retry-exhausted' logs/*.log | wc -l` must equal 0 across all shards. Any exhausted retry indicates GotSport is rate-limiting harder than `total=3, backoff_factor=1.0` can absorb — lower concurrency or raise backoff.
  - (d2) **Successful 429 retries are a health metric**: `grep 'gotsport 429 retries:' logs/*.log | wc -l` should be < 1% of teams scraped. Values > 5% suggest concurrency is too high for GotSport's current load tolerance.
  - (e) per-shard `Logging X team scrapes` step under 30 s (currently 6 min single-job)
  - (f) grep all shard logs for `PERF REGRESSION` — must return zero matches
- **End-to-end scheduled-run dry run (25K)**: trigger `gh workflow run scrape-games.yml -f limit_teams=25000` (explicit numeric input is required to force the sharded path; bare `gh workflow run` with no inputs routes through `should_shard=false` and only runs shard 0) and verify:
  - (a) ~25K teams total processed across 5 shards
  - (b) total wall time under 2.5 h (currently 4–5 h)
  - (c) shards finish within ~20% of each other (hash distribution is uniform but per-team work varies; wider tolerance than OFFSET sharding would have required)
- **Concurrency safety**: after a Monday, spot-check cron serialization with `gh run list --workflow=scrape-games.yml --limit 4 --json databaseId,status,startedAt,conclusion` — the Mon 06:00 UTC run's `completedAt` must precede Mon 11:15 UTC run's `startedAt`. Then for matrix parallelism within a single run, use `gh run view <run_id> --json jobs --jq '.jobs[] | {name, startedAt, completedAt}'` — this returns job-level timing:
  - For **sharded runs** (scheduled OR manual `-f limit_teams=N` with N >= 5000), all 5 matrix shards must run in parallel (overlapping `startedAt`/`completedAt` windows). Expect `prepare` to complete first, then all 5 `scrape-and-import (shard N)` jobs start within ~10s of each other.
  - For **small manual runs** (`limit_teams < 5000` or empty), only shard 0 executes — shards 1–4 show as skipped (gray) in the Actions UI, which is expected per the `if:` gate.
- **Prepare-job alias-maintenance degradation visibility**: alias maintenance uses `continue-on-error: true` (step 11). After any workflow run, `gh run view <run_id> --json jobs` should be checked for `jobs[].steps[].conclusion == 'failure'` on the `Maintain GotSport direct ID aliases` step — this surfaces as a yellow annotation, not a red one. If it fails, import Tier 1 matching falls back to fuzzy_auto path (slower but correct). Add alerting on repeated failures (3+ consecutive runs) as tech-debt follow-up; not blocking for this plan.
- **Fallback paths exercised**: temporarily rename one of the new RPCs and run a small workflow. Verify:
  - Exactly one `PERF REGRESSION` error line appears per affected call site
  - Workflow still completes successfully (fallback path works)
  - Rename RPC back and confirm subsequent runs have zero PERF REGRESSION lines

Tech-debt follow-up (not in scope, flagged here):
- The hardcoded birth-year list at `scripts/scrape_games.py:425` should be made dynamic to match the SQL function in step 3. Follow-up plan required.
- Post-batch `_propagate_exclusions_to_new_games` and `_process_team_matching_stats` still run per-import-batch; collapsing them would shave further time off the auto-import phase.

## Context Files

- `C:/PitchRank/.github/workflows/scrape-games.yml` — workflow being restructured into `prepare` + matrix
- `C:/PitchRank/scripts/scrape_games.py` — `_bulk_log_team_scrapes` (102-157), team-fetch branches (297-396), CLI args (584-606), main `scrape_games` (260-…)
- `C:/PitchRank/src/etl/enhanced_pipeline.py` — alias preload (159-208), `_update_team_scrape_dates` (2213-2232), `_bulk_insert_games` (1715, for adaptive-halving pattern)
- `C:/PitchRank/src/scrapers/gotsport.py` — `HTTPAdapter` retry config (89-99), env-var throttle (50-54), per-team sleep (293-294)
- `C:/PitchRank/src/scrapers/base.py:71-122` — existing `get_teams_to_scrape` caller; verify it remains untouched by Phase A migrations
- `C:/PitchRank/scripts/maintain_gotsport_direct_id_aliases.py` — now runs in single `prepare` job (not per-shard); verify env vars and exit code
- `C:/PitchRank/supabase/migrations/20251125000000_add_batch_update_ml_overperformance.sql` — JSONB-array RPC template to mirror for `bulk_update_last_scraped_at`
- `C:/PitchRank/supabase/migrations/20260126000000_fix_get_teams_to_scrape_provider_filter.sql` — existing `get_teams_to_scrape`; remains unchanged
- `C:/PitchRank/src/rankings/calculator.py:1146-1188` — Python-side RPC call shape to mirror for new bulk RPC calls
- `C:/PitchRank/.env` — source of `DATABASE_URL` for verification psql invocations
