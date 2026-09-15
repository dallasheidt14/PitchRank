---
name: supabase-pitchrank
description: Safe Supabase patterns for PitchRank - table schemas, query limits, timeouts, grants, and what NOT to do. Use when writing or reviewing a Supabase query, RPC, migration or a test double for supabase-py, tracing where a team_alias_map row came from, reading quarantine_games, bulk-updating games (including is_excluded), or diagnosing a statement timeout.
---

# Supabase Safety Skill for PitchRank

You are working with PitchRank's Supabase PostgreSQL database. This skill teaches safe patterns.

## Connection

```python
from supabase import create_client
import os

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)
```

The service-role key bypasses RLS entirely. It is correct for server-side scripts that must
write, but prefer `SUPABASE_KEY` (anon) for read-only lookups, and never let it reach a
browser or a log line. Keys live in root `.env` (or its `.env.local` override), both gitignored.

## Core Tables

### `teams`
```sql
id                UUID PRIMARY KEY  -- Row id; NOT what games join on
team_id_master    UUID NOT NULL UNIQUE  -- Canonical id; games.home/away_team_master_id join THIS
team_name         TEXT              -- Display name
club_name         TEXT              -- Parent club
age_group         TEXT              -- stored lowercase u-form: "u12". Normalize before comparing
gender            TEXT              -- "Male" or "Female"
state_code        TEXT              -- 2-letter state code
provider_id       UUID              -- FK to providers(id); there is no provider_code column
is_deprecated     BOOLEAN           -- TRUE if merged into another team
last_scraped_at   TIMESTAMPTZ
created_at        TIMESTAMPTZ       -- Table-rebuild artifact, NOT when the team appeared
```

`created_at` is unusable as an age signal: the minimum across the whole table is
2025-11-03, because the rows were rebuilt then. Every team looks equally new.
`team_scrape_log` begins the same day and carries the same limitation. Derive age from
game dates instead — a team's first and last `games.game_date` are real.

### `games`
```sql
id                UUID PRIMARY KEY
game_uid          TEXT UNIQUE       -- Deterministic dedup key (IMMUTABLE)
home_team_master_id UUID
away_team_master_id UUID
home_score        INT
away_score        INT
game_date         DATE
provider_id       UUID              -- FK to providers(id), not a code string
event_name        TEXT
-- Games are NEVER updated, only inserted
```

### `rankings_full`

> Canonical: the `rankings-algorithm` skill, § Output Tables → "`rankings_full` (Primary)".
> It lists the columns with the meaning the pipeline gives each one, which is what you need
> the moment a value looks wrong. Invoke that skill rather than reading a thinner copy here.

Three traps bite anyone writing a query against it, whichever skill is loaded: there is no
`powerscore` column (the chain is `powerscore_core` → `powerscore_adj` → `powerscore_ml` →
`power_score_true` → `power_score_final`); `national_rank` and `state_rank` are **always
NULL** here, because the views compute display ranks; and `sos` is raw and 1500-centred,
so every threshold reads `sos_norm` instead.

### `team_alias_map`
```sql
provider_team_id  TEXT              -- Provider's ID for the team
team_id_master    UUID              -- Our canonical ID
provider_id       UUID              -- FK to providers(id)
match_method      TEXT              -- not provenance (see below)
match_confidence  FLOAT             -- not provenance either
review_status     TEXT              -- only 'approved' rows are matched
created_at        TIMESTAMPTZ
-- Multiple aliases can point to same master
```

Infer nothing about an alias's origin from `match_method` or `match_confidence`.
`scripts/maintain_gotsport_direct_id_aliases.py` rewrites every approved GotSport alias with a
truthy `provider_team_id` to `direct_id` at confidence 1.0, the string `'None'` included, and
`maintain_tgs_direct_id_aliases.py` does the same for TGS.

Read provenance from `team_link_audit` instead:
- link-opponent rows carry `notes` of `Home: n, Away: m`
- create-team rows carry `Created new team "…" … Home: n, Away: m`
- unlink rows have `reverted_at` set, and their `games_updated` counts games unlinked

`linked_by` is `'frontend_user'` on every row and names no one. A link or create also fills every
still-NULL master-id slot carrying that provider id under the same provider, so an alias's games
can predate its `created_at`.

