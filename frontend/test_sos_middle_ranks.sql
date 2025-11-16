-- Query 2: Sample teams from middle ranks to see if they have different values
-- Run this query separately from test_sos_variation.sql

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

