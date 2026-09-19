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
        2013  # the first year; read a two-year band with extract_band_birth_year
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


# A two-year band as team names write it: "2013/2014", "2013/14", "13/14", "B13/14",
# "Academy-2013/2014", "2012/2013Black", "2013 - 2014". The run of joined years is
# matched whole and possessively, so a longer list ("B2014/B2015/B2016U") is judged
# as the list it is, never cut back to the band its first two years resemble.
# The edges refuse only what would extend the run or make it a U-age range: a digit,
# an apostrophe (the '11/'12 form is not read here), or a U ("U13/14", "13/14U",
# "U-13/14", "Under 14/15"). A two-digit year may not start just after "digit,
# separator", so "U13 / 14 / 15" cannot restart at 14; a four-digit one may, which
# keeps "U14/15 - 2011/2012" and "1-2016/2017" readable.
_BAND_YEAR = r"[BbGgMmFf]?(?:20[0-9]{2}|[0-9]{2})[BbGgMmFf]?"
_BAND_RUN_RE = re.compile(
    r"(?<![0-9'Uu])(?<![Uu]-)(?<!\b[Uu]nder )"
    r"(?:[BbGgMmFf]?20[0-9]{2}"
    r"|(?<![0-9][/–-])(?<![0-9][/–-]\s)(?<![0-9]\s[/–-])(?<![0-9]\s[/–-]\s)[BbGgMmFf]?[0-9]{2})"
    rf"[BbGgMmFf]?(?:\s*[/\-–]\s*{_BAND_YEAR})++"
    r"(?![0-9'Uu])"
)
# Restarts inside a crafted run can each rescan it to the end, so the scan is capped
# well above the length of any real team or division name.
_BAND_SCAN_LIMIT = 200


def extract_band_birth_year(team_name: str, current_year: Optional[int] = None) -> Optional[int]:
    """Younger birth year of the first two-year band in a team name, or None.

    A band is named by its younger year, however it is spelled: "2013/2014",
    "2013/14", "14/13" and "B13/14" all return 2014. Only a run of exactly two
    consecutive years is a band. A pair younger than U7 is a season written into
    the name ("2025-26", "22/23") and is passed over for a later band.

    The year comes back even when its band has aged out or is too young to board,
    so a caller that found a band converts it with calculate_age_group_from_band
    instead of falling back to a single year read from the same name.

    Examples:
        >>> extract_band_birth_year("FC Chicago 2013/14 Elite")
        2014
        >>> extract_band_birth_year("CSC 2014 / 2015 / 2016 Boys")
        None
    """
    if not team_name or len(team_name) > _BAND_SCAN_LIMIT:
        return None
    season = CURRENT_YEAR if current_year is None else current_year
    for run in _BAND_RUN_RE.finditer(team_name):
        years = [int(y) if len(y) == 4 else 2000 + int(y) for y in re.findall(r"20[0-9]{2}|[0-9]{2}", run.group(0))]
        if len(years) == 2 and abs(years[0] - years[1]) == 1 and max(years) <= season - 6:
            return max(years)
    return None


def calculate_age_group_from_band(younger_year: int, current_year: Optional[int] = None) -> Optional[str]:
    """Age group a two-year band names, from its younger year: 2014 -> "U13" in 2026-27.

    calculate_age_group_from_birth_year without its age-20 fold. A lone 2007 is U19,
    because U19 (2008/07) is the only band containing it, but the BAND 2007/06 is
    the group above U19 and has aged out.
    """
    season = CURRENT_YEAR if current_year is None else current_year
    age = season - younger_year + 1
    if 7 <= age <= 19:
        return "U19" if age == 18 else f"U{age}"
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
