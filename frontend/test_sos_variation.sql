-- Test to see if sos_norm values vary across different ranks
-- This will help identify if only top teams have the same value (expected)
-- or if ALL teams have the same value (problem)

-- Query 1: Get teams across different rank ranges
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

