-- Align get_biggest_movers.current_rank to the published rank.
--
-- current_rank was COALESCE(rank_in_cohort_ml, rank_in_cohort), but the site and
-- every rank-dependent feature use rank_in_cohort_final (power_score_final ordering;
-- see rankings_full.rank_in_cohort_final). The movers/spotlight infographics and the
-- marketing pipeline therefore displayed a rank that did not match pitchrank.io, and
-- mixed bases with rank_change (which ranking_history.py computes from the final rank
-- with the final ?? ml ?? base fallback).
--
-- Switch to COALESCE(rank_in_cohort_final, rank_in_cohort_ml, rank_in_cohort) so the
-- displayed rank matches the published rank and the rank_change basis. Return type is
-- unchanged, so no DROP is needed (only the SELECT/WHERE expressions change).

CREATE OR REPLACE FUNCTION get_biggest_movers(
  p_days INT DEFAULT 7,
  p_limit INT DEFAULT 5,
  p_direction TEXT DEFAULT 'up',
  p_age_group TEXT DEFAULT NULL,
  p_gender TEXT DEFAULT NULL
)
RETURNS TABLE (
  team_id UUID,
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
    rf.team_id,
    t.team_name,
    t.club_name,
    t.state_code,
    CASE
      WHEN p_days <= 7 THEN rf.rank_change_7d
      ELSE rf.rank_change_30d
    END AS rank_change,
    COALESCE(rf.rank_in_cohort_final, rf.rank_in_cohort_ml, rf.rank_in_cohort) AS current_rank
  FROM rankings_full rf
  JOIN teams t ON t.team_id_master = rf.team_id
  WHERE COALESCE(rf.rank_in_cohort_final, rf.rank_in_cohort_ml, rf.rank_in_cohort) IS NOT NULL
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
    -- Exclude teams with fewer than 8 games (unreliable rank swings)
    AND COALESCE(rf.games_played, 0) >= 8
    -- Exclude teams that just became ranked
    AND COALESCE(rf.status, '') != 'Not Enough Ranked Games'
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

-- Frontend infographic routes call this RPC with NEXT_PUBLIC_SUPABASE_ANON_KEY;
-- keep the grant self-contained so a fresh deploy does not depend on env defaults.
GRANT EXECUTE ON FUNCTION get_biggest_movers TO authenticated, anon;
