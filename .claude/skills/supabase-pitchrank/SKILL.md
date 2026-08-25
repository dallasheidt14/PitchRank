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
age_group         TEXT              -- "12", "u12", "U12" (normalize!)
gender            TEXT              -- "Male" or "Female"
state_code        TEXT              -- 2-letter state code
provider_id       UUID              -- FK to providers(id); there is no provider_code column
is_deprecated     BOOLEAN           -- TRUE if merged into another team
last_scraped_at   TIMESTAMPTZ
```

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
```sql
team_id              UUID PRIMARY KEY
powerscore_core      FLOAT          -- pre-ML, pre-gates (0.0-1.0)
powerscore_adj       FLOAT
powerscore_ml        FLOAT
power_score_true     FLOAT          -- post-gates, unanchored
power_score_final    FLOAT          -- power_score_true x AGE_TO_ANCHOR
rank_in_cohort_final INT            -- the published rank
national_power_score FLOAT          -- legacy column, still written
national_rank        INT            -- ALWAYS NULL; views compute display ranks
state_rank           INT            -- ALWAYS NULL; views compute display ranks
games_played         INT
wins, losses, draws  INT
last_calculated      TIMESTAMPTZ
-- 73 columns total; this is the subset worth knowing
```

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
| Connection timeout | 30 seconds |

## NEVER DO

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
# team_merge_map row and cascades team_alias_map/teams (games are immutable and
# resolve through the map at read time) — still effectively irreversible, so
# dry-run is the default and writing is opt-in.
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
