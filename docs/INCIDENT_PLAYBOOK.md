# Incident Playbook

> When things break, don't improvise. Follow this.

## 🔴 CRITICAL — Drop Everything

### Rankings Not Updating (>24h stale)
```
1. Check: Is calculate_rankings.py failing?
   cd /Users/pitchrankio-dev/Projects/PitchRank && python3 scripts/calculate_rankings.py --dry-run

2. Check: DB connection working?
   python3 -c "import psycopg2; from dotenv import load_dotenv; import os; load_dotenv('.env'); psycopg2.connect(os.getenv('DATABASE_URL'))"

3. Check: Ranky cron status
   → cron action=list → look for Ranky lastStatus

4. If code error → Spawn Codey with full traceback
5. If DB error → Check Supabase status page: status.supabase.com
6. If still stuck → Alert D H with findings
```

### Zero Games Importing for 48h+
```
1. Check: Are scrapers running?
   gh run list --repo dallasheidt14/PitchRank --limit 10

2. Check: Quarantine backing up?
   SELECT COUNT(*) FROM quarantine_games;

3. Check: Provider APIs responding?
   curl -s "https://system.gotsport.com" | head -5
   
4. If scraper broken → Spawn Codey
5. If provider down → Wait and document in DAILY_CONTEXT.md
6. If unknown → Alert D H
```

### Database Connection Failing
```
1. Check Supabase status: status.supabase.com
2. Check .env has DATABASE_URL
3. Test connection manually (see above)
4. If Supabase down → Wait, document downtime
5. If credentials issue → Alert D H (don't try to fix auth)
6. If connection pool exhausted → Restart gateway, reduce concurrent jobs
```

### Multiple Agents Failing Same Day
```
1. Check: Common error across failures?
   → cron action=list → check lastError on each

2. Common causes:
   - API key issue → Check billing/credits
   - Model name wrong → Fix to pinned version
   - Shared script broken → Spawn Codey

3. If pattern found → Fix root cause
4. If unclear → Alert D H with failure summary
```

---

## 🟡 WARNING — Handle Within 4 Hours

### Import Taking >3x Normal Time
```
Normal baselines (see Performance Baselines below):
- TGS 10 events: ~30 min (after fix), currently 5-6h
- GotSport event: ~10 min
- Rankings calc: ~15-20 min

If >3x baseline:
1. Check if data volume unusually high
2. Check for infinite loops in logs
3. If code issue → Spawn Codey to profile
4. If just slow → Let it finish, investigate after
```

### Quarantine >1000 Games
```
1. Analyze pattern:
   SELECT age_group, COUNT(*) FROM quarantine_games GROUP BY age_group ORDER BY 2 DESC;

2. If single age group (e.g., U8):
   → Policy decision, ask D H if we support this age

3. If mixed ages:
   → Team matching issue, check team_match_review_queue

4. If provider-specific:
   → Check if provider format changed
```

### GitHub Action Failing Repeatedly
```
1. Check the error:
   gh run view <run_id> --repo dallasheidt14/PitchRank --log | tail -100

2. Common fixes:
   - Timeout → Split into smaller batches
   - Dependency error → Update requirements.txt
   - Script error → Spawn Codey

3. If >3 consecutive failures → Alert D H
```

### Cron Job Stuck/Skipped
```
1. Check cron status:
   → cron action=list → find the job

2. If lastStatus: "error":
   → Check lastError message
   → Fix per DECISION_TREES.md

3. If lastStatus: "skipped":
   → Usually intentional (e.g., pre-flight OK)
   → Check if expected

4. If stuck in "running" for >2x normal:
   → May need manual intervention
```

---

## 🟢 LOW — Handle Within 24 Hours

### Stale Teams Count Growing
```
Normal: ~10-15k stale teams
Warning: >20k stale teams

1. Check when Scrappy last ran successfully
2. If Scrappy failing → Fix that first
3. If Scrappy running but not covering all teams:
   → May need to expand scrape scope
   → Document in DAILY_CONTEXT.md for D H
```

### Data Quality Metrics Drifting
```
Baselines:
- Missing state_code: ~1,000 is normal
- Missing club_name: ~3,500 is normal
- Teams without club: <500 is normal

If drifting up:
1. Check recent imports for bad data
2. Check if new provider added without proper mapping
3. Add to Cleany's next run scope
```

---

## 📊 Performance Baselines

| Operation | Normal | Warning | Critical |
|-----------|--------|---------|----------|
| TGS import (10 events) | 30 min* | >1h | >3h |
| GotSport event scrape | 10 min | >30 min | >1h |
| Rankings calculation | 15-20 min | >45 min | >2h |
| Watchy health check | <1 min | >3 min | >10 min |
| Weekly merge job | 5-10 min | >30 min | >1h |

*After implementing batch team creation fix

---

## 📞 Escalation

**Always escalate to D H:**
- Anything affecting live site rankings
- Data corruption or loss
- Security/auth issues
- Multiple systems failing
- You're stuck after 30 min of debugging

**Handle autonomously:**
- Single cron failure with clear fix
- Config issues (model names, etc.)
- Transient errors that resolve on retry

---

## 🔄 Post-Incident

After any WARNING or CRITICAL incident:
1. Update DAILY_CONTEXT.md with what happened
2. Add new pattern to DECISION_TREES.md if applicable
3. Log in memory/YYYY-MM-DD.md
4. Consider: Could this have been prevented? Detected earlier?

---

*Last updated: 2026-02-07 by Moltbot*
