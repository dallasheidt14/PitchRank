# Data Quality Checklist

Quick reference for Cleany and other data hygiene tasks.

## Weekly Checks (Cleany runs Sundays)

### 1. Club Name Case Normalization
```sql
-- Find clubs with inconsistent casing
SELECT club_name, COUNT(*) as team_count
FROM teams
WHERE club_name != INITCAP(club_name)
  AND club_name !~ '^[A-Z]{2,}$'  -- Skip all-caps abbreviations
GROUP BY club_name
HAVING COUNT(*) > 5
ORDER BY team_count DESC;
```
**Rule:** Use majority casing, prefer proper case.

### 2. Team Name Normalization
Common fixes:
- `14B` → `2014` (birth year, strip gender)
- `U14B` → `U14` (age group, strip gender)
- `G2016` → `2016` (birth year, strip gender prefix)
- `Boys` / `Girls` → remove (tracked in gender field)

### 3. Duplicate Teams
```sql
-- Find potential duplicates (same club, similar name)
SELECT club_name, team_name, COUNT(*) 
FROM teams 
GROUP BY club_name, team_name 
HAVING COUNT(*) > 1;
```
**Merge criteria:** Same club + normalized name + same age_group + same gender

### 4. Missing State Codes
```sql
SELECT COUNT(*) FROM teams WHERE state_code IS NULL;
```
**Fix:** Infer from club_name patterns or mark for review.

### 5. Orphaned Records
```sql
-- Games referencing non-existent teams
SELECT COUNT(*) FROM games g
LEFT JOIN teams t ON g.home_team_id = t.id
WHERE t.id IS NULL;
```

## Known Patterns

### Regional Clubs (DON'T MERGE)
- "FC Dallas East" vs "FC Dallas North" = Different clubs
- "Solar SC 08B" vs "Solar SC 09B" = Different age groups

### Safe Merges
- Case differences: "SOLAR SC" → "Solar SC"
- Punctuation: "FC Dallas - 14B" → "FC Dallas 14B"
- Common abbreviations: "Soccer Club" ↔ "SC"

### Needs Review
- Name variations: "Dallas Texans" vs "Texans SC"
- Year ambiguity: "12B" could be 2012 or U12
- Division markers: "Academy" vs "ECNL" vs "MLS Next"

## Automation Scripts
- `scripts/run_weekly_cleany.py` — Full weekly cleanup
- `scripts/club_name_normalizer.py` — Club case fixes
- `scripts/team_name_normalizer.py` — Team name parsing
- `scripts/find_duplicates.py` — Duplicate detection
