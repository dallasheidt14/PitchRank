-- Investigate team 79c926e1-c42f-404f-afbd-4ef1b7eb2893 SOS ranking issue

-- 1. Get this team's full data
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
    rf.status
FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
WHERE rf.team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893';

-- 2. How many teams in this cohort (age/gender) in Arizona?
SELECT
    rf.age_group,
    rf.gender,
    rf.state_code,
    COUNT(*) as team_count,
    AVG(rf.sos) as avg_sos,
    MIN(rf.sos) as min_sos,
    MAX(rf.sos) as max_sos
FROM rankings_full rf
WHERE rf.age_group = (SELECT age_group FROM rankings_full WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893')
  AND rf.gender = (SELECT gender FROM rankings_full WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893')
  AND rf.state_code = 'AZ'
  AND rf.status = 'Active'
GROUP BY rf.age_group, rf.gender, rf.state_code;

-- 3. Where does this team's SOS rank in Arizona (within cohort)?
WITH team_info AS (
    SELECT age_group, gender, sos FROM rankings_full
    WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893'
),
az_teams AS (
    SELECT rf.team_id, t.team_name, rf.sos, rf.sos_rank_state,
           ROW_NUMBER() OVER (ORDER BY rf.sos DESC) as calculated_rank
    FROM rankings_full rf
    JOIN teams t ON rf.team_id = t.team_id_master
    WHERE rf.age_group = (SELECT age_group FROM team_info)
      AND rf.gender = (SELECT gender FROM team_info)
      AND rf.state_code = 'AZ'
      AND rf.status = 'Active'
)
SELECT * FROM az_teams
WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893'
   OR calculated_rank <= 10  -- Show top 10 for comparison
ORDER BY sos DESC;

-- 4. Where does this team's SOS rank nationally (within cohort)?
WITH team_info AS (
    SELECT age_group, gender, sos FROM rankings_full
    WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893'
),
national_teams AS (
    SELECT rf.team_id, rf.state_code, rf.sos, rf.sos_rank_national,
           ROW_NUMBER() OVER (ORDER BY rf.sos DESC) as calculated_rank,
           COUNT(*) OVER () as total_teams
    FROM rankings_full rf
    WHERE rf.age_group = (SELECT age_group FROM team_info)
      AND rf.gender = (SELECT gender FROM team_info)
      AND rf.status = 'Active'
)
SELECT
    (SELECT calculated_rank FROM national_teams WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893') as this_team_rank,
    (SELECT sos FROM national_teams WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893') as this_team_sos,
    (SELECT total_teams FROM national_teams LIMIT 1) as total_in_cohort,
    (SELECT sos_rank_national FROM national_teams WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893') as stored_rank;

-- 5. Check if sos_rank columns are being calculated correctly
-- Compare stored vs calculated for a sample
WITH team_info AS (
    SELECT age_group, gender FROM rankings_full
    WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893'
),
ranked AS (
    SELECT rf.team_id, rf.state_code, rf.sos,
           rf.sos_rank_national as stored_national,
           rf.sos_rank_state as stored_state,
           ROW_NUMBER() OVER (ORDER BY rf.sos DESC) as calc_national,
           ROW_NUMBER() OVER (PARTITION BY rf.state_code ORDER BY rf.sos DESC) as calc_state
    FROM rankings_full rf
    WHERE rf.age_group = (SELECT age_group FROM team_info)
      AND rf.gender = (SELECT gender FROM team_info)
      AND rf.status = 'Active'
)
SELECT *,
       (stored_national - calc_national) as national_diff,
       (stored_state - calc_state) as state_diff
FROM ranked
WHERE team_id = '79c926e1-c42f-404f-afbd-4ef1b7eb2893'
   OR ABS(stored_national - calc_national) > 10
   OR ABS(stored_state - calc_state) > 10
ORDER BY ABS(stored_national - calc_national) DESC
LIMIT 20;
