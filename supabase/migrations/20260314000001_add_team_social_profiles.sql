-- team_social_profiles
-- Stores discovered social media handles for teams with confidence scores.
-- Populated by scripts/enrich_instagram_handles.py
-- review_status lifecycle: needs_review → confirmed | rejected
--                          auto_approved → confirmed | rejected
--
-- Confidence bands (Instagram):
--   >= 0.85  auto_approved  (high-confidence match, no review needed)
--   0.60-0.84  needs_review  (plausible, human should verify)
--   < 0.60   rejected  (not stored by default)

CREATE TABLE IF NOT EXISTS team_social_profiles (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- FK to teams.team_id_master (canonical UUID, consistent with all other tables)
    team_id          UUID NOT NULL REFERENCES teams(team_id_master) ON DELETE CASCADE,

    platform         TEXT NOT NULL DEFAULT 'instagram'
                       CHECK (platform IN ('instagram', 'twitter', 'facebook', 'tiktok', 'youtube')),

    handle           TEXT,                    -- e.g. dynamos_sc_g11
    profile_url      TEXT,                    -- e.g. https://instagram.com/dynamos_sc_g11

    confidence_score NUMERIC(4,3),            -- 0.000 – 1.000

    -- The best search query that produced this result
    query_used       TEXT,

    -- Per-component score breakdown + raw title/snippet for debugging
    -- { club_score, year_score, gender_score, tier_score, title, snippet }
    match_details    JSONB,

    review_status    TEXT NOT NULL DEFAULT 'needs_review'
                       CHECK (review_status IN (
                           'auto_approved',  -- script confidence >= 0.85
                           'needs_review',   -- script confidence 0.60-0.84
                           'confirmed',      -- human verified as correct
                           'rejected'        -- human confirmed as wrong
                       )),

    found_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One handle per team per platform (upsert key)
    UNIQUE (team_id, platform, handle)
);

-- Indexes for common access patterns
CREATE INDEX IF NOT EXISTS idx_team_social_profiles_team_id
    ON team_social_profiles (team_id);

CREATE INDEX IF NOT EXISTS idx_team_social_profiles_review_status
    ON team_social_profiles (review_status);

CREATE INDEX IF NOT EXISTS idx_team_social_profiles_platform_status
    ON team_social_profiles (platform, review_status);

CREATE INDEX IF NOT EXISTS idx_team_social_profiles_confidence
    ON team_social_profiles (confidence_score DESC);

-- Convenience view: approved/confirmed Instagram handles with team identity
CREATE OR REPLACE VIEW team_instagram_handles AS
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
    tsp.last_checked_at
FROM team_social_profiles tsp
JOIN teams t ON t.team_id_master = tsp.team_id
WHERE tsp.platform = 'instagram'
  AND tsp.review_status IN ('auto_approved', 'confirmed');

-- Review queue view: needs_review records with team context
CREATE OR REPLACE VIEW team_instagram_review_queue AS
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
    tsp.found_at
FROM team_social_profiles tsp
JOIN teams t ON t.team_id_master = tsp.team_id
WHERE tsp.platform = 'instagram'
  AND tsp.review_status = 'needs_review'
ORDER BY tsp.confidence_score DESC;
