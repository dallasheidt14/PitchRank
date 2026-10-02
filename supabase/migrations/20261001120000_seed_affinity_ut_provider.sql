-- Seed the affinity_ut provider row.
--
-- EnhancedETLPipeline._ensure_initialized() looks up providers.code == 'affinity_ut'
-- and raises ValueError if absent, so the import step of ut-scraper.yml fails on
-- the first run without this row. A dry run fails the same way: the lookup
-- happens before the dry-run branch.
INSERT INTO providers (code, name, base_url)
VALUES ('affinity_ut', 'Affinity Sports UT', 'https://uysa.sportsaffinity.com')
ON CONFLICT (code) DO NOTHING;
