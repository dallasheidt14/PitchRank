-- Migration: Switch views to use stored rank_in_cohort_final
-- Date: 2026-04-04
-- Purpose: Replace COALESCE(rank_in_cohort_ml, rank_in_cohort) with the published
--          rank_in_cohort_final computed from power_score_final ordering.
--          Uses status-aware fallback during transition (NULL column until first recalc).
--          Fixes state_rankings_view to use active-only CTE + join-back pattern so
--          non-Active teams remain visible with NULL state rank.

-- =====================================================
-- Step 1: Drop existing views (state depends on rankings)
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view with rank_in_cohort_final
-- =====================================================

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code AS state,
    -- Age extraction with U18->U19 remap
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
    END AS age,
    CASE
      WHEN rf.gender = 'Male' THEN 'M'
      WHEN rf.gender = 'Female' THEN 'F'
      WHEN rf.gender = 'Boys' THEN 'M'
      WHEN rf.gender = 'Girls' THEN 'F'
      WHEN rf.gender = 'M' THEN 'M'
      WHEN rf.gender = 'F' THEN 'F'
      ELSE rf.gender
    END AS gender,

    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,

    (SELECT COUNT(*)
     FROM games g
     WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_games_played,

    (SELECT COUNT(*)
     FROM games g
     WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score > g.away_score)
            OR (g.away_team_master_id = t.team_id_master AND g.away_score > g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_wins,

    (SELECT COUNT(*)
     FROM games g
     WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score < g.away_score)
            OR (g.away_team_master_id = t.team_id_master AND g.away_score < g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_losses,

    (SELECT COUNT(*)
     FROM games g
     WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
       AND g.home_score = g.away_score
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_draws,

    CASE
      WHEN (SELECT COUNT(*)
            FROM games g
            WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
              AND g.home_score IS NOT NULL
              AND g.away_score IS NOT NULL
              AND g.is_excluded = FALSE) > 0
      THEN (
        (
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score > g.away_score)
                  OR (g.away_team_master_id = t.team_id_master AND g.away_score > g.home_score))
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL
             AND g.is_excluded = FALSE)
          +
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
             AND g.home_score = g.away_score
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL
             AND g.is_excluded = FALSE) * 0.5
        ) /
        (SELECT COUNT(*)::NUMERIC
         FROM games g
         WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
           AND g.home_score IS NOT NULL
           AND g.away_score IS NOT NULL
           AND g.is_excluded = FALSE)
      ) * 100
      ELSE NULL
    END AS win_percentage,

    rf.power_score_final,
    rf.sos_norm,
    rf.sos_norm_state,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,
    rf.perf_centered,

    -- Published rank: status-aware fallback until first recalc populates rank_in_cohort_final
    CASE WHEN rf.status = 'Active'
        THEN COALESCE(rf.rank_in_cohort_final, rf.rank_in_cohort_ml, rf.rank_in_cohort)
        ELSE NULL
    END AS rank_in_cohort_final,

    rf.sos_rank_national,
    rf.sos_rank_state,

    rf.rank_change_7d,
    rf.rank_change_30d,
    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    rf.status,
    rf.last_game,
    rf.last_calculated

FROM teams t
LEFT JOIN rankings_full rf ON t.team_id_master = rf.team_id
LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
WHERE (rf.power_score_final IS NOT NULL OR cr.national_power_score IS NOT NULL)
  AND t.is_deprecated IS NOT TRUE;

COMMENT ON VIEW rankings_view IS 'National rankings view. Uses stored rank_in_cohort_final (with status-aware fallback to rank_in_cohort_ml/rank_in_cohort during transition). Age 18 remapped to 19. Excludes deprecated teams.';

-- =====================================================
-- Step 3: Recreate state_rankings_view with active-only CTE + join-back
-- =====================================================
-- Active teams get a state rank via ROW_NUMBER in a CTE.
-- Non-active teams remain visible with NULL rank_in_state_final via LEFT JOIN.

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
WITH active_state_ranks AS (
    SELECT
        rv.team_id_master,
        ROW_NUMBER() OVER (
            PARTITION BY rv.state, rv.age, rv.gender
            ORDER BY rv.power_score_final DESC, rv.team_id_master ASC
        ) AS rank_in_state_final
    FROM rankings_view rv
    WHERE rv.state IS NOT NULL
      AND rv.status = 'Active'
)
SELECT
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state AS state,
    rv.age AS age,
    rv.gender,

    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,

    rv.total_games_played,
    rv.total_wins,
    rv.total_losses,
    rv.total_draws,
    rv.win_percentage,

    rv.power_score_final,
    rv.sos_norm,
    rv.sos_norm_state,
    rv.offense_norm,
    rv.defense_norm,

    rv.perf_centered,

    rv.rank_in_cohort_final,

    asr.rank_in_state_final,

    rv.sos_rank_national,
    rv.sos_rank_state,

    rv.rank_change_7d,
    rv.rank_change_30d,

    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
