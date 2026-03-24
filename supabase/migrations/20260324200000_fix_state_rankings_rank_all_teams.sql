-- Fix: State rankings should rank ALL returned teams, not just Active ones.
-- Date: 2026-03-24
--
-- Problem: In small states (NE, MS, etc.), most teams have status
--          'Not Enough Ranked Games' (< 8 games). The RPC returns them
--          (line 112 includes both statuses), but rank_in_state_final is only
--          computed for Active teams via the active_ranked CTE. This means
--          teams appear in state results with NULL rank — confusing UX.
--
--          Larger states (CA, AZ, TX) have enough Active teams so the issue
--          is less visible there.
--
-- Fix: Compute rank_in_state_final for ALL teams in the result set.
--      Also compute a dynamic sos_rank_state for any team that has
--      sos_norm_state but no pre-calculated sos_rank_state.
--      Update get_team_state_rank to also return ranks for non-Active teams.

-- =====================================================
-- Function 1: get_state_rankings (CREATE OR REPLACE)
-- =====================================================

CREATE OR REPLACE FUNCTION get_state_rankings(
    p_state TEXT,
    p_age TEXT,
    p_gender TEXT,
    p_limit INT DEFAULT 1000,
    p_offset INT DEFAULT 0
)
RETURNS TABLE (
    team_id_master UUID,
    team_name TEXT,
    club_name TEXT,
    state TEXT,
    age INT,
    gender TEXT,
    games_played INT,
    wins INT,
    losses INT,
    draws INT,
    total_games_played INT,
    total_wins INT,
    total_losses INT,
    total_draws INT,
    win_percentage NUMERIC,
    power_score_final FLOAT8,
    sos_norm FLOAT8,
    sos_norm_state FLOAT8,
    offense_norm FLOAT8,
    defense_norm FLOAT8,
    perf_centered FLOAT8,
    rank_in_cohort_final INT,
    rank_in_state_final BIGINT,
    sos_rank_national INT,
    sos_rank_state INT,
    rank_change_7d INT,
    rank_change_30d INT,
    rank_change_state_7d INT,
    rank_change_state_30d INT,
    status TEXT,
    last_game TIMESTAMPTZ,
    last_calculated TIMESTAMPTZ
) LANGUAGE sql STABLE AS $$
    WITH
    -- Normalize gender parameter to rankings_full format
    gender_norm AS (
        SELECT CASE
            WHEN p_gender IN ('M', 'B') THEN 'Male'
            WHEN p_gender IN ('F', 'G') THEN 'Female'
            ELSE p_gender
        END AS gender_val
    ),
    -- Filter to the specific cohort first (fast — uses indexes)
    cohort AS (
        SELECT
            t.team_id_master,
            t.team_name,
            t.club_name,
            rf.state_code,
            rf.age_group,
            rf.gender AS raw_gender,
            COALESCE(rf.games_played, cr.games_played) AS games_played,
            COALESCE(rf.wins, cr.wins) AS wins,
            COALESCE(rf.losses, cr.losses) AS losses,
            COALESCE(rf.draws, cr.draws) AS draws,
            COALESCE(rf.total_games_played, 0) AS total_games_played,
            COALESCE(rf.total_wins, 0) AS total_wins,
            COALESCE(rf.total_losses, 0) AS total_losses,
            COALESCE(rf.total_draws, 0) AS total_draws,
            rf.power_score_final,
            rf.sos_norm,
            rf.sos_norm_state,
            rf.off_norm,
            rf.def_norm,
            rf.perf_centered,
            COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,
            rf.sos_rank_national,
            rf.sos_rank_state AS sos_rank_state_stored,
            rf.rank_change_7d,
            rf.rank_change_30d,
            rf.rank_change_state_7d,
            rf.rank_change_state_30d,
            rf.status,
            rf.last_game,
            rf.last_calculated
        FROM teams t
        JOIN rankings_full rf ON t.team_id_master = rf.team_id
        LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
        CROSS JOIN gender_norm gn
        WHERE rf.state_code = UPPER(p_state)
          AND (
              CASE
                  WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                  WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                  WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                  ELSE NULL
              END
          ) = p_age::INTEGER
          AND rf.gender = gn.gender_val
          AND rf.status IN ('Active', 'Not Enough Ranked Games')
          AND t.is_deprecated IS NOT TRUE
          AND rf.power_score_final IS NOT NULL
    ),
    -- Compute state rank for ALL teams (not just Active)
    all_ranked AS (
        SELECT
            c.team_id_master,
            ROW_NUMBER() OVER (ORDER BY c.power_score_final DESC) AS rank_in_state,
            ROW_NUMBER() OVER (ORDER BY c.sos_norm_state DESC NULLS LAST) AS sos_rank_in_state
        FROM cohort c
    )
    SELECT
        c.team_id_master,
        c.team_name,
        c.club_name,
        c.state_code AS state,
        p_age::INT AS age,
        CASE
            WHEN c.raw_gender = 'Male' THEN 'M'
            WHEN c.raw_gender = 'Female' THEN 'F'
            WHEN c.raw_gender = 'Boys' THEN 'M'
            WHEN c.raw_gender = 'Girls' THEN 'F'
            WHEN c.raw_gender = 'M' THEN 'M'
            WHEN c.raw_gender = 'F' THEN 'F'
            ELSE c.raw_gender
        END AS gender,
        c.games_played,
        c.wins,
        c.losses,
        c.draws,
        c.total_games_played,
        c.total_wins,
        c.total_losses,
        c.total_draws,
        CASE
            WHEN c.total_games_played > 0
            THEN ((c.total_wins::NUMERIC + c.total_draws::NUMERIC * 0.5)
                  / c.total_games_played::NUMERIC) * 100
            ELSE NULL
        END AS win_percentage,
        c.power_score_final,
        c.sos_norm,
        c.sos_norm_state,
        c.off_norm AS offense_norm,
        c.def_norm AS defense_norm,
        c.perf_centered,
        c.rank_in_cohort_final,
        ar.rank_in_state AS rank_in_state_final,
        c.sos_rank_national,
        -- Use pre-calculated sos_rank_state if available, otherwise dynamic
        COALESCE(c.sos_rank_state_stored, ar.sos_rank_in_state::INT) AS sos_rank_state,
        c.rank_change_7d,
        c.rank_change_30d,
        c.rank_change_state_7d,
        c.rank_change_state_30d,
        c.status,
        c.last_game,
        c.last_calculated
    FROM cohort c
    LEFT JOIN all_ranked ar ON c.team_id_master = ar.team_id_master
    ORDER BY c.power_score_final DESC
    LIMIT p_limit
    OFFSET p_offset;
