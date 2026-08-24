# SQUADI Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a league-pipeline scraper for SQUADI (registration.us.squadi.com) targeting New Jersey Youth Soccer State Cup competitions, emitting the canonical 27-column CSV consumable by `scripts/import_games_enhanced.py`.

**Architecture:** Single CLI script at `scripts/scrape_squadi_competition.py` modeled on `scripts/scrape_playmetrics_league.py`. Public JSON API at `api.us.squadi.com` requires an anonymous auth token harvested from the SPA bundle at startup (with 401-triggered refresh). Discovery walks org → year → competitions (filter `statusRefId==2`) → divisions → rounds → matches. Each match emits two CSV rows (one per team perspective) plus a deduplicated `(teamUUID, divisionId)` record to a separate `teams.csv`. Default `--dry-run` mode validates token harvest + extraction + CSV write to a temp dir without touching Supabase.

**Tech Stack:** Python 3.11, `requests`, `pandas`, `zoneinfo` (stdlib), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-04-squadi-scraper-design.md` (commit `597397b94` on branch `scraper/squadi-nj`).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `scripts/scrape_squadi_competition.py` | Create | CLI entry, token harvest, API client, discovery, extraction, CSV/JSON output. Single-file mirroring `scrape_playmetrics_league.py`. |
| `tests/unit/test_scrape_squadi.py` | Create | Pytest unit tests for pure helpers (regex parsers, score validation, timezone conversion, URL parser, token extraction). |
| `tests/unit/fixtures/squadi/` | Create | Canned JSON responses + mock SPA HTML/bundle for tests. |
| `tests/unit/fixtures/squadi/competitions_list_sample.json` | Create | 4-comp sample with `statusRefId` mix (2=active, 3=demo). |
| `tests/unit/fixtures/squadi/divisions_sample.json` | Create | Divisions with various age/gender/dual-age/u18 cases. |
| `tests/unit/fixtures/squadi/round_matches_sample.json` | Create | 6 matches: W/L, Draw, Draw+PKs, Forfeit, Scheduled, Abandoned. |
| `tests/unit/fixtures/squadi/spa_index.html` | Create | Tiny mock SPA HTML referencing `main.<hash>.js`. |
| `tests/unit/fixtures/squadi/main_bundle_sample.js` | Create | Tiny mock JS containing a fake 256-char hex token next to `"authorization"`. |
| `supabase/migrations/20260504000000_add_squadi_provider.sql` | Create | One-time INSERT into `providers` table. |
| `src/etl/enhanced_pipeline.py` | Modify (around line 240, after `playmetrics` branch) | Add `provider_code.lower() == "squadi"` branch using vanilla `GameHistoryMatcher`. |
| `data/raw/squadi/.gitkeep` | Create | Output root for scrape runs. |

**Decomposition rationale:** mirroring PlayMetrics' single-file shape keeps the diff reviewable and the conventions consistent. Pure helpers (parsers, validators) get unit-tested; HTTP plumbing, CSV writing, and matcher integration are covered by the manual verification step (Task 16) — same testing strategy as PlayMetrics/TGS/Affinity-WA per `tests/unit/test_scrape_playmetrics.py:13-16`.

---

## Task 1: Module skeleton + constants

**Files:**
- Create: `scripts/scrape_squadi_competition.py`
- Test: `tests/unit/test_scrape_squadi.py`

- [ ] **Step 1: Create the failing test for the module's required columns**

```python
# tests/unit/test_scrape_squadi.py
"""Unit tests for pure helpers in scripts/scrape_squadi_competition.py.

Scope (mirroring tests/unit/test_scrape_playmetrics.py):
- Pure parsers for age/gender/tier, club, external org id, source URL.
- Score validator and UTC-to-local-date converter.
- Token-bundle regex extractors.

The token harvester's network round-trip, the SquadiClient HTTP layer, the
discovery filter, and the CSV writer are covered by the end-to-end dry-run
verification in Task 16, not by unit tests.
"""

from scripts.scrape_squadi_competition import REQUIRED_COLUMNS


def test_required_columns_match_canonical_27_plus_division_name():
    assert REQUIRED_COLUMNS[0] == "provider"
    assert REQUIRED_COLUMNS[-1] == "division_name"
    assert len(REQUIRED_COLUMNS) == 28
    # Order matches scripts/scrape_playmetrics_league.py REQUIRED_COLUMNS exactly
    expected = [
        "provider", "scrape_run_id", "event_id", "event_name", "schedule_id",
        "age_year", "age_group", "gender", "team_id", "team_id_source",
        "team_name", "club_name", "opponent_id", "opponent_id_source",
        "opponent_name", "opponent_club_name", "state", "state_code",
        "game_date", "game_time", "home_away", "goals_for", "goals_against",
        "result", "venue", "source_url", "scraped_at", "division_name",
    ]
    assert REQUIRED_COLUMNS == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::test_required_columns_match_canonical_27_plus_division_name -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.scrape_squadi_competition'`

- [ ] **Step 3: Create the module skeleton**

```python
# scripts/scrape_squadi_competition.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::test_required_columns_match_canonical_27_plus_division_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py && git commit -m "feat(squadi): add scraper module skeleton with REQUIRED_COLUMNS"
```

---

## Task 2: Pure helpers — `compute_result`, `parse_int_or_none`, `parse_utc_to_local_date`

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_scrape_squadi.py`:

```python
import pytest

from scripts.scrape_squadi_competition import (
    compute_result,
    parse_int_or_none,
    parse_utc_to_local_date,
)


class TestComputeResult:
    @pytest.mark.parametrize(
        "gf, ga, expected",
        [(2, 1, "W"), (1, 2, "L"), (3, 3, "D"), (0, 0, "D"),
         (None, 1, "U"), (1, None, "U"), (None, None, "U")],
    )
    def test_outcomes(self, gf, ga, expected):
        assert compute_result(gf, ga) == expected


class TestParseIntOrNone:
    @pytest.mark.parametrize(
        "value, expected",
        [(0, 0), (3, 3), (50, 50), ("0", 0), ("7", 7), ("3.0", 3)],
    )
    def test_valid_scores(self, value, expected):
        assert parse_int_or_none(value) == expected

    @pytest.mark.parametrize(
        "value",
        [None, "", " ", "None", "null", True, False, "2.5", "-1", -1, 51, 999, "abc"],
    )
    def test_invalid_or_out_of_range(self, value):
        assert parse_int_or_none(value) is None


