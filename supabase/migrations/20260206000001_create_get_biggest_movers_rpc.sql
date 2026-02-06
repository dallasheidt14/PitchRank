-- Create get_biggest_movers RPC function
-- Used by /api/infographic/movers to generate real movers infographics
-- instead of hardcoded mock data
--
-- Schema reference (rankings_full):
--   PK: team_id UUID (references teams.team_id_master)
--   age_group TEXT (e.g., 'u12', '12')
--   gender TEXT (e.g., 'Male', 'Female', 'M', 'F')
--   rank_in_cohort INTEGER, rank_in_cohort_ml INTEGER
--   rank_change_7d INTEGER, rank_change_30d INTEGER

CREATE OR REPLACE FUNCTION get_biggest_movers(
  p_days INT DEFAULT 7,
  p_limit INT DEFAULT 5,
  p_direction TEXT DEFAULT 'up',
  p_age_group TEXT DEFAULT NULL,
  p_gender TEXT DEFAULT NULL
)
RETURNS TABLE (
  team_name TEXT,
  club_name TEXT,
  state_code TEXT,
  rank_change INT,
  current_rank INT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    t.team_name,
    t.club_name,
    t.state_code,
    CASE
      WHEN p_days <= 7 THEN rf.rank_change_7d
      ELSE rf.rank_change_30d
    END AS rank_change,
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS current_rank
  FROM rankings_full rf
  JOIN teams t ON t.team_id_master = rf.team_id
  WHERE COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) IS NOT NULL
    AND CASE
      WHEN p_days <= 7 THEN rf.rank_change_7d
      ELSE rf.rank_change_30d
    END IS NOT NULL
    AND (
      (p_direction = 'up' AND CASE WHEN p_days <= 7 THEN rf.rank_change_7d ELSE rf.rank_change_30d END > 0)
      OR
      (p_direction = 'down' AND CASE WHEN p_days <= 7 THEN rf.rank_change_7d ELSE rf.rank_change_30d END < 0)
    )
    AND (
      p_age_group IS NULL
      OR LOWER(rf.age_group) = LOWER(p_age_group)
      OR rf.age_group = REPLACE(LOWER(p_age_group), 'u', '')
    )
    AND (
      p_gender IS NULL
      OR LOWER(rf.gender) = LOWER(p_gender)
      OR (LOWER(p_gender) = 'male' AND rf.gender IN ('M', 'Male', 'Boys'))
      OR (LOWER(p_gender) = 'female' AND rf.gender IN ('F', 'Female', 'Girls'))
      OR (LOWER(p_gender) = 'm' AND rf.gender IN ('M', 'Male', 'Boys'))
      OR (LOWER(p_gender) = 'f' AND rf.gender IN ('F', 'Female', 'Girls'))
    )
    AND t.is_deprecated IS NOT TRUE
  ORDER BY
    CASE
      WHEN p_direction = 'up' THEN
        CASE WHEN p_days <= 7 THEN rf.rank_change_7d ELSE rf.rank_change_30d END
    END DESC NULLS LAST,
    CASE
      WHEN p_direction = 'down' THEN
        CASE WHEN p_days <= 7 THEN rf.rank_change_7d ELSE rf.rank_change_30d END
    END ASC NULLS LAST
  LIMIT p_limit;
$$;

-- Grant execute to authenticated and anon roles
GRANT EXECUTE ON FUNCTION get_biggest_movers TO authenticated, anon;
