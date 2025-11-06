-- Fix game_uid column type from UUID to VARCHAR(255)
-- This aligns with the code that generates string-based game_uid values
-- Format: "gotsport:2025-10-12:20127:544491"

-- =====================================================
-- CHANGE GAME_UID COLUMN TYPE TO VARCHAR(255)
-- =====================================================

-- First, drop any existing indexes that depend on game_uid
DROP INDEX IF EXISTS idx_games_uid;
DROP INDEX IF EXISTS idx_games_uid_lookup;
DROP INDEX IF EXISTS idx_games_uid_unique;
DROP INDEX IF EXISTS idx_games_uid_rls;

-- Change the column type from UUID to VARCHAR(255)
-- Note: This will convert existing UUID values to strings if any exist
DO $$
BEGIN
    -- Check if column exists and is UUID type
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'games' 
        AND column_name = 'game_uid'
        AND data_type = 'uuid'
    ) THEN
        -- Convert UUID to VARCHAR(255)
        ALTER TABLE games 
        ALTER COLUMN game_uid TYPE VARCHAR(255) USING game_uid::text;
        
        RAISE NOTICE 'Changed game_uid column from UUID to VARCHAR(255)';
    ELSIF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'games' 
        AND column_name = 'game_uid'
        AND data_type = 'character varying'
    ) THEN
        -- Already VARCHAR, just ensure it's VARCHAR(255)
        ALTER TABLE games 
        ALTER COLUMN game_uid TYPE VARCHAR(255);
        
        RAISE NOTICE 'game_uid column already VARCHAR, ensured VARCHAR(255)';
    ELSE
        -- Column doesn't exist, create it as VARCHAR(255)
        ALTER TABLE games 
        ADD COLUMN game_uid VARCHAR(255);
        
        RAISE NOTICE 'Created game_uid column as VARCHAR(255)';
    END IF;
END $$;

-- Recreate indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_games_uid_unique ON games(game_uid) WHERE game_uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_games_uid_lookup ON games(game_uid) WHERE game_uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_games_uid_rls ON games(game_uid) WHERE game_uid IS NOT NULL;

-- Add comment explaining the format
COMMENT ON COLUMN games.game_uid IS 'Deterministic game identifier. Format: {provider}:{date}:{team1_id}:{team2_id}. Example: "gotsport:2025-10-12:20127:544491"';

