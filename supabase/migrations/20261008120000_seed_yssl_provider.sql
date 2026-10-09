-- Seed the yssl provider row (Young Sportsmen's Soccer League, Chicago area).
-- EnhancedETLPipeline raises ValueError when this row is absent, and
-- scripts/import_yssl.py refuses to run without it.
INSERT INTO providers (code, name, base_url)
VALUES ('yssl', 'YSSL', 'https://www.yssl.org')
ON CONFLICT (code) DO NOTHING;
