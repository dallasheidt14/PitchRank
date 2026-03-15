-- Add profile_level to team_social_profiles.
--
-- Phase 1 (club sweep):  profile_level = 'club'
--   Searches once per unique club name.
--   One handle covers all teams in that club.
--
-- Phase 2 (team sweep):  profile_level = 'team'
--   Searches for team-specific accounts using birth_year + gender.
--   Runs after Phase 1; gives teams a more specific handle when one exists.
--
-- The unique constraint changes from (team_id, platform, handle)
-- to (team_id, platform, profile_level) — one club handle and one team
-- handle per team per platform, with full upsert support on re-runs.

ALTER TABLE team_social_profiles
    ADD COLUMN IF NOT EXISTS profile_level TEXT NOT NULL DEFAULT 'club'
        CHECK (profile_level IN ('club', 'team'));

-- Swap unique constraint
ALTER TABLE team_social_profiles
    DROP CONSTRAINT IF EXISTS team_social_profiles_team_id_platform_handle_key;

ALTER TABLE team_social_profiles
    ADD CONSTRAINT team_social_profiles_team_platform_level_key
        UNIQUE (team_id, platform, profile_level);

CREATE INDEX IF NOT EXISTS idx_team_social_profiles_profile_level
    ON team_social_profiles (profile_level);

-- Rebuild views to expose profile_level.
-- Must DROP first — CREATE OR REPLACE VIEW cannot insert columns mid-list.
DROP VIEW IF EXISTS team_instagram_review_queue;
DROP VIEW IF EXISTS team_instagram_handles;

CREATE VIEW team_instagram_handles AS
SELECT
    tsp.id,
    tsp.team_id,
    t.team_name,
    t.club_name,
    t.birth_year,
    t.gender,
    t.age_group,
    t.state_code,
    tsp.handle,
    tsp.profile_url,
    tsp.confidence_score,
    tsp.review_status,
    tsp.found_at,
    tsp.last_checked_at,
    tsp.profile_level
FROM team_social_profiles tsp
JOIN teams t ON t.team_id_master = tsp.team_id
WHERE tsp.platform = 'instagram'
  AND tsp.review_status IN ('auto_approved', 'confirmed');

CREATE VIEW team_instagram_review_queue AS
SELECT
    tsp.id,
    tsp.team_id,
    t.team_name,
    t.club_name,
    t.birth_year,
    t.gender,
    t.age_group,
    t.state_code,
    tsp.handle,
    tsp.profile_url,
    tsp.confidence_score,
    tsp.query_used,
    tsp.match_details,
    tsp.found_at,
    tsp.profile_level
FROM team_social_profiles tsp
JOIN teams t ON t.team_id_master = tsp.team_id
WHERE tsp.platform = 'instagram'
  AND tsp.review_status = 'needs_review'
ORDER BY tsp.profile_level, tsp.confidence_score DESC;
