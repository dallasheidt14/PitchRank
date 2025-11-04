-- PitchRank Safety Features Migration
-- Adds quarantine tables, watermarks, and game_uid for data integrity

-- =====================================================
-- QUARANTINE TABLES
-- =====================================================

-- Quarantine teams table (invalid team data)
CREATE TABLE IF NOT EXISTS quarantine_teams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_data JSONB NOT NULL,
    reason_code TEXT NOT NULL, -- 'validation_failed', 'duplicate', 'invalid_format', etc.
    error_details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quarantine_teams_reason ON quarantine_teams(reason_code);
CREATE INDEX IF NOT EXISTS idx_quarantine_teams_date ON quarantine_teams(created_at DESC);

-- Quarantine games table (invalid game data)
CREATE TABLE IF NOT EXISTS quarantine_games (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_data JSONB NOT NULL,
    reason_code TEXT NOT NULL, -- 'validation_failed', 'duplicate', 'invalid_format', etc.
    error_details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quarantine_games_reason ON quarantine_games(reason_code);
CREATE INDEX IF NOT EXISTS idx_quarantine_games_date ON quarantine_games(created_at DESC);

-- =====================================================
-- WATERMARK TRACKING
-- =====================================================

-- Scrape watermarks table (track last successful scrape per provider)
CREATE TABLE IF NOT EXISTS scrape_watermarks (
    provider TEXT NOT NULL PRIMARY KEY,
    last_successful_scrape TIMESTAMPTZ NOT NULL,
    games_found INTEGER DEFAULT 0,
    games_imported INTEGER DEFAULT 0,
    games_failed INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watermarks_provider ON scrape_watermarks(provider);
CREATE INDEX IF NOT EXISTS idx_watermarks_date ON scrape_watermarks(last_successful_scrape DESC);

-- =====================================================
-- GAME UID COLUMN
-- =====================================================

-- Add game_uid column to games table if not exists
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'games' AND column_name = 'game_uid'
    ) THEN
        ALTER TABLE games ADD COLUMN game_uid UUID;
        
        -- Create unique index on game_uid
        CREATE UNIQUE INDEX IF NOT EXISTS idx_games_uid ON games(game_uid) WHERE game_uid IS NOT NULL;
        
        -- Create index for efficient lookups
        CREATE INDEX IF NOT EXISTS idx_games_uid_lookup ON games(game_uid);
    END IF;
END $$;

-- =====================================================
-- VIEWS FOR REVIEW QUEUE
-- =====================================================

-- View: Pending alias reviews (matches needing manual review)
CREATE OR REPLACE VIEW pending_alias_reviews AS
SELECT 
    a.id,
    a.provider_id,
    p.name as provider_name,
    a.provider_team_id,
    a.team_id_master,
    t.team_name as matched_team_name,
    t.age_group,
    t.gender,
    a.match_method,
    a.match_confidence,
    a.created_at,
    CASE 
        WHEN a.match_confidence >= 0.85 THEN 'high'
        WHEN a.match_confidence >= 0.80 THEN 'medium'
        ELSE 'low'
    END as confidence_level
FROM team_alias_map a
JOIN providers p ON a.provider_id = p.id
LEFT JOIN teams t ON a.team_id_master = t.team_id_master
WHERE a.review_status = 'pending'
  AND a.match_confidence >= 0.75
  AND a.match_confidence < 0.9
ORDER BY a.match_confidence DESC, a.created_at ASC;

-- View: Recent quarantine entries
CREATE OR REPLACE VIEW recent_quarantine AS
SELECT 
    'team' as type,
    id,
    reason_code,
    error_details,
    created_at
FROM quarantine_teams
UNION ALL
SELECT 
    'game' as type,
    id,
    reason_code,
    error_details,
    created_at
FROM quarantine_games
ORDER BY created_at DESC
LIMIT 100;

-- =====================================================
-- FUNCTIONS
-- =====================================================

-- Function to update scrape watermark
CREATE OR REPLACE FUNCTION update_scrape_watermark(
    p_provider TEXT,
    p_games_found INTEGER DEFAULT 0,
    p_games_imported INTEGER DEFAULT 0,
    p_games_failed INTEGER DEFAULT 0
)
RETURNS void AS $$
BEGIN
    INSERT INTO scrape_watermarks (
        provider,
        last_successful_scrape,
        games_found,
        games_imported,
        games_failed,
        updated_at
    )
    VALUES (
        p_provider,
        NOW(),
        p_games_found,
        p_games_imported,
        p_games_failed,
        NOW()
    )
    ON CONFLICT (provider) DO UPDATE SET
        last_successful_scrape = NOW(),
        games_found = p_games_found,
        games_imported = p_games_imported,
        games_failed = p_games_failed,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Function to get last scrape date for provider
CREATE OR REPLACE FUNCTION get_last_scrape_date(p_provider TEXT)
RETURNS TIMESTAMPTZ AS $$
DECLARE
    last_date TIMESTAMPTZ;
BEGIN
    SELECT last_successful_scrape INTO last_date
    FROM scrape_watermarks
    WHERE provider = p_provider;
    
    RETURN COALESCE(last_date, '1970-01-01'::TIMESTAMPTZ);
END;
$$ LANGUAGE plpgsql;