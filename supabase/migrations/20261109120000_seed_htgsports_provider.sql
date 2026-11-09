-- EnhancedETLPipeline raises ValueError when this row is absent. One provider covers every
-- HTG Sports event (events.htgsports.net/?eventid=...).
INSERT INTO providers (code, name, base_url)
VALUES ('htgsports', 'HTG Sports', 'https://events.htgsports.net')
ON CONFLICT (code) DO NOTHING;
