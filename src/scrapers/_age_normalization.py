"""Shared age-integer-to-canonical-key helper.

Extracted from ``sincsports_events._normalize_age`` (was ``[8, 19]`` band)
and widened to ``[6, 19]`` so ``gotsport_tier_parser`` can distinguish
known-out-of-scope micro-cohorts (``u6``/``u7``/``u8``/``u9``) from genuine
unknowns (``None``). The U18 → U19 merge is preserved verbatim per repo
convention (``gotcha_age_group_format.md``).

The widening is additive for the legacy SincSports caller — ``parse_teamlist``
filters via ``effective_ages = include_ages or CANONICAL_AGE_GROUPS`` before
the helper's output is consumed, and ``CANONICAL_AGE_GROUPS`` excludes
``u6``/``u7``, so existing behavior is unchanged.
"""

from __future__ import annotations

import re
from typing import List, Optional

from src.utils.team_utils import calculate_age_group_from_birth_year

# Division name → cohort token. Tournament divisions almost always carry an
# unambiguous ``U{N}`` somewhere in the name (``"U19 Boys Blue"``,
# ``"U15/16 Boys Tan (2)"``). PitchRank tracks u10..u17 + u19 (u18 merges
# into u19); ``min_age``-style numerical edge cases are out of band.
# Slash form ``U15/16`` matches both numbers (the second number lacks its
# own U prefix); single ``U13`` matches just one.
_DIV_U_SLASH_RE = re.compile(r"\b[Uu](\d{1,2})/(\d{1,2})\b")
_DIV_U_TOKEN_RE = re.compile(r"\b[Uu](\d{1,2})\b")
# Birth-year slash form: ``2014/15`` (full second year ``2014/2015`` also
# accepted). SOM Sports tournament divisions use this for dual-age cohorts —
# ``"Oro 2014/15 11v11"`` → take the older (earlier) birth year → 2014 →
# look up its U-cohort (u12 in 2025-26 season). PlayMetrics divisions almost
# never use this form, so the extra branch is a no-op for that caller.
_DIV_BIRTH_YEAR_SLASH_RE = re.compile(r"\b(20\d{2})/(?:20)?(\d{2})\b")


def normalize_age(age_int: int) -> Optional[str]:
    """Map an age integer to a canonical lowercase key, applying the U18 → U19 merge.

    Returns ``None`` for ages outside ``[6, 19]``; the U18 special-case
    short-circuits ahead of the band check so the legacy convention is
    preserved regardless of band.
    """
    if age_int == 18:
        return "u19"
    if 6 <= age_int <= 19:
        return f"u{age_int}"
    return None


def derive_division_age_group(division_name: str) -> Optional[str]:
    """Pull a u-cohort out of a tournament division name.

    Returns ``"u10"``..``"u17"`` or ``"u19"``; ``None`` if no recognizable
    age token is present (caller falls back to team-name derivation, then
    ``min_age``).

    Three accepted forms (checked in order — first match wins):

    1. **U-token slash** (``"U15/16 Boys Tan (2)"``) → take the **higher**
       U-age, which is the OLDER cohort. Older players play up; the team is
       classified as their primary (older) tier.
    2. **Birth-year slash** (``"Oro 2014/15 11v11"``) → take the **earlier**
       birth year (older players), look up its U-cohort via the season-aware
       birth-year → cohort map. SOM Sports tournament divisions use this form.
    3. **Single U-token** (``"U19 Boys Blue"``).

    See ``memory/gotcha_slash_age_tokens.md`` for the unified older-cohort rule.
    """
    if not division_name:
        return None

    # Form 1: U-token slash (``U15/16`` → take higher U → u16)
    slash = _DIV_U_SLASH_RE.search(division_name)
    if slash:
        older = max(int(slash.group(1)), int(slash.group(2)))
        if 10 <= older <= 17:
            return f"u{older}"
        if older in (18, 19):
            return "u19"
        return None

    # Form 2: Birth-year slash (``2014/15`` → take earlier year → u-cohort)
    by_slash = _DIV_BIRTH_YEAR_SLASH_RE.search(division_name)
    if by_slash:
        year1 = int(by_slash.group(1))
        year2_raw = by_slash.group(2)
        year2 = int(year2_raw) if len(year2_raw) == 4 else 2000 + int(year2_raw)
        older_year = min(year1, year2)  # earlier birth year = older players
        cohort = calculate_age_group_from_birth_year(older_year)
        return cohort.lower() if cohort else None

    # Form 3: Single U-token(s) — collect all and take highest
    nums: List[int] = [int(m) for m in _DIV_U_TOKEN_RE.findall(division_name)]
    if not nums:
        return None
    older = max(nums)
    if 10 <= older <= 17:
        return f"u{older}"
    if older in (18, 19):
        return "u19"
    return None
