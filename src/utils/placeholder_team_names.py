"""The name a team carries when its provider could not name it.

A team discovered without a name is stored as ``PLACEHOLDER_TEAM_NAME``. Legacy rows carry
``unknown_<provider_team_id>``, which exposes the provider's id in a public column, so every backend
reader treats both forms as "no name". Only that exact legacy form counts: ``unknown_elite`` and
``unknown_FC Dallas`` are real registered names.

The site (``frontend/lib/utils.ts``, hash-pinned for the Compare research) recognises only the legacy
form, so it shows ``PLACEHOLDER_TEAM_NAME`` as stored rather than composing a name from the club.

No third-party imports, so any script can use this whatever its workflow installs.
"""

from __future__ import annotations

import re
from typing import Optional

PLACEHOLDER_TEAM_NAME = "Unknown team"

# A PostgREST ``or`` filter for selecting candidates. It also selects real names such as
# ``unknown_elite``, so callers decide each row with ``is_placeholder_team_name``.
PLACEHOLDER_TEAM_NAME_FILTER = rf"team_name.like.unknown\_%,team_name.eq.{PLACEHOLDER_TEAM_NAME}"

# ASCII digits and bounded: see .claude/rules/data-safety.md.
_LEGACY_SHAPE = re.compile(r"unknown_[0-9]{1,12}", re.IGNORECASE | re.ASCII)


def is_placeholder_team_name(team_name: Optional[str], provider_team_id: Optional[str] = None) -> bool:
    """Whether ``team_name`` stands in for a name the provider never gave.

    With a ``provider_team_id``, the legacy form must name that id exactly, and a blank id
    matches no legacy name. Without one, for a reader that does not select the id, any
    ``unknown_`` followed only by digits matches.
    """
    name = (team_name or "").strip()
    if name.lower() == PLACEHOLDER_TEAM_NAME.lower():
        return True
    if provider_team_id is None:
        return bool(_LEGACY_SHAPE.fullmatch(name))
    pid = str(provider_team_id).strip()
    return bool(pid) and name.lower() == f"unknown_{pid}".lower()
