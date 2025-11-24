-- Check North Carolina U12 Boys teams and their statuses
-- This will help us understand why only 6 teams are showing

-- Check all teams (regardless of status)
SELECT 
    COUNT(*) as total_teams,
    status,
    COUNT(*) FILTER (WHERE status = 'Active') as active_count,
    COUNT(*) FILTER (WHERE status = 'Inactive') as inactive_count,
    COUNT(*) FILTER (WHERE status = 'Not Enough Ranked Games') as not_enough_games_count
FROM state_rankings_view
WHERE state = 'NC'
  AND age = 12
  AND gender = 'M'
GROUP BY status
ORDER BY status;

-- Show sample teams with their statuses
SELECT 
    team_name,
    club_name,
    state,
    age,
    gender,
    status,
    power_score_final,
    games_played,
    total_games_played,
    last_game
FROM state_rankings_view
WHERE state = 'NC'
  AND age = 12
  AND gender = 'M'
ORDER BY 
    CASE status 
        WHEN 'Active' THEN 1 
        WHEN 'Inactive' THEN 2 
        ELSE 3 
    END,
    power_score_final DESC
LIMIT 50;

