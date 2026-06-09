-- Migration: Add active-only rankings count RPCs
-- Date: 2026-06-09
-- Purpose: Cohort "at a Glance" pages display an "active teams" count. The page
--          only fetches the top 2,000 ranked teams, so totalTeams = teams.length
--          undercounts large cohorts (e.g. national U12 boys shows 2,000 instead
--          of 6,170). These RPCs return the true count of Active teams, mirroring
--          the *_rankings_count filters but excluding 'Not Enough Ranked Games'.

-- =====================================================
-- Function 1: get_national_active_count - true Active count for a national cohort
-- =====================================================

CREATE OR REPLACE FUNCTION get_national_active_count(
    p_age TEXT DEFAULT '',
    p_gender TEXT DEFAULT ''
)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    WITH age_norm AS (
        SELECT CASE
            WHEN NULLIF(p_age, '') IS NULL THEN NULL
            WHEN p_age::INTEGER = 18 THEN 19
            ELSE p_age::INTEGER
        END AS age_val
    )
    SELECT COUNT(*)
    FROM rankings_full rf
    JOIN teams t ON t.team_id_master = rf.team_id
    CROSS JOIN age_norm an
    WHERE rf.status = 'Active'
      AND t.is_deprecated IS NOT TRUE
      AND rf.power_score_final IS NOT NULL
      AND (
          an.age_val IS NULL
          OR
          CASE
              WHEN (
                  CASE
                      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                      WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                      ELSE NULL
                  END
              ) = 18 THEN 19
              ELSE
                  CASE
                      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                      WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                      ELSE NULL
                  END
          END = an.age_val
      )
      AND (
          NULLIF(p_gender, '') IS NULL
          OR rf.gender = CASE
              WHEN p_gender IN ('M', 'B') THEN 'Male'
              WHEN p_gender IN ('F', 'G') THEN 'Female'
              ELSE p_gender
          END
      );
$$;

COMMENT ON FUNCTION get_national_active_count IS
  'Fast count of Active national teams for an age/gender cohort. Mirrors '
  'get_national_rankings_count but excludes ''Not Enough Ranked Games'' so the '
  'cohort "active teams" figure is not inflated by unranked teams.';

-- =====================================================
-- Function 2: get_state_active_count - true Active count for a state cohort
-- =====================================================

CREATE OR REPLACE FUNCTION get_state_active_count(
    p_state TEXT,
    p_age TEXT,
    p_gender TEXT
)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    SELECT COUNT(*)
    FROM rankings_full rf
    JOIN teams t ON t.team_id_master = rf.team_id
    WHERE rf.state_code = UPPER(p_state)
      AND rf.age_group = ANY (
          CASE WHEN (CASE WHEN p_age::INTEGER = 18 THEN 19 ELSE p_age::INTEGER END) = 19
               THEN ARRAY['u19','U19','19','u18','U18','18']
               ELSE ARRAY['u'||(p_age::INTEGER)::text, 'U'||(p_age::INTEGER)::text, (p_age::INTEGER)::text]
          END
      )
      AND rf.gender = CASE
          WHEN p_gender IN ('M', 'B') THEN 'Male'
          WHEN p_gender IN ('F', 'G') THEN 'Female'
          ELSE p_gender
      END
      AND rf.status = 'Active'
      AND t.is_deprecated IS NOT TRUE
      AND rf.power_score_final IS NOT NULL;
$$;

COMMENT ON FUNCTION get_state_active_count IS
  'Fast count of Active teams for a state age/gender cohort. Mirrors '
  'get_state_rankings_count but excludes ''Not Enough Ranked Games''.';

-- =====================================================
-- Grant permissions
-- =====================================================

GRANT EXECUTE ON FUNCTION get_national_active_count(TEXT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION get_national_active_count(TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_state_active_count(TEXT, TEXT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION get_state_active_count(TEXT, TEXT, TEXT) TO authenticated;
