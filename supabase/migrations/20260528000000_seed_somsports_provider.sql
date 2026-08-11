-- Seed the somsports provider row.
--
-- EnhancedETLPipeline._ensure_initialized() looks up
-- providers.code == 'somsports' and raises ValueError if absent, so any
-- non-dry-run SOM Sports / athletes2events tournament import would fail on
-- a fresh database where only the gotsport seed from the initial schema
-- migration ran.
--
-- This migration only adds the row introduced by this PR (the SOM Sports
-- tournament scraper). Other manually-created providers (playmetrics, tgs,
-- sincsports, affinity_wa, modular11) are pre-existing tech debt and should
-- be backfilled in a separate "seed all providers" migration, not bundled
-- here.
INSERT INTO providers (code, name, base_url)
VALUES ('somsports', 'SOM Sports / athletes2events', 'https://somsports.athletes2events.com')
ON CONFLICT (code) DO NOTHING;
