# PitchRank Setup Checklist

Use this checklist to track your setup progress.

## Prerequisites

- [ ] Python 3.8+ installed
  - Check: `python --version` or `python3 --version`
  - Download: https://www.python.org/downloads/

## Quick Setup (Automated)

Run the automated setup script:

```bash
python setup_pitchrank.py
```

This will guide you through all steps automatically.

## Manual Setup Steps

### 1. Virtual Environment

- [ ] Create virtual environment
  ```bash
  python -m venv venv
  ```
- [ ] Activate virtual environment
  - Windows: `venv\Scripts\activate`
  - Mac/Linux: `source venv/bin/activate`
- [ ] Install dependencies
  ```bash
  pip install -r requirements.txt
  ```

### 2. Supabase Configuration

- [ ] Create Supabase account
  - Sign up: https://supabase.com
- [ ] Create Supabase project
  - Dashboard: https://app.supabase.com
  - Project ref: `pfkrhmprwxtghtpinrot`
- [ ] Configure environment
  ```bash
  python configure_env.py
  ```
  - Or create `.env` file manually with:
    - `SUPABASE_URL`
    - `SUPABASE_KEY`
    - `SUPABASE_SERVICE_ROLE_KEY`

### 3. Database Setup

#### Option A: Production Supabase (Cloud)

- [ ] Configure environment
  ```bash
  python configure_env.py
  ```
  - Or create `.env` file manually with:
    - `SUPABASE_URL`
    - `SUPABASE_KEY`
    - `SUPABASE_SERVICE_ROLE_KEY`

#### Option B: Local Supabase (Development - Recommended for Testing)

**Prerequisites:**
- [ ] Docker Desktop installed and running
- [ ] Supabase CLI installed:
  - Windows (Scoop): `scoop bucket add supabase https://github.com/supabase/scoop-bucket.git && scoop install supabase`
  - Mac (Homebrew): `brew install supabase/tap/supabase`
  - Linux: See https://github.com/supabase/cli#install-the-cli

**Setup Steps:**
- [ ] Initialize Supabase project
  ```bash
  supabase init
  ```
- [ ] Start local Supabase (requires Docker Desktop running)
  ```bash
  supabase start
  ```
  - Note the output showing `SUPABASE_URL`, `SUPABASE_KEY`, and `SUPABASE_SERVICE_ROLE_KEY`
- [ ] Create `.env.local` file with local credentials:
  ```bash
  USE_LOCAL_SUPABASE=true
  SUPABASE_URL=http://localhost:54321
  SUPABASE_KEY=<from_supabase_start_output>
  SUPABASE_SERVICE_ROLE_KEY=<from_supabase_start_output>
  ```
- [ ] (Optional) Link to production to pull schema
  ```bash
  supabase link --project-ref pfkrhmprwxtghtpinrot
  supabase db pull
  ```
- [ ] Apply migrations to local database
  ```bash
  supabase db reset
  ```
  
**Benefits of Local Development:**
- No SSL/TLS errors (local HTTP)
- Faster imports (no network latency)
- Free to test (no API limits)
- Full database access via Supabase Studio (http://localhost:54323)

**Switching Between Local and Production:**
- Use `.env.local` with `USE_LOCAL_SUPABASE=true` for local development
- Use `.env` (production credentials) for production imports
- The code automatically detects `USE_LOCAL_SUPABASE` environment variable

### 4. Verification

- [ ] Test database connection
  ```bash
  python test_connection.py
  ```
  Should show all tables with green checkmarks.

### 5. Sample Data (Optional)

- [ ] Create sample data
  ```bash
  python scripts/create_sample_data.py
  ```
- [ ] Import sample teams (if CSV available)
  ```bash
  python scripts/import_teams_enhanced.py data/samples/all_teams_master.csv sample
  ```

## Verification Commands

### Check Setup Status
```bash
python setup_guide.py
```

### Test Connection
```bash
python test_connection.py
```

### View Database Tables
- Supabase Dashboard: https://pfkrhmprwxtghtpinrot.supabase.co/project/pfkrhmprwxtghtpinrot

## Common Issues

### Virtual Environment Not Found
- Ensure you're in the PitchRank directory
- Create venv: `python -m venv venv`
- Activate before running scripts

### Supabase Connection Failed
- Check `.env` file exists and has correct credentials
- Verify Supabase project is active
- Test connection: `python test_connection.py`

### Database Tables Missing
- Run migrations: `supabase db push`
- Or manually run: `supabase/migrations/20240101000000_initial_schema.sql` in Supabase SQL Editor

### Supabase CLI Not Found
- Install CLI (see Database Setup section)
- Verify: `supabase --version`
- On Windows, may need to restart terminal after installation

### Import Errors
- Ensure database tables exist first
- Check CSV file format matches expected columns
- Verify provider code is correct (gotsport, tgs, usclub, sample)

## Getting Help

1. Check this checklist
2. Run `python setup_guide.py` to see what's missing
3. Review error messages for specific issues
4. Check Supabase dashboard for database status

## Next Steps After Setup

1. **Explore Sample Data**: Run `python scripts/create_sample_data.py` to generate test data
2. **Import Real Teams**: Use `python scripts/import_teams_enhanced.py` with your CSV files
3. **Import Game History**: Use `python scripts/import_games_enhanced.py <file> <provider>` with game data
4. **Review Aliases**: Use `python scripts/review_aliases.py` to review team matches
5. **Calculate Rankings**: Implement ranking algorithms (to be added)

---

**Setup Complete Checklist:**
- [ ] Python 3.8+ installed
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] .env file configured
- [ ] Supabase project linked
- [ ] Database migrations applied
- [ ] Connection tested successfully
- [ ] Sample data created (optional)

Once all items are checked, you're ready to use PitchRank! 🚀

