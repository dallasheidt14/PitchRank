-- Verify that state_rankings_view actually returns sos_norm_state
-- Run this in Supabase SQL Editor

-- Test query: Get Arizona U12 Boys and check if sos_norm_state is returned
SELECT 
    team_name,
    state,
    age,
    gender,
    sos_norm,
    sos_norm_state,
    ROUND((sos_norm * 100)::numeric, 1) as sos_norm_display,
    ROUND((sos_norm_state * 100)::numeric, 1) as sos_norm_state_display
FROM state_rankings_view
WHERE age = 12
  AND gender = 'M'
  AND state = 'AZ'
  AND status IN ('Active', 'Not Enough Ranked Games')
ORDER BY rank_in_state_final
LIMIT 10;

-- Check if sos_norm_state column exists and has non-null values
SELECT 
    COUNT(*) as total_teams,
    COUNT(sos_norm_state) as teams_with_sos_norm_state,
    COUNT(sos_norm) as teams_with_sos_norm,
    ROUND(AVG(sos_norm_state)::numeric, 3) as avg_sos_norm_state,
    ROUND(AVG(sos_norm)::numeric, 3) as avg_sos_norm
FROM state_rankings_view
WHERE age = 12
  AND gender = 'M'
  AND state = 'AZ'
  AND status IN ('Active', 'Not Enough Ranked Games');

