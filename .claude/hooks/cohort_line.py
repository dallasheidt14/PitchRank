"""Print the current season's cohort mapping.

Reads the season from src/utils/team_utils.py so the hook never re-derives it.
"""

import os
import sys

sys.path.insert(0, os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

from src.utils.team_utils import CURRENT_YEAR, calculate_age_group_from_birth_year  # noqa: E402

cohort = calculate_age_group_from_birth_year(2014)
season = f"{CURRENT_YEAR}-{CURRENT_YEAR + 1}"
print(f"soccer season {season} (rolls Aug 1): birth year 2014 => {cohort}, so 14B = {cohort} Male")
