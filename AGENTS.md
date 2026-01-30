# AGENTS.md — Moltbot Session Behavior and Workflow Rules for PitchRank

> This document defines how Moltbot operates within sessions, interacts with the codebase, and executes tasks safely.

---

## Session Startup Checklist

When starting a new session, Moltbot reads these files in order:

```
1. SOUL.md                          — Operating philosophy
2. AGENTS.md                        — This file (workflow rules)
3. HEARTBEAT.md                     — Health check definitions
4. PROJECT_FLOW.md                  — System architecture
5. SYSTEM_OVERVIEW.md               — Component relationships
6. .github/workflows/*.yml          — Scheduled job definitions
7. config/settings.py               — Environment configuration
```

### Quick Context Commands
```bash
# Check current state
git status
git branch --show-current
git log --oneline -5

# Verify environment
python -c "from dotenv import load_dotenv; load_dotenv('.env.local'); import os; print('SUPABASE_URL:', 'SET' if os.getenv('SUPABASE_URL') else 'MISSING')"

# Check recent builds
ls -la logs/*.log | tail -5
```

---

## Git Workflow Rules

### Branch Naming Convention
```
claude/<feature-name>         — Feature development
claude/fix-<issue>            — Bug fixes
claude/hotfix-<issue>         — Urgent production fixes
claude/experiment-<name>      — Exploratory work (never merge)
```

### Commit Message Format
```
<type>: <short summary>

<optional body with details>

<optional footer with issue refs>
```

**Types**: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`

**Examples**:
```
feat: add TGS event scraper for IDs 4150-4200
fix: handle null opponent_id in game deduplication
refactor: consolidate team matching logic into MergeResolver
docs: update WEEKLY_EVENT_WORKFLOW with new schedule
```

### Pre-Commit Checklist
```
□ git status — verify only intended files staged
□ git diff --staged — review all changes
□ No secrets in diff (.env values, API keys)
□ No large binary files (>1MB)
□ Tests pass (if applicable)
□ Linting passes (if configured)
```

### Protected Operations
These require explicit human approval:
- `git push origin main`
- `git merge * main`
- `git reset --hard`
- `git rebase` on shared branches
- Any force push

---

## Production Pipeline Safety

### Before Modifying Scrapers (`src/scrapers/`)

1. **Understand the target site structure**
   ```bash
   # Read existing scraper
   cat src/scrapers/gotsport.py | head -100

   # Check for rate limiting config
   grep -n "delay\|timeout\|retry" src/scrapers/gotsport.py
   ```

2. **Test in isolation**
   ```bash
   # Single team/event test
   python -c "from src.scrapers.gotsport import GotSportScraper; ..."
   ```

3. **Use conservative limits for initial runs**
   ```bash
   python scripts/scrape_games.py --provider gotsport --limit-teams 10 --dry-run
   ```

### Before Modifying Rankings (`src/rankings/`)

1. **Understand the calculation chain**
   ```
   v53e (base) → SOS iterations → Layer 13 (ML) → Final PowerScore
   ```

2. **Always use --dry-run first**
   ```bash
   python scripts/calculate_rankings.py --dry-run --ml
   ```

3. **Validate PowerScore bounds**
   - All scores must be in `[0.0, 1.0]`
   - Check min/max in output summary

4. **Compare against baseline**
   ```sql
   -- Check current top 10 before recalculation
   SELECT team_id, national_power_score, national_rank
   FROM rankings_full
   ORDER BY national_power_score DESC
   LIMIT 10;
   ```

### Before Modifying ETL (`src/etl/`)

1. **Test with validation-only mode**
   ```bash
   python scripts/import_games_enhanced.py data/raw/test.jsonl gotsport --validate-only
   ```

2. **Use small batch sizes for testing**
   ```bash
   python scripts/import_games_enhanced.py data.jsonl gotsport --batch-size 100 --limit 500 --dry-run
   ```

3. **Check quarantine after imports**
   ```sql
   SELECT COUNT(*) FROM team_quarantine WHERE created_at > NOW() - INTERVAL '1 hour';
   ```

---

## Command Execution Rules

### Safe Commands (execute freely)
```bash
# Reading/searching
cat, head, tail, grep, find, ls, tree
git status, git log, git diff, git branch

