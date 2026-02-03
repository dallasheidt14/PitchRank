# Metrics Baseline

Reference for Watchy and system health monitoring.

## Normal Ranges

| Metric | Normal | Warning | Critical |
|--------|--------|---------|----------|
| Games/24h | 1,000 - 10,000 | < 500 | 0 |
| Quarantine | < 500 | 500 - 1,000 | > 1,000 |
| Stale Teams | < 30,000 | 30,000 - 50,000 | > 50,000 |
| Pending Reviews | < 10,000 | 10,000 - 20,000 | > 20,000 |
| Total Teams | ~100,000 | ±10% change | ±20% change |
| Total Games | ~680,000 | ±5% daily | ±10% daily |

## Scraping Health

| Source | Expected Frequency | Typical Games/Run |
|--------|-------------------|-------------------|
| GotSport | Daily | 500 - 2,000 |
| TGS | Sunday nights | 2,000 - 5,000 |
| ECNL | Weekly | 500 - 1,500 |

## GitHub Actions

| Workflow | Expected Duration | Max Timeout |
|----------|------------------|-------------|
| Scrape Games | 2-4 hours | 6 hours |
| Process Missing | 5-15 min | 30 min |
| Calculate Rankings | 15-30 min | 60 min |
| TGS Scrape | 3-4 hours | 6 hours |

## Database Size Trends
- Teams: +500-1000/week (new teams discovered)
- Games: +5,000-15,000/week (depending on season)
- Rankings snapshots: 1/day when calculated

## Alert Response Guide

### Games = 0 in 24h
1. Check GitHub Actions for failures
2. Check if it's a holiday/off-season
3. Verify database connectivity
4. Alert D H if unexplained

### High Quarantine (>1000)
1. Check recent error patterns
2. If mostly "empty scores" → likely scheduled games imported wrong
3. If mostly "invalid age" → new age groups being scraped
4. Can often bulk delete if non-critical

### Stale Teams (>50,000)
1. Check if Scrape Games workflow is running
2. Verify last_scraped_at is being updated
3. May need to trigger manual scrape with higher limit

### Cron Agent Failed
1. Check model name (common issue)
2. Check if script exists
3. Look at error message in cron state
4. Fix and re-test manually
