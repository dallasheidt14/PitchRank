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

# Globals set in main()
SCRAPE_TS: Optional[str] = None
SCRAPE_RUN_ID: Optional[str] = None
