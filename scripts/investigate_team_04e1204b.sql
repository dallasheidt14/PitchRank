-- Investigate team 04e1204b-487e-4be4-81d8-1d6c29a5ad1b SOS ranking issue
-- User reports: "very good team with tough schedule, showing 213th SOS nationally - should be higher"

-- =====================================================
-- 1. Get this team's full ranking data
-- =====================================================
SELECT
    rf.team_id,
    t.team_name,
    t.club_name,
    rf.age_group,
    rf.gender,
    rf.state_code,
    rf.games_played,
    rf.power_score_final,
    rf.sos,
    rf.sos_raw,
    rf.sos_norm,
    rf.sos_norm_state,
    rf.sos_rank_national,
    rf.sos_rank_state,
    rf.off_norm,
    rf.def_norm,
    rf.abs_strength,
    rf.status,
    rf.rank_in_cohort
FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
WHERE rf.team_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b';

-- =====================================================
-- 2. Cohort statistics (how many teams, SOS distribution)
-- =====================================================
WITH team_info AS (
    SELECT age_group, gender FROM rankings_full
    WHERE team_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b'
)
SELECT
    rf.age_group,
    rf.gender,
    COUNT(*) as total_teams,
    COUNT(CASE WHEN rf.games_played >= 10 THEN 1 END) as teams_with_10plus_games,
    AVG(rf.sos) as avg_sos,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rf.sos) as median_sos,
    MIN(rf.sos) as min_sos,
    MAX(rf.sos) as max_sos,
    STDDEV(rf.sos) as stddev_sos
FROM rankings_full rf, team_info ti
WHERE rf.age_group = ti.age_group
  AND rf.gender = ti.gender
  AND rf.status = 'Active'
GROUP BY rf.age_group, rf.gender;

-- =====================================================
-- 3. Where does this team rank in SOS nationally? (calculated vs stored)
-- =====================================================
WITH team_info AS (
    SELECT age_group, gender, sos, games_played FROM rankings_full
    WHERE team_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b'
),
national_teams AS (
    SELECT
        rf.team_id,
        t.team_name,
        rf.state_code,
        rf.sos,
        rf.games_played,
        rf.sos_rank_national as stored_rank,
        ROW_NUMBER() OVER (ORDER BY rf.sos DESC) as calculated_rank_all,
        ROW_NUMBER() OVER (
            ORDER BY CASE WHEN rf.games_played >= 10 THEN rf.sos ELSE NULL END DESC NULLS LAST
        ) as calculated_rank_10plus,
        COUNT(*) OVER () as total_teams
    FROM rankings_full rf
    JOIN teams t ON rf.team_id = t.team_id_master
    WHERE rf.age_group = (SELECT age_group FROM team_info)
      AND rf.gender = (SELECT gender FROM team_info)
      AND rf.status = 'Active'
)
SELECT
    team_id,
    team_name,
    state_code,
    sos,
    games_played,
    stored_rank,
    calculated_rank_all,
    calculated_rank_10plus,
    total_teams
FROM national_teams
WHERE team_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b'
   OR calculated_rank_all <= 20  -- Show top 20 for comparison
ORDER BY sos DESC
LIMIT 30;

