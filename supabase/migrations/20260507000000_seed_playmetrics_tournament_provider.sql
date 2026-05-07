-- Seed the playmetrics_tournament provider row.
--
-- EnhancedETLPipeline._ensure_initialized() looks up
-- providers.code == 'playmetrics_tournament' and raises ValueError if absent,
-- so any non-dry-run tournament import would fail on a fresh database where
-- only the gotsport seed from the initial schema migration ran.
--
-- This migration only adds the row introduced by this PR (the tournament
-- scraper). Other manually-created providers (playmetrics, tgs, sincsports,
-- affinity_wa, modular11) are pre-existing tech debt and should be backfilled
-- in a separate "seed all providers" migration, not bundled here.
INSERT INTO providers (code, name, base_url)
VALUES ('playmetrics_tournament', 'PlayMetrics (Tournaments)', 'https://playmetricssports.com')
ON CONFLICT (code) DO NOTHING;
