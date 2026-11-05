-- Seed the affinity_hi provider row.
--
-- EnhancedETLPipeline._ensure_initialized() looks up providers.code == 'affinity_hi'
-- and raises ValueError if absent, so the import step of hi-scraper.yml fails on
-- the first run without this row. A dry run fails the same way: the lookup
-- happens before the dry-run branch.
INSERT INTO providers (code, name, base_url)
VALUES ('affinity_hi', 'Affinity Sports HI', 'https://hysa.sportsaffinity.com')
ON CONFLICT (code) DO NOTHING;