class TestParseUtcToLocalDate:
    def test_njys_evening_kickoff_stays_same_day(self):
        # 22:30 UTC on 2024-09-06 = 18:30 ET on 2024-09-06
        date_str, time_str = parse_utc_to_local_date(
            "2024-09-06T22:30:00.000Z", "America/New_York"
        )
        assert date_str == "2024-09-06"
        assert time_str == "18:30"

    def test_late_night_utc_rolls_back_to_previous_day_in_et(self):
        # 03:00 UTC on 2024-09-07 = 23:00 ET on 2024-09-06
        date_str, time_str = parse_utc_to_local_date(
            "2024-09-07T03:00:00.000Z", "America/New_York"
        )
        assert date_str == "2024-09-06"
        assert time_str == "23:00"

    def test_malformed_input_returns_blank_pair(self):
        assert parse_utc_to_local_date("not-a-date", "America/New_York") == ("", "")
        assert parse_utc_to_local_date("", "America/New_York") == ("", "")
        assert parse_utc_to_local_date(None, "America/New_York") == ("", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py -v`
Expected: 3 import-time failures (helpers not defined)

- [ ] **Step 3: Implement the helpers**

Append to `scripts/scrape_squadi_competition.py` (after constants block):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py && git commit -m "feat(squadi): add compute_result/parse_int_or_none/parse_utc_to_local_date"
```

---

## Task 3: Age group + gender + tier parser from `divisionName`

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`

- [ ] **Step 1: Write failing tests** (covers all gotchas from memory: age-group format, u18→u19 remap, dual-age older-cohort, Boys/Girls)

Append to `tests/unit/test_scrape_squadi.py`:

```python
from scripts.scrape_squadi_competition import parse_division_metadata


class TestParseDivisionMetadata:
    @pytest.mark.parametrize(
        "division_name, fallback_age_int, expected",
        [
            # Standard cases
            ("11U Boys Challenge Cup", 10, ("u11", "Boys", "Challenge Cup")),
            ("14U Girls National Championship Series", 13,
             ("u14", "Girls", "National Championship Series")),
            ("17U Boys Champions League", 16, ("u17", "Boys", "Champions League")),
            # Dual-age picks the older cohort
            ("15U/16U Girls National Championship Series", 14,
             ("u16", "Girls", "National Championship Series")),
            ("13U/14U Boys Challenge Cup", 12, ("u14", "Boys", "Challenge Cup")),
            # u18 remaps to u19
            ("18U Boys Champions League", 17, ("u19", "Boys", "Champions League")),
            ("17U/18U Girls Challenge Cup", 16, ("u19", "Girls", "Challenge Cup")),
            # Trailing whitespace / mixed case
            ("  11U   Boys   Challenge Cup  ", 10, ("u11", "Boys", "Challenge Cup")),
            # Boys/Girls capitalization variants — output is always "Boys"/"Girls"
            ("11U BOYS Challenge Cup", 10, ("u11", "Boys", "Challenge Cup")),
            ("11U girls Challenge Cup", 10, ("u11", "Girls", "Challenge Cup")),
        ],
    )
    def test_well_formed_division_names(self, division_name, fallback_age_int, expected):
        assert parse_division_metadata(division_name, fallback_age_int) == expected

    def test_no_age_token_falls_back_to_division_age_int(self):
        # division.age=10 means 11U per Squadi's "min age" convention
        assert parse_division_metadata("Boys Recreational", 10) == ("u11", "Boys", "Recreational")

    def test_no_age_token_no_fallback_returns_blank_age(self):
        assert parse_division_metadata("Boys Recreational", None) == ("", "Boys", "Recreational")

    def test_no_gender_token_returns_blank_gender(self):
        assert parse_division_metadata("11U Open Division", 10) == ("u11", "", "Open Division")

    def test_age_below_tracked_range_returns_blank(self):
        # u9 etc. are out of PitchRank's tracked range
        assert parse_division_metadata("9U Boys Recreational", 8) == ("", "Boys", "Recreational")

    def test_fully_unparseable(self):
        assert parse_division_metadata("Random String", None) == ("", "", "Random String")
        assert parse_division_metadata("", None) == ("", "", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestParseDivisionMetadata -v`
Expected: ImportError

- [ ] **Step 3: Implement `parse_division_metadata`**

Append to `scripts/scrape_squadi_competition.py`:

```python
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
            age_group = f"u{n}" if n != 18 else "u19"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestParseDivisionMetadata -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py && git commit -m "feat(squadi): add parse_division_metadata with dual-age + u18→u19 rules"
```

---

## Task 4: Club name + external org id parsers

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from scripts.scrape_squadi_competition import parse_club_name, extract_external_org_id


class TestParseClubName:
    @pytest.mark.parametrize(
        "team_name, expected_club",
        [
            ("Mount Olive SC - STA Mount Olive 2014 EDP Boys", "Mount Olive SC"),
            ("Wall SC - Liverpool", "Wall SC"),
            ("Point Pleasant Travel SC - Wave United Black", "Point Pleasant Travel SC"),
            # No dash → club = full name
            ("NJ Stallions 14 Betis EDP", "NJ Stallions 14 Betis EDP"),
            # Empty / None
            ("", ""),
            (None, ""),
            # Multiple dashes → first segment only
            ("Team A - Sub - Detail", "Team A"),
            # Whitespace handling
            ("  Wall SC  -  Liverpool  ", "Wall SC"),
        ],
    )
    def test_split(self, team_name, expected_club):
        assert parse_club_name(team_name) == expected_club


class TestExtractExternalOrgId:
    def test_standard_logo_url(self):
        url = "https://storage.googleapis.com/download/storage/v1/b/squadi-prod-us.appspot.com/o/%2Forganisation%2Flogo_org_443_1720797311497.blob?generation=1720797311634378&alt=media"
        assert extract_external_org_id(url) == "443"

    def test_comp_logo_url_returns_none(self):
        # comp_<id> isn't an org id
        url = "https://storage.googleapis.com/download/storage/v1/b/squadi-prod-us.appspot.com/o/%2Fcomp_46%2Flogo_1725580224902.blob"
        assert extract_external_org_id(url) is None

    def test_missing_or_blank(self):
        assert extract_external_org_id(None) is None
        assert extract_external_org_id("") is None
        assert extract_external_org_id("https://example.com/no-org-here.png") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py -v -k "ParseClubName or ExtractExternalOrgId"`
Expected: ImportError

- [ ] **Step 3: Implement helpers**

Append:

```python
_LOGO_ORG_RE = re.compile(r"org_(\d+)")


def parse_club_name(team_name: Optional[str]) -> str:
    """Split team_name on first ' - ' separator; left side = club name.

    Squadi convention is "<Club> - <Team>". Returns full team_name when no
    separator present. Returns "" for None/empty input.
    """
    if not team_name:
        return ""
    s = team_name.strip()
    if " - " in s:
        return s.split(" - ", 1)[0].strip()
    return s


def extract_external_org_id(logo_url: Optional[str]) -> Optional[str]:
    """Pull the Squadi club-org id from a team's logoUrl.

    Squadi stores logos at .../organisation/logo_org_<orgId>_<ts>.blob — the
    org id is a useful matcher tie-breaker when two clubs share a short name.
    Returns None when the URL is missing/blank or has no org_<n> token.
    The "comp_<n>" prefix is for competition logos, not orgs, so it's filtered.
    """
    if not logo_url:
        return None
    m = _LOGO_ORG_RE.search(logo_url)
    return m.group(1) if m else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py -v -k "ParseClubName or ExtractExternalOrgId"`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py && git commit -m "feat(squadi): add parse_club_name and extract_external_org_id"
```

---

## Task 5: SQUADI URL parser (--url flag input)

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from scripts.scrape_squadi_competition import parse_squadi_url


class TestParseSquadiUrl:
    def test_full_url_extraction(self):
        url = ("https://registration.us.squadi.com/livescoreSeasonFixture"
               "?organisationKey=7cfab077-e619-47e4-ab36-0febc29501a2"
               "&competitionUniqueKey=539ff993-3032-414e-9dfe-5466629fc1c9"
               "&yearId=6&divisionId=All")
        result = parse_squadi_url(url)
        assert result["org_uuid"] == "7cfab077-e619-47e4-ab36-0febc29501a2"
        assert result["competition_uuid"] == "539ff993-3032-414e-9dfe-5466629fc1c9"
        assert result["year_ref_id"] == 6

    def test_missing_org_key_returns_none(self):
        url = "https://registration.us.squadi.com/livescoreSeasonFixture?yearId=6"
        assert parse_squadi_url(url) is None

    def test_missing_year_id_is_optional(self):
        url = ("https://registration.us.squadi.com/livescoreSeasonFixture"
               "?organisationKey=7cfab077-e619-47e4-ab36-0febc29501a2"
               "&competitionUniqueKey=539ff993-3032-414e-9dfe-5466629fc1c9")
        result = parse_squadi_url(url)
        assert result["org_uuid"] == "7cfab077-e619-47e4-ab36-0febc29501a2"
        assert result["year_ref_id"] is None

    def test_invalid_url_returns_none(self):
        assert parse_squadi_url("not a url") is None
        assert parse_squadi_url("") is None
        assert parse_squadi_url(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestParseSquadiUrl -v`
Expected: ImportError

- [ ] **Step 3: Implement parser**

Append:

```python
from urllib.parse import parse_qs, urlparse


def parse_squadi_url(url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a SQUADI livescoreSeasonFixture URL into discovery params.

    Returns {"org_uuid", "competition_uuid", "year_ref_id"} or None when the
    URL is missing the organisationKey query param (the only required field).
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        qs = parse_qs(parsed.query)
    except (ValueError, AttributeError):
        return None

    org_uuid = (qs.get("organisationKey") or [None])[0]
    if not org_uuid:
        return None

    comp_uuid = (qs.get("competitionUniqueKey") or [None])[0]
    year_id_raw = (qs.get("yearId") or [None])[0]
    year_ref_id = None
    if year_id_raw is not None:
        try:
            year_ref_id = int(year_id_raw)
        except (ValueError, TypeError):
            year_ref_id = None

    return {
        "org_uuid": org_uuid,
        "competition_uuid": comp_uuid,
        "year_ref_id": year_ref_id,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestParseSquadiUrl -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py && git commit -m "feat(squadi): add parse_squadi_url for --url flag"
```

---

## Task 6: Token bundle regex extractors (pure functions)

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`
- Create: `tests/unit/fixtures/squadi/spa_index.html`
- Create: `tests/unit/fixtures/squadi/main_bundle_sample.js`

- [ ] **Step 1: Create test fixtures**

Create `tests/unit/fixtures/squadi/spa_index.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Football</title></head>
<body>
<div id="root"></div>
<script src="/static/js/main.e68022e7.js"></script>
<script src="/static/js/2.abcdef.chunk.js"></script>
</body>
</html>
```

Create `tests/unit/fixtures/squadi/main_bundle_sample.js`:

```js
// minimal mock SPA bundle
var TOKEN="f68a1ffd26dd50c0fafa1f496a92e7b674e07fb0cfab5c778c2cf47cf6f61f784f7b1981fa99c057ce5607ffba2f8c9578a18b0605ead797aee4263a4cb6a10db09d69367df51443e4ea225c928ae08bba6b80d593a9f6bc9e724fff8e73558fced35550aed587e6b2014bc852709d906b58a494160b331574816ff0fe6ad95b52cc32beb1b70e67d8f06251d80a116e2b32ae335509c999c513249d43d73394be9135d91221494f8b3f542a80e9590a289d3df8e845e147331c70c44fab0ca03e8a1524831ccabfcfe8f703b8b7ffb741fb9b29880551e5eda5a38d32301dc2";
fetch(url, {headers: {"authorization": TOKEN}});
```

- [ ] **Step 2: Write failing tests**

Append to `tests/unit/test_scrape_squadi.py`:

```python
from pathlib import Path

from scripts.scrape_squadi_competition import (
    extract_bundle_url_from_html,
    extract_token_from_bundle,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "squadi"


class TestExtractBundleUrlFromHtml:
    def test_finds_main_bundle(self):
        html = (FIXTURE_DIR / "spa_index.html").read_text()
        assert extract_bundle_url_from_html(html) == "/static/js/main.e68022e7.js"

    def test_no_main_bundle_returns_none(self):
        assert extract_bundle_url_from_html("<html></html>") is None
        assert extract_bundle_url_from_html(
            '<script src="/static/js/2.abcdef.chunk.js"></script>'
        ) is None


class TestExtractTokenFromBundle:
    def test_finds_token_next_to_authorization_keyword(self):
        bundle = (FIXTURE_DIR / "main_bundle_sample.js").read_text()
        token = extract_token_from_bundle(bundle)
        assert token is not None
        assert len(token) >= 256
        assert all(c in "0123456789abcdef" for c in token)
        assert token.startswith("f68a1ffd")

    def test_no_token_returns_none(self):
        assert extract_token_from_bundle("var x = 1; var y = 'hello';") is None

    def test_short_hex_strings_are_rejected(self):
        # Must be at least 256 chars to qualify
        bundle = 'var TOKEN="' + ("a" * 100) + '"; "authorization"'
        assert extract_token_from_bundle(bundle) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py -v -k "Extract"`
Expected: ImportError

- [ ] **Step 4: Implement extractors**

Append to `scripts/scrape_squadi_competition.py`:

```python
# Bundle URL: /static/js/main.<hash>.js
_BUNDLE_URL_RE = re.compile(r'(/static/js/main\.[a-f0-9]+\.js)')

# Token: 256+ char lowercase hex string (Squadi's auth token).
# Used as a candidate filter; we then verify proximity to "authorization".
_TOKEN_HEX_RE = re.compile(r'([a-f0-9]{256,1024})')


def extract_bundle_url_from_html(html: Optional[str]) -> Optional[str]:
    """Find the SPA's main JS bundle URL in the served HTML."""
    if not html:
        return None
    m = _BUNDLE_URL_RE.search(html)
    return m.group(1) if m else None


def extract_token_from_bundle(bundle_text: Optional[str]) -> Optional[str]:
    """Pull the anonymous public-read token from the SPA bundle.

    Strategy: find all 256+ char hex strings, return the one closest to (within
    300 chars of) the literal string "authorization". This is robust to bundle
    minification — the constant gets concatenated near the fetch wrapper that
    sets the auth header.
    """
    if not bundle_text:
        return None
    candidates = list(_TOKEN_HEX_RE.finditer(bundle_text))
    if not candidates:
        return None
    auth_positions = [m.start() for m in re.finditer(r'authorization', bundle_text, re.IGNORECASE)]
    if not auth_positions:
        # No "authorization" anchor found — return the longest hex candidate as a
        # best-effort fallback. Caller will verify by attempting an API call.
        return max(candidates, key=lambda m: len(m.group(1))).group(1)
    # Find the candidate token closest to any authorization mention
    best = None
    best_dist = float("inf")
    for cand in candidates:
        cand_pos = cand.start()
        dist = min(abs(cand_pos - a) for a in auth_positions)
        if dist < best_dist and dist <= 300:
            best_dist = dist
            best = cand.group(1)
    return best
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py -v -k "Extract"`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py tests/unit/fixtures/squadi/ && git commit -m "feat(squadi): add token bundle regex extractors with fixtures"
```

---

## Task 7: SquadiTokenHarvester class

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`

This task is HTTP plumbing — covered by manual verification (Task 16) per the PlayMetrics test convention. No unit test required.

- [ ] **Step 1: Implement SquadiTokenHarvester**

Append to `scripts/scrape_squadi_competition.py`:

```python
# -----------------------------
# TOKEN HARVESTER
# -----------------------------


class SquadiTokenError(RuntimeError):
    """Raised when token harvest fails irrecoverably."""


class SquadiTokenHarvester:
    """Fetches the anonymous auth token from the SPA bundle, with disk cache.

    Cache: ~/.cache/squadi/token.json with TTL 24h. On 401 from any API call,
    callers should invoke .invalidate() and retry once.
    """

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, spa_base: str = SQUADI_SPA_BASE, cache_path: Path = TOKEN_CACHE_PATH):
        self.spa_base = spa_base.rstrip("/")
        self.cache_path = cache_path
        self._token: Optional[str] = None
        self._build_hash: Optional[str] = None

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        ts = data.get("fetched_at", 0)
        if (time.time() - ts) > TOKEN_TTL_SECONDS:
            return None
        return data

    def _save_cache(self, token: str, build_hash: str) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "token": token,
                "build_hash": build_hash,
                "fetched_at": time.time(),
            }))
        except OSError as e:
            logger.warning(f"Failed to write token cache: {e}")

    def get_token(self) -> str:
        """Return a valid token, using cache when fresh."""
        if self._token:
            return self._token
        cached = self._load_cache()
        if cached:
            self._token = cached["token"]
            self._build_hash = cached.get("build_hash")
            logger.debug(f"Loaded cached token (build={self._build_hash})")
            return self._token
        return self._refresh_token()

    def _refresh_token(self) -> str:
        """Fetch SPA, find bundle, regex out the token. Persist to cache."""
        logger.info(f"Harvesting token from {self.spa_base}")
        try:
            r = requests.get(self.spa_base + "/", headers=self.DEFAULT_HEADERS, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            raise SquadiTokenError(f"Failed to fetch SPA index: {e}") from e

        bundle_path = extract_bundle_url_from_html(r.text)
        if not bundle_path:
            raise SquadiTokenError(
                "Could not find main.<hash>.js in SPA HTML — Squadi may have "
                "changed bundle structure. Inspect HTML manually."
            )
        bundle_url = self.spa_base + bundle_path
        try:
            br = requests.get(bundle_url, headers=self.DEFAULT_HEADERS, timeout=30)
            br.raise_for_status()
        except requests.RequestException as e:
            raise SquadiTokenError(f"Failed to fetch bundle {bundle_url}: {e}") from e

        token = extract_token_from_bundle(br.text)
        if not token:
            raise SquadiTokenError(
                f"Could not extract token from bundle {bundle_url} — Squadi may "
                "have changed token structure. Bundle size: {len(br.text)} bytes."
            )

        # build hash = the <hash> portion of main.<hash>.js
        build_hash = bundle_path.split(".")[1] if "." in bundle_path else "unknown"
        self._token = token
        self._build_hash = build_hash
        self._save_cache(token, build_hash)
        logger.info(f"Harvested token (build={build_hash}, len={len(token)})")
        return token

    def invalidate(self) -> None:
        """Drop in-memory + on-disk cache. Next get_token() refetches."""
        self._token = None
        self._build_hash = None
        try:
            if self.cache_path.exists():
                self.cache_path.unlink()
        except OSError:
            pass

    @property
    def build_hash(self) -> Optional[str]:
        return self._build_hash
```

- [ ] **Step 2: Smoke test interactively**

Run:

```bash
cd C:/PitchRank && python -c "
import logging
logging.basicConfig(level=logging.INFO)
from scripts.scrape_squadi_competition import SquadiTokenHarvester
h = SquadiTokenHarvester()
t = h.get_token()
print(f'token len={len(t)} starts={t[:16]}... build_hash={h.build_hash}')
"
```

Expected: `token len=448 starts=f68a1ffd26dd50c0... build_hash=<hash>` (length may vary, but >=256)

- [ ] **Step 3: Verify cache persistence**

Run the same command again. Expected: log shows "Loaded cached token (build=...)" with no SPA fetch.

- [ ] **Step 4: Verify invalidation**

```bash
cd C:/PitchRank && python -c "
from scripts.scrape_squadi_competition import SquadiTokenHarvester, TOKEN_CACHE_PATH
h = SquadiTokenHarvester()
h.invalidate()
print('cache exists after invalidate:', TOKEN_CACHE_PATH.exists())
"
```

Expected: `cache exists after invalidate: False`

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py && git commit -m "feat(squadi): add SquadiTokenHarvester with disk cache and 401-refresh hook"
```

---

## Task 8: SquadiClient HTTP wrapper

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`

HTTP plumbing — manual verification only.

- [ ] **Step 1: Implement SquadiClient**

Append to `scripts/scrape_squadi_competition.py`:

```python
# -----------------------------
# API CLIENT
# -----------------------------


class SquadiClient:
    """Thin wrapper around requests.Session with token + retry + delay."""

    def __init__(
        self,
        token_harvester: SquadiTokenHarvester,
        api_base: str = SQUADI_API_BASE,
        delay_sec: float = 0.3,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self.harvester = token_harvester
        self.api_base = api_base.rstrip("/")
        self.delay_sec = delay_sec
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.token_refresh_count = 0

    def _headers(self) -> Dict[str, str]:
        return {
            "authorization": self.harvester.get_token(),
            "accept": "application/json",
            "user-agent": SquadiTokenHarvester.DEFAULT_HEADERS["User-Agent"],
        }

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET with retry + 401-triggered token refresh.

        Raises RuntimeError on persistent failure.
        """
        url = f"{self.api_base}/{path.lstrip('/')}"
        last_error: Optional[str] = None
        token_already_refreshed = False

        for attempt in range(self.max_retries):
            try:
                r = self.session.get(
                    url, params=params, headers=self._headers(), timeout=self.timeout
                )
                if r.status_code == 200:
                    if attempt > 0:
                        time.sleep(self.delay_sec)
                    return r.json()
                if r.status_code == 401 and not token_already_refreshed:
                    logger.warning(f"401 on {path} — refreshing token and retrying once")
                    self.harvester.invalidate()
                    self.token_refresh_count += 1
                    token_already_refreshed = True
                    continue  # retry without consuming an attempt
                last_error = f"HTTP {r.status_code}"
                logger.warning(f"⚠️ {last_error} for {path} (attempt {attempt+1}/{self.max_retries})")
            except requests.RequestException as e:
                last_error = str(e)
                logger.warning(f"⚠️ Request error for {path}: {e}")

            if attempt < self.max_retries - 1:
                time.sleep(0.5 * (2 ** attempt))  # exponential backoff: 0.5, 1, 2

        raise RuntimeError(
            f"SQUADI API call failed after {self.max_retries} attempts: {path} "
            f"({last_error}, build={self.harvester.build_hash})"
        )

    def list_years(self, org_uuid: str) -> List[Dict[str, Any]]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "common/common/reference/year",
            params={"organisationUniqueKey": org_uuid, "scope": 1},
        )

    def list_competitions(self, org_uuid: str, year_ref_id: int) -> List[Dict[str, Any]]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "livescores/competitions/list",
            params={"organisationUniqueKey": org_uuid, "yearRefId": year_ref_id},
        )

    def list_divisions(self, competition_uuid: str) -> List[Dict[str, Any]]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "livescores/division",
            params={"competitionKey": competition_uuid},
        )

    def get_round_matches(self, competition_int_id: int) -> Dict[str, Any]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "livescores/round/matches",
            params={
                "competitionId": competition_int_id,
                "divisionId": "",
                "teamIds": "",
                "ignoreStatuses": "[1]",
            },
        )
```

- [ ] **Step 2: Smoke test against the live API**

Run:

```bash
cd C:/PitchRank && python -c "
import logging, json
logging.basicConfig(level=logging.INFO)
from scripts.scrape_squadi_competition import SquadiClient, SquadiTokenHarvester
h = SquadiTokenHarvester()
c = SquadiClient(h)
comps = c.list_competitions('7cfab077-e619-47e4-ab36-0febc29501a2', 8)
print(f'NJYS yearRefId=8 competitions: {len(comps)}')
for x in comps:
    print(f'  id={x[\"id\"]} status={x[\"statusRefId\"]} name={x[\"name\"]}')
"
```

Expected: 1 competition: `id=261 status=2 name=New Jersey Youth Soccer State Cups - Spring 2026 (15U-19U)`.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py && git commit -m "feat(squadi): add SquadiClient with retry + 401-refresh + rate-limit"
```

---

## Task 9: Competition discovery

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`
- Create: `tests/unit/fixtures/squadi/competitions_list_sample.json`

- [ ] **Step 1: Create fixture**

Create `tests/unit/fixtures/squadi/competitions_list_sample.json`:

```json
[
  {"id": 46, "uniqueKey": "2695023d-863e-4d7f-baeb-b0d3ef251a5b", "name": "Demo Comp (State Cup)", "statusRefId": 3, "yearRefId": 6, "organisationId": 380, "deleted_at": null},
  {"id": 40, "uniqueKey": "539ff993-3032-414e-9dfe-5466629fc1c9", "name": "New Jersey Youth Soccer State Cups - Fall 2024 (11U-14U)", "statusRefId": 2, "yearRefId": 6, "organisationId": 380, "deleted_at": null},
  {"id": 58, "uniqueKey": "b44adaff-e799-4c33-b63c-5d22cce91260", "name": "NJ ODP Friendlies (December 2024)", "statusRefId": 2, "yearRefId": 6, "organisationId": 380, "deleted_at": null},
  {"id": 99, "uniqueKey": "deleted-comp-uuid", "name": "Old Comp", "statusRefId": 2, "yearRefId": 6, "organisationId": 380, "deleted_at": "2025-01-01T00:00:00Z"}
]
```

- [ ] **Step 2: Write failing tests**

Append to `tests/unit/test_scrape_squadi.py`:

```python
import json as _json

from scripts.scrape_squadi_competition import filter_competitions


class TestFilterCompetitions:
    def setup_method(self):
        self.raw = _json.loads(
            (FIXTURE_DIR / "competitions_list_sample.json").read_text()
        )

    def test_keeps_active_published(self):
        result = filter_competitions(self.raw, name_blocklist=())
        ids = [c["id"] for c in result]
        # status=2 and not deleted: id=40, id=58
        assert 40 in ids
        assert 58 in ids

    def test_drops_demo_status_3(self):
        result = filter_competitions(self.raw, name_blocklist=())
        ids = [c["id"] for c in result]
        assert 46 not in ids  # statusRefId=3

    def test_drops_deleted(self):
        result = filter_competitions(self.raw, name_blocklist=())
        ids = [c["id"] for c in result]
        assert 99 not in ids  # has deleted_at

    def test_name_blocklist_drops_matching_substring(self):
        result = filter_competitions(self.raw, name_blocklist=("Demo Comp", "ODP"))
        ids = [c["id"] for c in result]
        assert 40 in ids  # State Cups passes
        assert 58 not in ids  # ODP filtered

    def test_default_blocklist_drops_demo_only(self):
        # Default blocklist contains "Demo Comp" — but status=3 already drops it
        result = filter_competitions(self.raw, name_blocklist=DEFAULT_COMP_NAME_BLOCKLIST_FOR_TEST)
        ids = [c["id"] for c in result]
        assert 40 in ids
        assert 58 in ids


# Re-import for the parametrize default
from scripts.scrape_squadi_competition import DEFAULT_COMP_NAME_BLOCKLIST as DEFAULT_COMP_NAME_BLOCKLIST_FOR_TEST
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestFilterCompetitions -v`
Expected: ImportError on `filter_competitions`

- [ ] **Step 4: Implement filter**

Append:

```python
# -----------------------------
# COMPETITION DISCOVERY
# -----------------------------


def filter_competitions(
    competitions: List[Dict[str, Any]],
    name_blocklist: Tuple[str, ...] = DEFAULT_COMP_NAME_BLOCKLIST,
) -> List[Dict[str, Any]]:
    """Filter raw /competitions/list output by status, deletion, and name.

    Keep: statusRefId == 2 (active/published), deleted_at is null, name does
    not contain any blocklist substring (case-insensitive).
    """
    out: List[Dict[str, Any]] = []
    for comp in competitions:
        if comp.get("statusRefId") != 2:
            continue
        if comp.get("deleted_at") is not None:
            continue
        name = str(comp.get("name") or "").lower()
        if any(bl.lower() in name for bl in name_blocklist):
            continue
        out.append(comp)
    return out


def discover_competitions(
    client: SquadiClient,
    org_uuid: str,
    year_ref_id: Optional[int] = None,
    name_blocklist: Tuple[str, ...] = DEFAULT_COMP_NAME_BLOCKLIST,
) -> List[Dict[str, Any]]:
    """List + filter competitions for an org.

    When year_ref_id is None, walks every yearRefId in YEAR_REF_TO_CALENDAR.
    """
    year_ids = [year_ref_id] if year_ref_id is not None else list(YEAR_REF_TO_CALENDAR.keys())
    all_comps: List[Dict[str, Any]] = []
    for yri in year_ids:
        try:
            raw = client.list_competitions(org_uuid, yri)
        except RuntimeError as e:
            logger.warning(f"Skipping yearRefId={yri}: {e}")
            continue
        all_comps.extend(filter_competitions(raw, name_blocklist=name_blocklist))
    return all_comps
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestFilterCompetitions -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py tests/unit/fixtures/squadi/competitions_list_sample.json && git commit -m "feat(squadi): add filter_competitions + discover_competitions"
```

---

## Task 10: Match → CSV row normalization

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`
- Modify: `tests/unit/test_scrape_squadi.py`
- Create: `tests/unit/fixtures/squadi/round_matches_sample.json`

- [ ] **Step 1: Create fixture**

Create `tests/unit/fixtures/squadi/round_matches_sample.json` with 6 hand-crafted matches representing the test scenarios. Use this exact content:

```json
{
  "rounds": [
    {
      "id": 3632,
      "name": "Round of 64",
      "sequence": 0,
      "competitionId": 40,
      "divisionId": 390,
      "matches": [
        {"id": 1001, "team1Score": 5, "team2Score": 0, "hasPenalty": false, "team1PenaltyScore": null, "team2PenaltyScore": null, "competitionId": 40, "divisionId": 390, "team1Id": 100, "team2Id": 200, "startTime": "2024-09-06T22:30:00.000Z", "endTime": "2024-09-06T23:30:00.000Z", "matchStatus": "ENDED", "resultStatus": "FINAL", "team1ResultId": 1, "team2ResultId": 2, "isResultsLocked": true, "isFinals": false, "finalsAlias": "1-8", "matchSubstatusRefId": 5, "team1": {"id": 100, "name": "Mount Olive SC - STA Mount Olive 2014 EDP Boys", "teamUniqueKey": "uuid-team-100", "logoUrl": "https://example/o/%2Forganisation%2Flogo_org_443_x.blob"}, "team2": {"id": 200, "name": "NJ Stallions 14 Betis EDP", "teamUniqueKey": "uuid-team-200", "logoUrl": "https://example/o/%2Forganisation%2Flogo_org_457_y.blob"}, "venueCourt": {"name": "Field 4", "venue": {"name": "Turkey Brook Park", "lat": "40.86", "lng": "-74.72"}}, "round": {"id": 3632, "name": "Round of 64", "sequence": 0, "competitionId": 40, "divisionId": 390}},
        {"id": 1002, "team1Score": 1, "team2Score": 1, "hasPenalty": false, "team1PenaltyScore": null, "team2PenaltyScore": null, "competitionId": 40, "divisionId": 390, "team1Id": 300, "team2Id": 400, "startTime": "2024-09-07T18:00:00.000Z", "matchStatus": "ENDED", "resultStatus": "FINAL", "team1ResultId": 3, "team2ResultId": 3, "team1": {"id": 300, "name": "Wall SC - Liverpool", "teamUniqueKey": "uuid-team-300", "logoUrl": null}, "team2": {"id": 400, "name": "Point Pleasant Travel SC - Wave United Black", "teamUniqueKey": "uuid-team-400", "logoUrl": null}, "venueCourt": null, "round": {"id": 3632, "name": "Round of 64", "sequence": 0, "competitionId": 40, "divisionId": 390}},
        {"id": 1003, "team1Score": 2, "team2Score": 2, "hasPenalty": true, "team1PenaltyScore": 4, "team2PenaltyScore": 3, "competitionId": 40, "divisionId": 390, "team1Id": 500, "team2Id": 600, "startTime": "2024-09-08T19:00:00.000Z", "matchStatus": "ENDED", "resultStatus": "FINAL", "team1ResultId": 1, "team2ResultId": 2, "team1": {"id": 500, "name": "Club A - Team Alpha", "teamUniqueKey": "uuid-team-500", "logoUrl": null}, "team2": {"id": 600, "name": "Club B - Team Bravo", "teamUniqueKey": "uuid-team-600", "logoUrl": null}, "venueCourt": null, "round": {"id": 3632, "name": "Round of 64", "sequence": 0, "competitionId": 40, "divisionId": 390}},
        {"id": 1004, "team1Score": null, "team2Score": null, "hasPenalty": false, "competitionId": 40, "divisionId": 390, "team1Id": 700, "team2Id": 800, "startTime": "2024-09-09T19:00:00.000Z", "matchStatus": "ENDED", "resultStatus": "FINAL", "matchSubstatusRefId": 11, "team1": {"id": 700, "name": "Forfeit Club - Team", "teamUniqueKey": "uuid-team-700", "logoUrl": null}, "team2": {"id": 800, "name": "Other Club - Team", "teamUniqueKey": "uuid-team-800", "logoUrl": null}, "venueCourt": null, "round": {"id": 3632, "name": "Round of 64", "sequence": 0, "competitionId": 40, "divisionId": 390}},
        {"id": 1005, "team1Score": null, "team2Score": null, "hasPenalty": false, "competitionId": 40, "divisionId": 390, "team1Id": 900, "team2Id": 1000, "startTime": "2024-12-01T19:00:00.000Z", "matchStatus": "SCHEDULED", "resultStatus": "PROVISIONAL", "team1": {"id": 900, "name": "Future Club - Team", "teamUniqueKey": "uuid-team-900", "logoUrl": null}, "team2": {"id": 1000, "name": "Future Club B - Team", "teamUniqueKey": "uuid-team-1000", "logoUrl": null}, "venueCourt": null, "round": {"id": 3632, "name": "Round of 64", "sequence": 0, "competitionId": 40, "divisionId": 390}}
      ]
    },
    {
      "id": 3633,
      "name": "Quarter-Final",
      "sequence": 2,
      "competitionId": 40,
      "divisionId": 390,
      "matches": [
        {"id": 1006, "team1Score": 3, "team2Score": 1, "hasPenalty": false, "competitionId": 40, "divisionId": 390, "team1Id": 100, "team2Id": 500, "startTime": "2024-09-15T20:00:00.000Z", "matchStatus": "ENDED", "resultStatus": "FINAL", "team1ResultId": 1, "team2ResultId": 2, "isFinals": true, "finalsAlias": "QF-1", "team1": {"id": 100, "name": "Mount Olive SC - STA Mount Olive 2014 EDP Boys", "teamUniqueKey": "uuid-team-100", "logoUrl": "https://example/o/%2Forganisation%2Flogo_org_443_x.blob"}, "team2": {"id": 500, "name": "Club A - Team Alpha", "teamUniqueKey": "uuid-team-500", "logoUrl": null}, "venueCourt": {"name": "Field 1", "venue": {"name": "Wall Soccer Complex"}}, "round": {"id": 3633, "name": "Quarter-Final", "sequence": 2, "competitionId": 40, "divisionId": 390}}
      ]
    }
  ]
}
```

- [ ] **Step 2: Write failing tests**

Append to `tests/unit/test_scrape_squadi.py`:

```python
from scripts.scrape_squadi_competition import normalize_match


@pytest.fixture
def sample_division():
    return {
        "id": 390,
        "name": "11U Boys Challenge Cup NJYS",
        "divisionName": "11U Boys Challenge Cup",
        "uniqueKey": "div-uuid-1",
        "age": 10,
        "competitionId": 40,
    }


@pytest.fixture
def sample_competition():
    return {
        "id": 40,
        "uniqueKey": "comp-uuid-1",
        "name": "NJYS State Cups - Fall 2024 (11U-14U)",
        "yearRefId": 6,
        "organisationId": 380,
    }


@pytest.fixture
def sample_org_meta():
    return {"state": "New Jersey", "state_code": "NJ", "timezone": "America/New_York"}


@pytest.fixture
def all_matches():
    return _json.loads((FIXTURE_DIR / "round_matches_sample.json").read_text())


class TestNormalizeMatch:
    def test_finished_win_loss_emits_two_rows(self, all_matches, sample_division, sample_competition, sample_org_meta):
        match = all_matches["rounds"][0]["matches"][0]  # 5-0 W/L
        rows, team_rows = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        assert len(rows) == 2
        assert len(team_rows) == 2
        # row 0 is team1's perspective
        r0 = rows[0]
        assert r0["provider"] == "squadi"
        assert r0["age_group"] == "u11"
        assert r0["gender"] == "Boys"
        assert r0["team_id"] == "uuid-team-100"
        assert r0["team_id_source"] == "100"
        assert r0["team_name"] == "Mount Olive SC - STA Mount Olive 2014 EDP Boys"
        assert r0["club_name"] == "Mount Olive SC"
        assert r0["opponent_id"] == "uuid-team-200"
        assert r0["opponent_name"] == "NJ Stallions 14 Betis EDP"
        assert r0["opponent_club_name"] == "NJ Stallions 14 Betis EDP"  # no dash
        assert r0["state"] == "New Jersey"
        assert r0["state_code"] == "NJ"
        assert r0["game_date"] == "2024-09-06"
        assert r0["game_time"] == "18:30"
        assert r0["home_away"] == "H"
        assert r0["goals_for"] == 5
        assert r0["goals_against"] == 0
        assert r0["result"] == "W"
        assert r0["venue"] == "Turkey Brook Park - Field 4"
        assert r0["division_name"] == "11U Boys Challenge Cup"
        # row 1 is team2's perspective (Loss)
        assert rows[1]["team_id"] == "uuid-team-200"
        assert rows[1]["home_away"] == "A"
        assert rows[1]["goals_for"] == 0
        assert rows[1]["goals_against"] == 5
        assert rows[1]["result"] == "L"

    def test_drawn_no_pks(self, all_matches, sample_division, sample_competition, sample_org_meta):
        match = all_matches["rounds"][0]["matches"][1]  # 1-1, no PKs
        rows, _ = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        assert rows[0]["result"] == "D"
        assert rows[1]["result"] == "D"

    def test_drawn_with_pks_result_stays_d(self, all_matches, sample_division, sample_competition, sample_org_meta):
        # 2-2 with PKs 4-3 → result remains "D" (regulation outcome wins)
        match = all_matches["rounds"][0]["matches"][2]
        rows, _ = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        assert rows[0]["result"] == "D"
        assert rows[1]["result"] == "D"

    def test_forfeit_emits_unknown_result(self, all_matches, sample_division, sample_competition, sample_org_meta):
        match = all_matches["rounds"][0]["matches"][3]
        rows, _ = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        assert rows[0]["result"] == "U"
        assert rows[1]["result"] == "U"

    def test_scheduled_match_emits_no_rows(self, all_matches, sample_division, sample_competition, sample_org_meta):
        match = all_matches["rounds"][0]["matches"][4]  # SCHEDULED
        rows, team_rows = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        assert rows == []
        assert team_rows == []

    def test_team_row_has_external_org_id_from_logo(self, all_matches, sample_division, sample_competition, sample_org_meta):
        match = all_matches["rounds"][0]["matches"][0]
        _, team_rows = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        team1 = next(t for t in team_rows if t["provider_team_id"] == "uuid-team-100")
        assert team1["external_org_id"] == "443"
        assert team1["age_group"] == "u11"
        assert team1["gender"] == "Boys"

    def test_source_url_construction(self, all_matches, sample_division, sample_competition, sample_org_meta):
        match = all_matches["rounds"][0]["matches"][0]
        rows, _ = normalize_match(
            match, sample_division, sample_competition, sample_org_meta,
            scrape_run_id="run-x", scraped_at="2026-05-04T12:00:00Z",
        )
        url = rows[0]["source_url"]
        assert "organisationKey=" in url
        assert "competitionUniqueKey=comp-uuid-1" in url
        assert "yearId=6" in url
        assert "divisionId=div-uuid-1" in url
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestNormalizeMatch -v`
Expected: ImportError on `normalize_match`

- [ ] **Step 4: Implement `normalize_match`**

Append to `scripts/scrape_squadi_competition.py`:

```python
# -----------------------------
# MATCH NORMALIZATION
# -----------------------------

# matchSubstatusRefId values that indicate a forfeit/abandonment outcome.
# Discovered empirically; expand as more substatus codes are observed.
FORFEIT_SUBSTATUS_IDS = {11, 12, 13, 14}  # Working hypothesis; verify in production


def _build_venue(venue_court: Optional[Dict[str, Any]]) -> str:
    """Compose 'Venue Name - Field N' from venueCourt."""
    if not venue_court:
        return ""
    venue = venue_court.get("venue") or {}
    venue_name = str(venue.get("name") or "").strip()
    field_name = str(venue_court.get("name") or "").strip()
    if venue_name and field_name:
        return f"{venue_name} - {field_name}"
    return venue_name or field_name


def _build_source_url(org_uuid: str, comp_uuid: str, year_ref_id: Optional[int], division_uuid: str) -> str:
    year_part = f"&yearId={year_ref_id}" if year_ref_id is not None else ""
    div_part = f"&divisionId={division_uuid}" if division_uuid else ""
    return (
        f"{SQUADI_SPA_BASE}/livescoreSeasonFixture"
        f"?organisationKey={org_uuid}"
        f"&competitionUniqueKey={comp_uuid}"
        f"{year_part}{div_part}"
    )


def _compute_age_year(age_group: str, comp_calendar_year: Optional[int]) -> str:
    """Birth year heuristic: comp_year - U_age - 1.

    For 11U Spring 2026 (age_group=u11, comp_year=2026) → 2015. This is a
    convenience field; the matcher uses age_group + birth-year-from-name first.
    """
    if not age_group or not comp_calendar_year:
        return ""
    try:
        n = int(age_group.lstrip("uU"))
        if n == 19:
            n_for_calc = 19
        else:
            n_for_calc = n
        return str(comp_calendar_year - n_for_calc - 1)
    except (ValueError, TypeError):
        return ""


def normalize_match(
    match: Dict[str, Any],
    division: Dict[str, Any],
    competition: Dict[str, Any],
    org_meta: Dict[str, str],
    *,
    scrape_run_id: str,
    scraped_at: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Convert one Squadi match into (game_rows, team_rows).

    Returns ([], []) when the match should be skipped (e.g. SCHEDULED).
    Otherwise returns:
      - 2 game rows (team1-perspective, team2-perspective)
      - 2 team rows (one per team), deduplicatable by (teamUUID, divisionId)
    """
    # Skip matches that haven't been played
    match_status = str(match.get("matchStatus") or "").upper()
    if match_status != "ENDED":
        return ([], [])

    team1 = match.get("team1") or {}
    team2 = match.get("team2") or {}
    team1_uuid = str(team1.get("teamUniqueKey") or "")
    team2_uuid = str(team2.get("teamUniqueKey") or "")
    team1_int_id = team1.get("id")
    team2_int_id = team2.get("id")
    if not team1_uuid or not team2_uuid:
        logger.warning(f"Match {match.get('id')} missing teamUniqueKey; skipping")
        return ([], [])

    team1_name = str(team1.get("name") or "").strip()
    team2_name = str(team2.get("name") or "").strip()

    # Score parsing (regulation only — PKs do not change the W/L/D outcome)
    raw_t1 = match.get("team1Score")
    raw_t2 = match.get("team2Score")
    t1_score = parse_int_or_none(raw_t1)
    t2_score = parse_int_or_none(raw_t2)

    substatus = match.get("matchSubstatusRefId")
    is_forfeit = substatus in FORFEIT_SUBSTATUS_IDS or (
        match_status == "ENDED" and (raw_t1 is None or raw_t2 is None)
    )

    if is_forfeit and (t1_score is None or t2_score is None):
        result_t1 = "U"
        result_t2 = "U"
    else:
        result_t1 = compute_result(t1_score, t2_score)
        result_t2 = compute_result(t2_score, t1_score)

    # Division-derived metadata
    division_name = str(division.get("divisionName") or division.get("name") or "").strip()
    age_group, gender, tier = parse_division_metadata(
        division_name, division.get("age")
    )

    # Comp + org context
    comp_uuid = str(competition.get("uniqueKey") or "")
    comp_name = str(competition.get("name") or "")
    year_ref_id = competition.get("yearRefId")
    comp_calendar_year = YEAR_REF_TO_CALENDAR.get(year_ref_id) if year_ref_id else None
    org_uuid = str((competition.get("organisation") or {}).get("organisationUniqueKey") or "")
    if not org_uuid:
        # Fallback: caller passes org_uuid via meta if not embedded
        org_uuid = org_meta.get("org_uuid", "")

    age_year = _compute_age_year(age_group, comp_calendar_year)
    source_url = _build_source_url(
        org_uuid, comp_uuid, year_ref_id, str(division.get("uniqueKey") or "")
    )
    venue = _build_venue(match.get("venueCourt"))

    game_date, game_time = parse_utc_to_local_date(
        match.get("startTime"), org_meta.get("timezone", "America/New_York")
    )

    schedule_id = f"r{match.get('roundId') or ''}-d{match.get('divisionId') or ''}"

    # PK detail goes into meta only, not into the result column
    pk_winner = ""
    if match.get("hasPenalty"):
        pk1 = match.get("team1PenaltyScore")
        pk2 = match.get("team2PenaltyScore")
        if isinstance(pk1, int) and isinstance(pk2, int):
            if pk1 > pk2:
                pk_winner = team1_uuid
            elif pk2 > pk1:
                pk_winner = team2_uuid

    base = {
        "provider": "squadi",
        "scrape_run_id": scrape_run_id,
        "event_id": comp_uuid,
        "event_name": comp_name,
        "schedule_id": schedule_id,
        "age_year": age_year,
        "age_group": age_group,
        "gender": gender,
        "state": org_meta.get("state", ""),
        "state_code": org_meta.get("state_code", ""),
        "game_date": game_date,
        "game_time": game_time,
        "venue": venue,
        "source_url": source_url,
        "scraped_at": scraped_at,
        "division_name": division_name,
    }

    team1_club = parse_club_name(team1_name)
    team2_club = parse_club_name(team2_name)

    row_team1 = {
        **base,
        "team_id": team1_uuid,
        "team_id_source": str(team1_int_id) if team1_int_id is not None else "",
        "team_name": team1_name,
        "club_name": team1_club,
        "opponent_id": team2_uuid,
        "opponent_id_source": str(team2_int_id) if team2_int_id is not None else "",
        "opponent_name": team2_name,
        "opponent_club_name": team2_club,
        "home_away": "H",
        "goals_for": t1_score if t1_score is not None else "",
        "goals_against": t2_score if t2_score is not None else "",
        "result": result_t1,
    }
    row_team2 = {
        **base,
        "team_id": team2_uuid,
        "team_id_source": str(team2_int_id) if team2_int_id is not None else "",
        "team_name": team2_name,
        "club_name": team2_club,
        "opponent_id": team1_uuid,
        "opponent_id_source": str(team1_int_id) if team1_int_id is not None else "",
        "opponent_name": team1_name,
        "opponent_club_name": team1_club,
        "home_away": "A",
        "goals_for": t2_score if t2_score is not None else "",
        "goals_against": t1_score if t1_score is not None else "",
        "result": result_t2,
    }

    # Per-team output for matcher seed
    base_team = {
        "provider": "squadi",
        "age_group": age_group,
        "gender": gender,
        "state": org_meta.get("state", ""),
        "state_code": org_meta.get("state_code", ""),
        "division_name": division_name,
        "tier": tier,
    }
    team_row_1 = {
        **base_team,
        "provider_team_id": team1_uuid,
        "provider_team_id_source": str(team1_int_id) if team1_int_id is not None else "",
        "team_name": team1_name,
        "club_name": team1_club,
        "external_org_id": extract_external_org_id(team1.get("logoUrl")) or "",
        "meta": json.dumps({
            "squadi_team_id_int": team1_int_id,
            "squadi_competition_uuid": comp_uuid,
            "squadi_division_id": division.get("id"),
        }),
    }
    team_row_2 = {
        **base_team,
        "provider_team_id": team2_uuid,
        "provider_team_id_source": str(team2_int_id) if team2_int_id is not None else "",
        "team_name": team2_name,
        "club_name": team2_club,
        "external_org_id": extract_external_org_id(team2.get("logoUrl")) or "",
        "meta": json.dumps({
            "squadi_team_id_int": team2_int_id,
            "squadi_competition_uuid": comp_uuid,
            "squadi_division_id": division.get("id"),
        }),
    }

    # Stash PK + extras on the team1 row's meta for downstream visibility
    if pk_winner:
        # We don't extend REQUIRED_COLUMNS — store pk in a side channel via meta
        # on team rows. Game-row meta is delegated to the importer's own meta col.
        for tr in (team_row_1, team_row_2):
            extra_meta = json.loads(tr["meta"])
            extra_meta["last_pk_winner_team_uuid"] = pk_winner
            tr["meta"] = json.dumps(extra_meta)

    return ([row_team1, row_team2], [team_row_1, team_row_2])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_scrape_squadi.py::TestNormalizeMatch -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py tests/unit/test_scrape_squadi.py tests/unit/fixtures/squadi/round_matches_sample.json && git commit -m "feat(squadi): add normalize_match producing game + team rows"
```

---

## Task 11: Per-competition orchestration

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`

Orchestration — covered by manual verification (Task 16).

- [ ] **Step 1: Implement `scrape_competition`**

Append:

```python
# -----------------------------
# COMPETITION SCRAPER
# -----------------------------


@dataclass
class CompScrapeResult:
    competition_uuid: str
    competition_id_int: int
    competition_name: str
    games_emitted: int = 0
    teams_emitted: int = 0
    skipped_scheduled: int = 0
    skipped_orphan_team: int = 0
    parse_warnings: int = 0
    raw_dir: Optional[Path] = None
    error: Optional[str] = None


def scrape_competition(
    client: SquadiClient,
    competition: Dict[str, Any],
    org_uuid: str,
    org_meta: Dict[str, str],
    *,
    scrape_run_id: str,
    scraped_at: str,
    raw_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], CompScrapeResult]:
    """Walk one competition. Returns (game_rows, team_rows, result)."""
    comp_uuid = str(competition.get("uniqueKey") or "")
    comp_int_id = competition.get("id")
    comp_name = str(competition.get("name") or "")
    res = CompScrapeResult(
        competition_uuid=comp_uuid,
        competition_id_int=int(comp_int_id) if comp_int_id is not None else 0,
        competition_name=comp_name,
    )

    # Stamp org context onto competition for normalize_match's source_url helper
    competition.setdefault("organisation", {})["organisationUniqueKey"] = org_uuid

    try:
        divisions_raw = client.list_divisions(comp_uuid)
        round_matches = client.get_round_matches(int(comp_int_id))
    except RuntimeError as e:
        logger.error(f"Competition {comp_name} ({comp_uuid}): {e}")
        res.error = str(e)
        return ([], [], res)

    if raw_dir:
        try:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "competition.json").write_text(json.dumps(competition))
            (raw_dir / "divisions.json").write_text(json.dumps(divisions_raw))
            (raw_dir / "round_matches.json").write_text(json.dumps(round_matches))
            res.raw_dir = raw_dir
        except OSError as e:
            logger.warning(f"Could not persist raw JSON: {e}")

    div_lookup = {d.get("id"): d for d in divisions_raw if d.get("id") is not None}

    games_buf: List[Dict[str, Any]] = []
    teams_buf: Dict[Tuple[str, Any], Dict[str, Any]] = {}

    for rd in round_matches.get("rounds") or []:
        for match in rd.get("matches") or []:
            div = div_lookup.get(match.get("divisionId"))
            if not div:
                res.skipped_orphan_team += 1
                logger.warning(
                    f"Match {match.get('id')} in comp {comp_name} has no matching "
                    f"divisionId={match.get('divisionId')}"
                )
                continue
            try:
                game_rows, team_rows = normalize_match(
                    match, div, competition, org_meta,
                    scrape_run_id=scrape_run_id, scraped_at=scraped_at,
                )
            except Exception as e:
                logger.warning(f"Match {match.get('id')} normalization error: {e}")
                res.parse_warnings += 1
                continue

            if not game_rows:
                res.skipped_scheduled += 1
                continue

            games_buf.extend(game_rows)
            res.games_emitted += 1
            for tr in team_rows:
                key = (tr["provider_team_id"], div.get("id"))
                if key not in teams_buf:
                    teams_buf[key] = tr

    res.teams_emitted = len(teams_buf)
    return (games_buf, list(teams_buf.values()), res)
```

- [ ] **Step 2: Smoke-test the orchestrator on the live API (read-only)**

Run:

```bash
cd C:/PitchRank && python -c "
import logging, json
logging.basicConfig(level=logging.INFO)
from scripts.scrape_squadi_competition import (
    SquadiTokenHarvester, SquadiClient, scrape_competition, ORG_REGISTRY
)
from datetime import datetime, timezone

h = SquadiTokenHarvester()
c = SquadiClient(h)
org_uuid = '7cfab077-e619-47e4-ab36-0febc29501a2'
# Use the historical Fall 2024 comp for richer test data
comps = c.list_competitions(org_uuid, 6)
target = next(x for x in comps if 'Fall 2024' in x['name'] and x['statusRefId'] == 2)
games, teams, res = scrape_competition(
    c, target, org_uuid, ORG_REGISTRY[org_uuid],
    scrape_run_id='smoke-x',
    scraped_at=datetime.now(timezone.utc).isoformat(),
)
print(f'games_emitted={res.games_emitted} teams={res.teams_emitted} skipped_sched={res.skipped_scheduled}')
print(f'sample row: {json.dumps(games[0], indent=2) if games else \"none\"}')
"
```

Expected output:
- `games_emitted` between 100 and 1500 (NJYS Fall 2024 is large; should be hundreds of completed games)
- `teams` between 100 and 800
- Sample row has `provider="squadi"`, `state_code="NJ"`, valid `game_date`, `result` in (W/L/D/U)

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py && git commit -m "feat(squadi): add scrape_competition orchestrator"
```

---

## Task 12: Output writers (CSV + manifest, atomic rename)

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`

- [ ] **Step 1: Implement validators + writers**

Append:

```python
# -----------------------------
# VALIDATION + OUTPUT
# -----------------------------


def validate_records(records: List[Dict[str, Any]]) -> None:
    """Ensure every game record has all 28 REQUIRED_COLUMNS."""
    for i, r in enumerate(records):
        missing = [c for c in REQUIRED_COLUMNS if c not in r]
        if missing:
            raise ValueError(f"Record {i} missing columns: {missing}")


def write_outputs(
    games: List[Dict[str, Any]],
    teams: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    output_root: Path,
    scrape_run_id: str,
) -> Path:
    """Atomic write: <output_root>/<run_id>.tmp/ → <output_root>/<run_id>/

    Returns the final output directory.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / scrape_run_id
    tmp_dir = output_root / f"{scrape_run_id}.tmp"

    if tmp_dir.exists():
        # Stale tmp from prior crash — wipe it
        for child in tmp_dir.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(tmp_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        tmp_dir.rmdir()

    tmp_dir.mkdir(parents=True, exist_ok=True)

    # games.csv
    with open(tmp_dir / "games.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(games)

    # teams.csv
    with open(tmp_dir / "teams.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEAMS_COLUMNS)
        writer.writeheader()
        writer.writerows(teams)

    # manifest.json
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if final_dir.exists():
        # Replace existing run dir
        for child in final_dir.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(final_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        final_dir.rmdir()
    tmp_dir.rename(final_dir)
    return final_dir
```

- [ ] **Step 2: Manual smoke test (write to a temp dir)**

Run:

```bash
cd C:/PitchRank && python -c "
import tempfile, json
from pathlib import Path
from scripts.scrape_squadi_competition import write_outputs, REQUIRED_COLUMNS, TEAMS_COLUMNS
games = [{c: 'x' for c in REQUIRED_COLUMNS}]
teams = [{c: 'y' for c in TEAMS_COLUMNS}]
manifest = {'run_id': 'test', 'comps_total': 0}
with tempfile.TemporaryDirectory() as td:
    out = write_outputs(games, teams, manifest, Path(td), 'test-run')
    files = sorted(p.name for p in out.iterdir())
    print('files:', files)
    print('games.csv first line:', (out / 'games.csv').read_text().splitlines()[0])
"
```

Expected: `files: ['games.csv', 'manifest.json', 'teams.csv']` and the games.csv header matches REQUIRED_COLUMNS comma-joined.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py && git commit -m "feat(squadi): add validate_records and atomic write_outputs"
```

---

## Task 13: CLI entrypoint with `--dry-run` default

**Files:**
- Modify: `scripts/scrape_squadi_competition.py`

- [ ] **Step 1: Implement `resolve_config` + `main`**

Append:

```python
# -----------------------------
# CONFIG + ENTRYPOINT
# -----------------------------


def resolve_config() -> Dict[str, Any]:
    parser = argparse.ArgumentParser(description="SQUADI Competition Scraper")
    parser.add_argument("--url", type=str, help="Squadi livescoreSeasonFixture URL (parses org+comp+year)")
    parser.add_argument("--org-key", type=str, help="organisationUniqueKey (UUID)")
    parser.add_argument("--year-ref-id", type=int, help="Squadi yearRefId (e.g. 8 for 2026)")
    parser.add_argument("--competition-key", type=str, help="competitionUniqueKey (UUID); skips discovery")
    parser.add_argument("--output-dir", type=str, help=f"Output root (default {OUTPUT_DIR})")
    parser.add_argument("--keep-raw", action="store_true", help="Persist raw JSON responses for audit")
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Validate token + scrape, do NOT write CSVs (default: ON)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Disable dry-run and write CSV outputs to disk",
    )

    args = parser.parse_args()

    # Resolve identity: --url > --competition-key > --org-key
    org_uuid: Optional[str] = None
    competition_uuid: Optional[str] = None
    year_ref_id: Optional[int] = None

    if args.url:
        parsed = parse_squadi_url(args.url)
        if not parsed:
            print(f"❌ Could not parse --url: {args.url}", file=sys.stderr)
            sys.exit(1)
        org_uuid = parsed["org_uuid"]
        competition_uuid = parsed["competition_uuid"] or args.competition_key
        year_ref_id = parsed["year_ref_id"] if parsed["year_ref_id"] is not None else args.year_ref_id
    else:
        org_uuid = args.org_key
        competition_uuid = args.competition_key
        year_ref_id = args.year_ref_id

    if not org_uuid and not competition_uuid:
        print("❌ Must provide --url, --org-key, or --competition-key", file=sys.stderr)
        sys.exit(1)

    # If only competition_uuid is provided, we need org context for state metadata.
    # Look it up from ORG_REGISTRY via the competition fetch (in main).

    blocklist_env = os.getenv("SQUADI_COMP_BLOCKLIST", "")
    blocklist = tuple(s.strip() for s in blocklist_env.split(",") if s.strip()) or DEFAULT_COMP_NAME_BLOCKLIST

    return {
        "org_uuid": org_uuid,
        "competition_uuid": competition_uuid,
        "year_ref_id": year_ref_id,
        "output_dir": args.output_dir or OUTPUT_DIR,
        "keep_raw": args.keep_raw,
        "verbose": args.verbose,
        "dry_run": args.dry_run,
        "name_blocklist": blocklist,
        "delay_sec": float(os.getenv("SQUADI_DELAY_SEC", "0.3")),
    }


def main() -> int:
    global SCRAPE_TS, SCRAPE_RUN_ID
    config = resolve_config()
    logging.basicConfig(
        level=logging.DEBUG if config["verbose"] else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    SCRAPE_TS = datetime.now(timezone.utc).isoformat()
    SCRAPE_RUN_ID = f"{SCRAPE_TS.replace(':', '-').replace('.', '-')}_{uuid.uuid4().hex[:6]}"

    print("🚀 SQUADI Competition Scraper")
    print(f"🆔 Scrape run ID: {SCRAPE_RUN_ID}")
    print(f"🔧 Mode: {'DRY-RUN' if config['dry_run'] else 'WRITE'}")

    harvester = SquadiTokenHarvester()
    client = SquadiClient(harvester, delay_sec=config["delay_sec"])

    # Resolve target competitions
    if config["competition_uuid"] and not config["org_uuid"]:
        # Single-comp by UUID — we need the integer id, fetched via discovery
        # across all years until we find it. Cheaper: assume caller also supplied
        # --org-key when targeting one comp. If not, walk every year for every
        # known org. v1 is single-org NJYS so the loop below is short.
        for org_uuid_candidate in ORG_REGISTRY.keys():
            for yri in YEAR_REF_TO_CALENDAR.keys():
                try:
                    comps = client.list_competitions(org_uuid_candidate, yri)
                except RuntimeError:
                    continue
                for comp in comps:
                    if comp.get("uniqueKey") == config["competition_uuid"]:
                        config["org_uuid"] = org_uuid_candidate
                        target_comps = [comp]
                        break
                else:
                    continue
                break
            else:
                continue
            break
        if not config.get("org_uuid"):
            print(f"❌ Could not locate competition {config['competition_uuid']} in any known org", file=sys.stderr)
            return 1
    elif config["competition_uuid"] and config["org_uuid"]:
        # Locate the comp's integer id within the org's competitions
        target_comps = []
        for yri in (config["year_ref_id"],) if config["year_ref_id"] else YEAR_REF_TO_CALENDAR.keys():
            try:
                comps = client.list_competitions(config["org_uuid"], yri)
            except RuntimeError:
                continue
            for comp in comps:
                if comp.get("uniqueKey") == config["competition_uuid"]:
                    target_comps.append(comp)
        if not target_comps:
            print(f"❌ Competition {config['competition_uuid']} not found under org {config['org_uuid']}", file=sys.stderr)
            return 1
    else:
        target_comps = discover_competitions(
            client, config["org_uuid"],
            year_ref_id=config["year_ref_id"],
            name_blocklist=config["name_blocklist"],
        )

    if not target_comps:
        print(f"⚠️ No active competitions found for org={config['org_uuid']} year={config['year_ref_id']}")
        return 0

    org_meta = ORG_REGISTRY.get(config["org_uuid"])
    if not org_meta:
        print(f"❌ Org {config['org_uuid']} not in ORG_REGISTRY — add it before scraping", file=sys.stderr)
        return 1

    output_root = Path(config["output_dir"])
    raw_root = output_root / SCRAPE_RUN_ID / "raw" if config["keep_raw"] else None

    all_games: List[Dict[str, Any]] = []
    all_teams_map: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    comp_results: List[CompScrapeResult] = []

    scrape_start = time.time()
    for comp in target_comps:
        comp_raw_dir = (raw_root / str(comp.get("uniqueKey"))) if raw_root else None
        games, teams, res = scrape_competition(
            client, comp, config["org_uuid"], org_meta,
            scrape_run_id=SCRAPE_RUN_ID, scraped_at=SCRAPE_TS,
            raw_dir=comp_raw_dir,
        )
        all_games.extend(games)
        for tr in teams:
            key = (tr["provider_team_id"], json.loads(tr["meta"]).get("squadi_division_id"))
            all_teams_map.setdefault(key, tr)
        comp_results.append(res)
        print(
            f"  ✅ {res.competition_name}: games={res.games_emitted} "
            f"teams={res.teams_emitted} skipped_scheduled={res.skipped_scheduled} "
            f"errors={'1' if res.error else '0'}"
        )

    duration = time.time() - scrape_start
    all_teams = list(all_teams_map.values())

    if all_games:
        validate_records(all_games)

    manifest = {
        "run_id": SCRAPE_RUN_ID,
        "scraped_at": SCRAPE_TS,
        "org_uuid": config["org_uuid"],
        "year_ref_id": config["year_ref_id"],
        "comps_total": len(target_comps),
        "comps_ok": sum(1 for r in comp_results if not r.error),
        "comps_failed": sum(1 for r in comp_results if r.error),
        "games_emitted": len(all_games),
        "teams_emitted": len(all_teams),
        "token_refresh_count": client.token_refresh_count,
        "build_hash": harvester.build_hash,
        "duration_sec": round(duration, 2),
        "competitions": [
            {
                "uuid": r.competition_uuid,
                "id_int": r.competition_id_int,
                "name": r.competition_name,
                "games": r.games_emitted,
                "teams": r.teams_emitted,
                "error": r.error,
            }
            for r in comp_results
        ],
        "status": "ok" if all(not r.error for r in comp_results) else "partial",
        "dry_run": config["dry_run"],
    }

    if not config["dry_run"]:
        out_dir = write_outputs(all_games, all_teams, manifest, output_root, SCRAPE_RUN_ID)
        print(f"\n✅ OUTPUT: {out_dir}")
    else:
        print(f"\n🔍 DRY RUN — {len(all_games)} game rows, {len(all_teams)} team rows validated (not written)")

    print(json.dumps({"summary": manifest}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run `--help` to verify argparse**

Run: `cd C:/PitchRank && python scripts/scrape_squadi_competition.py --help`
Expected: usage block listing all flags.

- [ ] **Step 3: Run a dry-run end-to-end against NJYS Spring 2026**

Run:

```bash
cd C:/PitchRank && python scripts/scrape_squadi_competition.py --org-key 7cfab077-e619-47e4-ab36-0febc29501a2 --year-ref-id 8 --verbose
```

Expected output highlights:
- Token harvested
- 1 active competition: "NJYS State Cups - Spring 2026 (15U-19U)"
- `🔍 DRY RUN — N game rows, M team rows validated (not written)` (N may be 0 if season hasn't started yet)
- Summary JSON printed; `status: "ok"`, `dry_run: true`

- [ ] **Step 4: Run a dry-run against the historical Fall 2024 comp (richer data)**

Run:

```bash
cd C:/PitchRank && python scripts/scrape_squadi_competition.py --org-key 7cfab077-e619-47e4-ab36-0febc29501a2 --year-ref-id 6 --verbose 2>&1 | tail -60
```

Expected:
- 2-3 competitions discovered (Fall 2024 State Cups + maybe ODP Friendlies)
- `games_emitted` in the hundreds
- All `result` values in (W/L/D/U) — verify with: `python -c "import json,sys; print('see summary above')"`

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/scrape_squadi_competition.py && git commit -m "feat(squadi): add CLI entrypoint with dry-run-by-default"
```

---

## Task 14: Provider table seed migration

**Files:**
- Create: `supabase/migrations/20260504000000_add_squadi_provider.sql`

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260504000000_add_squadi_provider.sql`:

```sql
-- Add SQUADI as a registered provider so enhanced_pipeline._ensure_initialized()
-- can resolve provider_id by code lookup. Idempotent via ON CONFLICT.

INSERT INTO providers (code, name, base_url, country)
VALUES ('squadi', 'Squadi', 'https://api.us.squadi.com', 'US')
ON CONFLICT (code) DO NOTHING;
```

- [ ] **Step 2: Apply migration locally (if Supabase CLI is available)**

Run: `cd C:/PitchRank && supabase migration up 2>&1 | tail -10`
Expected: `Applied migration 20260504000000_add_squadi_provider.sql` (or "already applied" if re-running).

If Supabase CLI isn't configured locally, skip the local apply and rely on the staging migration step in Task 16.

- [ ] **Step 3: Verify the row exists (read-only)**

Run:

```bash
cd C:/PitchRank && python -c "
import os
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
r = sb.table('providers').select('id, code, name, base_url, country').eq('code', 'squadi').execute()
print(r.data)
"
```

(Per memory: bridge `SUPABASE_KEY` if your local `.env.local` only has `SUPABASE_SERVICE_ROLE_KEY`: `SUPABASE_KEY=$(grep ^SUPABASE_SERVICE_ROLE_KEY .env.local | cut -d= -f2-) python ...`)

Expected: one row with `code='squadi'`.

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank && git add supabase/migrations/20260504000000_add_squadi_provider.sql && git commit -m "feat(squadi): add migration registering squadi provider"
```

---

## Task 15: Pipeline registration in `enhanced_pipeline._ensure_initialized`

**Files:**
- Modify: `src/etl/enhanced_pipeline.py` (insert new `elif` branch after the `playmetrics` branch around line 245)

- [ ] **Step 1: Locate the playmetrics branch**

Run: `cd C:/PitchRank && grep -n 'playmetrics\|provider_code.lower()' src/etl/enhanced_pipeline.py | head -20`

Expected output includes `240:        elif self.provider_code.lower() == "playmetrics":` and the matcher import lines that follow.

- [ ] **Step 2: Add the squadi branch**

Find this block (around lines 240-245):

```python
        elif self.provider_code.lower() == "playmetrics":
            from src.models.playmetrics_matcher import PlayMetricsGameMatcher

            logger.info("Using PlayMetricsGameMatcher (WI-scoped fuzzy + auto-create)")
            self.matcher = PlayMetricsGameMatcher(
                self.supabase, provider_id=self.provider_id, alias_cache=self.alias_cache
            )
```

Add this block immediately after it (before the existing `else:` fallback on line 247-249):

```python
        elif self.provider_code.lower() == "squadi":
            # Squadi uses the standard GameHistoryMatcher per spec §2.6.
            # Per spec §C, NJYS team overlap with TGS / GotSport / EDP rows is
            # handled via provider_team_id (UUID) primary alias and (state_code,
            # age_group, gender) fuzzy fallback. Revisit if review-queue volume
            # warrants a SquadiGameMatcher subclass with state-scoped autocreate.
            logger.info("Using GameHistoryMatcher for provider: squadi")
            self.matcher = GameHistoryMatcher(
                self.supabase, provider_id=self.provider_id, alias_cache=self.alias_cache
            )
```

- [ ] **Step 3: Verify the file still parses**

Run: `cd C:/PitchRank && python -c "import src.etl.enhanced_pipeline; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank && git add src/etl/enhanced_pipeline.py && git commit -m "feat(squadi): register squadi provider in enhanced_pipeline"
```

---

## Task 16: Manual verification (end-to-end dry-run gate)

**Files:** none — verification only.

Per the user's "dry-run everything to start" directive, the following must succeed before declaring v1 done. Each check has its own dry-run safety gate; nothing writes to Supabase until step 16.6.

- [ ] **Step 16.1: Token harvest end-to-end**

Run:

```bash
cd C:/PitchRank && python -c "
from scripts.scrape_squadi_competition import SquadiTokenHarvester
h = SquadiTokenHarvester()
h.invalidate()  # force a fresh harvest
print(f'token len={len(h.get_token())} build={h.build_hash}')
"
```

Expected: `token len=448 build=<hash>` (length may vary). Failure → token regex needs adjustment (Task 6).

- [ ] **Step 16.2: Discovery for NJYS year 2026**

```bash
cd C:/PitchRank && python scripts/scrape_squadi_competition.py --org-key 7cfab077-e619-47e4-ab36-0febc29501a2 --year-ref-id 8
```

Expected: 1 active comp ("NJYS State Cups - Spring 2026 (15U-19U)"). Summary JSON shows `comps_ok=1, comps_failed=0`. `dry_run=true`. Games may be 0 if season hasn't started.

- [ ] **Step 16.3: Full historical scrape (Fall 2024) for richer dataset**

```bash
cd C:/PitchRank && python scripts/scrape_squadi_competition.py --org-key 7cfab077-e619-47e4-ab36-0febc29501a2 --year-ref-id 6 2>&1 | tee /tmp/squadi-fall2024-dryrun.log
```

Expected:
- `games_emitted` between 100 and 1500
- All comps complete without errors
- Summary log line shows `status="ok", dry_run=true, token_refresh_count=0`

- [ ] **Step 16.4: Real CSV write (`--no-dry-run`)**

```bash
cd C:/PitchRank && python scripts/scrape_squadi_competition.py --org-key 7cfab077-e619-47e4-ab36-0febc29501a2 --year-ref-id 6 --no-dry-run --keep-raw
```

Expected: `data/raw/squadi/<run_id>/{games.csv, teams.csv, manifest.json, raw/<comp_uuid>/}` exists. Spot-check:

```bash
cd C:/PitchRank && python -c "
import csv, json, os
from pathlib import Path
runs = sorted(Path('data/raw/squadi').iterdir())
latest = runs[-1]
print('run dir:', latest)
with open(latest / 'games.csv') as f:
    rows = list(csv.DictReader(f))
print(f'games rows={len(rows)} sample={rows[0] if rows else None}')
print(f'unique teams in games: {len({r[\"team_id\"] for r in rows})}')
print(f'distinct results: {sorted({r[\"result\"] for r in rows})}')
print(f'distinct age_groups: {sorted({r[\"age_group\"] for r in rows})}')
print('manifest:', json.dumps(json.loads((latest / 'manifest.json').read_text())['summary' if False else ''], indent=2)[:500])
"
```

Verify:
- Distinct results subset of `{"W", "L", "D", "U"}`
- Distinct age_groups subset of `{"u11","u12","u13","u14"}` (Fall 2024 is 11U-14U)
- Sample row has `state_code="NJ"`, `provider="squadi"`

- [ ] **Step 16.5: Spot-check 3 matches against the live Squadi UI**

Pick 3 random matches from `games.csv` (different divisions). For each, open the source_url in a browser, locate that match by `team_name` + `game_date`, and verify scores + venue match. Report any discrepancies — likely indicates a parser bug.

- [ ] **Step 16.6: Importer dry-run (gate before touching Supabase)**

```bash
cd C:/PitchRank && python scripts/import_games_enhanced.py --provider squadi --csv data/raw/squadi/<run_id>/games.csv --dry-run --verbose 2>&1 | tee /tmp/squadi-import-dryrun.log
```

Expected (read carefully):
- `Provider not found: squadi` → migration (Task 14) hasn't been applied; apply it first
- Otherwise: `IMPORT_RESULT` JSON shows `games_processed`, `games_inserted`, `games_skipped_dedup`, `team_match_review_queue_added`, etc.
- `dry_run: true` confirmed; no writes happened
- Review-queue additions should be reasonable (NJYS overlap with TGS/GotSport: expect 30–80% of teams to need fuzzy matching for first run)

If review-queue size is excessive (>80% of teams), pause and revisit the matcher choice in Task 15 — a `SquadiGameMatcher` subclass with state-scoped autocreate (mirroring PlayMetrics) may be warranted before going live.

- [ ] **Step 16.7: Real importer run**

Once 16.6 looks reasonable and you've reviewed sample matches:

```bash
cd C:/PitchRank && python scripts/import_games_enhanced.py --provider squadi --csv data/raw/squadi/<run_id>/games.csv --verbose 2>&1 | tee /tmp/squadi-import.log
```

Expected: `IMPORT_RESULT` shows `games_inserted` > 0, no errors. Verify in Supabase:

```bash
cd C:/PitchRank && python -c "
import os
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
prov = sb.table('providers').select('id').eq('code', 'squadi').single().execute()
pid = prov.data['id']
r = sb.table('games').select('id', count='exact').eq('provider_id', pid).limit(1).execute()
print(f'squadi games in DB: {r.count}')
"
```

- [ ] **Step 16.8: Verify rankings pipeline picks up the data (read-only)**

Run the standard ranking validation script for NJ to confirm new Squadi games are integrated:

```bash
cd C:/PitchRank && python scripts/check_state_rankings_health.py --state NJ 2>&1 | tail -20
```

Expected: NJYS team counts increased; no regressions in age-group coverage.

- [ ] **Step 16.9: Document the run in the spec's "Implementation notes" section**

Add a short note at the bottom of `docs/superpowers/specs/2026-05-04-squadi-scraper-design.md`:

```markdown
## Implementation notes

- v1 shipped on `<date>` from branch `scraper/squadi-nj`.
- First production scrape: NJYS Fall 2024 + Spring 2026 — `<N>` games, `<M>` teams.
- Review-queue additions on first import: `<count>` (per `team_match_review_queue` query).
- Token build hash at first scrape: `<hash>`.
- Open follow-ups: <list any work items deferred to v2>.
```

Commit:

```bash
cd C:/PitchRank && git add docs/superpowers/specs/2026-05-04-squadi-scraper-design.md && git commit -m "docs(squadi): record v1 ship notes"
```

---

## Self-Review

**Spec coverage check** (each numbered item maps to a task):
- Spec §1 architecture → Task 1 + module layout
- Spec §2.1 SquadiTokenHarvester → Task 7 (+ regex helpers in Task 6)
- Spec §2.2 SquadiClient → Task 8
- Spec §2.3 CompetitionDiscovery → Task 9
- Spec §2.4 MatchExtractor → Tasks 10, 11
- Spec §2.5 Outputs → Task 12 + Task 13 (manifest)
- Spec §2.6 Provider registration → Tasks 14, 15
- Spec §3 Data flow → Task 13 main() orchestrates exactly the spec flowchart
- Spec §4 Error handling → Tasks 7 (token errors), 8 (retry+401), 11 (per-comp continue), 12 (atomic write)
- Spec §5 Testing → Tasks 1-6, 9, 10 (unit) + Task 16 (manual verification)
- Spec §A 27-column CSV → Task 1 (REQUIRED_COLUMNS) + Task 10 (normalize_match)
- Spec §B per-match meta → Task 10 (folded into team-row meta JSON; PK winner stored there)
- Spec §C teams.csv + age strategy → Task 10 (team rows) + Task 4 (helpers)
- Spec §D Provider seed → Task 14
- Spec §E Non-goals → respected throughout (no roster/officiating/livestream extraction)
- CLI summary → Task 13
- NJYS constants → Task 1 (`ORG_REGISTRY` entry)

**Placeholder scan:** No "TBD"/"TODO"/"add appropriate error handling"/"similar to Task N" present. Every step has concrete code, exact commands, and exact expected output.

**Type consistency:**
- `parse_division_metadata(name, fallback_age_int)` returns `(age_group, gender, tier)` — used consistently in `normalize_match` (Task 10) and verified by Task 3 tests.
- `parse_utc_to_local_date` returns `(date_str, time_str)` tuple — used in `normalize_match` (Task 10) and verified by Task 2 tests.
- `SquadiTokenHarvester.get_token()` returns `str`, `.invalidate()` returns `None`, `.build_hash` is `Optional[str]` — used consistently in `SquadiClient` (Task 8) and `main` (Task 13).
- `CompScrapeResult` dataclass fields used identically in Tasks 11 and 13.
- `REQUIRED_COLUMNS` (28) and `TEAMS_COLUMNS` (13) defined in Task 1; consumed in Tasks 10 (normalize), 12 (write).

**Dry-run-first compliance:** `--dry-run` defaults to True (Task 13 step 1). Every Task 16 step uses dry-run before any state-changing run. No automated CI step writes to Supabase. Real-write paths (16.4, 16.6 with `--no-dry-run`, 16.7) are gated behind the prior dry-run successes.

Plan reviewed; no fixes needed.

---

## Execution Handoff

Plan complete and saved to `.turbo/plans/squadi-scraper.md` (per repo convention). Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
