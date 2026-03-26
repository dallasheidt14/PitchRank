"""Team-related utility functions"""

import re
from datetime import datetime
from typing import Optional, Tuple


def _soccer_season_year() -> int:
    """Return the current soccer season year based on Aug 1 cutoff.

    Soccer seasons run Aug 1 – Jul 31.  Before Aug 1 the season year is the
    previous calendar year (e.g. March 2026 → 2025 season).  On or after Aug 1
    the season year equals the calendar year (e.g. Sep 2026 → 2026 season).
    """
    now = datetime.now()
    return now.year if now.month >= 8 else now.year - 1


# Season year for age calculations — auto-updates every Aug 1
CURRENT_YEAR = _soccer_season_year()


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
    match = re.search(r'\b(20\d{2})\b', team_name)
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
    """
    age = current_year - birth_year + 1
    if 7 <= age <= 19:  # Valid youth soccer age range
        return f"U{age}"
    return None


