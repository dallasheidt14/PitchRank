-- Detailed Import Progress Monitoring Queries
-- Run these in SQLTools or psql to monitor progress
-- These are READ-ONLY queries - they won't affect the import

-- ============================================================================
-- 1. OVERALL PROGRESS SUMMARY
-- ============================================================================
SELECT 
    COUNT(*) as total_games_in_database,
    COUNT(DISTINCT DATE(created_at)) as days_with_imports,
    MIN(created_at) as first_import,
    MAX(created_at) as latest_import,
    COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) as games_added_today,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as games_added_last_hour,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as games_added_last_24h
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport');

-- ============================================================================
-- 2. STAGING TABLE STATUS (Current Batch Progress)
-- ============================================================================
SELECT 
    COUNT(*) as total_in_staging,
    COUNT(*) FILTER (WHERE validation_status = 'valid') as valid_games,
    COUNT(*) FILTER (WHERE validation_status = 'invalid') as invalid_games,
    COUNT(*) FILTER (WHERE validation_status = 'pending') as pending_validation,
    COUNT(*) FILTER (WHERE home_team_master_id IS NOT NULL AND away_team_master_id IS NOT NULL) as matched_games,
    COUNT(*) FILTER (WHERE home_team_master_id IS NULL OR away_team_master_id IS NULL) as unmatched_games
FROM games_staging;

-- ============================================================================
-- 3. IMPORT ACTIVITY BY DATE (Last 7 Days)
-- ============================================================================
SELECT 
    DATE(created_at) as import_date,
    COUNT(*) as games_imported,
    COUNT(DISTINCT DATE_TRUNC('hour', created_at)) as active_hours,
    MIN(created_at) as first_game_time,
    MAX(created_at) as last_game_time
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY import_date DESC;

-- ============================================================================
-- 4. RECENT IMPORT ACTIVITY (Last Hour - Detailed)
-- ============================================================================
SELECT 
    DATE_TRUNC('minute', created_at) as minute,
    COUNT(*) as games_imported,
    COUNT(DISTINCT game_uid) as unique_games
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND created_at > NOW() - INTERVAL '1 hour'
GROUP BY DATE_TRUNC('minute', created_at)
ORDER BY minute DESC
LIMIT 60;

-- ============================================================================
-- 5. STAGING TABLE BREAKDOWN (What's Currently Being Processed)
-- ============================================================================
SELECT 
    validation_status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM games_staging
GROUP BY validation_status
ORDER BY count DESC;

-- ============================================================================
-- 6. DUPLICATE DETECTION (Games That Would Be Skipped)
-- ============================================================================
SELECT 
    COUNT(*) as potential_duplicates
FROM games_staging gs
WHERE gs.validation_status = 'valid'
    AND EXISTS (
        SELECT 1 FROM games g 
        WHERE g.game_uid = gs.game_uid
    );

-- ============================================================================
-- 7. TEAM MATCHING STATUS IN STAGING
-- ============================================================================
SELECT 
    CASE 
        WHEN home_team_master_id IS NOT NULL AND away_team_master_id IS NOT NULL THEN 'Both Teams Matched'
        WHEN home_team_master_id IS NOT NULL OR away_team_master_id IS NOT NULL THEN 'One Team Matched'
        ELSE 'No Teams Matched'
    END as matching_status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM games_staging
GROUP BY matching_status
ORDER BY count DESC;

-- ============================================================================
-- 8. IMPORT RATE CALCULATION (Games Per Hour)
-- ============================================================================
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
    AND created_at > NOW() - INTERVAL '24 hours'

UNION ALL

SELECT 
    'Today' as period,
    COUNT(*) as games_imported,
    ROUND(COUNT(*) / EXTRACT(EPOCH FROM (NOW() - DATE_TRUNC('day', NOW()))) / 3600, 0) as games_per_hour
FROM games 
WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
    AND DATE(created_at) = CURRENT_DATE;

-- ============================================================================
-- 9. ESTIMATED TIME REMAINING (Based on CSV Total)
-- ============================================================================
WITH progress AS (
    SELECT 
        (SELECT COUNT(*) FROM games WHERE provider_id = (SELECT id FROM providers WHERE code = 'gotsport')) as imported,
        996136 as csv_total,  -- Update this with actual CSV row count
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
    END as estimated_hours_remaining,
    CASE 
        WHEN rate_per_hour > 0 THEN 
            ROUND((csv_total - imported)::numeric / rate_per_hour / 24, 1)
        ELSE NULL
    END as estimated_days_remaining
FROM progress;

-- ============================================================================
-- 10. VALIDATION ERRORS IN STAGING (If Any)
-- ============================================================================
SELECT 
    validation_errors->>0 as error_type,
    COUNT(*) as count
FROM games_staging
WHERE validation_status = 'invalid'
    AND validation_errors IS NOT NULL
GROUP BY validation_errors->>0
ORDER BY count DESC
LIMIT 20;

-- ============================================================================
-- 11. GAMES BY DATE RANGE IN STAGING (When Were They Scraped?)
-- ============================================================================
SELECT 
    DATE(game_date) as game_date,
    COUNT(*) as games_in_staging
FROM games_staging
WHERE game_date IS NOT NULL
GROUP BY DATE(game_date)
ORDER BY game_date DESC
LIMIT 30;

-- ============================================================================
-- 12. COMPLETE STATUS DASHBOARD (All-in-One View)
-- ============================================================================
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
    'Staging Invalid' as metric,
    COUNT(*) FILTER (WHERE validation_status = 'invalid')::text as value
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

