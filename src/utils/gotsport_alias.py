"""Which GotSport registration speaks for a team.

A club re-registers a squad season to season and a merge repoints the absorbed
team's aliases onto the survivor, so one canonical team routinely carries several
GotSport ids -- 5,681 of them hold two or more numeric rankings-space aliases, and
2,316 of those absorbed at least one merge. Every tool that probes ``team_details``
has to choose one, and three of them had grown their own copy of that choice with
three different answers: ``assign_team_states`` takes whichever row PostgREST
returns first, and two others take the lowest id. Two tools could therefore read
the same team and disagree about it.

**The newest registration wins here.** GotSport's id space is a sequential
surrogate key allocated upward over time: across 182,295 numeric aliases below
``MAX_PROVIDER_ID`` the correlation between id and discovery time is +0.563, and
the median id per discovery quarter rises monotonically (389,708 -> 563,820 ->
632,828 -> 750,578 over 2025-Q4 to 2026-Q3). The lowest id is therefore the
*stalest* record on file, which is the wrong end for any caller asking what a team
is called now. A third of within-team pairs invert, because the alias timestamp is
PitchRank's discovery time rather than GotSport's registration time; the quarter
medians are the cleaner signal.

Dependency-free apart from the caller's Supabase client, so the hygiene and
backfill workflows -- which install only supabase, python-dotenv and requests --
can import it, exactly as ``team_association_map`` and ``age_group`` already are.

``scripts/repair_out_of_board_cohorts.py`` and ``scripts/assign_team_states.py``
still carry their own copies; migrating them changes what those two tools decide,
so it is tracked separately rather than done here.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# team_details answers to a numeric team_id. Ids at or above this come from
# org_event schedule scrapes, identify a team only within its own event, and 404
# permanently -- 4,192 of the 4,200 teams holding one are still placeholders.
MAX_PROVIDER_ID = 3_000_000

# ASCII digits only and bounded. ``str.isdigit()`` is Unicode-aware, so a bare
# shape check accepts "٧٤٢" and passes it into the query string verbatim, and "²"
# passes it and then raises ValueError in int() -- aborting the whole alias fetch.
# The column is provider-supplied free text: it already holds bracket placeholders
# such as "Playoffs AWinner". See .claude/rules/data-safety.md.
_NUMERIC_ID = re.compile(r"^[0-9]{1,7}$")


def is_rankings_space_id(provider_team_id: Optional[str]) -> bool:
    """Whether ``team_details`` can be expected to know this provider id."""
    pid = str(provider_team_id or "").strip()
    return bool(_NUMERIC_ID.match(pid)) and int(pid) < MAX_PROVIDER_ID


def fetch_gotsport_aliases(supabase, team_ids: List[str], approved_only: bool = True) -> Dict[str, str]:
    """Map each team id to the GotSport provider id that speaks for it.

    ``approved_only`` keeps an unreviewed mapping out of anything that writes back
    to ``teams``: the service-role client sees every ``review_status``, so without
    it a pending alias can outrank an approved one and rename a canonical team from
    a registration nobody has confirmed belongs to it.
    """
    provider = supabase.table("providers").select("id").eq("code", "gotsport").execute().data
    if not provider:
        return {}
    provider_id = provider[0]["id"]

    aliases: Dict[str, str] = {}
    for i in range(0, len(team_ids), 100):
        query = (
            supabase.table("team_alias_map")
            .select("team_id_master,provider_team_id")
            .eq("provider_id", provider_id)
            .in_("team_id_master", team_ids[i : i + 100])
        )
        if approved_only:
            query = query.eq("review_status", "approved")
        for row in query.execute().data or []:
            tid, pid = row["team_id_master"], str(row["provider_team_id"]).strip()
            if not is_rankings_space_id(pid):
                continue
            if tid not in aliases or int(pid) > int(aliases[tid]):
                aliases[tid] = pid
    return aliases
