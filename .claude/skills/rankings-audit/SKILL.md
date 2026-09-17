---
name: rankings-audit
description: Audit and investigate PitchRank ranking changes. Use when power scores shift unexpectedly, teams move dramatically in rankings, or ranking calculation seems wrong.
---

# Rankings Audit

## Quick Health Check
```bash
python scripts/orchestrator_status.py
```

## Key Tables

| Table | Purpose |
|-------|---------|
| `ranking_history` | Historical snapshots (team_id, snapshot_date, rank_in_cohort, power_score_final) |
| `current_rankings` | Latest rankings (national_rank, state_rank, games_played, SOS) |
| `games` | Game results (scores, dates, teams) |
| `teams` | Team info (name, club, state, age_group, gender) |
| `team_ranking_exclusions` | Teams kept off the boards — every game they played is dropped for both sides |

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

### 5. Sink Team (Placeholder Provider ID)
**Symptom:** `rank_in_cohort_final` swings by thousands between snapshots (e.g. #120 → #5,039 → #380), with hundreds of games a month against opponents from every age group
**Cause:** An approved `team_alias_map` row is keyed on `'None'`, the string a null opponent id becomes when stringified. Games carrying that id were attached to this team, through the import matcher or an admin link's backfill, and stay attached after the alias is fixed. The importer and matcher refuse `''`, `'None'` and `'null'` alike, so a sink found today holds games stored before those guards or written by a path that skips them.
**Check:**
```sql
-- Which provider id did the team's own side carry?
SELECT CASE WHEN home_team_master_id = 'X' THEN home_provider_id ELSE away_provider_id END AS side_id,
       count(*)
FROM games
WHERE home_team_master_id = 'X' OR away_team_master_id = 'X'
GROUP BY 1 ORDER BY 2 DESC;

-- Placeholder aliases, and how they were made
SELECT a.provider_id, a.provider_team_id, a.team_id_master, a.review_status,
       l.notes, l.games_updated, l.linked_at, l.reverted_at
FROM team_alias_map a
LEFT JOIN team_link_audit l
  ON l.provider_id = a.provider_id AND l.provider_team_id = a.provider_team_id
 AND l.team_id_master = a.team_id_master
WHERE lower(trim(a.provider_team_id)) IN ('', 'none', 'null');
```
Read provenance from `team_link_audit`, not `match_method`, which maintenance scripts relabel to `direct_id`.
- A link-opponent or create-team row means an admin linked it from the site. That action also filled every still-empty team slot carrying the id under the same provider, so games can predate the alias's `created_at`.
- A row with `reverted_at` set is an unlink.
- No row leaves the origin unknown: importers and scripts write aliases without one, and both site routes only log a failed audit insert.

**Fix:** For a GotSport alias, run `scripts/exclude_none_opponent_games.py`, which is a dry run unless given `--execute`. It rejects the alias and sets `is_excluded` on the games attached through the placeholder side. It refuses `--execute` when the exclusion trigger would also flip another game sharing a date, team pair and scores. For another provider, do the same by hand and count those twins first. A ranking rerun alone changes nothing.

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

## Ranking Algorithm (Glicko-2 + ML Layer 13)
- Two-pass Glicko-2 convergence per cohort, then SOS/SCF dampening and a within-cohort sigmoid → `powerscore_core`; the `rankings-algorithm` skill has the full pipeline
- ML Layer 13 residual adjustment (positive corrections gated by `sos_norm`, negative always full)
- State rankings = PowerScore rank within state+cohort
- National rankings = `rank_in_cohort_final` (`rankings_full.national_rank` is always NULL; views compute display ranks)

## When to Escalate
- PowerScore outside [0.0, 1.0]
- `sos_norm` > 0.95 for teams with < 12 games
- PowerScore swings > 30% with no games played
- Entire cohort shifts dramatically (possible algorithm bug)
- Rankings not updating (calculation failing)
- Duplicate teams affecting rankings
