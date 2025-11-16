-- Check SOS variation after removing clipping and switching to z-score normalization
-- This should show much better variation in sos_norm values, especially for top-ranked teams

-- Check U12 Male cohort (the one we were debugging)
-- Note: rankings_view uses 'age' (integer) and 'gender' ('M'/'F'), not 'age_group'
-- KEY METRIC: unique_sos_norm_values should be much higher now (was 1 for top 100+ teams before)
SELECT 
  COUNT(*) as total_teams,
  COUNT(DISTINCT sos_norm) as unique_sos_norm_values,
  MIN(sos_norm) as min_sos_norm,
  MAX(sos_norm) as max_sos_norm,
  AVG(sos_norm) as avg_sos_norm,
  STDDEV(sos_norm) as stddev_sos_norm,
  -- Check if top teams still have identical values (they shouldn't now)
  COUNT(DISTINCT CASE WHEN rank_in_cohort_final <= 20 THEN sos_norm END) as unique_sos_in_top_20,
  COUNT(DISTINCT CASE WHEN rank_in_cohort_final <= 100 THEN sos_norm END) as unique_sos_in_top_100
FROM rankings_view
WHERE age = 12 AND gender = 'M';

-- Check top 20 teams to see if they have different sos_norm values now
SELECT 
  rank_in_cohort_final,
  team_name,
  power_score_final,
  sos_norm,
  offense_norm,
  defense_norm
FROM rankings_view
WHERE age = 12 AND gender = 'M'
ORDER BY rank_in_cohort_final
LIMIT 20;

-- Check raw SOS values to see if they exceed 1.0 now (they should)
-- Note: rankings_full uses 'age_group' (string like 'u12') and 'gender' (string like 'Male')
SELECT 
  COUNT(*) as total_teams,
  COUNT(CASE WHEN sos > 1.0 THEN 1 END) as teams_with_sos_over_1,
  MIN(sos) as min_sos,
  MAX(sos) as max_sos,
  AVG(sos) as avg_sos
FROM rankings_full
WHERE age_group = 'u12' AND gender = 'Male';

