# Using SQLTools with COPY Import

## Overview
SQLTools is a VS Code extension that provides a GUI for database management. It can complement the COPY import script by:
- Managing database connections
- Executing SQL scripts
- Monitoring import progress
- Viewing staging table data

## Setup SQLTools Connection

### 1. Install SQLTools Extension
- Open VS Code Extensions (Ctrl+Shift+X)
- Search for "SQLTools" by mtxr
- Install the extension

### 2. Install Supabase Driver
- Click on SQLTools icon in sidebar
- Click "Add New Connection"
- Select "PostgreSQL" driver
- Or install "SQLTools PostgreSQL/Cockroach Driver" extension

### 3. Configure Connection

**Connection Name:** `Supabase Production`

**Connection Details:**
- **Connection Type:** PostgreSQL
- **Server:** `aws-0-[region].pooler.supabase.com` (from DATABASE_URL)
- **Port:** `6543` (pooler) or `5432` (direct)
- **Database:** `postgres`
- **Username:** `postgres.[project-ref]` (from DATABASE_URL)
- **Password:** Your database password (not service role key)

**Get Connection Details:**
1. Go to Supabase Dashboard > Settings > Database
2. Find "Connection String" section
3. Copy "Direct Connection" string
4. Parse it: `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
   - Username: `postgres.[ref]`
   - Host: `aws-0-[region].pooler.supabase.com`
   - Port: `6543`
   - Database: `postgres`
   - Password: `[password]`

## Using SQLTools with COPY Import

### Option 1: Hybrid Approach (Recommended)
1. **Use Python script** for COPY operations (handles data preparation and COPY FROM STDIN)
2. **Use SQLTools** for:
   - Creating staging table (run `copy_import_sql.sql`)
   - Monitoring progress (query `games_staging` table)
   - Moving data to main table (run final INSERT statements)
   - Cleanup (drop staging table)

### Option 2: Full SQLTools Workflow
1. **Prepare data** with Python script (validation, team matching, etc.)
2. **Export to CSV** in COPY format
3. **Use SQLTools** to:
   - Create staging table
   - Execute COPY command (if SQLTools supports COPY FROM file)
   - Move data to main table

### Workflow Example

```bash
# Step 1: Run Python script to prepare and COPY data
python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport --stream --batch-size 2000

# Step 2: In SQLTools, connect to Supabase and run:
# - Check staging table: SELECT COUNT(*) FROM games_staging;
# - View validation status: SELECT validation_status, COUNT(*) FROM games_staging GROUP BY validation_status;
# - Run final INSERT (from copy_import_sql.sql)
# - Cleanup: DROP TABLE games_staging;
```

## SQLTools Advantages

✅ **Visual Database Management**
- Browse tables, views, indexes
- View data in staging table
- Monitor import progress

✅ **Query Execution**
- Run SQL scripts directly
- Execute final INSERT statements
- Check import statistics

✅ **Connection Management**
- Save connection credentials securely
- Easy switching between environments
- No need to remember connection strings

## Limitations

⚠️ **COPY FROM STDIN**
- SQLTools GUI may not support COPY FROM STDIN directly
- Python script handles this via `psql` subprocess
- You can still use SQLTools for other SQL operations

⚠️ **Large Data Sets**
- For 1M+ games, COPY via psql is still fastest
- SQLTools is better for monitoring and final SQL operations

## Recommended Approach

**Best of Both Worlds:**
1. **Python script** handles:
   - Data validation and transformation
   - Team matching
   - COPY FROM STDIN (bulk insert)
   
2. **SQLTools** handles:
   - Database connection management
   - Monitoring staging table
   - Running final INSERT statements
   - Cleanup operations

This gives you the speed of COPY with the convenience of SQLTools GUI!



