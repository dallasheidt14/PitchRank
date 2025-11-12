-- Quick check: How many games were inserted recently?
-- Run this in SQLTools or psql to see if batches are completing

SELECT 
    COUNT(*) as total_games,
    COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) as games_added_today,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as games_added_last_hour,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '10 minutes') as games_added_last_10min,
    MAX(created_at) as latest_import_time
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport');

-- Check if staging table exists (means batch is in progress)
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'games_staging')
        THEN (SELECT COUNT(*) FROM games_staging)
        ELSE 0
    END as games_in_staging;

