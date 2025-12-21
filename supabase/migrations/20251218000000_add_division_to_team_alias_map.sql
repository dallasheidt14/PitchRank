-- Add division column to team_alias_map for MLS NEXT HD/AD differentiation
--
-- Problem: Modular11 uses the SAME provider_team_id (e.g., "391") for both
-- HD (Homegrown Division) and AD (Academy Division) teams. Without a way to
-- differentiate, games get assigned to whichever team alias was created first.
--
-- Solution:
-- 1. Add division column to store HD/AD designation
-- 2. The matcher will now create division-suffixed provider_team_ids (e.g., "391_HD", "391_AD")
--    allowing separate aliases for each division variant

-- Add division column to team_alias_map
ALTER TABLE team_alias_map
ADD COLUMN IF NOT EXISTS division TEXT;

-- Add comment explaining the column
COMMENT ON COLUMN team_alias_map.division IS
    'MLS NEXT division: HD (Homegrown Division) or AD (Academy Division). Used by Modular11 provider to differentiate teams with the same club ID but different competitive tiers.';

-- Create index for division lookups (useful for filtering aliases by division)
CREATE INDEX IF NOT EXISTS idx_team_alias_map_division
ON team_alias_map(division)
WHERE division IS NOT NULL;

-- Create composite index for division-aware lookups
CREATE INDEX IF NOT EXISTS idx_team_alias_map_provider_division
ON team_alias_map(provider_id, division)
WHERE division IS NOT NULL;
