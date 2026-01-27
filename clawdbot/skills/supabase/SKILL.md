---
name: supabase
description: Supabase database expert for PitchRank. Use when working with database queries, RLS policies, migrations, schema changes, or optimizing Postgres performance. Covers teams, games, rankings, and all PitchRank tables.
allowed-tools: Bash, Read, Write, Edit, Grep
user-invocable: true
---

# Supabase Database Expert

You are a Supabase and PostgreSQL expert for PitchRank. You help with database queries, schema design, RLS policies, and performance optimization.

## PitchRank Database Context

### Core Tables
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `teams` | Master team registry | `team_id_master`, `team_name`, `age_group`, `gender`, `state_code` |
| `games` | Game results (IMMUTABLE) | `game_uid`, `home_team_id`, `away_team_id`, `home_score`, `away_score` |
| `team_alias_map` | Provider ID → Master ID | `provider_team_id`, `team_id_master`, `provider` |
| `rankings_full` | Calculated rankings | `team_id`, `power_score`, `rank`, `age_group` |
| `scrape_requests` | User missing game requests | `id`, `team_id`, `status`, `requested_at` |
| `build_logs` | Import audit trail | `build_id`, `records_processed`, `metrics` |

### Key Relationships
```
teams.team_id_master ← team_alias_map.team_id_master
teams.team_id_master ← games.home_team_id / away_team_id
teams.team_id_master ← rankings_full.team_id
teams.team_id_master ← scrape_requests.team_id
```

---

## Supabase Helper Functions

### Authentication Functions
```sql
-- Get current user's UUID (use in RLS policies)
auth.uid()

-- Get current user's JWT claims
auth.jwt()

-- Check user role from JWT
(auth.jwt() ->> 'role')::text

-- Check if user is premium
(auth.jwt() -> 'app_metadata' ->> 'plan')::text = 'premium'
```

### Usage in RLS
```sql
-- CORRECT: Wrap in subquery for performance
CREATE POLICY "Users can view own data"
ON user_data FOR SELECT
USING ((select auth.uid()) = user_id);

-- INCORRECT: Direct call (slower)
CREATE POLICY "Users can view own data"
ON user_data FOR SELECT
USING (auth.uid() = user_id);
```

---

## Row Level Security (RLS) Best Practices

### Always Enable RLS
```sql
ALTER TABLE my_table ENABLE ROW LEVEL SECURITY;
```

### Granular Policies (One per Operation)
```sql
-- ✅ CORRECT: Separate policies
CREATE POLICY "select_teams" ON teams FOR SELECT USING (true);
CREATE POLICY "insert_teams" ON teams FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
CREATE POLICY "update_teams" ON teams FOR UPDATE USING (auth.uid() IS NOT NULL);

-- ❌ INCORRECT: Combined operations
CREATE POLICY "all_teams" ON teams FOR ALL USING (true);
```

### Specify Roles Explicitly
```sql
CREATE POLICY "anon_can_read_rankings"
ON rankings_full
FOR SELECT
TO anon, authenticated
USING (true);
```

### Index RLS-Checked Columns
```sql
-- If RLS checks user_id, index it
CREATE INDEX idx_user_data_user_id ON user_data(user_id);
```

---

## Migration Best Practices

### Naming Convention
```
YYYYMMDDHHmmss_short_description.sql
Example: 20260127143000_add_team_birth_year.sql
```

### Migration Template
```sql
-- Migration: Add birth_year column to teams
-- Author: Clawdbot
-- Date: 2026-01-27

-- Add new column
ALTER TABLE teams
ADD COLUMN birth_year INTEGER;

-- Add check constraint
ALTER TABLE teams
ADD CONSTRAINT valid_birth_year
CHECK (birth_year IS NULL OR (birth_year >= 2005 AND birth_year <= 2020));

-- Create index for common queries
CREATE INDEX idx_teams_birth_year ON teams(birth_year);

-- Add comment
COMMENT ON COLUMN teams.birth_year IS 'Birth year extracted from team name, e.g., 2014 for "FC Dallas 2014B"';
```

### Always Set search_path
```sql
-- Security: Prevent search_path injection
SET search_path = '';

-- Use fully qualified names
SELECT * FROM public.teams WHERE public.teams.age_group = 'u14';
```

---

## Query Patterns for PitchRank

