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

- [ ] Install Supabase CLI
  - Windows (Scoop): `scoop install supabase`
  - Mac (Homebrew): `brew install supabase/tap/supabase`
  - Or: `npm install -g supabase`
- [ ] Initialize Supabase
  ```bash
  supabase init
  ```
- [ ] Link project
  ```bash
  supabase link --project-ref pfkrhmprwxtghtpinrot
  ```
- [ ] Apply migrations
  ```bash
  supabase db push
  ```
  
  Or run setup helper:
  ```bash
  python scripts/setup_supabase.py
  ```

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
  python scripts/import_master_teams.py --path data/samples --provider sample
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
2. **Import Real Teams**: Use `python scripts/import_master_teams.py` with your CSV files
3. **Import Game History**: Use `python scripts/import_game_history_enhanced.py` with game data
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

