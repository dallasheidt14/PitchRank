# SKILLS_ROADMAP.md — Missing Capabilities for Sub-Agents

> This document identifies scripts and tools that would make PitchRank's sub-agents more effective.

---

## Current State Summary

| Agent | Core Skills | Completeness |
|-------|-------------|--------------|
| **Cleany** | Dedup, normalize, merge, validate | 95% ✅ |
| **Scrappy** | GotSport, TGS, event discovery | 80% |
| **Ranky** | v53e, ML Layer 13, SOS | 90% |
| **Watchy** | Health checks (manual) | 60% |

---

## 1. CLEANY — Missing Skills

### ✅ Already Strong
- Duplicate detection (100% success rate)
- Team name normalization
- Merge execution with audit trail
- Revert capability

### 🟡 Would Be Nice

#### 1.1 Quarantine Auto-Resolver
**What**: Script to automatically resolve low-confidence quarantine entries
**Why**: Quarantine backlog grows faster than manual review
**Effort**: Medium

```python
# Proposed: scripts/resolve_quarantine.py
def auto_resolve_quarantine(min_confidence=0.95):
    """
    Auto-resolve quarantine entries where:
    - Fuzzy match score >= 95%
    - Same state, age, gender
    - No division conflicts
    """
    pass
```

#### 1.2 Club Canonicalization Script
**What**: Batch update teams with normalized club names
**Why**: `club_normalizer.py` exists but no script applies it
**Effort**: Low

```python
# Proposed: scripts/apply_club_normalization.py
def normalize_all_clubs(dry_run=True):
    """Apply club_normalizer to all teams, update club_name field"""
    pass
```

#### 1.3 Merge Undo Dashboard
**What**: CLI tool to quickly revert recent merges
**Why**: `revert_team_merge()` exists but no convenient wrapper
**Effort**: Low

```bash
# Proposed: scripts/undo_merge.py
python undo_merge.py --merge-id <uuid>
python undo_merge.py --team-id <deprecated_team_id>
python undo_merge.py --last 5  # Undo last 5 merges
```

---

## 2. SCRAPPY — Missing Skills

### ✅ Already Strong
- GotSport team scraping
- Event discovery
- Rate limiting

### 🔴 Critical Gaps

#### 2.1 Scraper Health Monitor
**What**: Script to test if scrapers can reach target sites
**Why**: Silent failures when site structure changes
**Effort**: Low

```python
# Proposed: scripts/test_scrapers.py
def test_all_scrapers():
    """
    Quick connectivity test for all scrapers:
    - GotSport: Can fetch team page?
    - TGS: Can fetch event list?
    - Returns: {scraper: status, error}
    """
    pass
```

#### 2.2 Scrape Delta Reporter
**What**: Compare this week's scrape to last week
**Why**: Detect anomalies (sudden drop in games, missing teams)
**Effort**: Medium

```python
# Proposed: scripts/scrape_delta.py
def compare_scrapes(current_file, previous_file):
    """
    Report:
    - New teams found
    - Teams with no new games
    - Games count change (%)
    - Missing expected events
    """
    pass
```

#### 2.3 Provider Status Dashboard
**What**: Single view of all provider health
**Why**: Currently need to check multiple logs
**Effort**: Medium

```python
# Proposed: scripts/provider_status.py
def get_all_provider_status():
    """
    Returns for each provider:
    - Last successful scrape
    - Games scraped (last 7 days)
    - Error count
    - Health status (OK/WARNING/CRITICAL)
    """
    pass
```

### 🟡 Would Be Nice

#### 2.4 Event Auto-Discovery
**What**: Automatically find new GotSport event IDs to scrape
**Why**: Currently hardcoded ranges (4050-4150 for TGS)
**Effort**: High

#### 2.5 Retry Queue
**What**: Track failed scrapes and auto-retry
**Why**: Transient failures currently lost
**Effort**: Medium

---

## 3. RANKY — Missing Skills

### ✅ Already Strong
- v53e calculation
- ML Layer 13
- SOS iterations
- Merge resolution

### 🟡 Would Be Nice

#### 3.1 Rankings Diff Report
**What**: Compare current rankings to previous week
**Why**: Detect unexpected rank changes (data quality signal)
**Effort**: Low

```python
# Proposed: scripts/rankings_diff.py
def compare_rankings(current_date, previous_date):
    """
    Report:
    - Biggest movers (up/down)
    - New teams in top 100
    - Teams dropped from rankings
    - PowerScore distribution change
    """
    pass
```

#### 3.2 Rankings Backtest Tool
**What**: Test ranking changes against historical data
**Why**: Validate algorithm changes before production
**Effort**: Medium (partial exists in `data/backtest_results/`)

#### 3.3 Cohort Coverage Report
**What**: Identify age/gender/state combinations with thin data
**Why**: Rankings less reliable with few games
**Effort**: Low

```python
# Proposed: scripts/coverage_report.py
def coverage_by_cohort():
    """
    For each state/age/gender:
    - Team count
    - Average games per team
    - Teams with <5 games (unreliable rankings)
    """
    pass
```

---

## 4. WATCHY — Missing Skills

### 🔴 Critical Gaps (Biggest Need)

#### 4.1 Automated Heartbeat Runner
**What**: Script that runs all HEARTBEAT.md checks
**Why**: Currently checks are documented but not automated
**Effort**: Medium