$$;

COMMENT ON FUNCTION get_state_rankings IS
  'Fast state rankings RPC. Filters to (state, age, gender) cohort FIRST, '
  'then computes ROW_NUMBER() on ALL returned teams (not just Active). '
  'Previously only Active teams got rank_in_state_final, which left small '
  'states (NE, MS) with teams showing but no ranks. '
  'Also computes dynamic sos_rank_state for teams without pre-calculated values. '
  'Age normalization handles 12, u12, U12 formats via regex.';

-- =====================================================
-- Function 2: get_state_rankings_count (unchanged, just re-grant)
-- =====================================================

-- No changes needed — count is unaffected by ranking logic.

-- =====================================================
-- Function 3: get_team_state_rank (rank all teams, not just Active)
-- =====================================================

CREATE OR REPLACE FUNCTION get_team_state_rank(p_team_id UUID)
RETURNS TABLE (
    state_rank BIGINT,
    sos_rank_state BIGINT
) LANGUAGE sql STABLE AS $$
    WITH team_info AS (
        SELECT
            team_id,
            state_code,
            age_group,
            gender,
            power_score_final,
            sos_norm_state,
            status
        FROM rankings_full
        WHERE team_id = p_team_id
    )
    SELECT
        -- State rank: count ALL ranked teams with higher power_score_final + 1
        (
            SELECT COUNT(*) + 1
            FROM rankings_full rf
            WHERE rf.state_code = ti.state_code
              AND rf.age_group = ti.age_group
              AND rf.gender = ti.gender
              AND rf.status IN ('Active', 'Not Enough Ranked Games')
              AND rf.power_score_final IS NOT NULL
              AND rf.power_score_final > ti.power_score_final
        )::BIGINT AS state_rank,
        -- SOS state rank: count ALL ranked teams with higher sos_norm_state + 1
        (
            SELECT COUNT(*) + 1
            FROM rankings_full rf
            WHERE rf.state_code = ti.state_code
              AND rf.age_group = ti.age_group
              AND rf.gender = ti.gender
              AND rf.status IN ('Active', 'Not Enough Ranked Games')
              AND rf.power_score_final IS NOT NULL
              AND rf.sos_norm_state IS NOT NULL
              AND ti.sos_norm_state IS NOT NULL
              AND rf.sos_norm_state > ti.sos_norm_state
        )::BIGINT AS sos_rank_state
    FROM team_info ti
    WHERE ti.status IN ('Active', 'Not Enough Ranked Games')
      AND ti.power_score_final IS NOT NULL;
$$;

-- =====================================================
-- View: state_rankings_view (rank ALL teams, restore state rank changes)
-- =====================================================
-- The 20260321 migration regressed this view by:
-- 1. Only ranking Active teams (same issue as the RPCs)
-- 2. Losing rank_change_state_7d/30d columns (added in 20260310)

DROP VIEW IF EXISTS state_rankings_view CASCADE;

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state AS state,
    rv.age AS age,
    rv.gender,

    -- Record stats (capped at 30 for rankings algorithm)
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,

    -- Total games and record (all games, not capped)
    rv.total_games_played,
    rv.total_wins,
    rv.total_losses,
    rv.total_draws,
    rv.win_percentage,

    -- Metrics
    rv.power_score_final,
    rv.sos_norm,
    rv.sos_norm_state,
    rv.offense_norm,
    rv.defense_norm,

    -- Performance/form signal
    rv.perf_centered,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank: computed for ALL teams (Active + Not Enough Ranked Games)
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final,

    -- SOS Ranks (passed through from base view)
    rv.sos_rank_national,
    rv.sos_rank_state,

    -- National rank change tracking (passed through from base view)
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- State rank change tracking (from rankings_full)
    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    -- Activity status fields (passed through from base view)
    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
JOIN rankings_full rf ON rv.team_id_master = rf.team_id
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW state_rankings_view IS
  'State rankings view: ranks ALL teams (Active + Not Enough Ranked Games) within '
  'each state/age/gender cohort. Previously only Active teams got state ranks, '
  'leaving small states with no ranked teams. Includes state rank change columns.';

-- =====================================================
-- Grant permissions
-- =====================================================

GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

GRANT EXECUTE ON FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT) TO anon;
GRANT EXECUTE ON FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_team_state_rank(UUID) TO anon;
GRANT EXECUTE ON FUNCTION get_team_state_rank(UUID) TO authenticated;
