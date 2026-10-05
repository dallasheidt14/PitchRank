-- EnhancedETLPipeline raises ValueError when this row is absent. Elite Academy League
-- (Modular11 tournament 27) is its own provider, separate from MLS NEXT's `modular11`:
-- its team ids are Modular11 UID_team values, never the MLS NEXT club-age keys.
INSERT INTO providers (code, name, base_url)
VALUES ('modular11_ea', 'Modular11 Elite Academy League', 'https://www.modular11.com')
ON CONFLICT (code) DO NOTHING;