LEFT JOIN active_state_ranks asr ON rv.team_id_master = asr.team_id_master
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW state_rankings_view IS 'State rankings view. Active teams get rank_in_state_final via active-only CTE (power_score_final DESC, team_id ASC). Non-active teams visible with NULL state rank.';

-- =====================================================
-- Step 4: Update get_state_rankings RPC to use rank_in_cohort_final
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
    gender_norm AS (
        SELECT CASE
            WHEN p_gender IN ('M', 'B') THEN 'Male'
            WHEN p_gender IN ('F', 'G') THEN 'Female'
            ELSE p_gender
        END AS gender_val
    ),
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
            -- Status-aware fallback for rank_in_cohort_final
            CASE WHEN rf.status = 'Active'
                THEN COALESCE(rf.rank_in_cohort_final, rf.rank_in_cohort_ml, rf.rank_in_cohort)
                ELSE NULL
            END AS rank_in_cohort_final,
            rf.sos_rank_national,
            rf.sos_rank_state,
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
              END
          ) = CASE WHEN p_age::INTEGER = 18 THEN 19 ELSE p_age::INTEGER END
          AND rf.gender = gn.gender_val
          AND rf.status IN ('Active', 'Not Enough Ranked Games')
          AND t.is_deprecated IS NOT TRUE
          AND rf.power_score_final IS NOT NULL
    ),
    active_ranked AS (
        SELECT
            c.team_id_master,
            ROW_NUMBER() OVER (ORDER BY c.power_score_final DESC, c.team_id_master ASC) AS rank_in_state
        FROM cohort c
        WHERE c.status = 'Active'
    )
    SELECT
        c.team_id_master,
        c.team_name,
        c.club_name,
        c.state_code AS state,
        CASE WHEN p_age::INTEGER = 18 THEN 19 ELSE p_age::INTEGER END AS age,
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
        c.sos_rank_state,
        c.rank_change_7d,
        c.rank_change_30d,
        c.rank_change_state_7d,
        c.rank_change_state_30d,
        c.status,
        c.last_game,
        c.last_calculated
    FROM cohort c
    LEFT JOIN active_ranked ar ON c.team_id_master = ar.team_id_master
    ORDER BY c.power_score_final DESC
    LIMIT p_limit
    OFFSET p_offset;
$$;

COMMENT ON FUNCTION get_state_rankings IS 'Paginated state rankings RPC. Uses stored rank_in_cohort_final (with status-aware fallback). State rank via active-only CTE with canonical ordering (power_score_final DESC, team_id ASC). Age 18 remapped to 19.';

-- =====================================================
-- Step 5: Update get_team_state_rank RPC with canonical ordering
-- =====================================================

CREATE OR REPLACE FUNCTION get_team_state_rank(p_team_id UUID)
RETURNS TABLE (
    state_rank BIGINT,
    sos_rank_state BIGINT
) LANGUAGE sql STABLE AS $$
    WITH team_info AS (
        SELECT team_id, state_code, age_group, gender, power_score_final, sos_norm_state, status
        FROM rankings_full WHERE team_id = p_team_id
    )
    SELECT
        (SELECT COUNT(*) + 1 FROM rankings_full rf
         WHERE rf.state_code = ti.state_code
           AND rf.age_group = ti.age_group
           AND rf.gender = ti.gender
           AND rf.status = 'Active'
           AND (rf.power_score_final > ti.power_score_final
                OR (rf.power_score_final = ti.power_score_final AND rf.team_id < ti.team_id))
        )::BIGINT AS state_rank,
        (SELECT COUNT(*) + 1 FROM rankings_full rf
         WHERE rf.state_code = ti.state_code
           AND rf.age_group = ti.age_group
           AND rf.gender = ti.gender
           AND rf.status = 'Active'
           AND rf.sos_norm_state IS NOT NULL
           AND ti.sos_norm_state IS NOT NULL
           AND rf.sos_norm_state > ti.sos_norm_state
        )::BIGINT AS sos_rank_state
    FROM team_info ti
    WHERE ti.status = 'Active';
$$;

COMMENT ON FUNCTION get_team_state_rank IS 'Single-team state rank RPC. Counts Active teams with higher power_score_final (tie-break: team_id ASC). Only returns for Active teams.';
