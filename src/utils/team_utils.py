"""Team-related utility functions"""

import re
from typing import Optional, Tuple

# Current year for age calculations (update annually at season rollover)
CURRENT_YEAR = 2025


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
        # 2005-2018 covers U7 to U20 for 2025 season
        if 2005 <= year <= 2018:
            return year
    return None


def calculate_age_group_from_birth_year(birth_year: int, current_year: int = CURRENT_YEAR) -> Optional[str]:
    """
    Calculate age group from birth year.

    Formula: age = current_year - birth_year + 1 → f"U{age}"

    Args:
        birth_year: The birth year (e.g., 2014)
        current_year: The current year for calculation (default: 2025)

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


def get_age_group_from_team_name(team_name: str, fallback_age_group: Optional[str] = None) -> Tuple[Optional[str], Optional[int]]:
    """
    Get age group from team name, with optional fallback.

    Prioritizes birth year in team name over any fallback value.
    This ensures teams playing up are ranked by their actual age group.

    Args:
        team_name: The team name to extract age group from
        fallback_age_group: Optional fallback age group (e.g., from bracket)

    Returns:
        Tuple of (age_group, birth_year) - birth_year is None if using fallback

    Examples:
        >>> get_age_group_from_team_name("ILLINOIS MAGIC FC 2014", "U13")
        ('U12', 2014)  # Birth year takes priority over bracket age
        >>> get_age_group_from_team_name("FC Chicago Elite", "U13")
        ('U13', None)  # Falls back to provided age group
    """
    birth_year = extract_birth_year_from_name(team_name)
    if birth_year:
        age_group = calculate_age_group_from_birth_year(birth_year)
        if age_group:
            return (age_group, birth_year)

    # Normalize fallback age group
    if fallback_age_group:
        fallback = fallback_age_group.strip().upper()
        if not fallback.startswith('U'):
            fallback = f"U{fallback}"
        return (fallback, None)

    return (None, None)


def is_playing_up(actual_age_group: str, bracket_age_group: str) -> bool:
    """
    Determine if a team is playing up (in an older bracket).

    Args:
        actual_age_group: Team's actual age group (e.g., "U11")
        bracket_age_group: The bracket/division age group (e.g., "U12")

    Returns:
        True if team is playing up, False otherwise

    Examples:
        >>> is_playing_up("U11", "U12")
        True
        >>> is_playing_up("U12", "U12")
        False
        >>> is_playing_up("U13", "U12")
        False  # Playing down
    """
    if not actual_age_group or not bracket_age_group:
        return False

    actual_match = re.search(r'U?(\d+)', actual_age_group, re.I)
    bracket_match = re.search(r'U?(\d+)', bracket_age_group, re.I)

    if actual_match and bracket_match:
        actual_age = int(actual_match.group(1))
        bracket_age = int(bracket_match.group(1))
        return bracket_age > actual_age

    return False
