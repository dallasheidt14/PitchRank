-- Query rankings_full directly to get perf_centered values
-- (rankings_view doesn't expose perf_centered, only canonical fields)

SELECT
    t.team_name,
    t.club_name,
    rf.age_group,
    rf.gender,
    rf.power_score_final,
    rf.powerscore_core,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,
    rf.perf_centered,           -- THIS IS THE KEY!
    rf.perf_raw,                -- Raw performance before normalization
    rf.games_played,
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_final,
    rf.status
FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
WHERE (t.team_name ILIKE '%PRFC%Scottsdale%14%Pre-Academy%'
   OR t.team_name ILIKE '%Dynamos%SC%14%SC%')
  AND rf.age_group IN ('12', 'u12', 'U12')  -- Filter to 14B (age 12)
  AND rf.gender IN ('M', 'Male', 'Boys')
ORDER BY rf.power_score_final DESC;
