-- Fix get_teams_to_scrape to accept provider_id parameter
--
-- Bug: The RPC function returned ALL providers' teams that needed scraping,
-- but the Python code then filtered by a specific provider_id. When all teams
-- for the target provider had been recently scraped, but other providers had
-- stale teams, the function returned those other providers' team IDs, which
-- then got filtered to 0 results.
--
-- Fix: Add optional provider_id parameter to filter at the database level.
-- Default is NULL for backward compatibility (returns all providers).

CREATE OR REPLACE FUNCTION get_teams_to_scrape(p_provider_id UUID DEFAULT NULL)
RETURNS TABLE (
    team_id UUID,
    provider_team_id TEXT,
    team_name TEXT,
    last_scraped TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.team_id_master,
        t.provider_team_id,
        t.team_name,
        t.last_scraped_at
    FROM teams t
    WHERE (t.last_scraped_at IS NULL OR t.last_scraped_at < NOW() - INTERVAL '7 days')
      AND (p_provider_id IS NULL OR t.provider_id = p_provider_id)
    ORDER BY t.last_scraped_at ASC NULLS FIRST;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_teams_to_scrape(UUID) IS
'Returns teams that need scraping (not scraped in last 7 days or never scraped).
Optional p_provider_id parameter filters to a specific provider.
If p_provider_id is NULL, returns teams from all providers (backward compatible).';
