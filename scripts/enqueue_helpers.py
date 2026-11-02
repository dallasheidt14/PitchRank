#!/usr/bin/env python3
"""
Shared helpers for the enqueue scripts that select teams from tables directly.

A find_* RPC hands its caller paging, merge resolution and the provider fields;
a script that reads a table itself has to do all of that, so it lives here rather
than in any one caller.
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
    concurrency. Offsets also shift when rows leave the filter during the read (a
    NULL score being filled, say); such a read needs keyset paging (id > last id).
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


def expand_to_aliases(supabase, canonical):
    """Extend a raw-id -> canonical map to cover every deprecated alias of each target.

    A merge leaves rows filed under the pre-merge id, while a caller usually starts
    from the survivor or from whichever single id it happened to see. Resolving only
    the ids it started with misses the other predecessors, so look the merge map up a
    second time by canonical_team_id. Every target maps to itself.
    """
    full = dict(canonical)
    targets = sorted(set(canonical.values()))
    for batch in _chunks(targets):
        rows = (
            supabase.table("team_merge_map")
            .select("deprecated_team_id,canonical_team_id")
            .in_("canonical_team_id", batch)
            .execute()
            .data
            or []
        )
        for r in rows:
            full[r["deprecated_team_id"]] = r["canonical_team_id"]
    for target in targets:
        full.setdefault(target, target)
    return full


def load_team_rows(supabase, team_ids, columns=TEAM_ROW_COLUMNS):
    """Fetch team rows keyed by master id; by default the provider fields enqueue_scrape_request needs."""
    teams = {}
    for batch in _chunks(sorted(team_ids)):
        rows = (
            supabase.table("teams")
            .select(columns)
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
