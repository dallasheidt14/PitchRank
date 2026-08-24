"""Team-related utility functions"""

import re
from datetime import datetime
from typing import Optional


def _soccer_season_year(now=None) -> int:
    """Return the soccer season year for a date (default: today), Aug 1 cutoff.

    Soccer seasons run Aug 1 – Jul 31.  Before Aug 1 the season year is the
    previous calendar year (e.g. March 2026 → 2025 season).  On or after Aug 1
    the season year equals the calendar year (e.g. Sep 2026 → 2026 season).
    """
    now = now or datetime.now()
    return now.year if now.month >= 8 else now.year - 1


# Season year for age calculations — auto-updates every Aug 1
CURRENT_YEAR = _soccer_season_year()


def scrape_excluded_birth_years(today=None) -> list[int]:
    """Birth years outside PitchRank's u10-u19 range for the season of `today`.

    The old end is age 21+ (yr-21, yr-20); yr-19 stays eligible because the
    age-20 collapse files it into u19. The young end is U9 and younger
    (yr-8, yr-7, yr-6). Mirrors the SQL in the scrape-eligibility RPCs
    (migration 20260824120000); change both together or they diverge.
    """
    yr = _soccer_season_year(today)
    return [yr - 21, yr - 20, yr - 8, yr - 7, yr - 6]


def extract_birth_year_from_name(team_name: str) -> Optional[int]:
    """
    Extract birth year from a team name.

    Looks for 4-digit years starting with 20 (e.g., 2014, 2013, 2015).
    Returns the birth year if found and valid, None otherwise.

    Args:
        team_name: The team name to extract birth year from

    Returns:
        Birth year as integer, or None if not found

    Examples:
        >>> extract_birth_year_from_name("ILLINOIS MAGIC FC 2014")
        2014
        >>> extract_birth_year_from_name("FC Chicago 2013-2014 Elite")
        2013  # Returns first match
        >>> extract_birth_year_from_name("Chicago Fire Academy")
        None
    """
    if not team_name:
        return None

    # Match years like 2010-2018 (valid youth soccer birth years)
    match = re.search(r"\b(20\d{2})\b", team_name)
    if match:
        year = int(match.group(1))
        # Validate it's a reasonable birth year for youth soccer
        # Covers U7 to U20 for the current season
        if (CURRENT_YEAR - 20) <= year <= (CURRENT_YEAR - 6):
            return year
    return None


def calculate_age_group_from_birth_year(birth_year: int, current_year: int = CURRENT_YEAR) -> Optional[str]:
    """
    Calculate age group from birth year.

    Formula: age = current_year - birth_year + 1 → f"U{age}"
    Season year rolls over on Aug 1 (see _soccer_season_year).
    Age 18 collapses into U19 to match AGE_GROUPS (config/settings.py).

    Args:
        birth_year: The birth year (e.g., 2014)
        current_year: The season year for calculation (default: auto from Aug 1 cutoff)

    Returns:
        Age group string like "U12", or None if invalid

    Examples:
        >>> calculate_age_group_from_birth_year(2014, 2025)
        'U12'
        >>> calculate_age_group_from_birth_year(2013, 2025)
        'U13'
        >>> calculate_age_group_from_birth_year(2008, 2025)
        'U19'
    """
    age = current_year - birth_year + 1
    # A birth year sits in one of two bands, because the season runs Aug 1 - Jul 31
    # and so straddles Jan 1. This formula returns the OLDER of the two. For the
    # oldest cohort that band does not exist -- U19 is 2008/07, and there is no U20
    # in youth soccer -- so 2007 computed age 20 and fell out as None, leaving those
    # teams with no cohort at all. Only birth year 2007 reaches age 20; no other
    # year changes.
    if age == 20:
        age = 19
    if 7 <= age <= 19:  # Valid youth soccer age range
        if age == 18:
            age = 19
        return f"U{age}"
    return None
