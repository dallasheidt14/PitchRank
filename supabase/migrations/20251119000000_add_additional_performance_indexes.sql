-- Additional Performance Indexes Migration
-- Adds missing indexes identified in performance review for frequently-accessed query patterns
-- Date: 2025-11-19

-- =====================================================
-- TEAMS TABLE INDEXES
-- =====================================================

-- Composite index for age_group and gender lookups
-- Used heavily in fuzzy matching queries where teams are filtered by age/gender
-- Improves performance of team_matcher.py fuzzy matching operations
CREATE INDEX IF NOT EXISTS idx_teams_age_gender
ON teams(age_group, gender);

-- Index on team_id_master for faster master team lookups
CREATE INDEX IF NOT EXISTS idx_teams_master_id
ON teams(team_id_master) WHERE team_id_master IS NOT NULL;

-- =====================================================
-- GAMES TABLE INDEXES
-- =====================================================

-- Composite index for date range queries filtered by provider
-- Used in rankings calculation and ETL pipeline date filtering
CREATE INDEX IF NOT EXISTS idx_games_date_provider
ON games(game_date DESC, provider_id);

-- Index on home and away team IDs for JOIN operations
-- Improves performance when fetching all games for a team
CREATE INDEX IF NOT EXISTS idx_games_home_team
ON games(home_team_master_id) WHERE home_team_master_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_games_away_team
ON games(away_team_master_id) WHERE away_team_master_id IS NOT NULL;

-- =====================================================
-- TEAM ALIAS MAP INDEXES
-- =====================================================

-- Composite index for filtering by review status and match method
-- Used in match review queue and quality assurance queries
CREATE INDEX IF NOT EXISTS idx_alias_status_method
ON team_alias_map(review_status, match_method);

-- Index for finding aliases by provider and status
CREATE INDEX IF NOT EXISTS idx_alias_provider_status
ON team_alias_map(provider_id, review_status);

-- =====================================================
-- PERFORMANCE NOTES
-- =====================================================

-- These indexes specifically target query patterns identified in performance review:
-- 1. Fuzzy matching queries that filter teams by (age_group, gender)
-- 2. Date range queries in rankings calculator that also filter by provider
-- 3. Team alias review queue queries that filter by status and method
--
-- Expected performance improvements:
-- - Fuzzy matching: 10-50x faster (from table scans to index scans)
-- - Date range queries: 5-10x faster
-- - Review queue queries: 10-20x faster
--
-- All indexes use "IF NOT EXISTS" for safe re-running
-- Indexes can be safely dropped if they don't provide benefit
