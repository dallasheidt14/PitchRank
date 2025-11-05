-- PitchRank Row Level Security (RLS) Migration
-- Comprehensive RLS implementation for production security
-- 
-- This migration:
-- 1. Enables RLS on all 14 core tables
-- 2. Creates helper functions for user identification
-- 3. Implements policies for anon, authenticated, and service_role
-- 4. Adds performance indexes for RLS policies
-- 5. Updates views to work properly with RLS

-- =====================================================
-- HELPER FUNCTIONS
-- =====================================================

-- Function to safely get current user ID (returns UUID or NULL)
CREATE OR REPLACE FUNCTION get_user_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT auth.uid();
$$;

COMMENT ON FUNCTION get_user_id() IS 'Returns the current authenticated user UUID, or NULL if not authenticated';

-- Function to check if current user is admin
-- Note: This assumes you'll add an admin_users table or use auth.users metadata
-- For now, this is a placeholder that returns false - customize based on your admin setup
CREATE OR REPLACE FUNCTION is_admin()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    -- Check if user exists in auth.users and has admin role
    -- Adjust this based on your admin implementation
    SELECT EXISTS (
        SELECT 1 
        FROM auth.users 
        WHERE id = auth.uid() 
        AND (raw_user_meta_data->>'role' = 'admin' OR raw_user_meta_data->>'is_admin' = 'true')
    );
$$;

COMMENT ON FUNCTION is_admin() IS 'Returns true if current user has admin privileges, false otherwise';

-- =====================================================
-- ENABLE RLS ON ALL TABLES
-- =====================================================

-- CORE DATA TABLES
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE games ENABLE ROW LEVEL SECURITY;
ALTER TABLE current_rankings ENABLE ROW LEVEL SECURITY;
ALTER TABLE providers ENABLE ROW LEVEL SECURITY;

-- MAPPING/MATCHING TABLES
ALTER TABLE team_alias_map ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_match_review_queue ENABLE ROW LEVEL SECURITY;

-- CORRECTION/AUDIT TABLES
ALTER TABLE user_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE game_corrections ENABLE ROW LEVEL SECURITY;

-- OPERATIONAL TABLES
ALTER TABLE build_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_scrape_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE validation_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_watermarks ENABLE ROW LEVEL SECURITY;

-- QUARANTINE TABLES
ALTER TABLE quarantine_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE quarantine_games ENABLE ROW LEVEL SECURITY;

-- =====================================================
-- PERFORMANCE INDEXES FOR RLS POLICIES
-- =====================================================

-- Indexes to support efficient RLS policy checks
-- Most policies will use these for fast lookups

-- User corrections: Index on submitted_by for user-specific queries
CREATE INDEX IF NOT EXISTS idx_user_corrections_submitted_by ON user_corrections(submitted_by);
CREATE INDEX IF NOT EXISTS idx_user_corrections_status_submitted ON user_corrections(status, submitted_by) WHERE status = 'pending';

-- Game corrections: Index on submitted_by for user-specific queries
CREATE INDEX IF NOT EXISTS idx_game_corrections_submitted_by ON game_corrections(submitted_by);
CREATE INDEX IF NOT EXISTS idx_game_corrections_status_submitted ON game_corrections(status, submitted_by) WHERE status = 'pending';

-- Games: Ensure game_uid index exists for corrections lookup
CREATE INDEX IF NOT EXISTS idx_games_uid_rls ON games(game_uid) WHERE game_uid IS NOT NULL;

-- Teams: Ensure team_id_master index exists (may already exist)
CREATE INDEX IF NOT EXISTS idx_teams_master_id_rls ON teams(team_id_master);

-- =====================================================
-- PUBLIC ACCESS POLICIES (anon role)
-- =====================================================

-- Teams: Public read-only access
CREATE POLICY "teams_anon_select" ON teams
    FOR SELECT
    TO anon
    USING (true);

COMMENT ON POLICY "teams_anon_select" ON teams IS 'Allows anonymous users to read all team data for public rankings';

-- Games: Public read-only access
CREATE POLICY "games_anon_select" ON games
    FOR SELECT
    TO anon
    USING (true);

