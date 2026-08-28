---
name: supabase-pitchrank
description: Safe Supabase patterns for PitchRank - table schemas, query limits, what NOT to do
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
-- Multiple aliases can point to same master
```

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

## Safe Query Patterns

### Pagination (REQUIRED for large tables)
```python
# Supabase has ~1000 row default limit
# Always paginate for large queries

def fetch_all_teams(client):
    all_teams = []
    offset = 0
    batch_size = 1000

    while True:
        result = client.table('teams') \
            .select('*') \
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

## NEVER DO

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
# BAD - only gets first ~1000 rows
client.table('games').select('*').execute()

# GOOD - paginate
.range(0, 999).execute()
.range(1000, 1999).execute()
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
.range(0, 99)          # Pagination
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

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Database endpoint |
| `SUPABASE_SERVICE_ROLE_KEY` | Admin access (server-side only!) |
| `SUPABASE_KEY` | Anon key (client-side) |

**NEVER expose SERVICE_ROLE_KEY in frontend code!**
