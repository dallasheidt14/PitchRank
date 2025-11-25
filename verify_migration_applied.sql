-- Verify that the migration was applied correctly
-- Check if sos_norm_state exists in the views

-- Check rankings_view
SELECT 
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'rankings_view'
  AND column_name IN ('sos_norm', 'sos_norm_state')
ORDER BY column_name;

-- Check state_rankings_view
SELECT 
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'state_rankings_view'
  AND column_name IN ('sos_norm', 'sos_norm_state')
ORDER BY column_name;

-- Test query to see if sos_norm_state is actually returned
SELECT 
    team_name,
    sos_norm,
    sos_norm_state,
    CASE 
        WHEN sos_norm_state IS NULL THEN 'MISSING sos_norm_state'
        ELSE 'OK'
    END as status
FROM state_rankings_view
WHERE age = 12
  AND gender = 'M'
  AND state = 'AZ'
LIMIT 5;

