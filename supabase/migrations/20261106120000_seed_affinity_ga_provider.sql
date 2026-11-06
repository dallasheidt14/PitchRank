-- Seed the affinity_ga provider row.
--
-- EnhancedETLPipeline._ensure_initialized() looks up providers.code == 'affinity_ga'
-- and raises ValueError if absent, so the import step of ga-scraper.yml fails on
-- the first run without this row. A dry run fails the same way: the lookup
-- happens before the dry-run branch.
INSERT INTO providers (code, name, base_url)
VALUES ('affinity_ga', 'Affinity Sports GA', 'https://gs.sportsaffinity.com')
ON CONFLICT (code) DO NOTHING;
