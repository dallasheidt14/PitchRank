-- EnhancedETLPipeline raises ValueError when this row is absent. MLS NEXT (Homegrown and
-- Academy Divisions) publishes its 2026-27 schedules and results through Kitman Labs, not
-- Modular11. Its team ids are Kitman squad ids with the season appended (`5747:2026`), never
-- the Modular11 club-age keys that `modular11` aliases carry.
INSERT INTO providers (code, name, base_url)
VALUES ('mlsnext_kitman', 'MLS NEXT', 'https://mls-assist.theintelligenceplatform.com')
ON CONFLICT (code) DO NOTHING;
