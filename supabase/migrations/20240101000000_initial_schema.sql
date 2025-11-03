-- PitchRank Database Schema - Corrected Version
-- Focus: National rankings by age group and gender, with state breakdowns

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =====================================================
-- CORE TABLES
-- =====================================================

-- Providers table (for future multi-source support)
CREATE TABLE IF NOT EXISTS providers (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    code TEXT UNIQUE NOT NULL, -- 'gotsport'
    name TEXT NOT NULL,
    base_url TEXT,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert GotSport as the provider
INSERT INTO providers (code, name, base_url) 
VALUES ('gotsport', 'GotSport', 'https://www.gotsport.com')
ON CONFLICT (code) DO NOTHING;

-- Master team list
CREATE TABLE IF NOT EXISTS teams (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    team_id_master UUID NOT NULL UNIQUE,
    provider_team_id TEXT NOT NULL, -- Team_ID from your data
    provider_id UUID REFERENCES providers(id),
    
    -- Team identification
    team_name TEXT NOT NULL,
    club_name TEXT,
    state TEXT,
    state_code CHAR(2),
    
    -- Age group info (both formats)
    age_group TEXT NOT NULL, -- 'u10', 'u11', etc.
    birth_year INTEGER, -- 2016, 2015, etc.
    gender TEXT NOT NULL CHECK (gender IN ('Male', 'Female')),
    
    -- Tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_scraped_at TIMESTAMPTZ,
    
    UNIQUE(provider_id, provider_team_id)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_teams_provider_lookup ON teams(provider_id, provider_team_id);
CREATE INDEX IF NOT EXISTS idx_teams_name_lookup ON teams USING gin(team_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_teams_age_gender ON teams(age_group, gender);
CREATE INDEX IF NOT EXISTS idx_teams_state ON teams(state_code);
CREATE INDEX IF NOT EXISTS idx_teams_master_id ON teams(team_id_master);

-- Game history table
CREATE TABLE IF NOT EXISTS games (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    
    -- Teams and scores
    home_team_master_id UUID REFERENCES teams(team_id_master),
    away_team_master_id UUID REFERENCES teams(team_id_master),
    home_provider_id TEXT NOT NULL,
    away_provider_id TEXT NOT NULL,
    home_score INTEGER CHECK (home_score >= 0),
    away_score INTEGER CHECK (away_score >= 0),
    result CHAR(1) CHECK (result IN ('W', 'L', 'D', 'U')),
    
    -- Game info
    game_date DATE NOT NULL,
    competition TEXT,
    division_name TEXT,
    event_name TEXT,
    venue TEXT,
    
    -- Source tracking
    provider_id UUID REFERENCES providers(id),
    source_url TEXT,
    scraped_at TIMESTAMPTZ,
    
    -- For tracking imports
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Prevent duplicates
    UNIQUE(provider_id, home_provider_id, away_provider_id, game_date, 
           COALESCE(home_score::text, 'null'), COALESCE(away_score::text, 'null'))
);

-- Indexes for game queries
CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date DESC);
CREATE INDEX IF NOT EXISTS idx_games_home_team ON games(home_team_master_id, game_date DESC);
CREATE INDEX IF NOT EXISTS idx_games_away_team ON games(away_team_master_id, game_date DESC);
CREATE INDEX IF NOT EXISTS idx_games_provider ON games(provider_id);

-- Team alias map for matching variations
CREATE TABLE IF NOT EXISTS team_alias_map (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    provider_id UUID REFERENCES providers(id),
    provider_team_id TEXT NOT NULL,
    team_id_master UUID REFERENCES teams(team_id_master),
    match_confidence FLOAT NOT NULL,
    match_method TEXT NOT NULL, -- 'exact_id', 'fuzzy_name', 'manual'
    review_status TEXT DEFAULT 'approved' CHECK (review_status IN ('pending', 'approved', 'rejected', 'new_team')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(provider_id, provider_team_id)
);

CREATE INDEX IF NOT EXISTS idx_alias_lookup ON team_alias_map(provider_id, provider_team_id);
CREATE INDEX IF NOT EXISTS idx_alias_team ON team_alias_map(team_id_master);
CREATE INDEX IF NOT EXISTS idx_alias_status ON team_alias_map(review_status);

-- Current rankings (continuously updated)
CREATE TABLE IF NOT EXISTS current_rankings (
    team_id UUID REFERENCES teams(team_id_master) PRIMARY KEY,
    
    -- National rankings by age group
    national_rank INTEGER,
    national_power_score FLOAT NOT NULL,
    
    -- State rankings
    state_rank INTEGER,
    
    -- Performance metrics
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    goals_for INTEGER DEFAULT 0,
    goals_against INTEGER DEFAULT 0,
    
    -- Key ranking factors
    win_percentage FLOAT,
    points_per_game FLOAT,
    strength_of_schedule FLOAT,
    
    -- For cross-age SOS calculation
    global_power_score FLOAT, -- Normalized across all ages
    
    -- Tracking
    last_game_date DATE,
    last_calculated TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rankings_national ON current_rankings(national_power_score DESC);
CREATE INDEX IF NOT EXISTS idx_rankings_state ON current_rankings(state_rank);
CREATE INDEX IF NOT EXISTS idx_rankings_global ON current_rankings(global_power_score DESC);

-- User corrections/additions table
CREATE TABLE IF NOT EXISTS user_corrections (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    correction_type TEXT NOT NULL, -- 'new_game', 'team_correction', 'missing_game'
    
    -- For team corrections
    team_id UUID REFERENCES teams(team_id_master),
    suggested_age_group TEXT,
    suggested_name TEXT,
    
    -- For game additions
    game_data JSONB,
    
    -- Submission info
    submitted_by TEXT,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_corrections_status ON user_corrections(status);
CREATE INDEX IF NOT EXISTS idx_corrections_type ON user_corrections(correction_type);
CREATE INDEX IF NOT EXISTS idx_corrections_team ON user_corrections(team_id);

-- Build logs (ETL tracking)
CREATE TABLE IF NOT EXISTS build_logs (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    build_id VARCHAR(255) NOT NULL,
    stage VARCHAR(100) NOT NULL,
    provider_id UUID REFERENCES providers(id),
    parameters JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    records_processed INTEGER DEFAULT 0,
    records_succeeded INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]',
    warnings JSONB DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_build_logs_id ON build_logs(build_id);
CREATE INDEX IF NOT EXISTS idx_build_logs_provider ON build_logs(provider_id);
CREATE INDEX IF NOT EXISTS idx_build_logs_stage ON build_logs(stage);

-- Team scrape log
CREATE TABLE IF NOT EXISTS team_scrape_log (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    team_id UUID NOT NULL REFERENCES teams(team_id_master) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    games_found INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'success' CHECK (status IN ('success', 'error', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_scrape_team ON team_scrape_log(team_id);
CREATE INDEX IF NOT EXISTS idx_scrape_provider ON team_scrape_log(provider_id);
CREATE INDEX IF NOT EXISTS idx_scrape_date ON team_scrape_log(scraped_at DESC);

-- Validation errors log
CREATE TABLE IF NOT EXISTS validation_errors (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    build_id VARCHAR(255),
    record_type VARCHAR(50) NOT NULL,
    record_data JSONB DEFAULT '{}',
    error_type VARCHAR(50) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_validation_build ON validation_errors(build_id);
CREATE INDEX IF NOT EXISTS idx_validation_type ON validation_errors(record_type);
CREATE INDEX IF NOT EXISTS idx_validation_date ON validation_errors(created_at DESC);

-- =====================================================
-- VIEWS FOR EASY ACCESS
-- =====================================================

-- National rankings by age group and gender
CREATE OR REPLACE VIEW rankings_by_age_gender AS
SELECT 
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    t.age_group,
    t.gender,
    r.national_rank,
    r.state_rank,
    r.national_power_score,
    r.global_power_score,
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.win_percentage,
    r.strength_of_schedule
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
ORDER BY t.age_group, t.gender, r.national_rank;

-- State rankings view
CREATE OR REPLACE VIEW state_rankings AS
SELECT 
    t.team_id_master,
    t.team_name,
    t.state_code,
    t.age_group,
    t.gender,
    r.state_rank,
    r.national_rank,
    r.national_power_score,
    r.global_power_score
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
ORDER BY t.state_code, t.age_group, t.gender, r.state_rank;

-- Pending alias reviews
CREATE OR REPLACE VIEW aliases_pending_review AS
SELECT 
    a.id,
    a.provider_team_id,
    a.team_id_master,
    t.team_name,
    t.age_group,
    t.gender,
    a.match_method,
    a.match_confidence,
    p.name as provider_name
FROM team_alias_map a
JOIN teams t ON a.team_id_master = t.team_id_master
JOIN providers p ON a.provider_id = p.id
WHERE a.review_status = 'pending'
ORDER BY a.match_confidence DESC, a.created_at ASC;

-- Recent build activity
CREATE OR REPLACE VIEW recent_builds AS
SELECT 
    bl.build_id,
    bl.stage,
    p.name as provider_name,
    bl.started_at,
    bl.completed_at,
    bl.records_processed,
    bl.records_succeeded,
    bl.records_failed,
    CASE 
        WHEN bl.completed_at IS NULL THEN 'running'
        WHEN bl.records_failed > 0 THEN 'partial'
        ELSE 'success'
    END as status
FROM build_logs bl
LEFT JOIN providers p ON bl.provider_id = p.id
ORDER BY bl.started_at DESC
LIMIT 100;

-- =====================================================
-- FUNCTIONS
-- =====================================================

-- Function to calculate state rankings from national rankings
CREATE OR REPLACE FUNCTION calculate_state_rankings()
RETURNS void AS $$
BEGIN
    -- Update state rankings based on national rankings
    WITH ranked_by_state AS (
        SELECT 
            r.team_id,
            t.state_code,
            t.age_group,
            t.gender,
            ROW_NUMBER() OVER (
                PARTITION BY t.state_code, t.age_group, t.gender 
                ORDER BY r.national_power_score DESC
            ) as state_rank
        FROM current_rankings r
        JOIN teams t ON r.team_id = t.team_id_master
    )
    UPDATE current_rankings r
    SET state_rank = rbs.state_rank
    FROM ranked_by_state rbs
    WHERE r.team_id = rbs.team_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get teams that need scraping (haven't been scraped in 7 days)
CREATE OR REPLACE FUNCTION get_teams_to_scrape()
RETURNS TABLE (
    team_id UUID,
    provider_team_id TEXT,
    team_name TEXT,
    last_scraped TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.team_id_master,
        t.provider_team_id,
        t.team_name,
        t.last_scraped_at
    FROM teams t
    WHERE t.last_scraped_at IS NULL 
       OR t.last_scraped_at < NOW() - INTERVAL '7 days'
    ORDER BY t.last_scraped_at ASC NULLS FIRST;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_teams_updated_at BEFORE UPDATE ON teams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