### Get Team with Rankings
```sql
SELECT
    t.team_id_master,
    t.team_name,
    t.age_group,
    t.state_code,
    r.power_score,
    r.rank
FROM public.teams t
LEFT JOIN public.rankings_full r ON t.team_id_master = r.team_id
WHERE t.age_group = 'u14'
  AND t.gender = 'Male'
ORDER BY r.rank ASC
LIMIT 10;
```

### Get Team's Recent Games
```sql
SELECT
    g.game_date,
    g.home_score,
    g.away_score,
    ht.team_name as home_team,
    at.team_name as away_team
FROM public.games g
JOIN public.teams ht ON g.home_team_id = ht.team_id_master
JOIN public.teams at ON g.away_team_id = at.team_id_master
WHERE g.home_team_id = $1 OR g.away_team_id = $1
ORDER BY g.game_date DESC
LIMIT 20;
```

### Find Pending Scrape Requests
```sql
SELECT
    sr.id,
    sr.team_id,
    t.team_name,
    sr.requested_at,
    sr.status
FROM public.scrape_requests sr
JOIN public.teams t ON sr.team_id = t.team_id_master
WHERE sr.status = 'pending'
ORDER BY sr.requested_at ASC;
```

### Data Quality: Find Age Mismatches
```sql
SELECT
    team_id_master,
    team_name,
    age_group,
    -- Extract birth year from name
    SUBSTRING(team_name FROM '(20\d{2})') as name_birth_year
FROM public.teams
WHERE team_name ~ '20\d{2}'
  AND age_group IS NOT NULL;
```

---

## Python Supabase Client

### Basic Queries
```python
from supabase import create_client
import os

client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# Select with filters
result = client.table("teams")\
    .select("team_id_master, team_name, age_group")\
    .eq("age_group", "u14")\
    .eq("gender", "Male")\
    .order("team_name")\
    .limit(100)\
    .execute()

# Insert
result = client.table("build_logs").insert({
    "build_id": "gotsport_20260127_abc",
    "records_processed": 150,
    "metrics": {"games_imported": 45}
}).execute()

# Update
result = client.table("teams")\
    .update({"age_group": "u12"})\
    .eq("team_id_master", team_id)\
    .execute()

# Upsert (insert or update)
result = client.table("team_alias_map").upsert({
    "provider_team_id": "gotsport_12345",
    "team_id_master": master_id,
    "provider": "gotsport"
}).execute()
```

### Pagination
```python
# Cursor-based (preferred for large datasets)
def get_all_teams():
    teams = []
    offset = 0
    batch_size = 1000

    while True:
        result = client.table("teams")\
            .select("*")\
            .range(offset, offset + batch_size - 1)\
            .execute()

        if not result.data:
            break

        teams.extend(result.data)

        if len(result.data) < batch_size:
            break

        offset += batch_size

    return teams
```

---

## Performance Tips

### Use Indexes
```sql
-- For common WHERE clauses
CREATE INDEX idx_teams_age_gender ON teams(age_group, gender);
CREATE INDEX idx_games_date ON games(game_date DESC);
CREATE INDEX idx_scrape_requests_status ON scrape_requests(status);
```

### Analyze Query Plans
```sql
EXPLAIN ANALYZE
SELECT * FROM teams WHERE age_group = 'u14';
```

### Avoid SELECT *
```python
# ❌ Bad
client.table("teams").select("*")

# ✅ Good
client.table("teams").select("team_id_master, team_name, age_group")
```

### Use Count Efficiently
```python
# Get count without fetching data
result = client.table("teams")\
    .select("team_id_master", count="exact")\
    .eq("age_group", "u14")\
    .execute()

count = result.count
```

---

## Games Table (Immutable)

The `games` table is IMMUTABLE. A trigger prevents direct updates:

```sql
-- This will FAIL
UPDATE games SET home_score = 3 WHERE game_uid = 'xxx';
-- Error: Cannot update immutable game. Use game_corrections table instead.
```

### To Correct a Game
1. Insert into `game_corrections` table
2. Wait for approval
3. Approved corrections are applied by admin

---

## Common Supabase CLI Commands

```bash
# Generate migration from schema changes
supabase db diff -f my_migration_name

# Apply migrations
supabase db push

# Reset local database
supabase db reset

# Generate TypeScript types
supabase gen types typescript --local > types/supabase.ts
```

---

## Security Rules

1. **Always enable RLS** on new tables
2. **Never expose service_role key** to client
3. **Use anon key** for public read operations
4. **Validate user input** before queries
5. **Set search_path = ''** in functions
6. **Use SECURITY INVOKER** for functions (not DEFINER)
