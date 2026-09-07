#!/usr/bin/env python3
"""
Shared helpers for the enqueue scripts that read behavioural tables directly.

The RPC-driven selectors (enqueue_active_teams, enqueue_yesterday_games,
enqueue_discovery_teams, enqueue_safety_net) get paging, merge resolution and
the provider fields handed to them by their find_* RPC. A script that selects
from a table instead has to do all of it itself, so it lives here rather than in
any one caller.
"""

PAGE_SIZE = 1000
BATCH_SIZE = 100

# The signal is a user clicking "find missing game" on a team page, which
# frontend/app/api/scrape-missing-game writes as missing_game at priority 1.
# create-team's new_team rows are an admin action, not user interest.
USER_CLICK_REQUEST_TYPE = "missing_game"

TEAM_ROW_COLUMNS = "team_id_master,team_name,provider_id,provider_team_id,last_scraped_at"


def _paged(query_builder):
    """Page a PostgREST select past the 1000-row cap.

    Ordered by id because Postgres is free to return an unordered query's rows in
    a different order for each range, which drops and repeats rows across the page
    boundary. That is the whole guarantee: three of the four tables read here key
    on gen_random_uuid(), so a row inserted mid-read still lands at a random
    position and can displace another. A total order fixes the boundary, not
    concurrency.
    """
    rows, offset = [], 0
    while True:
        batch = query_builder().order("id").range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _chunks(items, size=BATCH_SIZE):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def resolve_merges(supabase, team_ids):
    """Map deprecated team ids onto their canonical survivor.

    execute_team_merge flattens chains, so one hop is enough.
    """
    canonical = {}
    for batch in _chunks(sorted(team_ids)):
        rows = (
            supabase.table("team_merge_map")
            .select("deprecated_team_id,canonical_team_id")
            .in_("deprecated_team_id", batch)
            .execute()
            .data
            or []
        )
        for r in rows:
            canonical[r["deprecated_team_id"]] = r["canonical_team_id"]
    return {t: canonical.get(t, t) for t in team_ids}


def load_team_rows(supabase, team_ids):
    """Fetch the provider fields enqueue_scrape_request needs, keyed by master id."""
    teams = {}
    for batch in _chunks(sorted(team_ids)):
        rows = (
            supabase.table("teams")
            .select(TEAM_ROW_COLUMNS)
            .in_("team_id_master", batch)
            .execute()
            .data
            or []
        )
        for r in rows:
            teams[r["team_id_master"]] = r
    return teams


def teams_with_pending_user_request(supabase, team_ids):
    """Teams holding a pending row this job must not touch.

    enqueue_scrape_request's UPDATE branch rewrites game_date from the parameter,
    so calling it on a user's own pending row would move that row's +/-90 day
    scrape window onto today, off the date the user asked about.

    Priority 1 is the proxy for "a user chose this date", because request_type
    cannot be. The RPC's UPDATE branch does not touch request_type, so a click
    landing on an existing pending automatic row promotes it to priority 1 and
    writes the user's date while the row still reads as active_team. And a
    retention_hygiene row is already priority 1, so a click on one leaves a row
    byte-identical to an unclicked one. The other two priority-1 producers
    (create-team, enqueue_user_interest_teams) both anchor on today, so protecting
    them costs nothing beyond a skipped re-anchor.
    """
    protected = set()
    for batch in _chunks(sorted(team_ids)):
        rows = (
            supabase.table("scrape_requests")
            .select("team_id_master")
            .in_("team_id_master", batch)
            .eq("status", "pending")
            .eq("priority", 1)
            .execute()
            .data
            or []
        )
        protected.update(r["team_id_master"] for r in rows if r["team_id_master"])
    return protected
