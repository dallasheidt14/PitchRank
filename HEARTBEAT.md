# HEARTBEAT.md — Automated Health Monitoring for PitchRank

> This document defines health checks Moltbot runs to detect silent failures and maintain system integrity.

---

## Monitoring Philosophy

```
✓ SILENT when healthy
✓ ALERT only when intervention required
✓ LOW noise, HIGH signal
✓ ACTIONABLE recommendations
```

---

## Health Check Categories

1. [Data Pipeline Health](#1-data-pipeline-health)
2. [Scraper Status](#2-scraper-status)
3. [File Freshness](#3-file-freshness)
4. [Repository State](#4-repository-state)
5. [Database Health](#5-database-health)
6. [Environment Availability](#6-environment-availability)
7. [Runtime Errors](#7-runtime-errors)
8. [Production Safety](#8-production-safety)

---

## 1. Data Pipeline Health

### 1.1 Games Import Rate

**What to check**: Number of games imported in the last 7 days

**Detection**:
```python
from supabase import create_client
import os
from datetime import datetime, timedelta

client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
week_ago = (datetime.now() - timedelta(days=7)).isoformat()
result = client.table('games').select('id', count='exact').gte('created_at', week_ago).execute()
count = result.count or 0
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count > 1000 | Silent |
| ⚠️ WARNING | 100 < count ≤ 1000 | Log: "Low import rate this week" |
| ❌ CRITICAL | count ≤ 100 | Alert: "Pipeline may be stalled - only {count} games in 7 days" |

---

### 1.2 Team Quarantine Backlog

**What to check**: Unresolved teams in quarantine table

**Detection**:
```python
result = client.table('team_quarantine').select('id', count='exact').is_('resolved_at', 'null').execute()
backlog = result.count or 0
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | backlog < 50 | Silent |
| ⚠️ WARNING | 50 ≤ backlog < 200 | Log: "Quarantine backlog growing ({backlog} teams)" |
| ❌ CRITICAL | backlog ≥ 200 | Alert: "Quarantine overflow - {backlog} teams need review" |

---

### 1.3 Build Log Errors

**What to check**: Failed builds in last 24 hours

**Detection**:
```python
day_ago = (datetime.now() - timedelta(days=1)).isoformat()
result = client.table('build_logs').select('build_id, errors').gte('created_at', day_ago).not_.is_('errors', 'null').execute()
failed_builds = [b for b in (result.data or []) if b.get('errors')]
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | len(failed_builds) == 0 | Silent |
| ⚠️ WARNING | 1 ≤ len(failed_builds) ≤ 3 | Log: "Recent build errors: {build_ids}" |
| ❌ CRITICAL | len(failed_builds) > 3 | Alert: "Multiple pipeline failures in 24h" |

---

## 2. Scraper Status

### 2.1 GotSport Scraper Health

**What to check**: Last successful GotSport scrape

**Detection**:
```python
result = client.table('teams').select('last_scraped_at').eq('provider_code', 'gotsport').order('last_scraped_at', desc=True).limit(1).execute()
last_scrape = result.data[0]['last_scraped_at'] if result.data else None
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | last_scrape within 3 days | Silent |
| ⚠️ WARNING | last_scrape 3-7 days ago | Log: "GotSport scraper hasn't run in {days} days" |
| ❌ CRITICAL | last_scrape > 7 days or None | Alert: "GotSport scraper appears dead" |

---

### 2.2 Scraper Response Codes

**What to check**: HTTP error patterns in recent logs

**Detection**:
```bash
grep -c "429\|503\|timeout\|connection refused" logs/scrape_*.log 2>/dev/null || echo "0"
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count < 10 | Silent |
| ⚠️ WARNING | 10 ≤ count < 50 | Log: "Elevated error rate in scraper ({count} errors)" |
| ❌ CRITICAL | count ≥ 50 | Alert: "Possible rate limiting or site blocking" |

---

### 2.3 Zero-Result Scrapes

**What to check**: Scraper runs that returned 0 games

**Detection**:
```bash
grep -l "Games: 0" logs/scrape_*.log 2>/dev/null | wc -l
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count == 0 | Silent |
| ⚠️ WARNING | count == 1 | Log: "One scraper run returned zero games" |
| ❌ CRITICAL | count > 1 | Alert: "Multiple zero-result scrapes - check site structure" |

---

## 3. File Freshness

### 3.1 Log File Age

**What to check**: Most recent log file modification

**Detection**:
```bash
find logs/ -name "*.log" -mtime -1 -type f | wc -l
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count > 0 | Silent (recent activity) |
| ⚠️ WARNING | count == 0 and any logs exist | Log: "No log activity in 24 hours" |
| ❌ CRITICAL | No log files exist | Alert: "Log directory empty or missing" |

---

### 3.2 Log File Size

**What to check**: Excessively large log files

**Detection**:
```bash
find logs/ -name "*.log" -size +50M -type f
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | No files > 50MB | Silent |
| ⚠️ WARNING | 1-2 files > 50MB | Log: "Large log files: {files}" |
| ❌ CRITICAL | > 2 files > 50MB | Alert: "Log rotation needed - multiple large files" |

---

### 3.3 Cache Staleness

**What to check**: Age of cached data files

**Detection**:
```bash
find data/cache/ -name "*.json" -mtime +7 -type f | wc -l
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count == 0 | Silent |
| ⚠️ WARNING | 0 < count ≤ 10 | Log: "Stale cache files detected" |
| ❌ CRITICAL | count > 10 | Alert: "Cache not being refreshed properly" |

---

## 4. Repository State

### 4.1 Dirty Working Tree

**What to check**: Uncommitted changes in working directory

**Detection**:
```bash
git status --porcelain | wc -l
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count == 0 | Silent |
| ⚠️ WARNING | 0 < count ≤ 5 | Log: "Uncommitted changes: {count} files" |
| ❌ CRITICAL | count > 5 | Alert: "Many uncommitted changes - risk of data loss" |

---

### 4.2 Branch Divergence

**What to check**: Local branch behind remote

**Detection**:
```bash
git fetch origin main 2>/dev/null
git rev-list --left-right --count main...origin/main 2>/dev/null
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | behind == 0 | Silent |
| ⚠️ WARNING | 0 < behind ≤ 10 | Log: "Local main is {behind} commits behind" |
| ❌ CRITICAL | behind > 10 | Alert: "Significantly out of sync with remote" |

---

### 4.3 Broken Python Imports

**What to check**: Import errors in main modules

**Detection**:
```bash
python -c "
import sys
sys.path.insert(0, '.')
try:
    from src.rankings.calculator import compute_rankings_with_ml
    from src.etl.enhanced_pipeline import EnhancedETLPipeline
    from src.scrapers.gotsport import GotSportScraper
    print('OK')
except ImportError as e:
    print(f'FAIL: {e}')
"
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | Output is "OK" | Silent |
| ❌ CRITICAL | Import error | Alert: "Broken imports: {error}" |

---

## 5. Database Health

### 5.1 Supabase Connectivity

**What to check**: Can connect to Supabase

**Detection**:
```python
try:
    client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
    client.table('teams').select('team_id_master').limit(1).execute()
    status = "OK"
except Exception as e:
    status = f"FAIL: {e}"
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | status == "OK" | Silent |
| ❌ CRITICAL | Connection fails | Alert: "Supabase unreachable - all operations blocked" |

---

### 5.2 Rankings Freshness

**What to check**: When rankings were last calculated

**Detection**:
```python
result = client.table('rankings_full').select('last_calculated').order('last_calculated', desc=True).limit(1).execute()
last_calc = result.data[0]['last_calculated'] if result.data else None
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | last_calc within 7 days | Silent |
| ⚠️ WARNING | last_calc 7-14 days ago | Log: "Rankings are {days} days old" |
| ❌ CRITICAL | last_calc > 14 days or None | Alert: "Rankings severely outdated" |

---

### 5.3 Team Count Validation

**What to check**: Total ranked teams vs expected minimum

**Detection**:
```python
result = client.table('rankings_full').select('team_id', count='exact').execute()
team_count = result.count or 0
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | team_count > 10000 | Silent |
| ⚠️ WARNING | 5000 < team_count ≤ 10000 | Log: "Lower than expected team count: {team_count}" |
| ❌ CRITICAL | team_count ≤ 5000 | Alert: "Rankings may be incomplete - only {team_count} teams" |

---

## 6. Environment Availability

### 6.1 Required Environment Variables

**What to check**: Critical env vars are set

**Detection**:
```python
required = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY']
missing = [v for v in required if not os.getenv(v)]
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | len(missing) == 0 | Silent |
| ❌ CRITICAL | Any missing | Alert: "Missing env vars: {missing}" |

---

### 6.2 Python Dependencies

**What to check**: All required packages installed

**Detection**:
```bash
pip check 2>&1 | grep -c "has requirement" || echo "0"
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count == 0 | Silent |
| ⚠️ WARNING | count > 0 | Log: "Dependency conflicts detected" |

---

### 6.3 Disk Space

**What to check**: Available disk space

**Detection**:
```bash
df -h . | awk 'NR==2 {print $5}' | tr -d '%'
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | usage < 80% | Silent |
| ⚠️ WARNING | 80% ≤ usage < 90% | Log: "Disk usage at {usage}%" |
| ❌ CRITICAL | usage ≥ 90% | Alert: "Disk nearly full - {usage}%" |

---

## 7. Runtime Errors

### 7.1 Recent Python Exceptions

**What to check**: Unhandled exceptions in logs

**Detection**:
```bash
grep -c "Traceback\|Exception\|Error:" logs/*.log 2>/dev/null || echo "0"
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count < 5 | Silent |
| ⚠️ WARNING | 5 ≤ count < 20 | Log: "Multiple errors in logs ({count})" |
| ❌ CRITICAL | count ≥ 20 | Alert: "High error rate - review logs" |

---

### 7.2 GitHub Actions Failures

**What to check**: Recent workflow run status

**Detection**:
```bash
gh run list --status failure --limit 5 --json databaseId,conclusion,name 2>/dev/null
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | No recent failures | Silent |
| ⚠️ WARNING | 1-2 failures | Log: "Recent workflow failures: {names}" |
| ❌ CRITICAL | ≥ 3 failures | Alert: "Multiple CI/CD failures" |

---

## 8. Data Hygiene

### 8.1 Weekly Merge Run

**What to check**: Last successful duplicate team merge

**Detection**:
```bash
# Check merge tracker
cat scripts/merges/merge_tracker.json | jq '.last_run'
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | last_run within 10 days | Silent |
| ⚠️ WARNING | last_run 10-14 days ago | Log: "Data hygiene overdue" |
| ❌ CRITICAL | last_run > 14 days or missing | Alert: "Weekly merge hasn't run" |

---

### 8.2 Quarantine Growth Rate

**What to check**: Teams added to quarantine vs merged

**Detection**:
```python
# Compare quarantine size week-over-week
result = client.table('team_quarantine').select('id', count='exact').is_('resolved_at', 'null').execute()
current = result.count or 0
# Compare to last week's count from merge_tracker.json
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | Growth < 50/week | Silent |
| ⚠️ WARNING | 50 ≤ growth < 100 | Log: "Quarantine growing faster than merges" |
| ❌ CRITICAL | Growth ≥ 100/week | Alert: "Quarantine backlog accelerating" |

---

## 9. Production Safety

### 8.1 Exposed Secrets Check

**What to check**: Credentials not in tracked files

**Detection**:
```bash
git ls-files | xargs grep -l "SUPABASE_SERVICE_ROLE_KEY=ey\|password=" 2>/dev/null | wc -l
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count == 0 | Silent |
| ❌ CRITICAL | count > 0 | Alert: "SECRETS EXPOSED IN REPO - ROTATE IMMEDIATELY" |

---

### 8.2 Main Branch Protection

**What to check**: Unexpected changes to main branch

**Detection**:
```bash
git log --oneline origin/main -1 --format="%H %s"
# Compare against known last good commit
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | No unexpected commits | Silent |
| ⚠️ WARNING | Unreviewed commits | Log: "New commits on main: {summary}" |

---

### 8.3 Workflow Modification Detection

**What to check**: Changes to CI/CD workflows

**Detection**:
```bash
git diff HEAD~5 --name-only -- .github/workflows/ | wc -l
```

| Status | Condition | Action |
|--------|-----------|--------|
| ✅ OK | count == 0 | Silent |
| ⚠️ WARNING | count > 0 | Log: "Workflow files modified recently" |

---

## Heartbeat Execution Schedule

### Recommended Frequency

| Check Category | Frequency | Notes |
|----------------|-----------|-------|
| Database Health | Daily (6 AM UTC) | After overnight processes |
| Data Pipeline Health | Daily (7 AM UTC) | Check import results |
| Scraper Status | Every 3 days | Matches scrape schedule |
| File Freshness | Weekly (Sunday) | Low urgency |
| Repository State | Weekly (Sunday) | Before hygiene run |
| Environment Availability | On startup only | No periodic check needed |
| Runtime Errors | Daily (8 AM UTC) | Review overnight logs |
| Production Safety | Weekly (Sunday) | Security audit |

---

## Alert Escalation

### Level 1: Log Only (⚠️ WARNING)
- Write to `logs/heartbeat.log`
- No notification

### Level 2: Alert (❌ CRITICAL)
- Write to `logs/heartbeat.log`
- Create GitHub issue (if configured)
- Trigger notification webhook (if configured)

### Alert Message Format
```
🚨 PITCHRANK HEARTBEAT ALERT

Check: [Check Name]
Status: CRITICAL
Time: [ISO timestamp]
Details: [Specific findings]

Recommended Action:
[Actionable steps]

Dashboard: [Link to relevant logs/UI]
```

---

## Quick Health Check Script

```bash
#!/bin/bash
# quick_health.sh - Run critical checks only

echo "=== PitchRank Quick Health Check ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# 1. Git status
echo "📁 Repository State:"
git status --short

# 2. Supabase connectivity
echo ""
echo "🔌 Database:"
python -c "
from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv('.env.local')
try:
    c = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
    c.table('teams').select('team_id_master').limit(1).execute()
    print('✅ Supabase connected')
except Exception as e:
    print(f'❌ Supabase failed: {e}')
"

# 3. Recent errors
echo ""
echo "📋 Recent Errors:"
grep -c "Error\|Exception" logs/*.log 2>/dev/null || echo "No logs found"

# 4. Disk space
echo ""
echo "💾 Disk Space:"
df -h . | awk 'NR==2 {print "Used: " $5 " of " $2}'

echo ""
echo "=== Check Complete ==="
```

---

## Version

```
HEARTBEAT.md v1.1.0
PitchRank Repository
Last Updated: 2026-01-30
Changed: Reduced check frequencies to daily/weekly intervals
```
