-- Test if rankings_view is returning sos_norm correctly
-- This will show if the view is working properly

-- Check a specific cohort (U12 Male) to see if values vary
SELECT 
    team_name,
    age,
    gender,
    power_score_final,
    sos_norm,
    offense_norm,
    defense_norm,
    rank_in_cohort_final
FROM rankings_view
WHERE age = 12 
  AND gender = 'M'
ORDER BY power_score_final DESC
LIMIT 20;

-- Check statistics for this cohort
SELECT 
    COUNT(*) as total_teams,
    COUNT(DISTINCT sos_norm) as unique_sos_norm,
    MIN(sos_norm) as min_sos,
    MAX(sos_norm) as max_sos,
    AVG(sos_norm) as avg_sos
FROM rankings_view
WHERE age = 12 
  AND gender = 'M';