COMMENT ON POLICY "games_anon_select" ON games IS 'Allows anonymous users to read all game history for public rankings';

-- Current rankings: Public read-only access
CREATE POLICY "current_rankings_anon_select" ON current_rankings
    FOR SELECT
    TO anon
    USING (true);

COMMENT ON POLICY "current_rankings_anon_select" ON current_rankings IS 'Allows anonymous users to read all rankings for public display';

-- Providers: Public read-only access
CREATE POLICY "providers_anon_select" ON providers
    FOR SELECT
    TO anon
    USING (true);

COMMENT ON POLICY "providers_anon_select" ON providers IS 'Allows anonymous users to read provider information';

-- =====================================================
-- AUTHENTICATED USER POLICIES
-- =====================================================

-- Teams: Authenticated users can read all teams
CREATE POLICY "teams_authenticated_select" ON teams
    FOR SELECT
    TO authenticated
    USING (true);

COMMENT ON POLICY "teams_authenticated_select" ON teams IS 'Allows authenticated users to read all team data';

-- Games: Authenticated users can read all games
CREATE POLICY "games_authenticated_select" ON games
    FOR SELECT
    TO authenticated
    USING (true);

COMMENT ON POLICY "games_authenticated_select" ON games IS 'Allows authenticated users to read all game history';

-- Current rankings: Authenticated users can read all rankings
CREATE POLICY "current_rankings_authenticated_select" ON current_rankings
    FOR SELECT
    TO authenticated
    USING (true);

COMMENT ON POLICY "current_rankings_authenticated_select" ON current_rankings IS 'Allows authenticated users to read all rankings';

-- Providers: Authenticated users can read all providers
CREATE POLICY "providers_authenticated_select" ON providers
    FOR SELECT
    TO authenticated
    USING (true);

COMMENT ON POLICY "providers_authenticated_select" ON providers IS 'Allows authenticated users to read provider information';

-- User corrections: Authenticated users can create their own corrections
-- Note: submitted_by must be set to the current user's UUID as text
-- The application should set this field, or use the trigger below
CREATE POLICY "user_corrections_authenticated_insert" ON user_corrections
    FOR INSERT
    TO authenticated
    WITH CHECK (
        submitted_by = get_user_id()::text
    );

COMMENT ON POLICY "user_corrections_authenticated_insert" ON user_corrections IS 'Allows authenticated users to create corrections with their own user ID';

-- User corrections: Authenticated users can read their own corrections
CREATE POLICY "user_corrections_authenticated_select" ON user_corrections
    FOR SELECT
    TO authenticated
    USING (
        submitted_by = get_user_id()::text
    );

COMMENT ON POLICY "user_corrections_authenticated_select" ON user_corrections IS 'Allows authenticated users to read only their own corrections';

-- User corrections: Authenticated users can update only their own pending corrections
CREATE POLICY "user_corrections_authenticated_update" ON user_corrections
    FOR UPDATE
    TO authenticated
    USING (
        submitted_by = get_user_id()::text 
        AND status = 'pending'
    )
    WITH CHECK (
        submitted_by = get_user_id()::text 
        AND status = 'pending'
    );

COMMENT ON POLICY "user_corrections_authenticated_update" ON user_corrections IS 'Allows authenticated users to update only their own pending corrections';

-- Game corrections: Authenticated users can create their own corrections
-- Note: submitted_by must be set to the current user's UUID as text
-- The application should set this field when creating corrections
CREATE POLICY "game_corrections_authenticated_insert" ON game_corrections
    FOR INSERT
    TO authenticated
    WITH CHECK (
        submitted_by = get_user_id()::text
    );

COMMENT ON POLICY "game_corrections_authenticated_insert" ON game_corrections IS 'Allows authenticated users to create game corrections with their own user ID';

-- Game corrections: Authenticated users can read their own corrections
CREATE POLICY "game_corrections_authenticated_select" ON game_corrections
    FOR SELECT
    TO authenticated
    USING (
        submitted_by = get_user_id()::text
    );

