# SQL Queries for Viewing Rankings

Useful SQL queries to explore and view rankings data in Supabase.

## Basic Queries

### 1. View National Rankings (Top 20)
```sql
SELECT 
    national_rank,
    team_name,
    club_name,
    state_code,
    age_group,
    gender,
    power_score_final,
    national_power_score,
    global_power_score,
    games_played,
    wins,
    losses,
    draws,
    win_percentage,
    strength_of_schedule,  -- Alias for sos (backward compatibility)
    sos,  -- Raw SOS value (0.0-1.0)
    sos_norm  -- Normalized SOS (percentile/z-score within cohort)
FROM rankings_view
ORDER BY national_rank
LIMIT 20;
```

### 2. View State Rankings (Top 20 by State)
```sql
SELECT 
    state_rank,
    national_rank,
    team_name,
    club_name,
    state_code,
    age_group,
    gender,
    power_score,
    power_score_final,
    games_played,
    wins,
    losses,
    strength_of_schedule
FROM state_rankings_view
WHERE state_code = 'CA'  -- Change to your state code
ORDER BY state_rank
LIMIT 20;
```

### 3. View Rankings by Age Group and Gender
```sql
SELECT 
    national_rank,
    team_name,
    age_group,
    gender,
    power_score_final,
    games_played,
    wins,
    losses,
    strength_of_schedule
FROM rankings_view
WHERE age_group = 'u12'
  AND gender = 'Male'
ORDER BY national_rank
LIMIT 50;
```

## Comprehensive Queries

### 4. View All Rankings with Full Details (Including Both SOS Values)
```sql
SELECT 
    rv.national_rank,
    rv.team_name,
    rv.club_name,
    rv.state_code,
    rv.age_group,
    rv.gender,
    rv.power_score_final,
    rv.national_power_score,
    rv.global_power_score,
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,
    rv.win_percentage,
    rv.strength_of_schedule,  -- Alias for sos
    rv.sos,  -- Raw SOS value (0.0-1.0, iteratively refined)
    rv.sos_norm,  -- Normalized SOS (percentile/z-score within cohort)
    rv.national_sos_rank,
    rf.powerscore_ml,
    rf.powerscore_adj,
    rf.powerscore_core,
    rf.ml_overperf,
    rf.off_raw,
    rf.def_norm
FROM rankings_view rv
LEFT JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rv.age_group = 'u12'
  AND rv.gender = 'Male'
ORDER BY rv.national_rank
LIMIT 50;
```

### 5. Compare National vs State Rankings
```sql
SELECT 
    srv.state_rank,
    srv.national_rank,
    srv.team_name,
    srv.state_code,
    srv.power_score_final,
    (srv.national_rank - srv.state_rank) as rank_difference
FROM state_rankings_view srv
WHERE srv.state_code = 'CA'
  AND srv.age_group = 'u12'
  AND srv.gender = 'Male'
ORDER BY srv.state_rank
LIMIT 20;
```

### 6. View Teams with Highest Power Scores
```sql
SELECT 
    national_rank,
    team_name,
    age_group,
    gender,
    power_score_final,
    national_power_score,
    global_power_score,
    games_played,
    strength_of_schedule
FROM rankings_view
ORDER BY power_score_final DESC
LIMIT 50;
```

### 7. View Teams by Strength of Schedule (Both SOS Values)
```sql
SELECT 
    national_sos_rank,
    national_rank,
    team_name,
    age_group,
    gender,
    strength_of_schedule,  -- Raw SOS (0.0-1.0)
    sos_norm,  -- Normalized SOS (percentile/z-score)
    power_score_final,
    games_played
FROM rankings_view
WHERE age_group = 'u12'
  AND gender = 'Male'
ORDER BY strength_of_schedule DESC NULLS LAST
LIMIT 50;
```

### 7b. Compare Raw vs Normalized SOS
```sql
SELECT 
    national_rank,
    team_name,
    age_group,
    gender,
    sos,  -- Raw SOS value
    sos_norm,  -- Normalized SOS
    (sos_norm - sos) as sos_difference,  -- Difference between normalized and raw
    strength_of_schedule,
    power_score_final
FROM rankings_view
WHERE age_group = 'u12'
  AND gender = 'Male'
  AND sos IS NOT NULL
  AND sos_norm IS NOT NULL
ORDER BY sos DESC
LIMIT 50;
```

## Analytics Queries

