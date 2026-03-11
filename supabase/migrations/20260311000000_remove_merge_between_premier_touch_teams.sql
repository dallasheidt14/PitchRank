-- Remove team_merge_map entries linking Premier Touch FC teams 49609b32 and c87030ed.
-- These teams are distinct and should not be merged. A merge entry causes the frontend
-- to treat them as the same team (getTeamGames resolves all merged IDs and queries
-- games for ALL of them), making game moves between them invisible.

-- Delete any merge in either direction
DELETE FROM team_merge_map
WHERE (deprecated_team_id = '49609b32-0248-4bc9-bf9a-3671142b9c3d'
       AND canonical_team_id = 'c87030ed-4448-4b2b-b8e5-81029d865d20')
   OR (deprecated_team_id = 'c87030ed-4448-4b2b-b8e5-81029d865d20'
       AND canonical_team_id = '49609b32-0248-4bc9-bf9a-3671142b9c3d');
