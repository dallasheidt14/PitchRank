-- Biggest movers within a state cohort (state_code x age_group x gender)
-- rather than the national cohort.
--
-- The national get_biggest_movers ranks within huge national cohorts (thousands
-- of teams per age/gender), so a legitimate weekly score change moves a team
-- 1000+ positions -> "+2035 spots" copy. State cohorts are far smaller, so the
-- deltas are believable and the movers are locally relevant.
--
-- current_rank is the team's rank within its state cohort, derived on the fly
-- from rank_in_cohort_final (the published national-cohort rank already orders
-- teams correctly, so ranking by it within a state yields the state position).
-- rank_change is rank_change_state_7d/30d, computed by the ranking engine
-- (ranking_history.py) and persisted in rankings_full.

CREATE OR REPLACE FUNCTION get_biggest_state_movers(
  p_state TEXT,
  p_limit INT DEFAULT 5,
  p_direction TEXT DEFAULT 'up',
  p_days INT DEFAULT 7,
  p_age_group TEXT DEFAULT NULL,
  p_gender TEXT DEFAULT NULL,
  p_max_state_rank INT DEFAULT 50
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
  WITH state_ranked AS (
    SELECT
      rf.team_id,
      t.team_name,
      t.club_name,
      rf.state_code,
      rf.games_played,
      CASE WHEN p_days <= 7 THEN rf.rank_change_state_7d ELSE rf.rank_change_state_30d END AS rank_change,
      RANK() OVER (
        PARTITION BY rf.state_code, rf.age_group, rf.gender
        ORDER BY rf.rank_in_cohort_final ASC
      )::INT AS state_rank
    FROM rankings_full rf
    JOIN teams t ON t.team_id_master = rf.team_id
    -- Eligibility that affects the rank basis must be applied before RANK():
    -- rank_in_cohort_final IS NOT NULL already excludes non-Active teams, and
    -- excluding deprecated teams here keeps state_rank from being padded by them.
    WHERE rf.state_code = p_state
      AND rf.rank_in_cohort_final IS NOT NULL
      AND t.is_deprecated IS NOT TRUE
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
  )
  SELECT
    sr.team_id,
    sr.team_name,
    sr.club_name,
    sr.state_code,
    sr.rank_change,
    sr.state_rank AS current_rank
  FROM state_ranked sr
  WHERE sr.rank_change IS NOT NULL
    AND COALESCE(sr.games_played, 0) >= 8
    AND (p_max_state_rank IS NULL OR sr.state_rank <= p_max_state_rank)
    AND (
      (p_direction = 'up' AND sr.rank_change > 0)
      OR (p_direction = 'down' AND sr.rank_change < 0)
    )
  ORDER BY
    CASE WHEN p_direction = 'up' THEN sr.rank_change END DESC NULLS LAST,
    CASE WHEN p_direction = 'down' THEN sr.rank_change END ASC NULLS LAST
  LIMIT p_limit;
$$;

-- Frontend infographic routes and the marketing pipeline call this with the
-- anon/service keys; keep the grant self-contained.
GRANT EXECUTE ON FUNCTION get_biggest_state_movers TO authenticated, anon;
