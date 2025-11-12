-- ============================================================================
-- IMPORT PROGRESS MONITORING QUERIES
-- Copy and paste these into SQLTools or psql
-- All queries are READ-ONLY - they won't affect the import
-- ============================================================================

-- Check total games
SELECT COUNT(*) FROM games WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport');

-- Check games added today
SELECT COUNT(*) FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
AND DATE(created_at) = CURRENT_DATE;

-- Check games added in last hour
SELECT COUNT(*) FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
AND created_at > NOW() - INTERVAL '1 hour';

-- Check if staging table has data (active batch)
SELECT COUNT(*) FROM games_staging;

-- Check staging table breakdown (valid vs invalid)
SELECT 
    validation_status,
    COUNT(*) as count
FROM games_staging
GROUP BY validation_status;

-- Check staging table - how many are matched vs unmatched
SELECT 
    COUNT(*) FILTER (WHERE home_team_master_id IS NOT NULL AND away_team_master_id IS NOT NULL) as matched_games,
    COUNT(*) FILTER (WHERE home_team_master_id IS NULL OR away_team_master_id IS NULL) as unmatched_games,
    COUNT(*) as total_in_staging
FROM games_staging;

-- Check how many duplicates are in staging (will be skipped)
SELECT COUNT(*) as potential_duplicates
FROM games_staging gs
WHERE gs.validation_status = 'valid'
    AND EXISTS (
        SELECT 1 FROM games g 
        WHERE g.game_uid = gs.game_uid
    );

-- Overall progress summary
SELECT 
    COUNT(*) as total_games_in_database,
    COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) as games_added_today,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as games_added_last_hour,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as games_added_last_24h,
    MIN(created_at) as first_import,
    MAX(created_at) as latest_import
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport');

-- Import activity by date (last 7 days)
SELECT 
    DATE(created_at) as import_date,
    COUNT(*) as games_imported
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY import_date DESC;

-- Recent import activity (last hour by minute)
SELECT 
    DATE_TRUNC('minute', created_at) as minute,
    COUNT(*) as games_imported
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at > NOW() - INTERVAL '1 hour'
GROUP BY DATE_TRUNC('minute', created_at)
ORDER BY minute DESC
LIMIT 60;

-- Import rate (games per hour)
SELECT 
    'Last Hour' as period,
    COUNT(*) as games_imported,
    ROUND(COUNT(*) / 1.0, 0) as games_per_hour
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at > NOW() - INTERVAL '1 hour'

UNION ALL

SELECT 
    'Last 24 Hours' as period,
    COUNT(*) as games_imported,
    ROUND(COUNT(*) / 24.0, 0) as games_per_hour
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at > NOW() - INTERVAL '24 hours';

-- Estimated time remaining (update csv_total with actual CSV row count)
WITH progress AS (
    SELECT 
        (SELECT COUNT(*) FROM games WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')) as imported,
        996136 as csv_total,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as rate_per_hour
    FROM games 
    WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
)
SELECT 
    imported,
    csv_total,
    csv_total - imported as remaining,
    rate_per_hour,
    CASE 
        WHEN rate_per_hour > 0 THEN 
            ROUND((csv_total - imported)::numeric / rate_per_hour, 1)
        ELSE NULL
    END as estimated_hours_remaining
FROM progress;

-- Complete status dashboard (all metrics in one view)
SELECT 
    'Database Total' as metric,
    COUNT(*)::text as value
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')

UNION ALL

SELECT 
    'Staging Total' as metric,
    COUNT(*)::text as value
FROM games_staging

UNION ALL

SELECT 
    'Staging Valid' as metric,
    COUNT(*) FILTER (WHERE validation_status = 'valid')::text as value
FROM games_staging

UNION ALL

SELECT 
    'Games Added Today' as metric,
    COUNT(*)::text as value
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND DATE(created_at) = CURRENT_DATE

UNION ALL

SELECT 
    'Games Added Last Hour' as metric,
    COUNT(*)::text as value
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at > NOW() - INTERVAL '1 hour'

UNION ALL

SELECT 
    'Latest Import Time' as metric,
    MAX(created_at)::text as value
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport');