Treat `''`, `'None'` and `'null'` (any case, any padding; `src/utils/provider_ids.py` defines the
set) in `provider_team_id` and `games.home_provider_id`/`away_provider_id` as placeholders, never
teams, and exclude them from joins and counts.

A `provider_team_id` means nothing without its `provider_id`: the table is unique on the pair, and
one canonical team holds games from several providers. When acting on the games an alias attached,
filter `games.provider_id` to the alias's provider as well as the side's provider team id and master
id. Leave unfiltered any check that must see every copy of a fixture — `trg_propagate_game_exclusion`
matches date, team pair and scores whatever the provider.

### `team_merge_map`
```sql
deprecated_team_id UUID UNIQUE      -- Team that was merged away
canonical_team_id  UUID             -- Team it was merged into
merged_at         TIMESTAMPTZ
merged_by         TEXT
```

**Any per-team aggregate over `games` must resolve merges first.** `execute_team_merge`
cascades `teams` and `team_alias_map`, but `games.home_team_master_id` /
`away_team_master_id` keep pointing at the **pre-merge** id. **Nothing repoints them and
no view resolves them for you** — `20260210000000` added merge resolution to
`rankings_view` and `20260211000000_rollback_rankings_view_to_20260204.sql` reverted it
for performance; the live views exclude deprecated teams instead. 119,791 game rows
currently sit on deprecated ids.

Use `MergeResolver` (`src/utils/merge_resolver.py`) from Python — root CLAUDE.md makes it
the canonical path for any team-id lookup. When querying SQL directly:

```sql
LEFT JOIN team_merge_map m ON m.deprecated_team_id = <tid>
-- then group on:
COALESCE(m.canonical_team_id, <tid>)
```

Skipping this understates activity, silently. A 2026-08-27 audit that omitted it
mislabelled ~772 active teams as dormant. `team_scrape_log.team_id` is not repointed by a
merge either, so counts over that table need the same treatment.

One hop suffices, by design rather than by luck: `execute_team_merge` step 4
(`20251230000000_add_cascade_merge_support.sql:68-78`) repoints any incoming
`team_merge_map` rows at the new canonical, flattening chains as it goes. A chain can only
appear from a direct insert that bypasses the RPC.

### `quarantine_games`
```sql
id             UUID PRIMARY KEY
raw_data       JSONB             -- the rejected source game, including its "provider"
reason_code    TEXT              -- 'validation_failed' for validator rejections
error_details  TEXT              -- validator messages joined with '; '
created_at     TIMESTAMPTZ
```

Every provider's rejected games land here under the same messages. TGS logs
`Missing required field: opponent_id` routinely, for instance. Filter
`raw_data->>'provider'` before reading a count as evidence about one provider's import.

### `team_match_review_queue`
```sql
id                        SERIAL PRIMARY KEY
provider_id               VARCHAR(50) NOT NULL   -- provider CODE ('gotsport'), not the UUID
provider_team_id          VARCHAR(255) NOT NULL
provider_team_name        VARCHAR(255) NOT NULL
suggested_master_team_id  UUID
confidence_score          DECIMAL(3,2) NOT NULL  -- CHECK >= 0.75 AND < 0.90
match_details             JSONB
priority_score            DOUBLE PRECISION
status                    VARCHAR(20)            -- 'pending', 'approved', 'rejected'
```

A write that breaks a constraint here fails silently: both matcher writers catch the exception
and only log `Error creating review queue entry`. Two traps:
- a NULL `provider_team_id`. `GameHistoryMatcher._create_review_queue_entry` refuses placeholder
  provider ids before queueing; `Modular11GameMatcher._enqueue_modular11_review_with_suggestions`
  does not, and sends NULL for a falsy id.
- a `confidence_score` that rounds to 0.90 at two decimals, so anything from 0.895, which
  `confidence_range` rejects. Cap at 0.89, as `src/tournaments/alias_writer.py` does.

Before planning a write of NULL, or of a new value range, into any column, read its nullability
and checks live: `information_schema.columns.is_nullable` and `pg_get_constraintdef` over
`pg_constraint` both answer under the MCP role, unlike `role_table_grants` and
`constraint_column_usage` below.

## Safe Query Patterns

### Testing against PostgREST

A Python double for supabase-py must return only the columns `select()` asked for, and record
calls at `execute()`. A double that hands back whole fixture rows lets a column missing from the
select list pass every test while production raises `KeyError`, or reads `None` through `.get()`.
The frontend's `filteringClientMock` (`frontend/test/supabase-mock.ts`) applies the filters it
models but does not project columns either, so do not treat it as covering this.

