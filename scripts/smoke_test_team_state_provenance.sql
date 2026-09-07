-- One-off smoke test for 20260829120000_add_team_state_provenance.sql.
--
-- Proves the mechanism end to end on one team: the pre-image guard refuses a stale
-- write, a real write lands and is logged with its actor, and the revert puts the
-- provenance back. The last statement prints one row per step with the answer it
-- wanted beside the answer it got.
--
-- Deliberately free of DO blocks and dollar quoting: the Supabase SQL editor splits a
-- script on semicolons and takes a plpgsql body apart mid-string.
--
-- Safe on production. It never changes a team's state_code, only the three provenance
-- columns, and it undoes those. Re-running clears the previous run first.

DROP TABLE IF EXISTS pg_temp.smoke_team;
DROP TABLE IF EXISTS pg_temp.smoke_result;

DELETE FROM team_state_audit WHERE applied_by IN ('smoke', 'smoke_revert');

CREATE TEMP TABLE smoke_team AS
SELECT team_id_master AS team_id, state_code AS state
FROM teams
WHERE state_code IS NOT NULL AND is_deprecated = false
ORDER BY team_id_master
LIMIT 1;

CREATE TEMP TABLE smoke_result AS
SELECT 1 AS step,
       'stale pre-image refused' AS checked,
       'false' AS want,
       apply_team_state(team_id, 'ZZ', state::text, 'smoke_test', 0.95, 'smoke', 'correct', 'stale pre-image')::text AS got
FROM smoke_team;

INSERT INTO smoke_result
SELECT 2, 'write applied', 'true',
       apply_team_state(team_id, state::text, state::text, 'smoke_test', 0.95, 'smoke', 'correct', 'smoke test')::text
FROM smoke_team;

INSERT INTO smoke_result
SELECT 3, 'ledger rows written', '1', count(*)::text
FROM team_state_audit WHERE applied_by = 'smoke';

INSERT INTO smoke_result
SELECT 4, 'ledger stamped the actor', 'smoke', max(applied_by)
FROM team_state_audit WHERE applied_by = 'smoke';

INSERT INTO smoke_result
SELECT 5, 'revert wrote', '1', rows_changed::text
FROM revert_team_states('smoke', now() - interval '1 hour', now() + interval '1 hour',
                        'smoke_revert', NULL, 500, false, 'undo the smoke test');

INSERT INTO smoke_result
SELECT 6, 'team state untouched', s.state, t.state_code
FROM teams t JOIN smoke_team s ON s.team_id = t.team_id_master;

INSERT INTO smoke_result
SELECT 7, 'provenance restored', 'null', coalesce(t.state_source, 'null')
FROM teams t JOIN smoke_team s ON s.team_id = t.team_id_master;

SELECT step, checked, want, got, CASE WHEN want = got THEN 'PASS' ELSE 'FAIL' END AS verdict
FROM smoke_result ORDER BY step;

-- Run this once every row above says PASS.
-- DELETE FROM team_state_audit WHERE applied_by IN ('smoke', 'smoke_revert');