```python
# Proposed: scripts/run_heartbeat.py
def run_all_checks():
    """
    Execute all HEARTBEAT.md checks:
    1. Database health
    2. Scraper status
    3. File freshness
    4. Repository state
    5. etc.

    Returns: {check: status, details}
    Outputs: logs/heartbeat.log
    """
    pass
```

#### 4.2 Alert Dispatcher
**What**: Send alerts to configured channels
**Why**: Currently no alerting beyond logs
**Effort**: Medium

```python
# Proposed: scripts/alert.py
def send_alert(level, message, details):
    """
    Dispatch alert to configured channels:
    - Log file (always)
    - GitHub issue (if critical)
    - Webhook (Slack/Discord)
    - Email (if configured)
    """
    pass
```

#### 4.3 Log Analyzer
**What**: Parse logs for error patterns
**Why**: Currently manual grep through large logs
**Effort**: Low

```python
# Proposed: scripts/analyze_logs.py
def analyze_recent_logs(hours=24):
    """
    Scan logs and report:
    - Error count by type
    - Most common exceptions
    - Warnings that might need attention
    - Anomalous patterns
    """
    pass
```

#### 4.4 Workflow Monitor
**What**: Check GitHub Actions status programmatically
**Why**: Watchy needs to know if workflows failed
**Effort**: Low

```python
# Proposed: scripts/check_workflows.py
def get_workflow_status():
    """
    Query GitHub API for recent workflow runs:
    - Last success/failure per workflow
    - Failure rate (7 days)
    - Currently running jobs
    """
    # Uses: gh run list --json
    pass
```

---

## Priority Matrix

| Skill | Agent | Priority | Effort | Impact |
|-------|-------|----------|--------|--------|
| Automated Heartbeat Runner | Watchy | 🔴 HIGH | Medium | Enables autonomous monitoring |
| Alert Dispatcher | Watchy | 🔴 HIGH | Medium | Makes monitoring actionable |
| Scraper Health Monitor | Scrappy | 🔴 HIGH | Low | Early failure detection |
| Workflow Monitor | Watchy | 🟡 MEDIUM | Low | CI/CD visibility |
| Log Analyzer | Watchy | 🟡 MEDIUM | Low | Faster debugging |
| Rankings Diff Report | Ranky | 🟡 MEDIUM | Low | Quality assurance |
| Quarantine Auto-Resolver | Cleany | 🟡 MEDIUM | Medium | Reduce manual work |
| Provider Status Dashboard | Scrappy | 🟡 MEDIUM | Medium | Single pane of glass |
| Club Canonicalization | Cleany | 🟢 LOW | Low | Data quality |
| Scrape Delta Reporter | Scrappy | 🟢 LOW | Medium | Anomaly detection |
| Coverage Report | Ranky | 🟢 LOW | Low | Data quality insight |

---

## Recommended Implementation Order

### Phase 1: Enable Watchy (1-2 days)
```
1. run_heartbeat.py      — Run all health checks
2. alert.py              — Dispatch alerts
3. check_workflows.py    — GitHub Actions status
```

**Result**: Watchy becomes fully autonomous

### Phase 2: Strengthen Scrappy (1 day)
```
4. test_scrapers.py      — Connectivity tests
5. provider_status.py    — Dashboard view
```

**Result**: Early detection of scraper issues

### Phase 3: Enhance Cleany (1 day)
```
6. resolve_quarantine.py — Auto-resolve high-confidence
7. apply_club_normalization.py — Batch normalize
```

**Result**: Reduced manual data hygiene work

### Phase 4: Polish Ranky (1 day)
```
8. rankings_diff.py      — Week-over-week comparison
9. coverage_report.py    — Data coverage analysis
```

**Result**: Better quality assurance

---

## Quick Wins (Can Build Today)

### 1. `scripts/quick_health.sh` (exists in HEARTBEAT.md)
Already documented — just needs to be a real executable file.

### 2. `scripts/check_workflows.py`
```python
#!/usr/bin/env python3
import subprocess
import json

def check_workflows():
    result = subprocess.run(
        ['gh', 'run', 'list', '--limit', '10', '--json', 'name,status,conclusion'],
        capture_output=True, text=True
    )
    runs = json.loads(result.stdout)

    failures = [r for r in runs if r['conclusion'] == 'failure']
    if failures:
        print(f"⚠️  {len(failures)} recent failures:")
        for f in failures:
            print(f"   - {f['name']}")
    else:
        print("✅ All recent workflows passed")

if __name__ == '__main__':
    check_workflows()
```

### 3. `scripts/test_scrapers.py`
```python
#!/usr/bin/env python3
import requests

TARGETS = {
    'gotsport': 'https://www.gotsport.com',
    'tgs': 'https://tgs.totalglobalsports.com',
}

def test_scrapers():
    for name, url in TARGETS.items():
        try:
            r = requests.head(url, timeout=10)
            status = "✅" if r.status_code == 200 else f"⚠️ {r.status_code}"
        except Exception as e:
            status = f"❌ {e}"
        print(f"{name}: {status}")

if __name__ == '__main__':
    test_scrapers()
```

---

## Version

```
SKILLS_ROADMAP.md v1.0.0
Last Updated: 2026-01-30
```