### Pagination (REQUIRED for large tables)
```python
# PostgREST caps a response at max-rows: 200,000 on the hosted project (measured
# 2026-09-09), but 1,000 under a local `supabase start` (supabase/config.toml).
# Paginate regardless -- for memory, and for scans that could exceed either cap.
# Order by a unique column: without .order() PostgREST promises no row order, so
# successive pages can skip or repeat rows (a matcher paging candidates that way can
# miss an existing team and create a duplicate).

def fetch_all_teams(client):
    all_teams = []
    offset = 0
    batch_size = 1000

    while True:
        result = client.table('teams') \
            .select('*') \
            .order('team_id_master') \
            .range(offset, offset + batch_size - 1) \
            .execute()

        if not result.data:
            break

        all_teams.extend(result.data)
        offset += batch_size

    return all_teams
```

### Batch Insert/Upsert
```python
# Max recommended batch size: 1000 rows
BATCH_SIZE = 1000

for i in range(0, len(records), BATCH_SIZE):
    batch = records[i:i + BATCH_SIZE]
    client.table('table_name').upsert(batch).execute()
    time.sleep(0.5)  # Small delay between batches
```

### Safe Filtering
```python
# Filter by exact match
.eq('state_code', 'CA')

# Filter by list
.in_('team_id_master', team_ids[:100])  # Keep lists at 100 or fewer (URI length)

# Filter by null
.is_('resolved_at', 'null')

# Filter not null
.not_.is_('resolved_at', 'null')
```

## Rate Limits

| Limit | Value |
|-------|-------|
| Requests/second | 100 |
| Batch size | 1000 rows max |
| URL length | ~8KB (limits .in_() list size) |
| PostgREST client timeout | 120 seconds by default — **overridable, see below** |

### Long-running RPCs are NOT supported here — batch from the caller

**An RPC gets 8 seconds. A function cannot raise its own limit.**

PostgreSQL arms `statement_timeout` once, at the start of each top-level client command.
Statements run inside a function never re-arm it, so `SET LOCAL statement_timeout` in a
function body changes the GUC and nothing else — the timer already counting for the
`SELECT my_function(...)` that PostgREST issued is untouched. A function-level
`SET statement_timeout = '300s'` in the `CREATE FUNCTION` header has the same defect.

Verified 2026-08-27 against production:

```sql
DO $$ BEGIN SET LOCAL statement_timeout='1s'; PERFORM pg_sleep(3); END $$;  -- succeeds
SET LOCAL statement_timeout='1s'; SELECT pg_sleep(3);                        -- 57014
```

What is in force is the session's value. `pg_db_role_setting` on this project carries
`statement_timeout=8s` for `authenticator` and has **no `service_role` entry**; PostgREST
logs in as `authenticator` and then `SET ROLE service_role`, which does not re-apply
per-role settings. So a service-role RPC gets 8 seconds no matter what the body says.

**Raising the client timeout does not help** — it only stops the *client* hanging up early.
`postgrest_client_timeout=360` is still worth setting when a call may legitimately take
minutes, but it cannot extend the server's budget.

The pattern that works is caller-driven batching: the RPC does one page and returns a
cursor, and the script loops.

### Raw SQL through the Supabase MCP server gets the same 8 seconds

`mcp__supabase__execute_sql` reaches the database through the same role, so an ad-hoc
analysis query is capped at 8 seconds, not the 120 in the table above. It fails with
`ERROR: 57014: canceling statement due to statement timeout`.

Write the aggregate so one pass answers it. A per-row correlated subquery over `teams`
times out; the same result computed as a single `GROUP BY` plus a `row_number()` window
to pick the top row per group returns well inside the limit.

```sql
CREATE OR REPLACE FUNCTION public.refresh_x(p_after uuid DEFAULT NULL, p_batch_size int DEFAULT 2000)
RETURNS TABLE (rows_changed integer, last_id uuid) ...
  -- SELECT ... WHERE p_after IS NULL OR id > p_after ORDER BY id LIMIT p_batch_size
```

```python
after = None
while True:
    rows = sb.rpc("refresh_x", {"p_after": after, "p_batch_size": 2000}).execute().data or []
    if not rows or rows[0]["last_id"] is None:
        break
    after = rows[0]["last_id"]
```

