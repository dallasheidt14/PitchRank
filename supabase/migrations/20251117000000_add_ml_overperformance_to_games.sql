-- Migration: Add ML overperformance column to games table
-- Date: 2025-11-17
-- Purpose: Store per-game residual values (actual - expected goal margin) from Layer 13 ML model

-- Add ml_overperformance column to games table
ALTER TABLE games
ADD COLUMN IF NOT EXISTS ml_overperformance FLOAT;

-- Add comment explaining the column
COMMENT ON COLUMN games.ml_overperformance IS
  'ML residual value: actual goal margin - expected goal margin. '
  'Calculated by Layer 13 predictive model. '
  'Positive = outperformed expectations, Negative = underperformed. '
  'NULL for games not yet processed or teams with <6 games.';

-- Create index for efficient filtering by overperformance threshold
CREATE INDEX IF NOT EXISTS idx_games_ml_overperformance
  ON games(ml_overperformance)
  WHERE ml_overperformance IS NOT NULL;

-- Create composite index for team-based queries with overperformance
CREATE INDEX IF NOT EXISTS idx_games_home_team_ml_overperformance
  ON games(home_team_master_id, ml_overperformance)
  WHERE ml_overperformance IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_games_away_team_ml_overperformance
  ON games(away_team_master_id, ml_overperformance)
  WHERE ml_overperformance IS NOT NULL;
