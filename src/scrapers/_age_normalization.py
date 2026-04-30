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

from typing import Optional


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
