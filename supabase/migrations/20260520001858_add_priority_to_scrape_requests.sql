-- Add priority column to scrape_requests
-- Pre-flight (2026-05-20): 0 duplicate pending rows, 0 NULL team_id_master pending rows.
-- DELETE consolidation step is NOT needed.

ALTER TABLE scrape_requests
  ADD COLUMN IF NOT EXISTS priority smallint NOT NULL DEFAULT 5;

COMMENT ON COLUMN scrape_requests.priority IS
  'Lower number = higher priority. 1=user-clicked, 2=daily yesterday-game, 3=discovery, 4=safety-net, 5=default';

-- Note: NULL team_id_master rows are allowed to have multiple pending rows
-- because a partial unique index on a single column does NOT enforce uniqueness
-- over NULL values (NULLs are never considered equal in SQL unique constraints).

-- Unique pending per team (partial index — NULL team_id_master rows allowed multiple)
CREATE UNIQUE INDEX IF NOT EXISTS idx_scrape_requests_pending_team
  ON scrape_requests (team_id_master)
  WHERE status = 'pending';

-- Drain-order index
CREATE INDEX IF NOT EXISTS idx_scrape_requests_priority_pending
  ON scrape_requests (priority ASC, requested_at ASC)
  WHERE status = 'pending';