See `scripts/refresh_team_scrape_activity.py` and its migration for a worked example —
2,000 teams per call, measured at 289 ms against production.

**`backfill_total_game_stats` (`20260325100000`) is the counter-example, not a model.** It
carries `SET LOCAL statement_timeout = '300s'` and is cancelled on every production run;
`.turbo/backfill-review-2026-07-27.md` records `calculate_rankings.py`'s Python fallback
taking over weekly, and that fallback has never written a row. Do not copy its shape.

### A LIMIT stops no work below a full sort

A page-sized RPC can still do whole-table work. In a flat query with no index to supply the
sort, the planner evaluates the full WHERE for every candidate row, sorts them all, and only
then applies the LIMIT. That can fit the 8 seconds while the pages are cached and time out when they are not.

Null placement decides whether an index supplies the order. A btree built `ASC` (nulls last,
the default) serves `ASC` and plain `DESC`; one built `ASC NULLS FIRST` serves
`ASC NULLS FIRST` and `DESC NULLS LAST`, so a plain `DESC` against it sorts everything. In a
multicolumn index a column's order is usable only when every earlier column is pinned with
`=`. When the WHERE already excludes NULLs (`x < $cutoff`), write the null placement that
matches the index: rows are unchanged, and the planner can walk the index and stop once
OFFSET plus LIMIT rows are found, under an Incremental Sort when the ORDER BY adds a
tiebreaker the index lacks.

When no index can supply the order, as with a computed leading sort key, the scan and sort still
cover every candidate, but a costly per-row check can stop early. Filter and sort the candidates
on cheap columns in a subquery, apply the check in the outer WHERE, and repeat the same ORDER BY
before the LIMIT; any other outer order puts a sort above the check that drains it. The check
must stay a filter: a correlated `EXISTS` inside an `OR` does, but a top-level `AND [NOT] EXISTS`
becomes a join the planner may hash and re-sort, so confirm `EXPLAIN` shows it as a `SubPlan` in
the Subquery Scan's `Filter`. No `OFFSET 0` fence is needed: the inner ORDER BY stops PG17
flattening the subquery, and PG17 never pushes a filter holding a correlated subquery down into
one. `find_discovery_teams` (`20260915130000`) is the worked example.

Confirm with `EXPLAIN (ANALYZE, BUFFERS)` run twice; a plain `EXPLAIN` shows estimates and can
blame the wrong node. A first run that times out or shows a large `read=`, followed by a much
faster one, is a whole-candidate sort meeting a cold cache; two slow runs are the same shape with
nothing cached to hide it. A SQL function with `SECURITY DEFINER` or a `SET` clause is never
inlined, and PG17 plans its body generically, so test the body as a `PREPARE`d statement under
`SET plan_cache_mode = force_generic_plan`, as was done for `find_topup_teams`
(`20260915120000`).

### Bulk `is_excluded` updates pay a scan per row

Each row that flips to `is_excluded = true` fires `trg_propagate_game_exclusion`. The trigger
scans that whole `game_date`, because no index serves its `LEAST`/`GREATEST` key. It also flips
every other non-excluded game with the same team pair and aligned scores, so count those before
excluding.

At about 13 ms per row on a typical date (measured 2026-09-14), a 100-id `.in_()` batch takes
roughly 1.5 s warm, inside the 8-second budget.

## NEVER DO

### ❌ Grant a Browser Role Write Access to a Server-Only Table

An RLS policy and a table GRANT are independent axes, and checking one reads as having
checked both. `FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id)` makes
attribution unforgeable and says nothing about who may write at all. Pair it with
`GRANT INSERT ... TO authenticated` and any signed-in account, free tier included, can take
the public `NEXT_PUBLIC_SUPABASE_ANON_KEY` plus its own session JWT and POST straight to
`/rest/v1/<table>`, skipping every check the API route performs.