# Python inspection
python -c "..."  # One-liners
python scripts/*.py --help
python scripts/*.py --dry-run

# Database reads (via psql or Supabase client)
SELECT queries only
```

### Cautious Commands (verify before executing)
```bash
# Git writes
git add, git commit, git checkout, git stash

# File writes
echo ... > file, cat > file
python scripts/*.py  # Without --dry-run

# Package management
pip install, npm install
```

### Restricted Commands (require approval)
```bash
# Destructive git
git push, git reset, git rebase, git merge

# Database writes
INSERT, UPDATE, DELETE, DROP, TRUNCATE

# System changes
rm -rf, chmod, chown
systemctl, service

# Production execution
python scripts/calculate_rankings.py  # Without --dry-run
python scripts/import_games_enhanced.py  # Without --dry-run
```

---

## Workflow Integration

### GitHub Actions Interaction

**Reading workflow status**:
```bash
gh run list --limit 5
gh run view <run-id>
gh run view <run-id> --log
```

**Workflow dependencies** (must preserve order):
```
Monday Schedule:
06:00 UTC → scrape-games (batch 1)
11:15 UTC → scrape-games (batch 2)
16:05 UTC → fix-age-year-discrepancies
16:45 UTC → calculate-rankings
```

**Never modify workflow schedules without checking**:
1. Other workflows that depend on completion
2. Time zones (MST/MDT vs UTC conversion)
3. GitHub Actions runner availability

### Scraper Interaction

**Rate limiting awareness**:
```python
# GotSport defaults (from settings.py)
GOTSPORT_DELAY_MIN = 0.1  # seconds
GOTSPORT_DELAY_MAX = 2.5  # seconds
GOTSPORT_TIMEOUT = 30     # seconds
GOTSPORT_MAX_RETRIES = 2
```

**Safe scraping practices**:
- Always include `--limit-teams` for testing
- Monitor for 429/503 responses
- Check `last_scraped_at` before bulk runs
- Use `--null-teams-only` for bootstrap

### Rankings Job Interaction

**Pre-run validation**:
```bash
# Check if there's fresh game data
python -c "
from supabase import create_client
import os
client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
result = client.table('games').select('id', count='exact').gte('scraped_at', 'now() - interval 7 days').execute()
print(f'Games from last 7 days: {result.count}')
"
```

**Post-run validation**:
```bash
# Verify rankings were saved
python -c "
from supabase import create_client
import os
client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
result = client.table('rankings_full').select('team_id', count='exact').execute()
print(f'Teams ranked: {result.count}')
"
```

---

## Documentation Requirements

### When Creating New Features

1. Update `PROJECT_FLOW.md` if architecture changes
2. Add usage examples to relevant docs in `/docs/`
3. Update `README.md` if user-facing
4. Add inline comments for complex logic

### When Fixing Bugs

1. Document the root cause in commit message
2. Add test case if pattern is likely to recur
3. Update relevant documentation if behavior changed

### When Modifying Workflows

1. Update `.github/workflows/WEEKLY_UPDATE_SETUP.md`
2. Document new inputs/secrets required
3. Test manually with `workflow_dispatch` before enabling schedule

---

## Task Completion Definition

A task is **complete** when:

```
□ Requested functionality is implemented
□ Code is tested (--dry-run, validation, or manual)
□ No regressions in related functionality
□ Changes are committed with descriptive message
□ Relevant documentation is updated
□ Human has confirmed (for production changes)
```

A task is **blocked** when:

```
□ Missing information (ask specific questions)
□ Requires human decision (present options)
□ Requires credentials/access not available
□ Dependent system is unavailable
```

---

## Error Recovery Procedures

### Scraper Failure
```bash
# 1. Check logs
tail -100 logs/scrape_*.log

# 2. Verify target site is accessible
curl -I https://www.gotsport.com

# 3. Check for rate limiting
grep -i "429\|503\|rate" logs/scrape_*.log

# 4. Re-run with smaller scope
python scripts/scrape_games.py --provider gotsport --limit-teams 100
```

### Import Failure
```bash
# 1. Check for data issues
python scripts/import_games_enhanced.py data.jsonl gotsport --validate-only

# 2. Check quarantine growth
# If quarantine > 100 new records, investigate matching issues

# 3. Re-run with debug logging
python scripts/import_games_enhanced.py data.jsonl gotsport --debug --dry-run
```

### Rankings Failure
```bash
# 1. Check Supabase connectivity
python -c "from supabase import create_client; ..."

# 2. Verify game data exists
# SELECT COUNT(*) FROM games WHERE game_date > NOW() - INTERVAL '365 days';

# 3. Re-run with verbose output
python scripts/calculate_rankings.py --ml --dry-run 2>&1 | tee ranking_debug.log
```

---

## Session Shutdown Checklist

Before ending a session:

```
□ All changes committed (or stashed)
□ Working directory is clean (git status)
□ No background processes running
□ Summary of work completed documented
□ Any blockers or follow-ups noted
□ Branch pushed to remote (if work is complete)
```

---

## Version

```
AGENTS.md v1.0.0
PitchRank Repository
Last Updated: 2026-01-30
```
