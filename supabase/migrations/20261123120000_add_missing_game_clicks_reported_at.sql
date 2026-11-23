-- When the missing-game report first emailed each click; NULL until then. The scheduled report
-- emails the NULL ones.
ALTER TABLE missing_game_clicks ADD COLUMN IF NOT EXISTS reported_at TIMESTAMPTZ;

-- Clicks before the cutoff were emailed before this column existed; stamp them so the first run
-- does not send them again.
UPDATE missing_game_clicks
SET reported_at = NOW()
WHERE reported_at IS NULL
  AND clicked_at < '2026-11-23 15:00:00+00';
