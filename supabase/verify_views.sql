-- Verification queries to check if the views were created successfully
-- Run these in Supabase SQL Editor to verify
-- Updated to use canonical field names: power_score_final, sos_norm, rank_in_cohort_final, rank_in_state_final, state, age

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
-- Using canonical fields: state (not state_code), age (not age_group), rank_in_cohort_final (not national_rank)
SELECT 
    team_name,
    state,
    age,
    gender,
    rank_in_cohort_final,
    power_score_final,
    sos_norm,
    offense_norm,
    defense_norm,
    games_played,
    wins,
    losses,
    draws,
    win_percentage
FROM rankings_view
WHERE age = 'u12' AND gender = 'Male'
ORDER BY rank_in_cohort_final
LIMIT 5;

-- 4. Sample query from state_rankings_view (state rankings)
-- Using canonical fields: state, age, rank_in_cohort_final, rank_in_state_final
SELECT 
    team_name,
    state,
    age,
    gender,
    rank_in_state_final,
    rank_in_cohort_final,
    power_score_final,
    sos_norm,
    offense_norm,
    defense_norm,
    games_played,
    wins,
    losses,
    draws,
    win_percentage
FROM state_rankings_view
WHERE age = 'u12' AND gender = 'Male' AND state = 'CA'
ORDER BY rank_in_state_final
LIMIT 5;

-- 5. Verify canonical fields exist and legacy fields are absent
-- Check column names in rankings_view
SELECT 
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'rankings_view'
ORDER BY ordinal_position;

-- 6. Verify state_rankings_view columns
SELECT 
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'state_rankings_view'
ORDER BY ordinal_position;
