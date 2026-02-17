-- Filter unsupported age groups from get_teams_to_scrape
--
-- Bug: U8/U9/U19 teams were never scraped (Python filter blocked them),
-- so last_scraped_at stayed NULL. The RPC returned them every run with
-- NULLS FIRST ordering, crowding out eligible teams and causing the
-- scraper to report "0 teams to scrape" even when the user expected thousands.
--
-- Fix: Exclude birth_year outside the supported U10-U18 range at the DB level.
-- The supported range is calculated dynamically: current_year - 18 to current_year - 10.

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
      -- Only include supported age groups (U10-U18)
      -- birth_year range: current_year - 18 (oldest U18) to current_year - 10 (youngest U10)
      AND (t.birth_year IS NULL
           OR t.birth_year BETWEEN (EXTRACT(YEAR FROM NOW())::int - 18)
                                AND (EXTRACT(YEAR FROM NOW())::int - 10))
    ORDER BY t.last_scraped_at ASC NULLS FIRST;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_teams_to_scrape(UUID) IS
'Returns teams that need scraping (not scraped in last 7 days or never scraped).
Excludes teams outside the supported U10-U18 age range based on birth_year.
Optional p_provider_id parameter filters to a specific provider.';
