-- Add indexes for Import Stats dashboard queries
-- These indexes optimize the date-filtered queries used in the dashboard

-- Index on games.created_at for efficient date filtering
-- Used by: Overview (7-day counts), Daily Import Summary, Import Activity chart
CREATE INDEX IF NOT EXISTS idx_games_created_at ON games(created_at DESC);

-- Index on teams.created_at for efficient date filtering
-- Used by: Overview (7-day new teams count)
CREATE INDEX IF NOT EXISTS idx_teams_created_at ON teams(created_at DESC);

-- Composite index for build_logs queries ordered by started_at
-- Used by: Recent Build Activity section
CREATE INDEX IF NOT EXISTS idx_build_logs_started_at ON build_logs(started_at DESC);

-- Comment explaining the purpose
COMMENT ON INDEX idx_games_created_at IS 'Optimizes date-filtered queries for import statistics dashboard';
COMMENT ON INDEX idx_teams_created_at IS 'Optimizes date-filtered queries for new teams in import statistics';
COMMENT ON INDEX idx_build_logs_started_at IS 'Optimizes build log queries sorted by start time';
