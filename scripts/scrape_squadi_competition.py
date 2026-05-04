"""SQUADI competition scraper.

Public JSON API at https://api.us.squadi.com requires an anonymous auth token
harvested from the SPA bundle at https://registration.us.squadi.com. v1 scope:
NJYS State Cup competitions; the same code handles any US state on Squadi by
swapping the organisation UUID.

Outputs:
- data/raw/squadi/<scrape_run_id>/games.csv  (28-col canonical)
- data/raw/squadi/<scrape_run_id>/teams.csv  (matcher seed)
- data/raw/squadi/<scrape_run_id>/manifest.json
- data/raw/squadi/<scrape_run_id>/raw/<comp_uuid>/  (optional, --keep-raw)

Dry-run mode (--dry-run, default) validates token harvest + extraction without
writing any output to disk; use --no-dry-run to write CSVs.
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

sys.path.append(str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# -----------------------------
# CONSTANTS
# -----------------------------

SQUADI_SPA_BASE = "https://registration.us.squadi.com"
SQUADI_API_BASE = "https://api.us.squadi.com"
OUTPUT_DIR = "data/raw/squadi"
TOKEN_CACHE_PATH = Path.home() / ".cache" / "squadi" / "token.json"
TOKEN_TTL_SECONDS = 24 * 60 * 60  # 24h

# organisation_unique_key → metadata. Add entries as states are onboarded.
ORG_REGISTRY: Dict[str, Dict[str, str]] = {
    "7cfab077-e619-47e4-ab36-0febc29501a2": {
        "state": "New Jersey",
        "state_code": "NJ",
        "timezone": "America/New_York",
    },
}

# Squadi yearRefId → calendar year (from /common/common/reference/year, 2026-05-04)
YEAR_REF_TO_CALENDAR: Dict[int, int] = {
    1: 2020, 2: 2019, 3: 2021, 4: 2022, 5: 2023,
    6: 2024, 7: 2025, 8: 2026,
}

# Default name-blocklist for discovery (overridable via SQUADI_COMP_BLOCKLIST env).
DEFAULT_COMP_NAME_BLOCKLIST: Tuple[str, ...] = ("Demo Comp",)

REQUIRED_COLUMNS = [
    "provider",
    "scrape_run_id",
    "event_id",
    "event_name",
    "schedule_id",
    "age_year",
    "age_group",
    "gender",
    "team_id",
    "team_id_source",
    "team_name",
    "club_name",
    "opponent_id",
    "opponent_id_source",
    "opponent_name",
    "opponent_club_name",
    "state",
    "state_code",
    "game_date",
    "game_time",
    "home_away",
    "goals_for",
    "goals_against",
    "result",
    "venue",
    "source_url",
    "scraped_at",
    "division_name",
]

TEAMS_COLUMNS = [
    "provider",
    "provider_team_id",
    "provider_team_id_source",
    "team_name",
    "club_name",
    "age_group",
    "gender",
    "state",
    "state_code",
    "division_name",
    "tier",
    "external_org_id",
    "meta",
]

# -----------------------------
# PURE HELPERS
# -----------------------------


def compute_result(goals_for: Optional[int], goals_against: Optional[int]) -> str:
    """Compute result from a team's perspective: W / L / D / U."""
    if goals_for is None or goals_against is None:
        return "U"
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


def parse_int_or_none(v: Any) -> Optional[int]:
    """Parse a game score. Only whole integers in 0..50 are accepted; else None.

    Filters malformed scores at scrape time so they don't surface as bogus W/L/D
    rows. Matches the importer validation window (src/utils/enhanced_validators.py).
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if 0 <= v <= 50 else None
    s = str(v).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    try:
        f = float(s)
    except (ValueError, TypeError):
        return None
    if not f.is_integer():
        return None
    i = int(f)
    return i if 0 <= i <= 50 else None


def parse_utc_to_local_date(iso_utc: Optional[str], tz_name: str) -> Tuple[str, str]:
    """Convert a UTC ISO timestamp to (YYYY-MM-DD, HH:MM) in the given timezone.

    Returns ('', '') on parse failure or empty input.
    """
    if not iso_utc:
        return ("", "")
    try:
        dt_iso = iso_utc.rstrip("Z")
        dt = datetime.fromisoformat(dt_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo(tz_name))
        return (local.strftime("%Y-%m-%d"), local.strftime("%H:%M"))
    except (ValueError, TypeError):
        return ("", "")


# Match all "<n>U" tokens and pick the largest (older cohort wins for dual-age).
_AGE_TOKEN_RE = re.compile(r"\b(\d{1,2})[Uu]\b")


def parse_division_metadata(
    division_name: str,
    fallback_age_int: Optional[int],
) -> Tuple[str, str, str]:
    """Parse division.divisionName into (age_group, gender, tier).

    Rules (locked in spec §A and reinforced by memory):
    - age_group format: "u<n>" lowercase (gotcha_age_group_format).
    - Dual-age divisions take the OLDER cohort, e.g. "15U/16U" → u16
      (gotcha_slash_age_tokens).
    - u18 always remaps to u19 since PitchRank merges u18 into u19
      (gotcha_no_u18_age_group).
    - gender returns "Boys" / "Girls" — never "Male" / "Female"
      (gotcha_format_gender_returns_boys_girls). Empty string when ambiguous.
    - tier is the residual division name with the age and gender tokens stripped.
    - When the regex finds no age token, fall back to fallback_age_int + 1
      (Squadi stores division.age as "min age", so age=10 means 11U).
    - PitchRank tracks u10–u17 and u19; ages outside this range return "".
    """
    name = (division_name or "").strip()
    if not name:
        return ("", "", name)

    # Age — pick the largest U-token (older cohort)
    matches = _AGE_TOKEN_RE.findall(name)
    age_group = ""
    if matches:
        nums = sorted({int(m) for m in matches})
        n = nums[-1]
        if n == 18:
            age_group = "u19"
        elif n == 19 or 10 <= n <= 17:
            age_group = f"u{n}"
    elif fallback_age_int is not None:
        n = fallback_age_int + 1  # Squadi "min age" convention
        if n == 18:
            age_group = "u19"
        elif 10 <= n <= 17 or n == 19:
            age_group = f"u{n}"

    # Gender
    lower = name.lower()
    if " boys" in f" {lower}" or lower.startswith("boys"):
        gender = "Boys"
    elif " girls" in f" {lower}" or lower.startswith("girls"):
        gender = "Girls"
    else:
        gender = ""

    # Tier: residual after stripping all age tokens + gender tokens
    tier = _AGE_TOKEN_RE.sub("", name)
    tier = re.sub(r"(?i)\b(boys|girls)\b", "", tier)
    tier = re.sub(r"\s*/\s*", " ", tier)  # collapse "/ " from dual-age splits
    tier = re.sub(r"\s+", " ", tier).strip()

    return (age_group, gender, tier)


# Globals set in main()
SCRAPE_TS = None
SCRAPE_RUN_ID = None
