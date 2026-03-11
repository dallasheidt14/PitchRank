-- Move 3 Playmaker Sports Tournaments games (2026-02-28 and 2026-03-01)
-- FROM: Premier Touch FC LB 2014 (49609b32-0248-4bc9-bf9a-3671142b9c3d)
-- TO:   Premier Touch LA 2014    (c87030ed-4448-4b2b-b8e5-81029d865d20)
--
-- These games were scraped under the wrong team. The games table has an
-- immutability trigger, so we temporarily disable it for the update.

BEGIN;

-- 1. Unlock immutable games for update
UPDATE games SET is_immutable = false
WHERE (home_team_master_id = '49609b32-0248-4bc9-bf9a-3671142b9c3d'
    OR away_team_master_id = '49609b32-0248-4bc9-bf9a-3671142b9c3d')
  AND competition ILIKE '%Playmaker%'
  AND game_date IN ('2026-02-28', '2026-03-01')
  AND is_excluded = false;

-- 2. Move home games
UPDATE games
SET home_team_master_id = 'c87030ed-4448-4b2b-b8e5-81029d865d20'
WHERE home_team_master_id = '49609b32-0248-4bc9-bf9a-3671142b9c3d'
  AND competition ILIKE '%Playmaker%'
  AND game_date IN ('2026-02-28', '2026-03-01')
  AND is_excluded = false;

-- 3. Move away games
UPDATE games
SET away_team_master_id = 'c87030ed-4448-4b2b-b8e5-81029d865d20'
WHERE away_team_master_id = '49609b32-0248-4bc9-bf9a-3671142b9c3d'
  AND competition ILIKE '%Playmaker%'
  AND game_date IN ('2026-02-28', '2026-03-01')
  AND is_excluded = false;

-- 4. Re-lock games
UPDATE games SET is_immutable = true
WHERE (home_team_master_id = 'c87030ed-4448-4b2b-b8e5-81029d865d20'
    OR away_team_master_id = 'c87030ed-4448-4b2b-b8e5-81029d865d20')
  AND competition ILIKE '%Playmaker%'
  AND game_date IN ('2026-02-28', '2026-03-01')
  AND is_excluded = false;

COMMIT;
