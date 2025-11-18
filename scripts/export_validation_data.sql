-- =====================================================
-- Export Validation Data
-- =====================================================
-- Run these queries in Supabase SQL Editor
-- Then download the results as CSV files
-- =====================================================

-- QUERY 1: Export Recent Games (last 180 days)
-- Save as: validation_games.csv
-- =====================================================
SELECT
    id,
    game_date,
    home_team_master_id,
    away_team_master_id,
    home_score,
    away_score
FROM games
WHERE game_date >= CURRENT_DATE - INTERVAL '180 days'
    AND home_score IS NOT NULL
    AND away_score IS NOT NULL
ORDER BY game_date DESC
LIMIT 1000;

-- =====================================================
-- QUERY 2: Export Current Rankings
-- Save as: validation_rankings.csv
-- =====================================================
SELECT
    team_id_master,
    team_name,
    power_score_final,
    sos_norm,
    offense_norm,
    defense_norm,
    win_percentage,
    games_played
FROM rankings_view;

-- =====================================================
-- INSTRUCTIONS:
-- =====================================================
-- 1. Copy Query 1 above
-- 2. Run in Supabase SQL Editor
-- 3. Click "Download as CSV"
-- 4. Save as /tmp/validation_games.csv
--
-- 5. Copy Query 2 above
-- 6. Run in Supabase SQL Editor
-- 7. Click "Download as CSV"
-- 8. Save as /tmp/validation_rankings.csv
--
-- 9. Run: python src/predictions/validate_simple.py
-- =====================================================
