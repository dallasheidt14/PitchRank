"""Turn a provider's age-group label into the spelling `teams.age_group` stores.

The unknown-opponent hygiene chain runs four scripts that each derive a cohort and
then compare their answers, so they have to agree exactly. They previously kept
three hand-synced copies of this helper, and the copies drifted: one folded U18
into u19 and one did not, which scored every correct u19 auto-link a mismatch.

Kept dependency-free, and deliberately not in ``config.settings``: the hygiene
workflow installs only supabase, python-dotenv and requests, and importing that
module pulls the rankings stack (numpy, pandas) in behind it. This mirrors
``team_association_map``, which the same scripts already import.
"""

from __future__ import annotations

import re
from typing import Optional

# ASCII digits only, and at most two of them. ``str.isdigit()`` is Unicode-aware,
# so a bare shape check accepts "u٣٢" and "u１２"; it is also unbounded, so a long
# input reaches teams.age_group verbatim. Both are provider-supplied strings that
# end up in a database write and a PostgREST filter.
_AGE_GROUP = re.compile(r"^u([0-9]{1,2})$")

# U19 is the oldest board PitchRank keeps and it holds three birth years, so both
# boundary ages collapse into it -- the same two folds
# ``team_utils.calculate_age_group_from_birth_year`` applies. GotSport labels that
# cohort U18 and U20 far more often than U19.
_FOLD_INTO_U19 = frozenset({"u18", "u20"})


def normalize_age_group(value: Optional[object]) -> Optional[str]:
    """Return the stored ``u<age>`` spelling, or None when the label names no cohort.

    Accepts the provider's forms ("U14", "14", " u14 ") and the stored form.
    Cohorts PitchRank does not board are returned as-is rather than refused:
    GotSport reports real U8 and U9 teams, recording them accurately is right, and
    refusing them would send the caller back to the opponent's cohort -- which is
    the bug this chain exists to close.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s.isdigit():
        s = f"u{s}"
    if not _AGE_GROUP.match(s):
        return None
    return "u19" if s in _FOLD_INTO_U19 else s
