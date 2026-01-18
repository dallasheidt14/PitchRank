-- Migration: Add division column to team_alias_map for Modular11 HD/AD tracking
-- Date: 2025-12-05
-- Purpose: Store division information (HD/AD) for Modular11 teams in alias map
--          This allows tracking division without polluting the master teams table
--          and supports proper division-aware fuzzy matching

-- Add division column to team_alias_map
ALTER TABLE public.team_alias_map
ADD COLUMN IF NOT EXISTS division TEXT NULL;

-- Add comment explaining the column
COMMENT ON COLUMN public.team_alias_map.division IS 
'Division for Modular11 teams: HD (Homegrown Division) or AD (Academy Division). NULL for other providers or when division is not applicable.';

-- Create index for division lookups (optional, but helpful for Modular11 queries)
CREATE INDEX IF NOT EXISTS idx_team_alias_map_division 
ON public.team_alias_map(provider_id, division) 
WHERE division IS NOT NULL;













