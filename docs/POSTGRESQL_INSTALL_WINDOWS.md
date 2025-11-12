# PostgreSQL Installation Guide for Windows

## What You Need

For the COPY import script, you only need:
- ✅ **psql** (PostgreSQL command-line client)
- ❌ **NOT** the full PostgreSQL server (you're using Supabase cloud)

## Installation Options

### Option 1: PostgreSQL Full Installer (Recommended - Easiest)

**Why:** Easiest setup, automatic PATH configuration

**Steps:**
1. Go to: https://www.postgresql.org/download/windows/
2. Click **"Download the installer"**
3. Choose **EnterpriseDB** installer (official)
4. Download latest version (16.x or 15.x)

**During Installation:**
- ✅ **Select Components:**
  - ✅ **Command Line Tools** (includes psql) ← REQUIRED
  - ✅ **pgAdmin** (optional GUI tool - useful!)
  - ❌ **PostgreSQL Server** (NOT needed - you use Supabase cloud)
  - ❌ **Stack Builder** (optional - skip it)

- ✅ **Installation Directory:**
  - Default is fine: `C:\Program Files\PostgreSQL\16`

- ✅ **Data Directory:**
  - Can skip (not using local server)

- ✅ **Password:**
  - Set any password (won't be used - you connect to Supabase)

- ✅ **Port:**
  - Default 5432 is fine (won't conflict - Supabase uses different host)

- ✅ **Advanced Options:**
  - ✅ **Add PostgreSQL bin directory to PATH** ← IMPORTANT!
  - ✅ **Precompiled binaries** (faster)

**After Installation:**
- Verify: Open PowerShell and run `psql --version`
- Should show: `psql (PostgreSQL) 16.x`

### Option 2: Standalone psql Client (Lighter Weight)

**Why:** Smaller download, only what you need

**Steps:**
1. Go to: https://www.enterprisedb.com/download-postgresql-binaries
2. Download: **PostgreSQL 16.x Windows x86-64** (ZIP archive)
3. Extract ZIP file
4. Find `psql.exe` in `bin` folder
5. Add `bin` folder to PATH:
   - Copy path (e.g., `C:\postgresql\bin`)
   - Add to System Environment Variables > PATH

**Pros:**
- Smaller download (~50MB vs ~200MB)
- No server components

**Cons:**
- Manual PATH setup
- No pgAdmin GUI tool

### Option 3: Using Chocolatey (If You Have It)

```powershell
choco install postgresql --params '/Password:supabase' --params '/NoServer:true'
```

## Recommended: Option 1 (Full Installer)

**Why:**
- ✅ Easiest setup
- ✅ Automatic PATH configuration
- ✅ Includes pgAdmin (useful GUI tool)
- ✅ Official installer (most reliable)

## Verification

After installation, verify `psql` works:

```powershell
# Check version
psql --version

# Test connection to Supabase (will prompt for password)
psql -h db.pfkrhmprwxtghtpinrot.supabase.co -p 5432 -U postgres -d postgres
```

## What Gets Installed

**Required:**
- `psql.exe` - Command-line client (for COPY import)

**Optional but Useful:**
- `pgAdmin` - GUI database management tool
- Other PostgreSQL utilities (`pg_dump`, `pg_restore`, etc.)

**Not Needed:**
- PostgreSQL Server (you use Supabase cloud)
- Database data directory (Supabase handles this)

## Troubleshooting

**"psql is not recognized"**
- Restart PowerShell/terminal after installation
- Verify PATH includes: `C:\Program Files\PostgreSQL\16\bin`
- Or manually add to PATH in System Environment Variables

**Connection Issues**
- Make sure you're using Supabase connection string (not localhost)
- Check firewall isn't blocking port 5432
- Verify DATABASE_URL in `.env.local` is correct

## Next Steps

After installing:
1. Verify: `psql --version`
2. Test import: `python scripts/import_games_enhanced.py data/master/all_games_master.csv gotsport --stream --batch-size 2000`