COMMENT ON POLICY "game_corrections_authenticated_select" ON game_corrections IS 'Allows authenticated users to read only their own game corrections';

-- Game corrections: Authenticated users can update only their own pending corrections
CREATE POLICY "game_corrections_authenticated_update" ON game_corrections
    FOR UPDATE
    TO authenticated
    USING (
        submitted_by = get_user_id()::text 
        AND status = 'pending'
    )
    WITH CHECK (
        submitted_by = get_user_id()::text 
        AND status = 'pending'
    );

COMMENT ON POLICY "game_corrections_authenticated_update" ON game_corrections IS 'Allows authenticated users to update only their own pending game corrections';

-- =====================================================
-- BLOCK ANON/AUTHENTICATED FROM OPERATIONAL TABLES
-- =====================================================

-- Team alias map: No access for anon/authenticated (admin only)
CREATE POLICY "team_alias_map_deny_all" ON team_alias_map
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_alias_map_deny_all" ON team_alias_map IS 'Blocks all access to team alias mappings for non-service roles';

-- Team match review queue: No access for anon/authenticated (admin only)
CREATE POLICY "team_match_review_queue_deny_all" ON team_match_review_queue
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_match_review_queue_deny_all" ON team_match_review_queue IS 'Blocks all access to match review queue for non-service roles';

-- Build logs: No access for anon/authenticated (admin only)
CREATE POLICY "build_logs_deny_all" ON build_logs
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "build_logs_deny_all" ON build_logs IS 'Blocks all access to build logs for non-service roles';

-- Team scrape log: No access for anon/authenticated (admin only)
CREATE POLICY "team_scrape_log_deny_all" ON team_scrape_log
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_scrape_log_deny_all" ON team_scrape_log IS 'Blocks all access to scrape logs for non-service roles';

-- Validation errors: No access for anon/authenticated (admin only)
CREATE POLICY "validation_errors_deny_all" ON validation_errors
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "validation_errors_deny_all" ON validation_errors IS 'Blocks all access to validation errors for non-service roles';

-- Scrape watermarks: No access for anon/authenticated (admin only)
CREATE POLICY "scrape_watermarks_deny_all" ON scrape_watermarks
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "scrape_watermarks_deny_all" ON scrape_watermarks IS 'Blocks all access to scrape watermarks for non-service roles';

-- Quarantine teams: No access for anon/authenticated (admin only)
CREATE POLICY "quarantine_teams_deny_all" ON quarantine_teams
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "quarantine_teams_deny_all" ON quarantine_teams IS 'Blocks all access to quarantined teams for non-service roles';

-- Quarantine games: No access for anon/authenticated (admin only)
CREATE POLICY "quarantine_games_deny_all" ON quarantine_games
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "quarantine_games_deny_all" ON quarantine_games IS 'Blocks all access to quarantined games for non-service roles';

-- =====================================================
-- SERVICE ROLE POLICIES
-- =====================================================

-- Note: service_role bypasses RLS by default in Supabase
-- However, we explicitly allow all operations for clarity and documentation

-- Teams: Service role has full access
CREATE POLICY "teams_service_role_all" ON teams
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "teams_service_role_all" ON teams IS 'Service role has full access to teams table for ETL operations';

-- Games: Service role has full access
CREATE POLICY "games_service_role_all" ON games
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "games_service_role_all" ON games IS 'Service role has full access to games table for ETL operations';

-- Current rankings: Service role has full access
CREATE POLICY "current_rankings_service_role_all" ON current_rankings
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "current_rankings_service_role_all" ON current_rankings IS 'Service role has full access to rankings table for calculation updates';

-- Providers: Service role has full access
CREATE POLICY "providers_service_role_all" ON providers
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "providers_service_role_all" ON providers IS 'Service role has full access to providers table';

-- Team alias map: Service role has full access
CREATE POLICY "team_alias_map_service_role_all" ON team_alias_map
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_alias_map_service_role_all" ON team_alias_map IS 'Service role has full access to team alias mappings for ETL operations';

