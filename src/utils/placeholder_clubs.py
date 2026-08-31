"""Club names that mean "this team has no club".

Providers write a literal dropdown value instead of leaving the field empty, so
``club_name`` comes back non-null and every repair path that looks for a *missing*
club walks straight past it. TGS's "No Club Selection" is the largest single
``club_name`` in this database — 1,596 teams, more than any real club — and it is
not a club at all.

Pooling unrelated teams under one name is what makes this load-bearing rather than
cosmetic. Those 1,596 span 23 states among the 246 that have one, so any rule that
reads a club reads a fiction:

* ``assign_team_states`` Tier B abstains today only because two meaningful states
  silence a club. That is one distribution away from stamping 1,596 unrelated teams
  with whichever state happens to lead, and the lead is currently CA at 38%.
* ``GameHistoryMatcher._resolve_state_from_club`` asks whether every stated team of
  a club agrees. For a placeholder the answer is always no, so it spends two queries
  per created team to learn nothing.
* ``name_tokens`` feeds the club name to the locality index, which is why "selection"
  is currently being weighed as a possible place name.

``athlete one`` is here for a different reason and is not a typo: it is the provider
AthleteOne's own name landing in ``club_name``. Its 23 teams are not one club — only
two carry a state, both FL, which is exactly enough for Tier B's two-team floor to
propose Florida for the other 21. ``match_state_from_club.py`` reached the same
conclusion independently and has excluded it for longer than this module has existed.

The empty string is a member so that callers can normalise and test in one step.
"""

from __future__ import annotations

from typing import Optional

# The union of the five hand-copied ``NO_CLUB_VALUES`` sets that predate this module
# (match_state_from_club, extract_missing_club_names, backfill_missing_club_names,
# backfill_unknown_team_names, extract_and_import_tgs_teams). They had already drifted:
# eight values were missing from one copy and ``athlete one`` from four, which is the
# reason this is a module rather than a sixth copy.
PLACEHOLDER_CLUB_NAMES = frozenset(
    {
        "",
        "athlete one",
        "choose club",
        "n/a",
        "na",
        "no club",
        "no club assigned",
        "no club listed",
        "no club selected",
        "no club selection",
        "none",
        "not applicable",
        "not selected",
        "null",
        "select a club",
        "select club",
        "unassigned",
    }
)


def is_placeholder_club(club_name: Optional[str]) -> bool:
    """Whether this ``club_name`` names no club, so callers can treat it as absent.

    Matches on the same key clubs are grouped by — ``strip().lower()`` — because the
    raw column splits one value across case and whitespace variants, and the provider
    writes "NO CLUB SELECTION", "No Club Selection" and " no club selection " alike.
    """
    return (club_name or "").strip().lower() in PLACEHOLDER_CLUB_NAMES
