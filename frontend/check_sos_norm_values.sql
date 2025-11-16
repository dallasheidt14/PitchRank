-- Check if sos_norm values are actually different in rankings_full
-- Run this query in Supabase SQL editor to verify the data

SELECT 
    COUNT(*) as total_teams,
    COUNT(sos_norm) as teams_with_sos_norm,
    COUNT(*) - COUNT(sos_norm) as teams_without_sos_norm,
    COUNT(DISTINCT sos_norm) as unique_sos_norm_values,
    MIN(sos_norm) as min_sos_norm,
    MAX(sos_norm) as max_sos_norm,
    AVG(sos_norm) as avg_sos_norm
FROM rankings_full
WHERE power_score_final IS NOT NULL;

-- Sample 10 teams to see their sos_norm values
SELECT 
    team_id,
    age_group,
    gender,
    power_score_final,
    sos_norm,
    off_norm,
    def_norm
FROM rankings_full
WHERE power_score_final IS NOT NULL
ORDER BY power_score_final DESC
LIMIT 10;

