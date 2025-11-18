-- Query to get perf_centered values for PRFC Scottsdale and Dynamos SC
-- This will help us understand if the performance metric is correcting for double-counting

SELECT
    t.team_name,
    t.club_name,
    r.power_score_final,
    r.powerscore_core,
    r.sos_norm,
    r.offense_norm,
    r.defense_norm,
    r.perf_centered,        -- THIS IS THE KEY VALUE!
    r.perf_raw,             -- Raw performance before normalization
    r.gp as games_played,
    r.rank_in_cohort_final,
    r.status
FROM rankings_full r
JOIN teams t ON r.team_id = t.team_id_master
WHERE t.team_name ILIKE '%PRFC%Scottsdale%14%'
   OR t.team_name ILIKE '%Dynamos%14%'
ORDER BY r.power_score_final DESC;

-- Alternative if column names are different:
-- Check what columns actually exist in rankings_full:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name = 'rankings_full'
-- ORDER BY ordinal_position;
