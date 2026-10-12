"""Which proposed teams something else changed while the week's proposals were being written.

A proposal is judged on the team as its stage read it. When another session or job writes the
field a proposal changes, or merges the team away, while the week is being proposed, the proposal
is stale and is listed in its stage's stale.json for the owner. Reads only.
"""

from __future__ import annotations

from scripts.find_cross_provider_duplicates import page

GUARDED_FIELDS = ("club_name", "state_code", "age_group", "is_deprecated")
DEPRECATED = "is_deprecated"


def snapshot(sb) -> dict[str, list]:
    """Every team's guarded fields, keyed by team_id_master, in GUARDED_FIELDS order."""
    columns = ",".join(("team_id_master", *GUARDED_FIELDS))
    rows = page(lambda: sb.table("teams").select(columns), "team_id_master")
    return {row["team_id_master"]: [row[field] for field in GUARDED_FIELDS] for row in rows}


def changes(before: dict[str, list], after: dict[str, list]) -> dict[str, dict[str, list]]:
    """{team: {field: [before, after]}} for each guarded field that moved. A team missing from
    either snapshot reads as None there, so one created or deleted in the window moves in each field
    it holds a value in, is_deprecated always."""
    missing = [None] * len(GUARDED_FIELDS)
    moved = {}
    for team in before.keys() | after.keys():
        old, new = before.get(team, missing), after.get(team, missing)
        diff = {field: [a, b] for field, a, b in zip(GUARDED_FIELDS, old, new) if a != b}
        if diff:
            moved[team] = diff
    return moved


def stale(proposals: list[dict], moved: dict[str, dict[str, list]]) -> list[dict]:
    """The proposals whose team changed in the proposed field or in is_deprecated (merged, restored,
    created or deleted in the window)."""
    found = []
    for proposal in proposals:
        diff = moved.get(proposal["team_id_master"], {})
        why = {field: values for field, values in diff.items() if field in (proposal["field"], DEPRECATED)}
        if why:
            found.append({**proposal, "changed": why})
    return found
