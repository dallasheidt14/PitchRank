-- Seed the affinity_or provider row.
--
-- EnhancedETLPipeline._ensure_initialized() looks up providers.code == 'affinity_or'
-- and raises ValueError if absent, so the Oregon import step of or-scraper.yml
-- fails on the first run without this row. A dry run fails the same way: the
-- lookup happens before the dry-run branch.
--
-- Scope is the row this PR introduces. The other manually-created providers
-- (playmetrics, tgs, sincsports, affinity_wa, modular11, squadi, somsports)
-- remain pre-existing tech debt for a separate "seed all providers" migration,
-- matching the note in 20260507000000_seed_playmetrics_tournament_provider.sql.
INSERT INTO providers (code, name, base_url)
VALUES ('affinity_or', 'Affinity Sports OR', 'https://oysa.sportsaffinity.com')
ON CONFLICT (code) DO NOTHING;
