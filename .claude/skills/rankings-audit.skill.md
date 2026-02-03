---
name: rankings-audit
description: Audit and investigate PitchRank ranking changes. Use when power scores shift unexpectedly, teams move dramatically in rankings, or ranking calculation seems wrong.
---

# Rankings Audit

## Quick Health Check
```bash
cd /Users/pitchrankio-dev/Projects/PitchRank && python3 scripts/orchestrator_status.py
```

## Key Tables

| Table | Purpose |
|-------|---------|
| `ranking_history` | Historical snapshots (team_id, snapshot_date, rank_in_cohort, power_score_final) |
| `current_rankings` | Latest rankings (national_rank, state_rank, games_played, SOS) |
| `games` | Game results (scores, dates, teams) |
| `teams` | Team info (name, club, state, age_group, gender) |

## Investigate a Team's Ranking

### Get Team's Ranking History
```sql
SELECT snapshot_date, rank_in_cohort, power_score_final, age_group, gender
FROM ranking_history
WHERE team_id = 'TEAM_UUID'
ORDER BY snapshot_date DESC
LIMIT 10;
```

### Find Team by Name
```sql
SELECT id, team_id_master, team_name, club_name, state_code, age_group, gender
FROM teams
WHERE team_name ILIKE '%search_term%'
LIMIT 10;
```

### Get Team's Recent Games
```sql
-- First get column names
SELECT column_name FROM information_schema.columns WHERE table_name = 'games';

-- Then query appropriately based on schema
```

## Common Issues

### 1. Cross-Cohort Comparison
**Symptom:** Team shows massive rank jump
**Cause:** Team changed age groups (e.g., u11 → u10)
**Check:**
```sql
SELECT snapshot_date, age_group, gender, rank_in_cohort
FROM ranking_history WHERE team_id = 'X'
ORDER BY snapshot_date DESC LIMIT 5;
```
**Fix:** Movers script should only compare same cohort

### 2. Stale Snapshot Comparison
**Symptom:** Movers comparing to 30+ day old data
**Cause:** Team missing from recent snapshots
**Check:** Look for gaps in snapshot_date
**Fix:** Enforce time window in comparison (7-14 days)

### 3. SOS Cascade
**Symptom:** Many teams in same state/league move together
**Cause:** Strength of Schedule recalculation when opponents' results change
**Verify:** Check if teams share common opponents
**Normal behavior** if opponents had significant results

### 4. PowerScore Swing
**Symptom:** PowerScore changes 20%+ between snapshots
**Possible causes:**
- New games imported (check games table)
- Opponent results changed (SOS effect)
- Algorithm update (check for code changes)
- Bad data imported (check quarantine)

## Cohort Sizes (Reference)
```sql
SELECT age_group, gender, COUNT(*) as team_count
FROM ranking_history
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ranking_history)
AND rank_in_cohort IS NOT NULL
GROUP BY age_group, gender
ORDER BY team_count DESC;
```

Typical sizes:
- u12 male: ~5000 teams
- u11 male: ~4500 teams
- u10 male: ~2300 teams

## Ranking Algorithm (v53e)
- PowerScore = weighted combination of win %, SOS, recent form
- ML Layer 13 adjustments for age-specific patterns
- State rankings = PowerScore rank within state+cohort
- National rankings = PowerScore rank across all states in cohort

## When to Escalate
- PowerScore swings > 30% with no games played
- Entire cohort shifts dramatically (possible algorithm bug)
- Rankings not updating (calculation failing)
- Duplicate teams affecting rankings
