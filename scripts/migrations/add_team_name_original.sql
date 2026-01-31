-- Migration: Add team_name_original column for backup
-- Date: 2026-01-30
-- Purpose: Store original team names before normalization

-- Add the backup column
ALTER TABLE teams ADD COLUMN IF NOT EXISTS team_name_original TEXT;

-- Create partial index for finding unprocessed teams (where original is NULL)
CREATE INDEX IF NOT EXISTS idx_teams_original_null 
ON teams (id) WHERE team_name_original IS NULL;

-- Verify column was added
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'teams' AND column_name = 'team_name_original';
