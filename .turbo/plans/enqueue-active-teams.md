---
status: done
---

# Plan: Enqueue Active Teams — close the actively-playing-team re-scrape gap

## Context

The `scrape_requests` queue has three automatic producers, none of which re-queue a
team that is actively playing a multi-day tournament:

- `enqueue_yesterday_games.py` (daily, priority 2) only re-queues teams whose game is
  **already a row in our `games` table dated yesterday with a NULL `home_score`**. It
  cannot see games that aren't in our DB yet.
- `enqueue_discovery_teams.py` (weekly, priority 3) only targets teams with **no future
  games on record**.
- `enqueue_safety_net.py` (weekly, priority 4) only targets teams **never scraped or
  >90 days stale**.

Tournament bracket games only materialize on GotSport as rounds finish, so they are not
yet in our DB (no NULL-score fixture to trip `yesterday_game`), the team isn't stale
(scraped days ago), and it usually still has future games on record (so `discovery`
skips it). The team falls into a blind spot until someone manually clicks re-scrape.

**Proof (diagnosed 2026-06-22):** team `a202889c-ebe9-439b-a20c-8c713fc9399a`
(2015 AChacon Pre-MLS Next, u11, RSL Arizona North, provider_team_id 80237). Its
Premier SuperCopa games on Jun 19/20/21 2026 all have `created_at = 2026-06-22 18:32` —
they only entered our DB when the user manually re-scraped. They sat uncaptured ~3 days.

This plan adds a fourth producer — `enqueue_active_teams` — backed by a new
`find_recently_active_teams` RPC. It re-enqueues GotSport teams that **played a game in
the last N days** (default 3) and **haven't been scraped in the last M hours** (cooldown,
default 20) so we don't waste ZenRows residential budget (25× cost) or CloudFront WAF
allowance re-scraping a team we just scraped. It runs daily and enqueues at priority 2.
This both closes the tournament/bracket gap and keeps the queue continuously fed so the
scheduled `process_missing_games` drainer (every 15 min) and manual Help Clear Queue
(`drain_queue.py`) aren't idle. Consumers are unchanged. The ranking engine is frozen and
out of scope — this is pure queue-producer plumbing.

### Settled decisions (from this session)

- **Priority:** `2` — tie with `yesterday_game`. No renumbering of the 1–5 ladder.
  The idempotent `enqueue_scrape_request` upsert uses `LEAST(priority, …)`, so a team
  already pending at priority 1 (user-click) keeps priority 1; one pending at 3/4/5 gets
  promoted to 2. Harmless overlap.
- **Cadence:** daily cron.
- **Active window / cooldown defaults:** 3 days / 20 hours. Exposed as `--window-days`
  and `--cooldown-hours` script flags + workflow inputs so they can be widened later
  without a code change (e.g. if teams with a >3-day gap between tournament rounds slip
  through).
- **`DEFAULT_LIMIT`:** 2000 (per-run cap only; cooldown + dedup prevent re-churn).

## Pattern Survey

_All findings verified against `origin/main` (HEAD `8cbf7d954`); the working tree is the
stale branch `fix/modular11-events-division-mapping` (67 commits behind, dirty) and was
not used._

### Analogous Features (mirror these)

Three sibling producer scripts share a near-identical skeleton (all on `origin/main`):

- `scripts/enqueue_yesterday_games.py` — daily, priority 2, `request_type='yesterday_game'`,
  no `--limit`. Games-driven, time-windowed. **Closest template for the new script's
  intent.**
- `scripts/enqueue_discovery_teams.py` — weekly, priority 3, `request_type='discovery'`,
  `DEFAULT_LIMIT=1000`, has `--dry-run` + `--limit`. **Closest template for the
  `--limit`/`DEFAULT_LIMIT` argparse plumbing.**
- `scripts/enqueue_safety_net.py` — weekly, priority 4, `request_type='safety_net'`,
  `DEFAULT_LIMIT=500`, has `--dry-run` + `--limit`.

