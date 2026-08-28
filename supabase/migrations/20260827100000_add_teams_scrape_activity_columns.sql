-- Persist per-team scrape-activity signals so eligibility is a column read.
--
-- The scrape queue re-checks teams that stopped playing, or that never produced
-- a game at all: find_stale_teams selects on "never scraped or 90d+ stale" and
-- find_discovery_teams on "no future games", both of which a dormant team
-- satisfies permanently. Gating on activity needs per-team aggregates over
-- ~3M game rows, which times out when computed live, so refresh_team_scrape_activity()
-- materialises them here weekly.
--
-- No index is added. The eligibility rule is a five-branch OR containing a
-- non-indexable EXISTS, so Postgres applies it as a post-scan filter and an
-- index on any one column degrades to the provider_id prefix that
-- teams_provider_scrape_priority_idx already serves — while costing HOT-update
-- suppression on every row the weekly refresh touches.

ALTER TABLE teams ADD COLUMN IF NOT EXISTS last_played_at DATE;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS last_fixture_at DATE;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS game_row_count INTEGER;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS scrape_attempts INTEGER;

COMMENT ON COLUMN teams.last_played_at IS
  'Most recent game_date with both scores set, resolved through team_merge_map. '
  'NULL means either the refresh has not run for this team yet, or it has no '
  'scored game; use game_row_count to tell those apart.';

COMMENT ON COLUMN teams.last_fixture_at IS
  'Most recent game_date of any kind — past or future, scored or not — resolved '
  'through team_merge_map. NULL means the refresh has not run for this team yet.';

COMMENT ON COLUMN teams.game_row_count IS
  'Count of game rows of any kind, resolved through team_merge_map. 0 (not NULL) '
  'for a team with no games. NULL means the refresh has not run for this team yet.';

COMMENT ON COLUMN teams.scrape_attempts IS
  'Count of non-error team_scrape_log rows, resolved through team_merge_map. A '
  'rolling counter, not a lifetime one: team_scrape_log begins 2025-11-03. '
  '0 (not NULL) for a team never logged. NULL means the refresh has not run yet.';