-- Team match review queue: Service role has full access
CREATE POLICY "team_match_review_queue_service_role_all" ON team_match_review_queue
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_match_review_queue_service_role_all" ON team_match_review_queue IS 'Service role has full access to match review queue for ETL operations';

-- User corrections: Service role has full access
CREATE POLICY "user_corrections_service_role_all" ON user_corrections
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "user_corrections_service_role_all" ON user_corrections IS 'Service role has full access to user corrections for admin review';

-- Game corrections: Service role has full access
CREATE POLICY "game_corrections_service_role_all" ON game_corrections
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "game_corrections_service_role_all" ON game_corrections IS 'Service role has full access to game corrections for admin review';

-- Build logs: Service role has full access
CREATE POLICY "build_logs_service_role_all" ON build_logs
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "build_logs_service_role_all" ON build_logs IS 'Service role has full access to build logs for ETL tracking';

-- Team scrape log: Service role has full access
CREATE POLICY "team_scrape_log_service_role_all" ON team_scrape_log
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_scrape_log_service_role_all" ON team_scrape_log IS 'Service role has full access to scrape logs for ETL tracking';

-- Validation errors: Service role has full access
CREATE POLICY "validation_errors_service_role_all" ON validation_errors
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "validation_errors_service_role_all" ON validation_errors IS 'Service role has full access to validation errors for ETL tracking';

-- Scrape watermarks: Service role has full access
CREATE POLICY "scrape_watermarks_service_role_all" ON scrape_watermarks
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "scrape_watermarks_service_role_all" ON scrape_watermarks IS 'Service role has full access to scrape watermarks for ETL tracking';

-- Quarantine teams: Service role has full access
CREATE POLICY "quarantine_teams_service_role_all" ON quarantine_teams
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "quarantine_teams_service_role_all" ON quarantine_teams IS 'Service role has full access to quarantined teams for review';

-- Quarantine games: Service role has full access
CREATE POLICY "quarantine_games_service_role_all" ON quarantine_games
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "quarantine_games_service_role_all" ON quarantine_games IS 'Service role has full access to quarantined games for review';

-- =====================================================
-- TRIGGERS FOR AUTO-SETTING USER ID
-- =====================================================

-- Optional: Trigger to auto-set submitted_by for user_corrections
-- This ensures submitted_by is always set correctly even if application doesn't set it
CREATE OR REPLACE FUNCTION set_user_correction_submitter()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    -- Only set if not already set or if set to NULL
    IF NEW.submitted_by IS NULL OR NEW.submitted_by = '' THEN
        NEW.submitted_by := get_user_id()::text;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION set_user_correction_submitter() IS 'Automatically sets submitted_by to current user UUID when creating user corrections';

-- Create trigger for user_corrections
DROP TRIGGER IF EXISTS trigger_set_user_correction_submitter ON user_corrections;
CREATE TRIGGER trigger_set_user_correction_submitter
    BEFORE INSERT ON user_corrections
    FOR EACH ROW
    EXECUTE FUNCTION set_user_correction_submitter();

-- Optional: Trigger to auto-set submitted_by for game_corrections
CREATE OR REPLACE FUNCTION set_game_correction_submitter()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    -- Only set if not already set or if set to NULL
    IF NEW.submitted_by IS NULL OR NEW.submitted_by = '' THEN
        NEW.submitted_by := get_user_id()::text;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION set_game_correction_submitter() IS 'Automatically sets submitted_by to current user UUID when creating game corrections';

-- Create trigger for game_corrections
DROP TRIGGER IF EXISTS trigger_set_game_correction_submitter ON game_corrections;
CREATE TRIGGER trigger_set_game_correction_submitter
    BEFORE INSERT ON game_corrections
    FOR EACH ROW
    EXECUTE FUNCTION set_game_correction_submitter();

-- =====================================================
-- UPDATE VIEWS TO WORK WITH RLS
-- =====================================================

-- Views inherit RLS from their underlying tables
-- Since our views join public tables, they will work correctly with RLS
-- However, we need to ensure views are SECURITY INVOKER (default) so they respect RLS

