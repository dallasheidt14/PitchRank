-- Check raw SOS values before normalization to see if many teams have the same value
-- This will help identify if the issue is with raw SOS calculation or normalization

SELECT 
    COUNT(*) as total_teams,
    COUNT(DISTINCT sos) as unique_raw_sos,
    COUNT(DISTINCT sos_norm) as unique_normalized_sos,
    MIN(sos) as min_raw_sos,
    MAX(sos) as max_raw_sos,
    AVG(sos) as avg_raw_sos,
    MIN(sos_norm) as min_sos_norm,
    MAX(sos_norm) as max_sos_norm,
    AVG(sos_norm) as avg_sos_norm
FROM rankings_full
WHERE age_group = 'u12' 
  AND gender = 'Male'
  AND power_score_final IS NOT NULL;

-- Sample teams showing raw SOS vs normalized SOS
SELECT 
    team_id,
    age_group,
    gender,
    power_score_final,
    sos as raw_sos,
    sos_norm as normalized_sos,
    rank_in_cohort
FROM rankings_full
WHERE age_group = 'u12' 
  AND gender = 'Male'
  AND power_score_final IS NOT NULL
ORDER BY power_score_final DESC
LIMIT 30;

-- Check how many teams share the same raw SOS value
SELECT 
    sos as raw_sos,
    COUNT(*) as team_count,
    MIN(sos_norm) as min_norm,
    MAX(sos_norm) as max_norm,
    COUNT(DISTINCT sos_norm) as unique_norm_values
FROM rankings_full
WHERE age_group = 'u12' 
  AND gender = 'Male'
  AND power_score_final IS NOT NULL
GROUP BY sos
HAVING COUNT(*) > 1
ORDER BY COUNT(*) DESC
LIMIT 20;