-- =====================================================
-- 4. Who are this team's opponents and what are their strengths?
-- =====================================================
WITH team_games AS (
    SELECT
        g.id,
        g.game_date,
        CASE
            WHEN g.home_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b' THEN g.away_team_master_id
            ELSE g.home_team_master_id
        END as opponent_id,
        CASE
            WHEN g.home_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b' THEN g.home_score
            ELSE g.away_score
        END as team_score,
        CASE
            WHEN g.home_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b' THEN g.away_score
            ELSE g.home_score
        END as opp_score
    FROM games g
    WHERE (g.home_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b'
           OR g.away_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b')
      AND g.game_date >= CURRENT_DATE - INTERVAL '365 days'
      AND g.home_score IS NOT NULL
      AND g.away_score IS NOT NULL
)
SELECT
    tg.game_date,
    t.team_name as opponent_name,
    tg.team_score || '-' || tg.opp_score as score,
    COALESCE(rf.abs_strength, 0.35) as opp_abs_strength,
    rf.power_score_final as opp_power_score,
    rf.sos_norm as opp_sos_norm,
    rf.rank_in_cohort as opp_rank,
    rf.games_played as opp_games,
    rf.status as opp_status
FROM team_games tg
LEFT JOIN teams t ON tg.opponent_id = t.team_id_master
LEFT JOIN rankings_full rf ON tg.opponent_id = rf.team_id
ORDER BY tg.game_date DESC;

-- =====================================================
-- 5. Calculate average opponent strength manually
-- =====================================================
WITH team_games AS (
    SELECT
        CASE
            WHEN g.home_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b' THEN g.away_team_master_id
            ELSE g.home_team_master_id
        END as opponent_id
    FROM games g
    WHERE (g.home_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b'
           OR g.away_team_master_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b')
      AND g.game_date >= CURRENT_DATE - INTERVAL '365 days'
      AND g.home_score IS NOT NULL
      AND g.away_score IS NOT NULL
)
SELECT
    COUNT(*) as total_opponents,
    COUNT(DISTINCT tg.opponent_id) as unique_opponents,
    AVG(COALESCE(rf.abs_strength, 0.35)) as avg_opp_strength,
    AVG(rf.power_score_final) as avg_opp_power_score,
    AVG(rf.rank_in_cohort) as avg_opp_rank,
    MIN(rf.rank_in_cohort) as best_opp_rank,
    COUNT(CASE WHEN rf.rank_in_cohort <= 50 THEN 1 END) as opponents_top_50,
    COUNT(CASE WHEN rf.rank_in_cohort <= 100 THEN 1 END) as opponents_top_100
FROM team_games tg
LEFT JOIN rankings_full rf ON tg.opponent_id = rf.team_id;

-- =====================================================
-- 6. Compare this team's SOS to teams with similar opponent quality
-- =====================================================
WITH team_info AS (
    SELECT age_group, gender, sos FROM rankings_full
    WHERE team_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b'
),
team_opps AS (
    SELECT
        g.home_team_master_id as team_id,
        AVG(COALESCE(rf_away.abs_strength, 0.35)) as avg_opp_strength
    FROM games g
    JOIN rankings_full rf_home ON g.home_team_master_id = rf_home.team_id
    LEFT JOIN rankings_full rf_away ON g.away_team_master_id = rf_away.team_id
    WHERE rf_home.age_group = (SELECT age_group FROM team_info)
      AND rf_home.gender = (SELECT gender FROM team_info)
      AND g.game_date >= CURRENT_DATE - INTERVAL '365 days'
      AND g.home_score IS NOT NULL
    GROUP BY g.home_team_master_id

    UNION ALL

    SELECT
        g.away_team_master_id as team_id,
        AVG(COALESCE(rf_home.abs_strength, 0.35)) as avg_opp_strength
    FROM games g
    JOIN rankings_full rf_away ON g.away_team_master_id = rf_away.team_id
    LEFT JOIN rankings_full rf_home ON g.home_team_master_id = rf_home.team_id
    WHERE rf_away.age_group = (SELECT age_group FROM team_info)
      AND rf_away.gender = (SELECT gender FROM team_info)
      AND g.game_date >= CURRENT_DATE - INTERVAL '365 days'
      AND g.away_score IS NOT NULL
    GROUP BY g.away_team_master_id
)
SELECT
    t.team_name,
    rf.games_played,
    rf.sos,
    rf.sos_rank_national,
    to2.avg_opp_strength,
    CASE WHEN rf.team_id = '04e1204b-487e-4be4-81d8-1d6c29a5ad1b' THEN '<<< THIS TEAM' ELSE '' END as marker
FROM (
    SELECT team_id, AVG(avg_opp_strength) as avg_opp_strength
    FROM team_opps
    GROUP BY team_id
) to2
JOIN rankings_full rf ON to2.team_id = rf.team_id
JOIN teams t ON rf.team_id = t.team_id_master
WHERE rf.age_group = (SELECT age_group FROM team_info)
  AND rf.gender = (SELECT gender FROM team_info)
  AND rf.status = 'Active'
ORDER BY to2.avg_opp_strength DESC
LIMIT 30;
