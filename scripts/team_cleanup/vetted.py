"""What a merge list records about each team, so the applier can tell when one has changed since.

A merge is judged on two rows as they stood when the list was built. A later write to either
row's age group, gender, state or club can make the pair wrong without deprecating either, so a
list records both rows' values beside each pair, and the applier refuses a pair whose rows no
longer carry them, or that does not record both in full.
"""

from __future__ import annotations

IDENTITY_FIELDS = ("age_group", "gender", "state_code", "club_name")
MERGE_AS_VETTED, KEEP_AS_VETTED = "merge_as_vetted", "keep_as_vetted"


def as_vetted(team: dict) -> dict:
    return {field: team[field] for field in IDENTITY_FIELDS}


def stamp(merge_team: dict, keep_team: dict) -> dict:
    return {MERGE_AS_VETTED: as_vetted(merge_team), KEEP_AS_VETTED: as_vetted(keep_team)}


def records_teams(pair: dict) -> bool:
    """Whether the pair carries both teams' values in full."""
    return all(
        isinstance(pair.get(key), dict) and set(IDENTITY_FIELDS) <= set(pair[key])
        for key in (MERGE_AS_VETTED, KEEP_AS_VETTED)
    )


def changed_since_vetted(pair: dict, merge_team: dict, keep_team: dict) -> str | None:
    """Why the pair's rows no longer match what its list recorded, or the list records too little to
    compare; None when they match."""
    if not records_teams(pair):
        return "the list does not record the teams as they were vetted"
    changes = [
        f"{side} {field} {pair[key][field]!r} -> {team[field]!r}"
        for side, key, team in (("merge", MERGE_AS_VETTED, merge_team), ("keep", KEEP_AS_VETTED, keep_team))
        for field in IDENTITY_FIELDS
        if team[field] != pair[key][field]
    ]
    return f"changed since it was vetted: {'; '.join(changes)}" if changes else None
