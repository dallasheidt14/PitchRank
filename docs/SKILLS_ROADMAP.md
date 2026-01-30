# SKILLS_ROADMAP.md — Missing Capabilities for Sub-Agents

> This document identifies **READ-ONLY monitoring scripts** that would make PitchRank's sub-agents more effective.

---

## ⚠️ IMPORTANT: Design Principles

```
1. NO MODIFICATIONS to existing pipelines
2. NO CHANGES to team matching logic
3. NO CHANGES to alias matching
4. NO CHANGES to Cleany (it's perfect as-is)
5. All new skills are READ-ONLY observers
6. Skills report status, they don't fix things
```

---

## Current State Summary

| Agent | Core Skills | Status |
|-------|-------------|--------|
| **Cleany** | Dedup, normalize, merge, validate | ✅ PERFECT - DO NOT MODIFY |
| **Scrappy** | GotSport, TGS, event discovery | ✅ Working - needs monitoring |
| **Ranky** | v53e, ML Layer 13, SOS | ✅ Working - needs monitoring |
| **Watchy** | Health checks | ⚠️ Manual - needs automation |

---

## 1. CLEANY — No Changes

### Status: ✅ COMPLETE

Cleany is production-ready with:
- 100% merge success rate (1,286 merges, 0 failures)
- Conservative thresholds (won't over-merge)
- Full audit trail + reversibility
- Division conflict detection

**DO NOT add new functionality to Cleany.**

---

## 2. SCRAPPY — Read-Only Monitoring Skills

> These skills **observe** scraper health. They do NOT modify scraping logic, team matching, or alias handling.

### 2.1 Scraper Connectivity Test (READ-ONLY)
**What**: Simple HTTP check if target sites are reachable
**Touches**: Nothing - just checks URLs are up
**Safe**: ✅ YES - read-only HTTP HEAD requests

```python
# scripts/test_scrapers.py
# Does NOT use any scraper logic - just checks site availability
def test_connectivity():
    """
    Simple connectivity check:
    - HEAD request to gotsport.com
    - HEAD request to tgs site
    Returns: up/down status only
    """
    pass
```

### 2.2 Provider Status Report (READ-ONLY)
**What**: Query database for scraper metrics
**Touches**: SELECT queries only
**Safe**: ✅ YES - read-only database queries

```python
# scripts/provider_status.py
# Queries existing data, does not modify anything
def get_provider_status():
    """
    SELECT-only queries:
    - Last scraped_at per provider
    - Game count last 7 days
    - Team count per provider
    """
    pass
```

### 2.3 Scrape Delta Report (READ-ONLY)
**What**: Compare two scrape output files (JSON/CSV)
**Touches**: Local files only, no database
**Safe**: ✅ YES - file comparison only

```python
# scripts/scrape_delta.py
# Compares two local files, no DB writes
def compare_scrape_files(file_a, file_b):
    """
    File comparison only:
    - Count difference
    - New team IDs found
    - Missing team IDs
    Does NOT import or modify anything
    """
    pass
```

---

## 3. RANKY — Read-Only Monitoring Skills

> These skills **observe** ranking outputs. They do NOT modify calculation logic.

### 3.1 Rankings Diff Report (READ-ONLY)
**What**: Compare current rankings to previous snapshot
**Touches**: SELECT queries only
**Safe**: ✅ YES - read-only analysis

```python
# scripts/rankings_diff.py
# SELECT-only comparison of ranking snapshots
def compare_rankings():
    """
    Read-only analysis:
    - Top movers up/down
    - New teams in top 100
    - PowerScore distribution
    Does NOT recalculate anything
    """
    pass
```

### 3.2 Coverage Report (READ-ONLY)
**What**: Show data coverage by cohort
**Touches**: SELECT queries only
**Safe**: ✅ YES - read-only aggregation

```python
# scripts/coverage_report.py
# Aggregate queries only
def coverage_by_cohort():
    """
    SELECT COUNT(*) style queries:
    - Teams per state/age/gender
    - Average games per team
    - Teams with <5 games
    """
    pass
```

---

## 4. WATCHY — Monitoring Automation Skills

> These skills **automate HEARTBEAT.md checks**. They report status, they don't fix problems.

### 4.1 Heartbeat Runner (READ-ONLY)
**What**: Execute all documented health checks
**Touches**: SELECT queries, file reads, `git status`
**Safe**: ✅ YES - read-only checks

```python
# scripts/run_heartbeat.py
# Runs checks defined in HEARTBEAT.md
def run_all_checks():
    """
    Read-only checks:
    - Supabase connectivity (SELECT 1)
    - File freshness (stat files)
    - Git status (read-only)
    - Log file sizes

    Outputs to: logs/heartbeat.log
    Does NOT fix anything - just reports
    """
    pass
```

### 4.2 Workflow Monitor (READ-ONLY)
**What**: Check GitHub Actions status via CLI
**Touches**: `gh run list` command only
**Safe**: ✅ YES - read-only GitHub API

```python
# scripts/check_workflows.py
# Uses gh CLI to read workflow status
def check_workflows():
    """
    gh run list --json (read-only)
    Reports: pass/fail status
    Does NOT trigger or modify workflows
    """
    pass
```

### 4.3 Log Analyzer (READ-ONLY)
**What**: Parse log files for error patterns
**Touches**: Log files (read-only)
**Safe**: ✅ YES - file reading only

```python
# scripts/analyze_logs.py
# Grep through log files
def analyze_logs():
    """
    Read log files and count:
    - Errors by type
    - Exception frequency
    - Warning patterns
    Does NOT modify logs
    """
    pass
```

### 4.4 Alert Dispatcher (NOTIFICATION ONLY)
**What**: Send alerts to configured channels
**Touches**: External services (Slack, GitHub Issues)
**Safe**: ✅ YES - outbound notifications only

```python
# scripts/alert.py
# Sends notifications, does not modify PitchRank data
def send_alert(level, message):
    """
    Outbound only:
    - Write to logs/heartbeat.log
    - Create GitHub issue (optional)
    - Send webhook (optional)
    Does NOT modify any PitchRank data
    """
    pass
```

---

## Priority Matrix (Read-Only Skills Only)

| Skill | Agent | Type | Priority |
|-------|-------|------|----------|
| `run_heartbeat.py` | Watchy | Read-only checks | 🔴 HIGH |
| `check_workflows.py` | Watchy | Read-only API | 🔴 HIGH |
| `test_scrapers.py` | Scrappy | Read-only HTTP | 🔴 HIGH |
| `alert.py` | Watchy | Outbound only | 🟡 MEDIUM |
| `analyze_logs.py` | Watchy | Read-only files | 🟡 MEDIUM |
| `provider_status.py` | Scrappy | Read-only DB | 🟡 MEDIUM |
| `rankings_diff.py` | Ranky | Read-only DB | 🟢 LOW |
| `coverage_report.py` | Ranky | Read-only DB | 🟢 LOW |

---

## What These Skills Do NOT Touch

```
❌ Team matching logic (src/utils/merge_suggester.py)
❌ Alias matching (team_alias_map table)
❌ ETL pipeline (src/etl/)
❌ Scraper logic (src/scrapers/)
❌ Rankings calculation (src/rankings/)
❌ Cleany scripts (scripts/run_all_merges.py, etc.)
❌ Database writes of any kind
```

---

## Implementation Safety Rules

When building any skill:

1. **No imports from src/etl/** — Don't touch pipeline
2. **No imports from src/scrapers/** — Don't touch scraping
3. **No imports from src/rankings/** — Don't touch calculations
4. **No Supabase `.insert()`, `.update()`, `.delete()`** — Read-only
5. **No `git commit`, `git push`** — Observation only
6. **All database queries must be SELECT** — No modifications

---

## Version

```
SKILLS_ROADMAP.md v1.1.0
Last Updated: 2026-01-30
Note: Removed all Cleany modifications per owner request
```
