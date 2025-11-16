-- Test to see if sos_norm values vary across different ranks
-- This will help identify if only top teams have the same value (expected)
-- or if ALL teams have the same value (problem)

-- Get teams across different rank ranges
WITH ranked_teams AS (
    SELECT 
        rank_in_cohort_final,
        sos_norm,
        CASE 
            WHEN rank_in_cohort_final <= 20 THEN 'Top 20'
            WHEN rank_in_cohort_final <= 100 THEN '21-100'
            WHEN rank_in_cohort_final <= 500 THEN '101-500'
            WHEN rank_in_cohort_final <= 1000 THEN '501-1000'
            ELSE '1000+'
        END as rank_range,
        CASE 
            WHEN rank_in_cohort_final <= 20 THEN 1
            WHEN rank_in_cohort_final <= 100 THEN 2
            WHEN rank_in_cohort_final <= 500 THEN 3
            WHEN rank_in_cohort_final <= 1000 THEN 4
            ELSE 5
        END as sort_order
    FROM rankings_view
    WHERE age = 12 
      AND gender = 'M'
)
SELECT 
    rank_range,
    COUNT(*) as team_count,
    COUNT(DISTINCT sos_norm) as unique_sos_values,
    MIN(sos_norm) as min_sos,
    MAX(sos_norm) as max_sos,
    AVG(sos_norm) as avg_sos
FROM ranked_teams
GROUP BY rank_range, sort_order
ORDER BY sort_order;

-- Sample teams from middle ranks to see if they have different values
SELECT 
    rank_in_cohort_final,
    team_name,
    power_score_final,
    sos_norm,
    offense_norm,
    defense_norm
FROM rankings_view
WHERE age = 12 
  AND gender = 'M'
  AND rank_in_cohort_final BETWEEN 100 AND 120
ORDER BY rank_in_cohort_final
LIMIT 20;