**Shared skeleton (verbatim across all three):** shebang + docstring Usage block →
truststore SSL try/except (before `supabase` import) → `from dotenv import load_dotenv  # noqa: E402`,
`from supabase import create_client  # noqa: E402` → `load_dotenv(".env.local")` then
`load_dotenv(".env")` → `sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
→ INFO logging → constants (`GOTSPORT_PROVIDER_CODE="gotsport"`, `PRIORITY_*`,
`REQUEST_TYPE`, `DEFAULT_LIMIT`) → `get_gotsport_provider_id(supabase)` (selects
`providers.id WHERE code='gotsport'`, raises `RuntimeError` if missing) →
`find_teams_to_enqueue(...)` (calls the `find_*` RPC, dedups by `team_id_master` via a
`seen = {}` dict) → `enqueue_team(...)` (calls `enqueue_scrape_request` with the seven
`p_*` params) → `main()` (reads `SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL` +
`SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY`, `sys.exit(1)` if missing; `--dry-run` logs
first 20 + total; else loops with try/except, final log
`f"Enqueued {success} teams at priority {PRIORITY_*}, {fail} failed"`).

### Reusable Utilities (reuse unchanged / template on)

- **`enqueue_scrape_request(p_team_id_master uuid, p_team_name text, p_provider_id uuid,
  p_provider_team_id text, p_game_date date, p_request_type text, p_priority smallint)
  RETURNS uuid`** — `supabase/migrations/20260520044853_enqueue_scrape_request_rpc.sql`.
  `LANGUAGE plpgsql`. Idempotent: `UPDATE … SET priority = LEAST(priority, p_priority),
  game_date = COALESCE(p_game_date, game_date), … WHERE team_id_master = p_team_id_master
  AND status='pending'`; INSERT if no pending row. Targets the partial unique index
  `idx_scrape_requests_pending_team`. **Reused unchanged** — the only new things are the
  priority value (2) and `request_type='active_team'`.
- **`find_yesterday_null_score_teams` v2** —
  `supabase/migrations/20260526000000_find_yesterday_null_score_teams_v2.sql`. `LANGUAGE
  sql STABLE`, `RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)`.
  **Games-driven CTE** (UNION home/away master ids from `games` filtered on date) then
  `JOIN teams`. **Structural template for the new RPC.** The v1 teams-driven `EXISTS`
  form (`20260520050216`) timed out on tournament weekends — that is *why* v2 is
  games-first.
- **`find_stale_teams(p_provider_id uuid, p_row_limit integer DEFAULT 500)`** —
  `supabase/migrations/20260520155417_find_stale_teams.sql`. `LANGUAGE sql STABLE`. Source
  of the **U8/U9 + U20+ age exclusions, the `unknown_` placeholder exclusion, the
  `is_deprecated=false` + `provider_id` filters, and `ORDER BY last_scraped_at ASC NULLS
  FIRST`** — copy these predicates verbatim.
- **`find_discovery_teams(p_provider_id uuid, p_row_limit integer DEFAULT 1000)`** —
  `supabase/migrations/20260520054454_find_discovery_teams.sql`. Reference for the
  games-aggregation CTE form at scale.

**`scrape_requests` table + indexes:**
`supabase/migrations/20251113150557_add_scrape_requests.sql` (columns + RLS) and
`supabase/migrations/20260520001858_add_priority_to_scrape_requests.sql`:
`priority smallint NOT NULL DEFAULT 5`; unique partial index
`idx_scrape_requests_pending_team ON scrape_requests (team_id_master) WHERE status='pending'`;
drain-order index `idx_scrape_requests_priority_pending ON scrape_requests (priority ASC,
requested_at ASC) WHERE status='pending'`. The priority ladder
(`1=user, 2=yesterday, 3=discovery, 4=safety-net, 5=default`) is documented only as a
comment inside `20260520001858`.

**Join columns (confirmed on `origin/main`):**
- `games`: `game_date DATE`, `home_team_master_id UUID`, `away_team_master_id UUID`,
  `is_excluded BOOLEAN NOT NULL DEFAULT FALSE` (`20260220000000_add_game_exclusion.sql`),
  `home_score INTEGER`. Indexes `idx_games_date_desc`, `idx_games_date_provider`,
  `idx_games_is_excluded`.
- `teams`: `team_id_master UUID UNIQUE`, `provider_id UUID` (**per-team provider
  linkage — every sibling RPC filters GotSport via `teams.provider_id = p_provider_id`,
  not `games.provider_id`**), `provider_team_id TEXT`, `team_name TEXT`, `last_scraped_at
  TIMESTAMPTZ`, `is_deprecated BOOLEAN` (`20251208000001`), `age_group`, `birth_year`.

### Convention Anchors

- **Migration naming:** `<14-digit YYYYMMDDHHMMSS>_<snake_case>.sql` in
  `supabase/migrations/`. **Latest on `origin/main` = `20260615200001_schedule_homepage_stats_refresh.sql`**
  → the new migration must sort after it (use `20260622000000` or later).
- **Finder RPC conventions:** `LANGUAGE sql STABLE` (no SECURITY DEFINER, no search_path
  pin); `RETURNS TABLE(team_id_master uuid, team_name text, provider_team_id text)`; params
  `p_provider_id`, `p_row_limit`; leading comment block (purpose / ordering / "Used by");
  trailing `GRANT EXECUTE ON FUNCTION <sig> TO authenticated, service_role;`.
- **Workflow conventions:** file `enqueue-<thing>.yml`; title-case `name:`; `run-name:`
  shows DRY RUN/live; `concurrency: { group: enqueue-<thing>, cancel-in-progress: false }`;
  `runs-on: ubuntu-latest`; `actions/checkout@v5`; `actions/setup-python@v6` (python 3.11);
  env `SUPABASE_URL: ${{ secrets.SUPABASE_URL }}` and
  `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}` (note the env-name vs
  secret-name mismatch — preserve it); run step exports `PYTHONPATH` then runs the script
  with `$DRY_RUN_FLAG [$LIMIT_FLAG]`.
- **Tests:** every producer has `tests/unit/test_enqueue_<thing>.py` asserting the priority
  constant, the default limit, dedup behavior, and the `enqueue_team` payload (priority +
  request_type + game_date). Mirror this.

### Proposed Alignment

- **RPC** → template on `find_yesterday_null_score_teams_v2` (games-first CTE), parameterized
  with `p_active_window_days` / `p_cooldown_hours` / `p_row_limit`; copy the teams-side
  filters + ordering from `find_stale_teams`. **Refinement over the siblings:** use
  `make_interval(days => p_active_window_days)` / `make_interval(hours => p_cooldown_hours)`
  rather than string-concatenation interval casts (type-safe, better planner estimates).
  **Gotcha:** never use a teams-driven `EXISTS` form — it times out at 137K-team scale.
- **Script** → mirror `enqueue_discovery_teams.py` (has `--limit`/`DEFAULT_LIMIT`), plus new
  `--window-days` / `--cooldown-hours` flags wired into the RPC call. Constants
  `PRIORITY_ACTIVE_TEAM = 2`, `REQUEST_TYPE = "active_team"`, `DEFAULT_LIMIT = 2000`,
  `DEFAULT_WINDOW_DAYS = 3`, `DEFAULT_COOLDOWN_HOURS = 20`.
- **Workflow** → mirror `enqueue-yesterday-games.yml` (daily cron) + the `limit` input and
  `LIMIT_FLAG` wiring from `enqueue-discovery.yml`; add `window_days` / `cooldown_hours`
  string inputs with matching flag wiring. Daily cron offset from the 07:00 UTC
  yesterday-game slot.

## Implementation Steps

1. **Branch from `origin/main` (do NOT build on the current working tree)**
   - The working tree is on the stale branch `fix/modular11-events-division-mapping`
     (67 commits behind `origin/main`, with uncommitted/staged files). Building here would
     bundle unrelated work and miss recent migrations.
   - `git fetch origin` → `git checkout -b feat/enqueue-active-teams origin/main`.
   - Verify a clean tree against that baseline before editing:
     `git status -sb` should show the new branch tracking `origin/main` with no unrelated
     staged changes. All five files below are new except the optional priority-comment
     refresh in step 2.

2. **New migration: `supabase/migrations/20260622000000_find_recently_active_teams.sql`**
   (pick a timestamp later than `20260615200001`)
   - `CREATE OR REPLACE FUNCTION find_recently_active_teams(p_provider_id uuid,
     p_active_window_days integer DEFAULT 3, p_cooldown_hours integer DEFAULT 20,
     p_row_limit integer DEFAULT 2000) RETURNS TABLE(team_id_master uuid, team_name text,
     provider_team_id text) LANGUAGE sql STABLE AS $$ … $$;` — structure sketch:
     ```sql
     WITH active_masters AS (
         SELECT home_team_master_id AS master_id FROM games
         WHERE game_date >= CURRENT_DATE - make_interval(days => p_active_window_days)
           AND is_excluded = false AND home_team_master_id IS NOT NULL
         UNION
         SELECT away_team_master_id FROM games
         WHERE game_date >= CURRENT_DATE - make_interval(days => p_active_window_days)
           AND is_excluded = false AND away_team_master_id IS NOT NULL
     )
     SELECT t.team_id_master, t.team_name, t.provider_team_id
     FROM active_masters am
     JOIN teams t ON t.team_id_master = am.master_id,
          (SELECT EXTRACT(YEAR FROM NOW())::int AS yr) c   -- cross join; supplies c.yr below
     WHERE t.is_deprecated = false
       AND t.provider_id = p_provider_id
       AND (t.last_scraped_at IS NULL
            OR t.last_scraped_at < NOW() - make_interval(hours => p_cooldown_hours))
       -- COPY VERBATIM from find_stale_teams (20260520155417) — these REQUIRE the `c`
       -- cross join above for the c.yr references; do not re-derive them:
       AND (t.age_group IS NULL OR UPPER(TRIM(t.age_group)) NOT IN ('U8','U-8','U9','U-9'))
       AND (t.birth_year IS NULL OR t.birth_year NOT IN (c.yr - 21, c.yr - 20, c.yr - 9, c.yr - 8, c.yr - 7))
       AND NOT (t.team_name = 'unknown_' || t.provider_team_id)
     ORDER BY t.last_scraped_at ASC NULLS FIRST
     LIMIT p_row_limit;
     ```
   - **Preserve sibling conventions:** leading comment block (purpose, "Used by
     scripts/enqueue_active_teams.py", ordering rationale); trailing
     `GRANT EXECUTE ON FUNCTION find_recently_active_teams(uuid, integer, integer, integer)
     TO authenticated, service_role;`.
   - **Mirror surfaces to copy exactly from the cited siblings:** the games-first
     `UNION` CTE shape and the `JOIN teams … is_deprecated/provider_id` gate from
     `find_yesterday_null_score_teams_v2` (`20260526000000`); the age + `unknown_`
     placeholder predicates — together with the `(SELECT EXTRACT(YEAR FROM NOW())::int AS
     yr) c` cross join their `birth_year NOT IN (c.yr - …)` form requires — and the
     `ORDER BY last_scraped_at ASC NULLS FIRST` from `find_stale_teams` (`20260520155417`).
   - **Intentional deviation (note in the comment):** filter `is_excluded = false` in the
     games CTE so excluded/futsal games don't count as "activity." The existing finders
     don't filter `is_excluded`; this is a deliberate, narrow improvement, not a mirror.
   - **Priority-ladder registry update (forward-only):** in this same new migration, add
     `COMMENT ON COLUMN scrape_requests.priority IS 'Lower number = higher priority.
     1=user-clicked, 2=daily yesterday-game + active-team, 3=discovery, 4=safety-net,
     5=default';`. Do **not** edit the historical
     `20260520001858` migration (applied migrations are immutable); the COMMENT is the
     forward-only way to keep the documented ladder current.