### 8. Count Teams by Age Group and Gender
```sql
SELECT 
    age_group,
    gender,
    COUNT(*) as team_count,
    AVG(power_score_final) as avg_power_score,
    AVG(games_played) as avg_games_played
FROM rankings_view
GROUP BY age_group, gender
ORDER BY age_group, gender;
```

### 9. View Rankings Distribution by State
```sql
SELECT 
    state_code,
    COUNT(*) as team_count,
    AVG(power_score_final) as avg_power_score,
    MAX(power_score_final) as max_power_score,
    MIN(power_score_final) as min_power_score
FROM rankings_view
WHERE state_code IS NOT NULL
GROUP BY state_code
ORDER BY avg_power_score DESC;
```

### 10. View Teams with Most Games Played
```sql
SELECT 
    national_rank,
    team_name,
    age_group,
    gender,
    games_played,
    wins,
    losses,
    draws,
    win_percentage,
    power_score_final
FROM rankings_view
ORDER BY games_played DESC
LIMIT 50;
```

## ML-Enhanced Rankings Queries

### 11. View ML-Adjusted Rankings
```sql
SELECT 
    rv.national_rank,
    rv.team_name,
    rv.age_group,
    rv.gender,
    rf.powerscore_ml as ml_power_score,
    rf.powerscore_adj as adjusted_power_score,
    rf.powerscore_core as core_power_score,
    rf.ml_overperf,
    rf.ml_norm,
    rv.power_score_final,
    rv.games_played
FROM rankings_view rv
LEFT JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rf.powerscore_ml IS NOT NULL
ORDER BY rf.powerscore_ml DESC
LIMIT 50;
```

### 12. Compare ML vs Non-ML Rankings
```sql
SELECT 
    rv.national_rank,
    rv.team_name,
    rf.powerscore_ml,
    rf.powerscore_adj,
    (rf.powerscore_ml - rf.powerscore_adj) as ml_adjustment,
    rf.ml_overperf,
    rv.power_score_final
FROM rankings_view rv
LEFT JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rf.powerscore_ml IS NOT NULL
  AND rv.age_group = 'u12'
  AND rv.gender = 'Male'
ORDER BY rf.powerscore_ml DESC
LIMIT 50;
```

## Search Queries

### 13. Search for a Specific Team
```sql
SELECT 
    national_rank,
    state_rank,
    team_name,
    club_name,
    state_code,
    age_group,
    gender,
    power_score_final,
    games_played,
    wins,
    losses,
    strength_of_schedule
FROM rankings_view
WHERE team_name ILIKE '%team_name_here%'  -- Replace with actual team name
   OR club_name ILIKE '%club_name_here%';
```

### 14. View All Teams in a Specific State
```sql
SELECT 
    state_rank,
    national_rank,
    team_name,
    club_name,
    age_group,
    gender,
    power_score_final,
    games_played
FROM state_rankings_view
WHERE state_code = 'CA'  -- Change to your state
ORDER BY age_group, gender, state_rank;
```

## Quick Reference Queries

### 15. Top 10 Teams Overall
```sql
SELECT 
    national_rank,
    team_name,
    age_group,
    gender,
    power_score_final,
    games_played
FROM rankings_view
ORDER BY power_score_final DESC
LIMIT 10;
```

### 16. Top 10 Teams by State
```sql
SELECT 
    state_rank,
    team_name,
    state_code,
    age_group,
    gender,
    power_score,
    games_played
FROM state_rankings_view
WHERE state_code = 'CA'  -- Change to your state
ORDER BY power_score DESC
LIMIT 10;
```

### 17. View Rankings Summary Statistics
```sql
SELECT 
    COUNT(*) as total_teams,
    COUNT(DISTINCT age_group) as age_groups,
    COUNT(DISTINCT state_code) as states,
    AVG(power_score_final) as avg_power_score,
    MAX(power_score_final) as max_power_score,
    MIN(power_score_final) as min_power_score,
    AVG(games_played) as avg_games_played
FROM rankings_view;
```

## Using in Supabase

1. **Supabase Dashboard**: Go to SQL Editor and paste any query
2. **Filter Parameters**: Replace values like `'CA'`, `'u12'`, `'Male'` with your desired filters
3. **Limit Results**: Adjust `LIMIT` values to get more/fewer results

## Tips

- Use `rankings_view` for national rankings
- Use `state_rankings_view` for state-specific rankings
- Join with `rankings_full` to see comprehensive v53E + ML data
- Use `power_score_final` for the most accurate ranking (ML > global > adj > national)
- Use `power_score` alias in `state_rankings_view` for state rankings ordering

