-- Add league + distinction to get_national_rankings and get_state_rankings RPCs
-- so the rankings table UI can compose a clean display name from
-- (club_name, age, league, distinction) instead of the messy raw team_name.

-- DROP first because CREATE OR REPLACE cannot change a function's return columns.
DROP FUNCTION IF EXISTS get_national_rankings(TEXT, TEXT, INT, INT);
DROP FUNCTION IF EXISTS get_state_rankings(TEXT, TEXT, TEXT, INT, INT);

CREATE OR REPLACE FUNCTION get_national_rankings(
    p_age TEXT DEFAULT '',
    p_gender TEXT DEFAULT '',
    p_limit INT DEFAULT 1000,
    p_offset INT DEFAULT 0
)
RETURNS TABLE (
    team_id_master UUID,
    team_name TEXT,
    club_name TEXT,
    league TEXT,
    distinction TEXT,
    has_modular11_alias BOOLEAN,
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
    age_norm AS (
        SELECT CASE
            WHEN NULLIF(p_age, '') IS NULL THEN NULL
            WHEN p_age::INTEGER = 18 THEN 19
            ELSE p_age::INTEGER
        END AS age_val
    ),
    gender_norm AS (
        SELECT CASE
            WHEN p_gender IN ('M', 'B') THEN 'Male'
            WHEN p_gender IN ('F', 'G') THEN 'Female'
            ELSE p_gender
        END AS gender_val
    ),
    base AS (
        SELECT
            t.team_id_master,
            t.team_name,
            t.club_name,
            t.league,
            t.distinction,
            EXISTS (
                SELECT 1 FROM team_alias_map am
                JOIN providers p ON p.id = am.provider_id
                WHERE am.team_id_master = t.team_id_master
                  AND p.code = 'modular11'
            ) AS has_modular11_alias,
            rf.state_code,
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
            END AS normalized_age,
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
            CASE
                WHEN rf.status = 'Active'
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
        CROSS JOIN age_norm an
        CROSS JOIN gender_norm gn
        WHERE rf.status IN ('Active', 'Not Enough Ranked Games')
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
              OR rf.gender = gn.gender_val
          )
    )
    SELECT
        b.team_id_master,
        b.team_name,
        b.club_name,
        b.league,
        b.distinction,
        b.has_modular11_alias,
        b.state_code AS state,
        b.normalized_age AS age,
        CASE
            WHEN b.raw_gender = 'Male' THEN 'M'
            WHEN b.raw_gender = 'Female' THEN 'F'
            WHEN b.raw_gender = 'Boys' THEN 'M'
            WHEN b.raw_gender = 'Girls' THEN 'F'
            WHEN b.raw_gender = 'M' THEN 'M'
            WHEN b.raw_gender = 'F' THEN 'F'
            ELSE b.raw_gender
        END AS gender,
        b.games_played,
        b.wins,
        b.losses,
        b.draws,
        b.total_games_played,
        b.total_wins,
        b.total_losses,
        b.total_draws,
        CASE
            WHEN b.total_games_played > 0
            THEN ((b.total_wins::NUMERIC + b.total_draws::NUMERIC * 0.5)
                  / b.total_games_played::NUMERIC) * 100
            ELSE NULL
        END AS win_percentage,
        b.power_score_final,
        b.sos_norm,
        b.sos_norm_state,
        b.off_norm AS offense_norm,
        b.def_norm AS defense_norm,
        b.perf_centered,
        b.rank_in_cohort_final,
        b.sos_rank_national,
        b.sos_rank_state,
        b.rank_change_7d,
        b.rank_change_30d,
        b.rank_change_state_7d,
        b.rank_change_state_30d,
        b.status,
        b.last_game,
        b.last_calculated
    FROM base b
    ORDER BY
        b.rank_in_cohort_final ASC NULLS LAST,
        b.team_id_master ASC
    LIMIT p_limit
    OFFSET p_offset;
$$;

GRANT EXECUTE ON FUNCTION get_national_rankings(TEXT, TEXT, INT, INT) TO anon;
GRANT EXECUTE ON FUNCTION get_national_rankings(TEXT, TEXT, INT, INT) TO authenticated;

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
    league TEXT,
    distinction TEXT,
    has_modular11_alias BOOLEAN,
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
            t.league,
            t.distinction,
            EXISTS (
                SELECT 1 FROM team_alias_map am
                JOIN providers p ON p.id = am.provider_id
                WHERE am.team_id_master = t.team_id_master
                  AND p.code = 'modular11'
            ) AS has_modular11_alias,
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
    active_ranked AS (
        SELECT
            c.team_id_master,
            ROW_NUMBER() OVER (ORDER BY c.power_score_final DESC) AS rank_in_state
        FROM cohort c
        WHERE c.status = 'Active'
    )
    SELECT
        c.team_id_master,
        c.team_name,
        c.club_name,
        c.league,
        c.distinction,
        c.has_modular11_alias,
        c.state_code AS state,
        c.age_group::INT AS age,
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

GRANT EXECUTE ON FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT) TO anon;
GRANT EXECUTE ON FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT) TO authenticated;