When only server code should write, grant the browser roles nothing and have the route use
`createServiceSupabase()` after its own auth check:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "<table>_deny_all" ON <table>;
CREATE POLICY "<table>_deny_all" ON <table>
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS "<table>_service_role_all" ON <table>;
CREATE POLICY "<table>_service_role_all" ON <table>
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.<table> FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.<table>_id_seq FROM anon, authenticated;
```

The sequence needs its own REVOKE — a table-level one does not reach it, and
`pg_default_acl` grants `rwU` on new sequences here. `team_state_probe_log_id_seq` still
carries `anon=rwU` in production because its migration revoked only the table. `REVOKE ALL`
is also what removes TRUNCATE, which RLS does not govern.

Check whether the table even has a sequence before copying that line: a `uuid` primary key
with `gen_random_uuid()` has none, and `REVOKE ALL ON SEQUENCE` on a non-existent sequence
errors. `SELECT pg_get_serial_sequence('public.<table>','id');` returns NULL when there is
nothing to revoke.

### The grant and the policy are independent axes — the exposure is their intersection

Neither alone tells you whether something is reachable, and checking one reads as having
checked both. Resolve both before calling a gap a hole or dismissing one:

- **`anon` holds DELETE and TRUNCATE on `user_profiles`** (live ACL `anon=rdDxtm`), which
  looks alarming. It is inert: the table's only policy is `FOR SELECT`, RLS denies a command
  with no permissive policy, and `anon` is not a login role — PostgREST is the only way to
  reach it and it never issues TRUNCATE. Defense-in-depth, not a live hole.
- **`scrape_requests` was the opposite**: `anon=arwdDxtm` *and* an `INSERT … WITH CHECK
  (true)` policy, so anonymous callers really could write. Grant plus policy is what made it
  reachable.

TRUNCATE and REFERENCES are the asymmetry to remember: RLS governs SELECT/INSERT/UPDATE/
DELETE only, so for those two the grant is the whole story.

### Migration history cannot prove a grant EXISTS

It can only prove that nothing revoked one. `pg_default_acl` grants `anon`/`authenticated`
`arwdDxtm` on every new public relation here, so the privilege usually arrives from outside
any migration file. A tree-wide grep therefore answers "was this ever revoked?" and never
"can `anon` do this today?".

Resolve the live ACL instead:

```sql
SELECT c.relname, COALESCE(array_to_string(c.relacl, E'\n'), '(owner-only defaults)')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname = '<table>';
```

Read the flags as `a`=INSERT, `r`=SELECT, `w`=UPDATE, `d`=DELETE, `D`=TRUNCATE,
`x`=REFERENCES, `t`=TRIGGER, `m`=MAINTAIN.

**Do not use `information_schema.role_table_grants` for this.** Like
`constraint_column_usage` above, it is privilege-filtered: it returns **zero rows** for
`anon` and `authenticated` under the MCP server's role, which reads as "no grants exist" when
the table in fact grants everything to both.

### A Realtime subscription is gated by publication membership before RLS

`postgres_changes` delivers nothing for a table that is not in the `supabase_realtime`
publication, whatever its policies say — and membership is usually set in the dashboard, so
it is invisible in `supabase/migrations/`. Confirm it before concluding that a policy change
broke a live subscription, or that keeping SELECT open preserves one:

```sql
SELECT tablename FROM pg_publication_tables WHERE pubname = 'supabase_realtime';
```

As of 2026-09-08 that returns exactly one public table, `announcements`. A subscription on
`scrape_requests` (`frontend/hooks/useScrapeRequestNotifications.ts`) has therefore never
fired, and no migration adds the table. An RLS-gated UPDATE subscription may additionally
need `REPLICA IDENTITY FULL` — `relreplident` is `d` by default.

### ❌ Delete From `teams`

`teams` has **18 inbound foreign keys**, and a `DELETE` fails or destroys depending on
which team you pick:

- **9 are `ON DELETE NO ACTION`** — `games` (home + away), `team_alias_map`,
  `team_merge_map` (both columns), `scrape_requests`, `current_rankings`,
  `team_link_audit`, `user_corrections`. Any team with games **errors**.
- **7 are `ON DELETE CASCADE`** — `rankings_full`, `ranking_history`, `team_scrape_log`,
  `team_social_profiles`, `prediction_feature_history`, `game_explainability` (×2). A team
  without games deletes fine and **takes its ranking history with it**.
- 2 are `ON DELETE SET NULL` (`prospective_match_predictions`).

25 base tables carry a team-id column, so the 7 without an FK — `watchlist_items` among
them — orphan silently while the rest do not. Prefer marking a row (`is_deprecated`, a
status column) over removing it: a team is usually still an opponent in someone else's
game history, which is exactly what the `games` FK is refusing to let you break.

**To enumerate inbound FKs, use `pg_constraint`, not `information_schema`:**

```sql
SELECT src.relname, con.conname, con.confdeltype
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
WHERE con.contype = 'f' AND con.confrelid = 'public.teams'::regclass;
```

`information_schema.constraint_column_usage` is **privilege-filtered** — a read-only role
sees an empty result and concludes there are no constraints at all. That exact mistake
produced a "teams has no foreign keys" claim in this repo's docs on 2026-08-27.

### ❌ Delete Without WHERE
```python
# DANGEROUS - deletes ALL rows
client.table('teams').delete().execute()
```

### ❌ Update Without Filters
```python
# DANGEROUS - updates ALL rows
client.table('teams').update({'is_deprecated': True}).execute()
```

### ❌ Modify game_uid
```python
# game_uid is IMMUTABLE - used for deduplication
# Never update it
```

### ❌ Large IN() Clauses
```python
# BAD - URL too long, will fail
.in_('team_id', list_of_1000_ids)

