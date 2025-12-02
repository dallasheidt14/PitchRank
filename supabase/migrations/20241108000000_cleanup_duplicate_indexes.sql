-- Clean up duplicate indexes identified by Supabase linter
-- These duplicates slow down INSERTs without providing any benefit

-- =====================================================
-- GAMES TABLE - Remove older indexes, keep composite ones
-- =====================================================

-- Drop idx_games_date (keep idx_games_date_desc - more descriptive name)
DROP INDEX IF EXISTS idx_games_date;

-- Drop idx_games_home_team (keep idx_games_home_team_date - includes date)
DROP INDEX IF EXISTS idx_games_home_team;

-- Drop idx_games_away_team (keep idx_games_away_team_date - includes date)
DROP INDEX IF EXISTS idx_games_away_team;

-- Drop idx_games_uid (keep idx_games_uid_rls - RLS-specific name)
DROP INDEX IF EXISTS idx_games_uid;

-- =====================================================
-- TEAMS TABLE - Remove duplicate RLS index
-- =====================================================

-- Drop idx_teams_master_id (keep idx_teams_master_id_rls - RLS-specific)
DROP INDEX IF EXISTS idx_teams_master_id;

-- =====================================================
-- CURRENT_RANKINGS TABLE - Keep power_score, drop national
-- =====================================================

-- Drop idx_rankings_national (keep idx_rankings_power_score - more specific)
DROP INDEX IF EXISTS idx_rankings_national;

-- =====================================================
-- TEAM_ALIAS_MAP TABLE - Consolidate overlapping indexes
-- =====================================================

-- Drop idx_alias_lookup (keep idx_team_alias_provider_team_id - more specific)
DROP INDEX IF EXISTS idx_alias_lookup;

-- Drop idx_team_alias_provider (keep idx_team_alias_provider_team_id - includes team_id)
DROP INDEX IF EXISTS idx_team_alias_provider;

-- Drop idx_alias_team (keep idx_team_alias_master - more descriptive)
DROP INDEX IF EXISTS idx_alias_team;