-- Recreate views with explicit SECURITY INVOKER to ensure RLS is enforced
-- Note: These views don't need to be SECURITY DEFINER since they're just SELECT queries

-- Rankings by age and gender (already uses public tables, will respect RLS)
CREATE OR REPLACE VIEW rankings_by_age_gender
WITH (security_invoker = true)
AS
SELECT 
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code,
    t.age_group,
    t.gender,
    r.national_rank,
    r.state_rank,
    r.national_power_score,
    r.global_power_score,
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.win_percentage,
    r.strength_of_schedule
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
ORDER BY t.age_group, t.gender, r.national_rank;

COMMENT ON VIEW rankings_by_age_gender IS 'Public view of rankings by age group and gender. Respects RLS policies.';

-- State rankings (already uses public tables, will respect RLS)
CREATE OR REPLACE VIEW state_rankings
WITH (security_invoker = true)
AS
SELECT 
    t.team_id_master,
    t.team_name,
    t.state_code,
    t.age_group,
    t.gender,
    r.state_rank,
    r.national_rank,
    r.national_power_score,
    r.global_power_score
FROM current_rankings r
JOIN teams t ON r.team_id = t.team_id_master
ORDER BY t.state_code, t.age_group, t.gender, r.state_rank;

COMMENT ON VIEW state_rankings IS 'Public view of state rankings. Respects RLS policies.';

-- Aliases pending review (admin-only view, uses restricted table)
CREATE OR REPLACE VIEW aliases_pending_review
WITH (security_invoker = true)
AS
SELECT 
    a.id,
    a.provider_team_id,
    a.team_id_master,
    t.team_name,
    t.age_group,
    t.gender,
    a.match_method,
    a.match_confidence,
    p.name as provider_name
FROM team_alias_map a
JOIN teams t ON a.team_id_master = t.team_id_master
JOIN providers p ON a.provider_id = p.id
WHERE a.review_status = 'pending'
ORDER BY a.match_confidence DESC, a.created_at ASC;

COMMENT ON VIEW aliases_pending_review IS 'Admin-only view of pending alias reviews. Access restricted by RLS on team_alias_map.';

-- Recent builds (admin-only view, uses restricted table)
CREATE OR REPLACE VIEW recent_builds
WITH (security_invoker = true)
AS
SELECT 
    bl.build_id,
    bl.stage,
    p.name as provider_name,
    bl.started_at,
    bl.completed_at,
    bl.records_processed,
    bl.records_succeeded,
    bl.records_failed,
    CASE 
        WHEN bl.completed_at IS NULL THEN 'running'
        WHEN bl.records_failed > 0 THEN 'partial'
        ELSE 'success'
    END as status
FROM build_logs bl
LEFT JOIN providers p ON bl.provider_id = p.id
ORDER BY bl.started_at DESC
LIMIT 100;

COMMENT ON VIEW recent_builds IS 'Admin-only view of recent build activity. Access restricted by RLS on build_logs.';

-- Pending alias reviews (admin-only view, uses restricted table)
CREATE OR REPLACE VIEW pending_alias_reviews
WITH (security_invoker = true)
AS
SELECT 
    a.id,
    a.provider_id,
    p.name as provider_name,
    a.provider_team_id,
    a.team_id_master,
    t.team_name as matched_team_name,
    t.age_group,
    t.gender,
    a.match_method,
    a.match_confidence,
    a.created_at,
    CASE 
        WHEN a.match_confidence >= 0.85 THEN 'high'
        WHEN a.match_confidence >= 0.80 THEN 'medium'
        ELSE 'low'
    END as confidence_level
FROM team_alias_map a
JOIN providers p ON a.provider_id = p.id
LEFT JOIN teams t ON a.team_id_master = t.team_id_master
WHERE a.review_status = 'pending'
  AND a.match_confidence >= 0.75
  AND a.match_confidence < 0.9
ORDER BY a.match_confidence DESC, a.created_at ASC;

COMMENT ON VIEW pending_alias_reviews IS 'Admin-only view of pending alias reviews. Access restricted by RLS on team_alias_map.';

