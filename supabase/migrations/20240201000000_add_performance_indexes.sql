-- PitchRank Performance Indexes Migration
-- Adds indexes for improved query performance on frequently accessed columns

-- =====================================================
-- GAMES TABLE INDEXES
-- =====================================================

-- Composite index for home team queries with date filtering
CREATE INDEX IF NOT EXISTS idx_games_home_team_date ON games(home_team_master_id, game_date DESC);

-- Composite index for away team queries with date filtering
CREATE INDEX IF NOT EXISTS idx_games_away_team_date ON games(away_team_master_id, game_date DESC);

-- Index on provider for filtering by data source
CREATE INDEX IF NOT EXISTS idx_games_provider ON games(provider_id);

-- Index on game_uid for duplicate detection and lookups
CREATE INDEX IF NOT EXISTS idx_games_uid ON games(game_uid) WHERE game_uid IS NOT NULL;

-- Index on game_date for date range queries (if not already exists)
CREATE INDEX IF NOT EXISTS idx_games_date_desc ON games(game_date DESC);

-- =====================================================
-- TEAM ALIAS MAP INDEXES
-- =====================================================

-- Composite index for provider team lookup (may already exist, but ensure it's optimal)
CREATE INDEX IF NOT EXISTS idx_team_alias_provider ON team_alias_map(provider_id, provider_team_id);

-- Index for master team lookups
CREATE INDEX IF NOT EXISTS idx_team_alias_master ON team_alias_map(team_id_master);

-- Index for confidence-based queries (review queue, etc.)
CREATE INDEX IF NOT EXISTS idx_team_alias_confidence ON team_alias_map(match_confidence DESC);

-- =====================================================
-- RANKINGS INDEXES
-- =====================================================

-- Note: current_rankings uses team_id as primary key, so it's already indexed
-- Add composite index for state/age group queries if needed
-- Since current_rankings doesn't have age_group directly, we'll index by team_id
-- Age group filtering would be done via JOIN with teams table

-- Index for state rankings (if state_code is added to rankings later)
-- For now, rankings are filtered via JOIN with teams table

-- Index on national_power_score for ranking queries (descending for top teams)
CREATE INDEX IF NOT EXISTS idx_rankings_power_score ON current_rankings(national_power_score DESC);

-- Index on state_rank for state-level queries
CREATE INDEX IF NOT EXISTS idx_rankings_state_rank ON current_rankings(state_rank) WHERE state_rank IS NOT NULL;

