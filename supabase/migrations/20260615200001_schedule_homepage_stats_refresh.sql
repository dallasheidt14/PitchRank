-- Refresh the home page stats cache once a day, off the request path. pg_cron
-- runs in-database (no GitHub Actions schedule drift); the offset minute keeps it
-- off the top of the hour. cron.schedule upserts by job name, so this is
-- idempotent on re-apply.

CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
  'refresh-homepage-stats',
  '13 8 * * *',
  $$ SELECT public.refresh_homepage_stats(); $$
);
