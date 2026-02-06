-- Create get_biggest_movers RPC function
-- Used by /api/infographic/movers to generate real movers infographics
-- instead of hardcoded mock data

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
    rf.rank_in_cohort_final AS current_rank
  FROM rankings_full rf
  JOIN teams t ON t.team_id_master = rf.team_id_master
  WHERE rf.rank_in_cohort_final IS NOT NULL
    AND CASE
      WHEN p_days <= 7 THEN rf.rank_change_7d
      ELSE rf.rank_change_30d
    END IS NOT NULL
    AND (
      (p_direction = 'up' AND CASE WHEN p_days <= 7 THEN rf.rank_change_7d ELSE rf.rank_change_30d END > 0)
      OR
      (p_direction = 'down' AND CASE WHEN p_days <= 7 THEN rf.rank_change_7d ELSE rf.rank_change_30d END < 0)
    )
    AND (p_age_group IS NULL OR rf.age::text = REPLACE(LOWER(p_age_group), 'u', ''))
    AND (p_gender IS NULL OR LOWER(rf.gender) = LOWER(p_gender))
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
