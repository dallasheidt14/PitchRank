-- Verification queries to check if the views were created successfully
-- Run these in Supabase SQL Editor to verify

-- 1. Check if rankings_view exists and has data
SELECT 
    'rankings_view' as view_name,
    COUNT(*) as row_count
FROM rankings_view
LIMIT 1;

-- 2. Check if state_rankings_view exists and has data
SELECT 
    'state_rankings_view' as view_name,
    COUNT(*) as row_count
FROM state_rankings_view
LIMIT 1;

-- 3. Sample query from rankings_view (national rankings)
SELECT 
    team_name,
    age_group,
    gender,
    national_rank,
    national_power_score
FROM rankings_view
WHERE age_group = 'u12' AND gender = 'Male'
ORDER BY national_rank
LIMIT 5;

-- 4. Sample query from state_rankings_view (state rankings)
SELECT 
    team_name,
    state_code,
    age_group,
    gender,
    state_rank,
    national_rank,
    power_score
FROM state_rankings_view
WHERE age_group = 'u12' AND gender = 'Male' AND state_code = 'ca'
ORDER BY state_rank
LIMIT 5;

