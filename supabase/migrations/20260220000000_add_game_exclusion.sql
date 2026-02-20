-- Add is_excluded flag to games table
-- Allows excluding games from rankings and frontend display
-- (e.g., futsal tournament games scraped by accident)
ALTER TABLE games ADD COLUMN IF NOT EXISTS is_excluded BOOLEAN NOT NULL DEFAULT FALSE;

-- Index for fast filtering in rankings pipeline queries
CREATE INDEX IF NOT EXISTS idx_games_is_excluded ON games(is_excluded) WHERE is_excluded = TRUE;
