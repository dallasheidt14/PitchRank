-- Migration: Add get_big_weekend_games RPC
-- Date: 2026-06-12
-- Purpose: The weekly marketing pipeline's Thursday "Big Games This Weekend"
--          Instagram post needs upcoming Fri-Sun games where BOTH teams are
--          ranked top-N (default 25) in the same state cohort, ordered by
--          combined state rank (lower sum = bigger game).
--
-- Design notes:
--   * Called exclusively by the pipeline with the service-role key (no
--     statement timeout). Deliberately NOT granted to anon: ranking work over
--     candidate cohorts is too heavy for the 3s anon ceiling, and there is no
--     public caller.
--   * State rank is a ROW_NUMBER() window over ONLY the cohorts that contain a
--     candidate game (a typical weekend has ~170 cohorts / ~28K rows; 657 ms
--     measured live). A per-candidate correlated COUNT was tried first and
--     measured 6-8 s because every same-cohort pair (~1.5K) paid a cohort scan
--     before the rank ceiling could filter. The MATERIALIZED fences stop the
--     planner from pushing rank work back into the pair join.
--   * The window's ORDER BY carries a team_id tiebreaker, so ranks are
--     deterministic; exact-tie labels may differ by a few places from
--     get_state_rankings' ROW_NUMBER(), which has no tiebreaker. That is
--     acceptable for selecting marquee matchups.
--   * Cohort predicates mirror get_state_rankings' cohort/active_ranked CTEs
--     (20260603000000): status = 'Active', power_score_final IS NOT NULL,
--     teams.is_deprecated IS NOT TRUE, with state_code/age_group/gender read
--     from rankings_full (never teams.state_code).
--   * games.game_date is a DATE; there is no kickoff-time column, so callers
--     can only derive day labels (FRI/SAT/SUN).
--   * p_states optionally restricts matchups to a set of state codes (NULL = all
--     states). The marketing pipeline passes its bigger-state list so the slate
--     surfaces deep-cohort matchups rather than thin small-state #1-vs-#2 games.

-- Adding p_states creates a new signature, so CREATE OR REPLACE alone would
-- leave the old 4-arg overload callable; drop it explicitly.
DROP FUNCTION IF EXISTS get_big_weekend_games(DATE, DATE, INT, INT);

CREATE OR REPLACE FUNCTION get_big_weekend_games(
    p_start_date DATE,
    p_end_date DATE,
    p_rank_ceiling INT DEFAULT 25,
    p_limit INT DEFAULT 5,
    p_states TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    game_date DATE,
    home_team_id_master UUID,
    home_team_name TEXT,
    home_club_name TEXT,
    home_state_rank BIGINT,
    away_team_id_master UUID,
    away_team_name TEXT,
    away_club_name TEXT,
    away_state_rank BIGINT,
    state_code TEXT,
    age_group TEXT,
    gender TEXT
) LANGUAGE sql STABLE AS $$
    WITH candidate_games AS (
        SELECT g.id, g.game_date, g.home_team_master_id, g.away_team_master_id
        FROM games g
        WHERE g.is_excluded = false
          AND g.home_score IS NULL
          AND g.game_date BETWEEN p_start_date AND p_end_date
    ),
    pairs AS MATERIALIZED (
        SELECT
            cg.game_date,
            hrf.team_id AS home_team_id,
            ht.team_name AS home_team_name,
            ht.club_name AS home_club_name,
            arf.team_id AS away_team_id,
            awt.team_name AS away_team_name,
            awt.club_name AS away_club_name,
            hrf.state_code,
            hrf.age_group,
            hrf.gender AS raw_gender
        FROM candidate_games cg
        JOIN rankings_full hrf ON hrf.team_id = cg.home_team_master_id
        JOIN teams ht ON ht.team_id_master = hrf.team_id
        JOIN rankings_full arf ON arf.team_id = cg.away_team_master_id
        JOIN teams awt ON awt.team_id_master = arf.team_id
        WHERE hrf.status = 'Active'
          AND arf.status = 'Active'
          AND hrf.power_score_final IS NOT NULL
          AND arf.power_score_final IS NOT NULL
          AND ht.is_deprecated IS NOT TRUE
          AND awt.is_deprecated IS NOT TRUE
          AND hrf.state_code = arf.state_code
          AND hrf.age_group = arf.age_group
          AND hrf.gender = arf.gender
          AND (p_states IS NULL OR hrf.state_code = ANY (p_states))
    ),
    cohorts AS (
        SELECT DISTINCT p.state_code, p.age_group, p.raw_gender FROM pairs p
    ),
    cohort_ranks AS MATERIALIZED (
        SELECT
            rf.team_id,
            ROW_NUMBER() OVER (
                PARTITION BY rf.state_code, rf.age_group, rf.gender
                ORDER BY rf.power_score_final DESC, rf.team_id ASC
            ) AS state_rank
        FROM rankings_full rf
        JOIN teams t ON t.team_id_master = rf.team_id
        JOIN cohorts c ON c.state_code = rf.state_code
                      AND c.age_group = rf.age_group
                      AND c.raw_gender = rf.gender
        WHERE rf.status = 'Active'
          AND rf.power_score_final IS NOT NULL
          AND t.is_deprecated IS NOT TRUE
    )
    SELECT
        p.game_date,
        p.home_team_id AS home_team_id_master,
        p.home_team_name,
        p.home_club_name,
        hr.state_rank AS home_state_rank,
        p.away_team_id AS away_team_id_master,
        p.away_team_name,
        p.away_club_name,
        ar.state_rank AS away_state_rank,
        p.state_code,
        p.age_group,
        CASE
            WHEN p.raw_gender = 'Male' THEN 'M'
            WHEN p.raw_gender = 'Female' THEN 'F'
            WHEN p.raw_gender = 'Boys' THEN 'M'
            WHEN p.raw_gender = 'Girls' THEN 'F'
            ELSE p.raw_gender
        END AS gender
    FROM pairs p
    JOIN cohort_ranks hr ON hr.team_id = p.home_team_id
    JOIN cohort_ranks ar ON ar.team_id = p.away_team_id
    WHERE hr.state_rank <= p_rank_ceiling
      AND ar.state_rank <= p_rank_ceiling
    ORDER BY (hr.state_rank + ar.state_rank) ASC, p.game_date ASC, p.home_team_id ASC
    LIMIT p_limit;
$$;

COMMENT ON FUNCTION get_big_weekend_games IS
  'Upcoming unplayed games in a date window where both teams are ranked top-N '
  '(default 25) in the same state/age/gender cohort, ordered by combined state '
  'rank. p_states optionally restricts to a set of state codes (NULL = all). '
  'Pipeline-only (service role); intentionally no anon/authenticated grant.';

-- Pipeline-only: the marketing job calls this with the service-role key, and the
-- big-games route is a pure renderer that never queries it. Grant service_role
-- only; revoke PUBLIC/anon/authenticated so no signed-in user can spend the
-- per-cohort ranking work.
REVOKE ALL ON FUNCTION get_big_weekend_games(DATE, DATE, INT, INT, TEXT[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION get_big_weekend_games(DATE, DATE, INT, INT, TEXT[]) FROM anon;
REVOKE ALL ON FUNCTION get_big_weekend_games(DATE, DATE, INT, INT, TEXT[]) FROM authenticated;
GRANT EXECUTE ON FUNCTION get_big_weekend_games(DATE, DATE, INT, INT, TEXT[]) TO service_role;