-- Recent quarantine (admin-only view, uses restricted tables)
CREATE OR REPLACE VIEW recent_quarantine
WITH (security_invoker = true)
AS
SELECT 
    'team' as type,
    id,
    reason_code,
    error_details,
    created_at
FROM quarantine_teams
UNION ALL
SELECT 
    'game' as type,
    id,
    reason_code,
    error_details,
    created_at
FROM quarantine_games
ORDER BY created_at DESC
LIMIT 100;

COMMENT ON VIEW recent_quarantine IS 'Admin-only view of recent quarantine entries. Access restricted by RLS on quarantine tables.';

-- Pending match reviews (admin-only view, uses restricted table)
CREATE OR REPLACE VIEW pending_match_reviews
WITH (security_invoker = true)
AS
SELECT 
    q.id,
    q.provider_id,
    q.provider_team_id,
    q.provider_team_name,
    q.suggested_master_team_id,
    t.team_name as suggested_team_name,
    t.age_group as suggested_age_group,
    t.gender as suggested_gender,
    t.state_code as suggested_state,
    q.confidence_score,
    q.match_details,
    q.created_at
FROM team_match_review_queue q
LEFT JOIN teams t ON t.team_id_master = q.suggested_master_team_id
WHERE q.status = 'pending'
ORDER BY q.confidence_score DESC, q.created_at ASC;

COMMENT ON VIEW pending_match_reviews IS 'Admin-only view of pending match reviews. Access restricted by RLS on team_match_review_queue.';

-- Match type statistics (admin-only view, uses restricted table)
CREATE OR REPLACE VIEW match_type_statistics
WITH (security_invoker = true)
AS
SELECT 
    provider_id,
    p.name as provider_name,
    match_method,
    COUNT(*) as mapping_count,
    AVG(match_confidence) as avg_confidence,
    MIN(match_confidence) as min_confidence,
    MAX(match_confidence) as max_confidence
FROM team_alias_map tam
JOIN providers p ON tam.provider_id = p.id
GROUP BY provider_id, p.name, match_method
ORDER BY provider_id, mapping_count DESC;

COMMENT ON VIEW match_type_statistics IS 'Admin-only view of match type statistics. Access restricted by RLS on team_alias_map.';

-- Build metrics summary (admin-only view, uses restricted table)
CREATE OR REPLACE VIEW build_metrics_summary
WITH (security_invoker = true)
AS
SELECT 
    build_id,
    stage,
    provider_id,
    started_at,
    completed_at,
    records_processed,
    records_succeeded,
    records_failed,
    metrics->>'games_processed' AS games_processed,
    metrics->>'games_accepted' AS games_accepted,
    metrics->>'games_quarantined' AS games_quarantined,
    metrics->>'duplicates_found' AS duplicates_found,
    metrics->>'teams_matched' AS teams_matched,
    metrics->>'teams_created' AS teams_created,
    metrics->>'fuzzy_matches_auto' AS fuzzy_matches_auto,
    metrics->>'fuzzy_matches_manual' AS fuzzy_matches_manual,
    metrics->>'fuzzy_matches_rejected' AS fuzzy_matches_rejected,
    metrics->>'processing_time_seconds' AS processing_time_seconds,
    metrics->>'memory_usage_mb' AS memory_usage_mb,
    metrics->'errors' AS errors
FROM build_logs
WHERE metrics IS NOT NULL AND metrics != '{}'::JSONB
ORDER BY started_at DESC;

COMMENT ON VIEW build_metrics_summary IS 'Admin-only view of build metrics. Access restricted by RLS on build_logs.';

-- =====================================================
-- MIGRATION COMPLETE
-- =====================================================

-- Summary:
-- ✅ RLS enabled on all 14 tables
-- ✅ Helper functions created (get_user_id, is_admin)
-- ✅ Public read policies for teams, games, current_rankings, providers
-- ✅ Authenticated user policies for user_corrections and game_corrections
-- ✅ Block policies for operational and quarantine tables (anon/authenticated)
-- ✅ Service role policies for all tables (full access)
-- ✅ Performance indexes added for RLS policies
-- ✅ All views updated with security_invoker to respect RLS