3. **New script: `scripts/enqueue_active_teams.py`** (mirror `enqueue_discovery_teams.py`)
   - Header: shebang + docstring Usage block; truststore try/except before the `supabase`
     import; `load_dotenv(".env.local")` then `load_dotenv(".env")`; `sys.path.append(...)`;
     INFO logging — all identical to the siblings.
   - Constants: `GOTSPORT_PROVIDER_CODE = "gotsport"`, `PRIORITY_ACTIVE_TEAM = 2`,
     `REQUEST_TYPE = "active_team"`, `DEFAULT_LIMIT = 2000`, `DEFAULT_WINDOW_DAYS = 3`,
     `DEFAULT_COOLDOWN_HOURS = 20`.
   - `get_gotsport_provider_id(supabase)` — copy verbatim from a sibling.
   - `find_teams_to_enqueue(supabase, gotsport_provider_id, window_days, cooldown_hours,
     limit)` — call `supabase.rpc("find_recently_active_teams", {"p_provider_id": …,
     "p_active_window_days": window_days, "p_cooldown_hours": cooldown_hours,
     "p_row_limit": limit})`; dedup by `team_id_master` with the `seen = {}` pattern.
   - `enqueue_team(...)` — call `enqueue_scrape_request` with `p_priority=PRIORITY_ACTIVE_TEAM`,
     `p_request_type=REQUEST_TYPE`, `p_game_date=date.today().isoformat()` (placeholder, as
     discovery/safety-net do — `active_team` isn't tied to a specific fixture), and the
     `team_id_master / team_name / provider_id / provider_team_id` from the row.
   - `main()` — argparse `--dry-run`, `--limit` (default `DEFAULT_LIMIT`), `--window-days`
     (default `DEFAULT_WINDOW_DAYS`), `--cooldown-hours` (default `DEFAULT_COOLDOWN_HOURS`);
     env-var read + `sys.exit(1)` guard; `--dry-run` logs first 20 + total; else the
     try/except enqueue loop with final log
     `f"Enqueued {success} teams at priority {PRIORITY_ACTIVE_TEAM}, {fail} failed"`.

4. **New workflow: `.github/workflows/enqueue-active-teams.yml`** (mirror
   `enqueue-yesterday-games.yml` + discovery's limit wiring)
   - `name: Enqueue Active Teams`; `run-name:` showing DRY RUN/live.
   - `on.schedule.cron: '0 10 * * *'` (daily 10:00 UTC — 3h after the 07:00 yesterday-game
     slot so its enqueue+drain cycle has cleared; comment the DST drift like the sibling).
   - `on.workflow_dispatch.inputs`: `dry_run` (boolean, default false), `limit` (string,
     default ''), `window_days` (string, default ''), `cooldown_hours` (string, default '').
   - `concurrency: { group: enqueue-active-teams, cancel-in-progress: false }`.
   - Job: `runs-on: ubuntu-latest`, `timeout-minutes: 15`, `actions/checkout@v5`,
     `actions/setup-python@v6` (3.11), `pip install supabase python-dotenv` (add
     `truststore certifi` only if needed — discovery omits them and works on CI).
   - `env` flag wiring: `DRY_RUN_FLAG: ${{ inputs.dry_run == true && '--dry-run' || '' }}`,
     `LIMIT_FLAG: ${{ inputs.limit != '' && format('--limit {0}', inputs.limit) || '' }}`,
     and the same `format` pattern for `WINDOW_FLAG` (`--window-days`) and `COOLDOWN_FLAG`
     (`--cooldown-hours`).
   - Run step: `SUPABASE_URL: ${{ secrets.SUPABASE_URL }}`,
     `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}` (preserve the
     name/secret mismatch); `export PYTHONPATH="${PYTHONPATH}:${PWD}"` then
     `python scripts/enqueue_active_teams.py $DRY_RUN_FLAG $LIMIT_FLAG $WINDOW_FLAG $COOLDOWN_FLAG`.

5. **New test: `tests/unit/test_enqueue_active_teams.py`** (mirror
   `tests/unit/test_enqueue_safety_net.py`)
   - `test_priority_constant_is_2` → `PRIORITY_ACTIVE_TEAM == 2`.
   - `test_default_limit_is_2000` → `DEFAULT_LIMIT == 2000`.
   - `test_default_window_and_cooldown` → `DEFAULT_WINDOW_DAYS == 3`, `DEFAULT_COOLDOWN_HOURS == 20`.
   - `test_find_teams_to_enqueue_dedups_team_ids` → mocked RPC returns a duplicate
     `team_id_master`; assert deduped.
   - `test_find_teams_passes_window_and_cooldown_params` → assert the `find_recently_active_teams`
     RPC payload carries `p_active_window_days` / `p_cooldown_hours` / `p_row_limit`.
   - `test_enqueue_team_uses_priority_2_and_active_team_type` → assert the
     `enqueue_scrape_request` payload has `p_priority == 2`,
     `p_request_type == "active_team"`, `p_game_date == date.today().isoformat()`.

## Verification

- **Migration applies cleanly:** apply `20260622000000_find_recently_active_teams.sql` to a
  branch/staging DB (or via the Supabase MCP `apply_migration`) and confirm no error and the
  `GRANT` lands.
- **RPC returns and does not time out at scale** (the whole reason for the games-first
  form): run, against production-shaped data,
  ```sql
  EXPLAIN ANALYZE
  SELECT * FROM find_recently_active_teams(
    (SELECT id FROM providers WHERE code='gotsport'), 3, 20, 2000);
  ```
  Expect completion well under the statement-timeout budget, an index/bitmap scan on
  `games` driven by `game_date` (not a seq scan of all games), and a hash/nested-loop join
  to `teams` — never a teams-first plan.
- **Behavioral spot-check:** a team that played within the last 3 days and whose
  `last_scraped_at` is older than 20h should appear in the RPC output; a team scraped in the
  last 20h should be absent (cooldown). Confirm with a targeted query joining a couple of
  known recently-active `team_id_master`s.
- **Window boundary check:** a team whose most recent game is exactly 3 days ago (the
  inclusive boundary of `game_date >= CURRENT_DATE - make_interval(days => 3)`) and whose
  `last_scraped_at` is older than the cooldown IS included; a team whose last game was 4
  days ago is excluded by the default window (and only re-included by widening
  `--window-days`). Validate the boundary rather than assuming it.
- **Script dry-run (no writes):** `python scripts/enqueue_active_teams.py --dry-run` →
  logs the first 20 target teams + a total count, enqueues nothing.
- **Unit tests:** `pytest tests/unit/test_enqueue_active_teams.py -q` passes.
- **End-to-end (optional, on a branch DB):** run the script live, then confirm new
  `scrape_requests` rows with `request_type='active_team'`, `priority=2`, `status='pending'`;
  verify the unique partial index prevented duplicate pending rows for a team already
  pending from another producer (that row should hold `priority = LEAST(old, 2)`).
- **Edge cases to spot-check:** empty active set → RPC returns 0 rows, script logs
  "0 teams", no enqueues, exit 0; a team with `last_scraped_at IS NULL` is treated as
  eligible (NULLS FIRST ordering); excluded games (`is_excluded=true`) do not make a team
  count as active.

## Context Files

Read in full before implementing:

- `scripts/enqueue_discovery_teams.py` — primary script template (`--limit`/`DEFAULT_LIMIT`
  argparse + `find_*` RPC call + dedup + enqueue loop).
- `scripts/enqueue_yesterday_games.py` — secondary script template (daily, games-windowed
  intent) and the truststore header comment.
- `supabase/migrations/20260526000000_find_yesterday_null_score_teams_v2.sql` — games-first
  CTE RPC structure to mirror (and the scale-timeout history that mandates it).
- `supabase/migrations/20260520155417_find_stale_teams.sql` — source of the exact age /
  `unknown_` placeholder / `is_deprecated` / `provider_id` predicates and the
  `ORDER BY last_scraped_at ASC NULLS FIRST` to copy verbatim.
- `supabase/migrations/20260520044853_enqueue_scrape_request_rpc.sql` — the reused upsert
  RPC (LEAST/COALESCE semantics + the partial-unique-index target).
- `supabase/migrations/20260520001858_add_priority_to_scrape_requests.sql` — the priority
  ladder + the two partial indexes the queue relies on.
- `.github/workflows/enqueue-yesterday-games.yml` and `.github/workflows/enqueue-discovery.yml`
  — workflow templates (cron, inputs, flag wiring, secrets, run step).
- `tests/unit/test_enqueue_safety_net.py` — the unit-test pattern to mirror.