# GOOD - batch the calls
for batch in chunks(ids, 100):
    .in_('team_id', batch)
```

### ❌ Skip Pagination
```python
# BAD - unbounded; truncates silently at max-rows (200,000 hosted, 1,000 local)
client.table('games').select('*').execute()

# GOOD - paginate, ordered by a unique column
.order('id').range(0, 999).execute()
.order('id').range(1000, 1999).execute()
```

## Safe Patterns

### Count Query
```python
result = client.table('teams') \
    .select('id', count='exact') \
    .eq('state_code', 'CA') \
    .execute()
count = result.count  # Use .count, not len(result.data)
```

### Check Before Write
```python
# Check if exists before insert
existing = client.table('teams') \
    .select('team_id_master') \
    .eq('team_id_master', team_id) \
    .execute()

if existing.data:
    # Update existing
else:
    # Insert new
```

### Transaction-like Pattern
```python
# Supabase doesn't have transactions in Python SDK
# Use RPC functions for atomic operations. execute_team_merge inserts one
# team_merge_map row and cascades team_alias_map/teams; games keep the pre-merge
# id (see team_merge_map above) — still effectively irreversible, so dry-run is
# the default and writing is opt-in.
def merge_team(client, deprecated_id: str, canonical_id: str, *, dry_run: bool = True):
    if dry_run:
        print(f"would merge {deprecated_id} -> {canonical_id}")
        return
    return client.rpc('execute_team_merge', {
        'p_deprecated_team_id': deprecated_id,
        'p_canonical_team_id': canonical_id,
        'p_merged_by': 'agent-name',
        'p_merge_reason': 'reason'
    }).execute()
```

## Read-Only Queries (SAFE)

```python
# These are always safe
.select('*')           # Read data
.select('col', count='exact')  # Count
.order('col', desc=True)       # Sort
.limit(100)            # Limit results
.range(0, 99)          # Pagination (with .order on a unique column)
```

## Write Operations (CAUTION)

```python
# These modify data - every script or method that calls them needs a --dry-run /
# dry_run guard (CLAUDE.md). Policy: games rows are immutable — quarantine bad
# data instead of updating
.insert(records)       # Add new rows
.upsert(records)       # Insert or update
.update(data)          # Modify existing (NEEDS filter!)
.delete()              # Remove rows (NEEDS filter!)
```

## Applying a Migration

No workflow applies migrations on merge. They are often run by hand in the dashboard SQL
editor without repairing the ledger, or recorded under a different version than their file, so
the ledger and `supabase/migrations/` disagree in both directions. `supabase db push` then
refuses: it lists ledger versions with no local file (suggesting
`migration repair --status reverted`) and local files older than the newest ledger entry
(suggesting `--include-all`). Take neither suggestion; both end in re-running files that are
already live.

Before recommending a push, compare `mcp__supabase__list_migrations` with
`supabase/migrations/` by name as well as version, and confirm the functions, tables or indexes
the unlisted files create exist live. To ship one migration, run its SQL in the SQL editor,
then record it with `supabase migration repair --status applied <version>`.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Database endpoint |
| `SUPABASE_SERVICE_ROLE_KEY` | Admin access (server-side only!) |
| `SUPABASE_KEY` | Anon key (client-side) |

**NEVER expose SERVICE_ROLE_KEY in browser code!**
