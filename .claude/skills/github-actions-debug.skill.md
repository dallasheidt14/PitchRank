---
name: github-actions-debug
description: Debug GitHub Actions workflow failures for PitchRank. Use when investigating CI/CD errors, workflow timeouts, or runner issues.
---

# GitHub Actions Debug

## Quick Diagnosis

### List Recent Runs
```bash
gh run list --repo dallasheidt14/PitchRank --limit 10 --json status,conclusion,name,databaseId
```

### View Failed Run
```bash
gh run view <run-id> --repo dallasheidt14/PitchRank
```

### Get Failed Logs
```bash
gh run view <run-id> --repo dallasheidt14/PitchRank --log-failed
```

## Common Failure Patterns

### 1. Runner Not Acquired
**Error:** "The job was not acquired by Runner of type hosted"
**Cause:** GitHub infrastructure issue
**Fix:** Wait and retry, or check https://githubstatus.com
**Not a code issue!**

### 2. Timeout
**Error:** Job cancelled after X hours
**Cause:** Workflow exceeds timeout limit
**Fix:** Increase timeout in workflow YAML or optimize script
```yaml
jobs:
  process:
    timeout-minutes: 360  # 6 hours max for GitHub
```

### 3. Rate Limit
**Error:** API rate limit exceeded
**Cause:** Too many API calls to external service
**Fix:** Add delays, reduce concurrency, or batch requests

### 4. Out of Memory
**Error:** Process killed / OOM
**Cause:** Large dataset processing
**Fix:** Use streaming, pagination, or smaller batches

### 5. Missing Secrets
**Error:** Secret not found / empty variable
**Cause:** Secret not configured in repo settings
**Fix:** Add secret via GitHub UI: Settings → Secrets → Actions

## PitchRank Workflows

| Workflow | Schedule | Typical Duration | Timeout |
|----------|----------|------------------|---------|
| Scrape Games | Mon 6am, 11:15am UTC | 2-4h | 360min |
| Process Missing Games | Hourly | 5-15min | 30min |
| Calculate Rankings | Mon 7pm UTC | 15-30min | 60min |
| TGS Event Scrape | Sun 11:30pm | 3-4h | 360min |

## Workflow Files
Location: `/Users/pitchrankio-dev/Projects/PitchRank/.github/workflows/`

- `scrape-games.yml` - Team game scraping
- `process-missing-games.yml` - Missing games backfill
- `calculate-rankings.yml` - Weekly rankings
- `tgs-event-scrape.yml` - TGS tournament scraping

## Re-run Commands
```bash
# Re-run failed jobs only
gh run rerun <run-id> --repo dallasheidt14/PitchRank --failed

# Re-run entire workflow
gh run rerun <run-id> --repo dallasheidt14/PitchRank

# Manually trigger workflow
gh workflow run "Workflow Name" --repo dallasheidt14/PitchRank

# With inputs
gh workflow run "Scrape Games" --repo dallasheidt14/PitchRank -f limit_teams=25000
```

## When to Escalate
- Same workflow fails 3+ times consecutively
- Failure is in core logic (not infra)
- Multiple workflows failing simultaneously
- Need to modify workflow YAML significantly
