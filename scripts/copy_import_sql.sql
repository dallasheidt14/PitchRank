-- SQL Script for COPY Import (can be run via SQLTools or psql)
-- This script creates the staging table and moves data from staging to games table

-- Step 1: Create staging table
CREATE TABLE IF NOT EXISTS games_staging (
    game_uid VARCHAR(255),
    provider_id UUID,
    home_provider_id VARCHAR(50),
    away_provider_id VARCHAR(50),
    home_team_master_id UUID,
    away_team_master_id UUID,
    home_score INTEGER,
    away_score INTEGER,
    game_date DATE,
    result VARCHAR(1),
    competition TEXT,
    division_name TEXT,
    event_name TEXT,
    venue TEXT,
    source_url TEXT,
    scraped_at TIMESTAMPTZ,
    is_immutable BOOLEAN DEFAULT true,
    original_import_id TEXT,
    -- Validation fields
    validation_status VARCHAR(20) DEFAULT 'pending',
    validation_errors JSONB,
    -- Raw data for reference
    raw_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_staging_game_uid ON games_staging(game_uid);
CREATE INDEX IF NOT EXISTS idx_staging_provider ON games_staging(provider_id);

-- Step 2: After COPY import completes, move valid games to main table
-- (Run this after the Python script finishes COPY operations)

-- Insert games from staging, skipping duplicates
INSERT INTO games (
    game_uid, provider_id, home_provider_id, away_provider_id,
    home_team_master_id, away_team_master_id, home_score, away_score,
    game_date, result, competition, division_name, event_name,
    venue, source_url, scraped_at, is_immutable, original_import_id
)
SELECT 
    game_uid, provider_id, home_provider_id, away_provider_id,
    home_team_master_id, away_team_master_id, home_score, away_score,
    game_date, result, competition, division_name, event_name,
    venue, source_url, scraped_at, is_immutable, original_import_id
FROM games_staging
WHERE validation_status = 'valid'
  AND home_team_master_id IS NOT NULL
  AND away_team_master_id IS NOT NULL
  AND game_uid IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM games g 
      WHERE g.game_uid = games_staging.game_uid
  )
ON CONFLICT (game_uid) DO NOTHING;

-- Move invalid games to quarantine
INSERT INTO quarantine_games (reason_code, error_details, raw_data, provider_id)
SELECT 
    'validation_failed',
    COALESCE(validation_errors::text, 'Validation failed'),
    raw_data,
    provider_id
FROM games_staging
WHERE validation_status = 'invalid'
   OR home_team_master_id IS NULL
   OR away_team_master_id IS NULL
   OR game_uid IS NULL;

-- Step 3: Check import results
SELECT 
    validation_status,
    COUNT(*) as count
FROM games_staging
GROUP BY validation_status;

SELECT 
    COUNT(*) as total_staged,
    COUNT(CASE WHEN validation_status = 'valid' THEN 1 END) as valid_count,
    COUNT(CASE WHEN validation_status = 'invalid' THEN 1 END) as invalid_count
FROM games_staging;

-- Step 4: Cleanup staging table (after verifying import)
-- DROP TABLE IF EXISTS games_staging CASCADE;



