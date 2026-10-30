-- EnhancedETLPipeline raises ValueError when this row is absent, and
-- scripts/import_demosphere.py refuses to run without it. One row covers every Demosphere
-- league site; the site id is part of each provider team id.
INSERT INTO providers (code, name, base_url)
VALUES ('demosphere', 'Demosphere', 'https://elements.demosphere.com')
ON CONFLICT (code) DO NOTHING;
