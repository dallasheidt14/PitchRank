-- Add league column to teams table for tier-based ranking adjustments
ALTER TABLE teams ADD COLUMN IF NOT EXISTS league TEXT;

-- Index for fast lookups during ranking computation
CREATE INDEX IF NOT EXISTS idx_teams_league ON teams (league);

COMMENT ON COLUMN teams.league IS 'National league affiliation (ECNL, ECNL_RL, MLS_NEXT_HD, MLS_NEXT_AD, GA, DPL, NPL, EA, NL, ASPIRE). NULL = unaffiliated.';
