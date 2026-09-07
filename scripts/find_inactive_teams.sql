-- Non-deprecated teams whose last PLAYED game predates 2025-01-01.
--
-- Two things this query does that a naive version gets wrong:
--   1. Resolves games through team_merge_map. Merges cascade teams/team_alias_map
--      but games keep the pre-merge master id, so an active canonical team can look
--      dead if its history sits under a deprecated id. Skipping this overstates the
--      cohort by ~770 teams.
--   2. Counts only games with both scores set. A null-score row is a scheduled or
--      unscraped fixture, not evidence the team played.
--
-- Usage: read-only. Swap the final SELECT for the COUNT variant at the bottom to
-- size the cohort without pulling rows.

WITH team_games AS (
    SELECT home_team_master_id AS tid, game_date,
           (home_score IS NOT NULL AND away_score IS NOT NULL) AS played
    FROM games
    UNION ALL
    SELECT away_team_master_id AS tid, game_date,
           (home_score IS NOT NULL AND away_score IS NOT NULL) AS played
    FROM games
),
resolved AS (
    SELECT COALESCE(m.canonical_team_id, tg.tid) AS tid, tg.game_date, tg.played
    FROM team_games tg
    LEFT JOIN team_merge_map m ON m.deprecated_team_id = tg.tid
    WHERE tg.tid IS NOT NULL
),
activity AS (
    SELECT tid,
           MAX(game_date) FILTER (WHERE played)          AS last_played,
           COUNT(*)      FILTER (WHERE played)           AS played_games,
           COUNT(*)      FILTER (WHERE game_date > CURRENT_DATE) AS future_fixtures
    FROM resolved
    GROUP BY tid
)
SELECT t.team_id_master,
       t.team_name,
       t.club_name,
       t.state_code,
       t.age_group,
       t.gender,
       p.code                       AS provider,
       a.last_played,
       a.played_games,
       a.future_fixtures,
       t.last_scraped_at::date      AS last_scraped,
       (mt.tid IS NOT NULL)         AS is_merge_target,
       (rh.tid IS NOT NULL)         AS in_ranking_history
FROM teams t
JOIN activity a ON a.tid = t.team_id_master
LEFT JOIN providers p ON p.id = t.provider_id
LEFT JOIN (SELECT DISTINCT canonical_team_id AS tid FROM team_merge_map) mt ON mt.tid = t.team_id_master
LEFT JOIN (SELECT DISTINCT team_id AS tid FROM ranking_history) rh ON rh.tid = t.team_id_master
WHERE t.is_deprecated IS NOT TRUE
  AND a.last_played < '2025-01-01'
ORDER BY a.played_games DESC, a.last_played ASC;

-- Cohort size only:
--   ... SELECT COUNT(*) FROM teams t JOIN activity a ON a.tid = t.team_id_master
--       WHERE t.is_deprecated IS NOT TRUE AND a.last_played < '2025-01-01';
