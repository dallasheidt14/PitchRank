-- =====================================================
-- DIAGNOSTIC: Why do top teams from different states
-- have the same power score?
-- =====================================================
-- Run these queries in Supabase SQL Editor

-- =====================================================
-- 1. CEILING CLIPPING CHECK
-- Are teams hitting the powerscore ceiling (>= 1.0)?
-- =====================================================
SELECT
    'Ceiling Check' as diagnostic,
    COUNT(*) FILTER (WHERE powerscore_adj >= 0.99) as teams_at_ceiling,
    COUNT(*) FILTER (WHERE powerscore_core > 1.0) as teams_exceeding_1,
    MAX(powerscore_core) as max_powerscore_core,
    MAX(powerscore_adj) as max_powerscore_adj
FROM rankings_full
WHERE status = 'Active';

-- =====================================================
-- 2. TOP TEAM PER STATE - U14 MALE
-- Do different states have identical power_score_final?
-- =====================================================
WITH top_per_state AS (
    SELECT DISTINCT ON (rf.state_code)
        rf.state_code,
        t.team_name,
        rf.power_score_final,
        rf.powerscore_adj,
        rf.powerscore_core,
        rf.sos_norm,
        rf.sos,
        rf.off_norm,
        rf.def_norm,
        rf.perf_centered
    FROM rankings_full rf
    JOIN teams t ON rf.team_id = t.team_id_master
    WHERE rf.age_group = 'u14'
      AND rf.gender = 'Male'
      AND rf.status = 'Active'
      AND rf.state_code IS NOT NULL
    ORDER BY rf.state_code, rf.power_score_final DESC
)
SELECT
    state_code,
    team_name,
    ROUND(power_score_final::numeric, 4) as power_final,
    ROUND(powerscore_adj::numeric, 4) as ps_adj,
    ROUND(powerscore_core::numeric, 4) as ps_core,
    ROUND(sos_norm::numeric, 3) as sos_norm,
    ROUND(sos::numeric, 3) as sos_raw,
    ROUND(off_norm::numeric, 3) as off_norm,
    ROUND(def_norm::numeric, 3) as def_norm
FROM top_per_state
ORDER BY power_score_final DESC
LIMIT 20;

-- =====================================================
-- 3. COUNT IDENTICAL POWER SCORES
-- How many states share the exact same top power score?
-- =====================================================
WITH top_per_state AS (
    SELECT DISTINCT ON (rf.state_code)
        rf.state_code,
        rf.power_score_final
    FROM rankings_full rf
    WHERE rf.age_group = 'u14'
      AND rf.gender = 'Male'
      AND rf.status = 'Active'
      AND rf.state_code IS NOT NULL
    ORDER BY rf.state_code, rf.power_score_final DESC
)
SELECT
    ROUND(power_score_final::numeric, 4) as power_score,
    COUNT(*) as states_with_same_score,
    STRING_AGG(state_code, ', ' ORDER BY state_code) as states
FROM top_per_state
GROUP BY ROUND(power_score_final::numeric, 4)
HAVING COUNT(*) > 1
ORDER BY states_with_same_score DESC;

-- =====================================================
-- 4. SOS DISTRIBUTION BY STATE
-- Does raw SOS vary by state but sos_norm doesn't?
-- =====================================================
SELECT
    rf.state_code,
    COUNT(*) as team_count,
    ROUND(AVG(rf.sos_norm)::numeric, 3) as avg_sos_norm,
    ROUND(MAX(rf.sos_norm)::numeric, 3) as max_sos_norm,
    ROUND(AVG(rf.sos)::numeric, 3) as avg_sos_raw,
    ROUND(MAX(rf.sos)::numeric, 3) as max_sos_raw,
    ROUND(AVG(rf.power_score_final)::numeric, 3) as avg_power_score
FROM rankings_full rf
WHERE rf.age_group = 'u14'
  AND rf.gender = 'Male'
  AND rf.status = 'Active'
  AND rf.state_code IS NOT NULL
GROUP BY rf.state_code
HAVING COUNT(*) >= 10
ORDER BY avg_sos_raw DESC
LIMIT 15;

-- =====================================================
-- 5. VERIFY: Is SOS actually different between states?
-- Compare CA (typically strong) vs smaller state
-- =====================================================
SELECT
    rf.state_code,
    ROUND(AVG(rf.sos)::numeric, 4) as avg_raw_sos,
    ROUND(STDDEV(rf.sos)::numeric, 4) as stddev_raw_sos,
    ROUND(AVG(rf.sos_norm)::numeric, 4) as avg_sos_norm,
    ROUND(STDDEV(rf.sos_norm)::numeric, 4) as stddev_sos_norm,
    COUNT(*) as team_count
FROM rankings_full rf
WHERE rf.age_group = 'u14'
  AND rf.gender = 'Male'
  AND rf.status = 'Active'
  AND rf.state_code IN ('CA', 'TX', 'FL', 'ID', 'MT', 'WY', 'ND')
GROUP BY rf.state_code
ORDER BY avg_raw_sos DESC;

-- =====================================================
-- 6. FORMULA VERIFICATION
-- Does powerscore_core = 0.25*off + 0.25*def + 0.50*sos + 0.15*perf?
-- =====================================================
SELECT
    team_id,
    ROUND(powerscore_core::numeric, 4) as stored_core,
    ROUND((0.25 * off_norm + 0.25 * def_norm + 0.50 * sos_norm + 0.15 * COALESCE(perf_centered, 0))::numeric, 4) as calculated_core,
    ROUND((powerscore_core - (0.25 * off_norm + 0.25 * def_norm + 0.50 * sos_norm + 0.15 * COALESCE(perf_centered, 0)))::numeric, 6) as difference
FROM rankings_full
WHERE status = 'Active'
  AND off_norm IS NOT NULL
  AND def_norm IS NOT NULL
  AND sos_norm IS NOT NULL
ORDER BY ABS(powerscore_core - (0.25 * off_norm + 0.25 * def_norm + 0.50 * sos_norm + 0.15 * COALESCE(perf_centered, 0))) DESC
LIMIT 10;
