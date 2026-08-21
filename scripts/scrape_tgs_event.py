import argparse
import csv
import hashlib
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
from src.utils.team_utils import CURRENT_YEAR, calculate_age_group_from_birth_year

BASE = "https://api.athleteone.com/api"
OUTPUT_DIR = "data/raw/tgs"

# The date from which a U-age label ('BU11') can be resolved, not the date such
# labels start appearing -- they occur on both sides of it. From here on, the
# event's own game dates identify the season the label was written against.
# Before it they do not: 3430 (Apr 2025) and 3967 (Sep 2025) both carry U-age
# divisions sitting two seasons behind their play dates, so those are skipped
# rather than guessed. --u-format-before-cutover lifts that for a backfill.
U_FORMAT_CUTOVER_DATE = "2026-08-01"
U_FORMAT_BEFORE_CUTOVER = False

# Global scrape identifiers (set in main())
SCRAPE_TS = None
SCRAPE_RUN_ID = None

REQUIRED_COLUMNS = [
    "provider",
    "scrape_run_id",
    "event_id",
    "event_name",
    "schedule_id",
    "age_year",  # Legacy birth-year column, always empty; cohorts are age groups
    "age_group",
    "gender",
    "team_id",
    "team_id_source",
    "team_name",
    "club_name",  # Extracted from "Club Name - Team Name" format
    "opponent_id",
    "opponent_id_source",
    "opponent_name",
    "opponent_club_name",  # Extracted from "Club Name - Team Name" format
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
]

# Removed - using get-schedules-by-flight endpoint directly


# -----------------------------
# CONFIG LOADER
# -----------------------------


def resolve_config():
    """Load configuration with precedence: CLI > ENV > Defaults"""
    parser = argparse.ArgumentParser(description="TGS API Scraper")

    parser.add_argument("--start-event", type=int, help="Start event ID")
    parser.add_argument("--end-event", type=int, help="End event ID")
    parser.add_argument("--output-dir", type=str, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing output")
    parser.add_argument("--max-workers", type=int, help="Max parallel workers for flight processing (default: 8)")
    parser.add_argument(
        "--u-format-before-cutover",
        action="store_true",
        help=(
            f"Read U-age division labels against the current season even for events played before "
            f"{U_FORMAT_CUTOVER_DATE}. Manual backfills only — verify the event's labels match the "
            f"current season first, since pre-cutover events are usually one or two seasons behind."
        ),
    )

    args = parser.parse_args()

    # CLI > ENV > Default
    start_event = args.start_event or int(os.getenv("TGS_START_EVENT", "3900"))
    end_event = args.end_event or int(os.getenv("TGS_END_EVENT", "4000"))
    output_dir = args.output_dir or os.getenv("TGS_OUTPUT_DIR", OUTPUT_DIR)
    max_workers = args.max_workers or int(os.getenv("TGS_MAX_WORKERS", "8"))

    return {
        "start_event": start_event,
        "end_event": end_event,
        "output_dir": output_dir,
        "dry_run": args.dry_run,
        "max_workers": max_workers,
        "u_format_before_cutover": args.u_format_before_cutover,
    }


# -----------------------------
# HELPER FUNCTIONS
# -----------------------------


# A U-age token, optionally gender-prefixed ('BU11') and optionally continuing
# into more ages ('GU18/19', 'U15 - U18'). The lookbehind keeps the U attached to
# a cohort token instead of matching mid-word, so 'SKU12' is not an age.
U_AGE_TOKEN_RE = re.compile(r"(?<![A-Z])[BG]?U-?(\d{1,2})((?:\s*[/-]\s*U?\d{1,2}\b)*)")


def u_age_of(division_name: str) -> Optional[int]:
    """The single U-age this label names, or None if it names none or several.

    A multi-age label is only honoured when every age it lists lands in the same
    cohort once U18 collapses into U19 ('GU18/19'). Anything spanning real
    cohorts ('U13-U19', 'GU17/18') names no single one, and stamping its teams
    with the first age filed the whole flight as the youngest.
    """
    ages = set()
    for match in U_AGE_TOKEN_RE.finditer(division_name.upper()):
        ages.add(int(match.group(1)))
        ages.update(int(a) for a in re.findall(r"\d{1,2}", match.group(2)))

    if not ages or len({19 if age == 18 else age for age in ages}) != 1:
        return None
    return max(ages)


# A band written as two adjacent four-digit years. Anchored to the pair so a
# season suffix elsewhere in the label cannot join the band.
_ADJACENT_BAND = re.compile(r"(?<!\d)(20\d{2})\s*/\s*(20\d{2})(?!\d)")

# A season stamp TGS appends to a division name: "B2015 (2026-27)". It is not a
# birth year, and counting it as one makes a single-year label look as though it
# named two cohorts, so names_a_cohort rejects the flight before it is fetched.
# The band branch never saw this because it reads an ADJACENT pair; the
# single-year branch below counts every four-digit number in the string.
_SEASON_SUFFIX = re.compile(r"\(\s*20\d{2}\s*[-/]\s*(?:20)?\d{2}\s*\)")


def _tracked_age_group(age: int) -> Optional[str]:
    """Cohort label for a U-age, or None outside the tracked U10-U19 range."""
    age = 19 if age == 18 else age
    return f"u{age}" if 10 <= age <= 19 else None


def season_year_of(game_date: str) -> int:
    """Season year a date falls in. Seasons run Aug 1 to Jul 31."""
    year, month = int(game_date[:4]), int(game_date[5:7])
    return year if month >= 8 else year - 1


def extract_age_group(division_name: str, label_season: Optional[int] = None) -> Optional[str]:
    """Cohort a division names, as of the current season. 'BU11' -> 'u11'.

    A U-age names the cohort as of the season that wrote it, and that cohort
    ages one group every Aug 1 while the label on the event stays fixed. So the
    label is advanced by the seasons elapsed since: a BU11 event from 2026-27
    reads u11 this season and u12 the next, tracking the same players and the
    stored `teams.age_group` that also rolls. Callers pass label_season once the
    event's dates identify it, and None where it cannot be trusted.

    TGS also still carries legacy birth-year labels ('B2015') on older events.
    A birth year is not a cohort either, so those convert against the current
    season the same way.
    """
    age = u_age_of(division_name)
    if age is not None:
        if label_season is None:
            return None
        return _tracked_age_group(age + CURRENT_YEAR - label_season)

    # A dual-year label names a BAND, not two separate cohorts: the season runs
    # Aug 1 - Jul 31, so a band straddles Jan 1 and gets written from both ends.
    # Every band satisfies U_N = {SEASON+1-N, SEASON-N}, so N = SEASON+1 minus the
    # YOUNGER year -- U11 is 2016/15 and 2016 is the year that names it. Reading a
    # band from its older year lands one group too old on every band in the table.
    #
    # The fold that maps a lone 2007 into U19 must NOT apply here. A bare 2007 is
    # genuinely U19, because U19 (2008/07) is the only band containing it -- but
    # the BAND 2007/06 is the group above U19 and has aged out. Folding it would
    # file an aged-out band as U19, which is what hid this error the first time:
    # "B2008/2007" comes out right under either rule, purely by coincidence.
    # Only an ADJACENT consecutive pair is a band. Taking every four-digit number
    # in the string mis-reads a season suffix ("B2016/2015 (2026-27)" would derive
    # from 2026) and silently files malformed multi-cohort labels ("B2016/2014")
    # as though they named one band.
    band = _ADJACENT_BAND.search(division_name)
    if band:
        first, second = int(band.group(1)), int(band.group(2))
        if abs(first - second) != 1:
            return None
        # N = SEASON + 1 - the YOUNGER year, and the age-20 fold is deliberately
        # NOT applied: a bare 2007 is U19, but the BAND 2007/06 has aged out.
        return _tracked_age_group(CURRENT_YEAR + 1 - max(first, second))

    years = [int(y) for y in re.findall(r"\d{4}", _SEASON_SUFFIX.sub("", division_name))]
    if len(set(years)) != 1:
        return None
    group = calculate_age_group_from_birth_year(years[0])
    if not group:
        return None
    return _tracked_age_group(int(group[1:]))


def u_label_season(game_dates: List[str]) -> Optional[int]:
    """Season a U-age label on this event was written against, or None.

    Only readable from the relabel onward, where the event's own dates identify
    it. Before that the label belongs to some earlier season we cannot pin:
    event 3430 (Apr 2025) files as U13 teams who are u15 now. Opting one in
    reads it as the cutover season rather than whatever year the run happens on.
    """
    if not game_dates:
        return None
    first_game = min(game_dates)
    if first_game >= U_FORMAT_CUTOVER_DATE:
        return season_year_of(first_game)
    return season_year_of(U_FORMAT_CUTOVER_DATE) if U_FORMAT_BEFORE_CUTOVER else None


def names_a_cohort(division_name: str) -> bool:
    """Whether the label could name a tracked cohort, before dates are known.

    Deliberately season-blind: this runs before the games are fetched, and a
    U-age needs its season to resolve. Asking extract_age_group here instead
    would read every U label as unresolvable and skip the flight before the
    dates that would have resolved it are ever loaded.
    """
    if (age := u_age_of(division_name)) is not None:
        return _tracked_age_group(age) is not None
    return extract_age_group(division_name) is not None


def extract_gender(
    division_name: str, event_name: Optional[str] = None, division_gender: Optional[str] = None
) -> Optional[str]:
    """Extract gender from the API's division_gender, then the names.

    Strategy:
    1. Trust the division's own divisionGender ('m'/'f') when the API supplies it
    2. Check division name prefix (e.g., 'B2012' -> 'Boys', 'G2013' -> 'Girls')
    3. Search the division name for keywords ('U11 Girls' has no B/G prefix)
    4. Fall back to the same keywords in the event name

    Returning None here is not harmless: normalize_gender() in
    extract_and_import_tgs_teams.py turns an empty gender into 'Male', so an
    unresolved girls division is created as a boys team at confidence 1.0.

    Returns normalized gender values that match validator expectations:
    - 'Boys' for B/male divisions
    - 'Girls' for G/female divisions
    """
    if division_gender:
        initial = division_gender.strip().lower()[:1]
        if initial == "m":
            return "Boys"
        elif initial == "f":
            return "Girls"

    # Try division name prefix first (e.g., "B2014", "G2013")
    division_upper = division_name.upper()
    if division_upper.startswith("B"):
        return "Boys"
    elif division_upper.startswith("G"):
        return "Girls"

    # Fallback: search division then event name for gender keywords
    # e.g., "U11 Girls", "Pre-ECNL Boys Northern Cal 2025-2026"
    for text in (division_upper, (event_name or "").upper()):
        if re.search(r"\bBOYS?\b|\bMALE\b|\bMEN\b", text):
            return "Boys"
        elif re.search(r"\bGIRLS?\b|\bFEMALE\b|\bWOMEN\b", text):
            return "Girls"

    return None


def generate_team_id(team_name: str) -> str:
    """Generate a team ID from team name using hash-based approach"""
    if not team_name or not team_name.strip():
        return ""
    # Normalize team name and generate hash
    normalized_name = team_name.lower().strip()
    hash_obj = hashlib.md5(normalized_name.encode())
    hash_str = hash_obj.hexdigest()[:12]
    return f"tgs:{hash_str}"


def compute_result(home_score: Optional[int], away_score: Optional[int]) -> str:
    """Compute result from scores: W (win), L (loss), D (draw), U (unknown)"""
    if home_score is None or away_score is None:
        return "U"
    if home_score > away_score:
        return "W"
    elif home_score < away_score:
        return "L"
    else:
        return "D"


def is_future_game(game_date_str: str) -> bool:
    """
    Check if a game date is in the future (hasn't happened yet).

    Args:
        game_date_str: Date string in YYYY-MM-DD format

    Returns:
        True if the game is in the future, False if it's today or in the past
    """
    if not game_date_str:
        return False  # No date = can't determine, don't filter

    try:
        # Parse the date (format: YYYY-MM-DD)
        game_date = datetime.strptime(game_date_str[:10], "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        return game_date > today
    except (ValueError, TypeError):
        return False  # Can't parse = don't filter


def parse_team_name(full_name: str) -> tuple[str, str]:
    """
    Parse team name in format "Club Name - Team Name" into club_name and team_name.

    Examples:
        "Next Level Soccer - Next Level Soccer 12 Black"
        -> ("Next Level Soccer", "Next Level Soccer 12 Black")

        "Arizona Arsenal ECNL G12" (no dash)
        -> ("", "Arizona Arsenal ECNL G12")

    Returns:
        Tuple of (club_name, team_name)
    """
    if not full_name or not full_name.strip():
        return ("", "")

    # Look for " - " pattern (dash with spaces on both sides)
    if " - " in full_name:
        parts = full_name.split(" - ", 1)
        club_name = parts[0].strip()
        team_name = parts[1].strip() if len(parts) > 1 else ""
        return (club_name, team_name)

    # No dash found - entire string is team name, no club name
    return ("", full_name.strip())


# -----------------------------
# API FUNCTIONS
# -----------------------------


def get_event_nav(event_id: int) -> Optional[Dict]:
    """Get event navigation settings to discover flights"""
    url = f"{BASE}/Event/get-public-event-nav-settings-by-eventID/{event_id}"
    headers = {
        "Origin": "https://public.totalglobalsports.com",
        "Referer": "https://public.totalglobalsports.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"⚠️ Event {event_id} nav returned status {r.status_code}")
    except Exception as e:
        print(f"⚠️ Error fetching nav for event {event_id}: {e}")
    return None


def get_event_details(event_id: int) -> Optional[Dict]:
    """Get event details to extract event name"""
    url = f"{BASE}/Event/get-event-details-by-eventID/{event_id}"
    headers = {
        "Origin": "https://public.totalglobalsports.com",
        "Referer": "https://public.totalglobalsports.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("data", {}) if isinstance(data, dict) else data
        else:
            print(f"⚠️ Event {event_id} details returned status {r.status_code}")
    except Exception as e:
        print(f"⚠️ Error fetching event {event_id} details: {e}")
    return None


def get_flight_division(flight_id: int) -> Optional[Dict]:
    """Get division info for a flight (division name, gender)"""
    url = f"{BASE}/Event/get-flight-division-by-flightID/{flight_id}"
    headers = {
        "Origin": "https://public.totalglobalsports.com",
        "Referer": "https://public.totalglobalsports.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("data", {}) if isinstance(data, dict) else data
    except Exception:
        pass
    return None


def get_games_for_flight(event_id: int, flight_id: int) -> List[Dict]:
    """Get all games for a flight - THE MONEY ENDPOINT"""
    url = f"{BASE}/Event/get-schedules-by-flight/{event_id}/{flight_id}/0"
    headers = {
        "Origin": "https://public.totalglobalsports.com",
        "Referer": "https://public.totalglobalsports.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            # Handle wrapped responses
            if isinstance(data, dict):
                if "data" in data:
                    data = data["data"]
                elif "result" in data and "data" in data:
                    data = data["data"]

            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "schedules" in data:
                return data["schedules"]
            elif isinstance(data, dict) and "games" in data:
                return data["games"]
    except Exception:
        pass
    return []


# Function moved above - get_games_for_flight now uses correct endpoint


# -----------------------------
# NORMALIZATION
# -----------------------------


def normalize_api_game(
    game: Dict, event_id: int, event_name: str, division: Dict, home_away: str, scrape_run_id: str, scrape_ts: str
) -> Dict:
    """Map API game data to canonical CSV schema"""
    division_id = division.get("divisionID")
    division_name = division.get("divisionName", "")

    # Resolved once in process_single_flight, which knows the event's dates.
    age_group = division.get("ageGroup", "")
    gender = extract_gender(division_name, event_name=event_name, division_gender=division.get("divisionGender"))

    # Get scores - API uses hometeamscore and awayteamscore
    # IMPORTANT: Use explicit None check, not 'or', because 0 is a valid score!
    home_score_raw = game.get("hometeamscore")
    if home_score_raw is None:
        home_score_raw = game.get("homeScore")

    away_score_raw = game.get("awayteamscore")
    if away_score_raw is None:
        away_score_raw = game.get("awayScore")

    # Convert to int, handling None and empty strings (but 0 is valid!)
    home_score = None
    away_score = None

    if home_score_raw is not None and home_score_raw != "":
        try:
            home_score = int(home_score_raw)
        except (ValueError, TypeError):
            home_score = None

    if away_score_raw is not None and away_score_raw != "":
        try:
            away_score = int(away_score_raw)
        except (ValueError, TypeError):
            away_score = None

    # Helper function to safely get and strip string values
    def safe_get_str(key: str, default: str = "") -> str:
        """Safely get a value from game dict and convert to string, handling None"""
        value = game.get(key)
        if value is None:
            return default
        return str(value).strip() if value else default

    # Determine team/opponent based on perspective
    if home_away == "H":
        team_full_name = safe_get_str("homeTeam", "")
        opponent_full_name = safe_get_str("awayTeam", "")
        # Get official provider team IDs from API (NOT generated - use official IDs!)
        team_provider_id = str(game.get("hometeamID") or "")
        opponent_provider_id = str(game.get("awayteamID") or "")
        # Get club names directly from API (much more reliable than parsing!)
        team_club_name = safe_get_str("homeTeamClub", "")
        opponent_club_name = safe_get_str("awayTeamClub", "")
        goals_for = home_score
        goals_against = away_score
    else:  # away
        team_full_name = safe_get_str("awayTeam", "")
        opponent_full_name = safe_get_str("homeTeam", "")
        # Get official provider team IDs from API (swap home/away for away perspective)
        team_provider_id = str(game.get("awayteamID") or "")
        opponent_provider_id = str(game.get("hometeamID") or "")
        # Get club names directly from API (swap home/away for away perspective)
        team_club_name = safe_get_str("awayTeamClub", "")
        opponent_club_name = safe_get_str("homeTeamClub", "")
        goals_for = away_score
        goals_against = home_score

    # Use full team name as team_name (no parsing needed since we have club from API)
    team_name = team_full_name.strip() if team_full_name else ""
    opponent_name = opponent_full_name.strip() if opponent_full_name else ""

    # Compute result from perspective
    result = compute_result(goals_for, goals_against)

    # Use official provider team IDs (allows matching to existing teams in database)
    # This is critical - using official IDs allows the system to match teams that
    # already exist from other providers (GotSport, etc.) instead of creating duplicates
    team_id = team_provider_id if team_provider_id else ""
    opponent_id = opponent_provider_id if opponent_provider_id else ""

    # Extract date from ISO datetime format (e.g., "2025-12-06T07:45:00" -> "2025-12-06")
    game_date_raw = game.get("gameDate", "")
    game_date = ""
    if game_date_raw:
        # Extract date portion (YYYY-MM-DD) from ISO datetime
        if "T" in game_date_raw:
            game_date = game_date_raw.split("T")[0]
        else:
            game_date = game_date_raw[:10] if len(game_date_raw) >= 10 else game_date_raw

    # Extract time from ISO datetime or use gameTime field
    game_time = game.get("gameTime", "")
    if not game_time and game_date_raw and "T" in game_date_raw:
        # Extract time portion from ISO datetime
        time_part = game_date_raw.split("T")[1] if "T" in game_date_raw else ""
        if time_part:
            # Convert "07:45:00" to "07:45" or keep as is
            game_time = time_part[:5] if len(time_part) >= 5 else time_part

    # Build source URL
    source_url = f"https://public.totalglobalsports.com/public/event/{event_id}"

    # State and state_code will be matched later via club name script
    state = ""
    state_code = ""

    return {
        "provider": "tgs",  # Add provider field for import pipeline
        "scrape_run_id": scrape_run_id,
        "event_id": event_id,
        "event_name": event_name,
        "schedule_id": division_id,
        "age_year": "",
        "age_group": age_group,
        "gender": gender,
        "team_id": team_id,
        "team_id_source": team_id,
        "team_name": team_name,
        "club_name": team_club_name,  # Extracted from "Club Name - Team Name" format
        "opponent_id": opponent_id,
        "opponent_id_source": opponent_id,
        "opponent_name": opponent_name,
        "opponent_club_name": opponent_club_name,  # Extracted from "Club Name - Team Name" format
        "state": state,
        "state_code": state_code,
        "game_date": game_date,
        "game_time": game_time,
        "home_away": home_away,
        "goals_for": goals_for if goals_for is not None else "",
        "goals_against": goals_against if goals_against is not None else "",
        "result": result,
        "venue": game.get("venue", ""),
        "source_url": source_url,
        "scraped_at": scrape_ts,
    }


# -----------------------------
# SCRAPER CORE
# -----------------------------


def process_single_flight(
    flight_info: Dict, event_id: int, event_name: str, parent_division_name: str
) -> Tuple[List[Dict], str]:
    """
    Process a single flight: get division info, get games, normalize records.

    This function is designed to be called in parallel via ThreadPoolExecutor.

    Args:
        flight_info: Flight dict with flightID, flightName, hasActiveSchedule
        event_id: Parent event ID
        event_name: Parent event name
        parent_division_name: Division name from parent structure (fallback)

    Returns:
        Tuple of (list of game records, status message)
    """
    flight_id = flight_info.get("flightID")
    flight_name = flight_info.get("flightName", "")
    records = []

    # EARLY FILTER: Check division name from parent structure first
    # This avoids making API calls for divisions outside U10-U19 range. A U-age
    # cannot be resolved to a cohort until the games date the event, so this only
    # asks whether the label could name one at all.
    if not names_a_cohort(parent_division_name):
        return [], f"⏭️  {parent_division_name} - {flight_name}: skipped (not U10-U19)"

    # Step 1: Get division info (division name, gender)
    flight_division = get_flight_division(flight_id)
    if not flight_division:
        return [], f"⚠️  {flight_name} ({flight_id}): no division info"

    division_name_from_api = flight_division.get("divisionName", parent_division_name)

    # SECOND FILTER: Check API-returned division name
    if not names_a_cohort(division_name_from_api):
        return [], f"⏭️  {division_name_from_api} - {flight_name}: skipped (not U10-U19)"

    # Step 2: Get games for this flight (THE MONEY ENDPOINT)
    games = get_games_for_flight(event_id, flight_id)
    if not games:
        return [], f"⚠️  {division_name_from_api} - {flight_name}: no games"

    # The games date the event, which is what decides whether a U-age label is
    # still current, so the cohort is only resolvable from here on.
    game_dates = [str(g.get("gameDate", ""))[:10] for g in games if g.get("gameDate")]
    age_group = extract_age_group(division_name_from_api, label_season=u_label_season(game_dates))
    if not age_group:
        if u_age_of(division_name_from_api) is not None:
            return [], (
                f"⏭️  {division_name_from_api} - {flight_name}: skipped "
                f"(U-age label predates {U_FORMAT_CUTOVER_DATE}; --u-format-before-cutover to include)"
            )
        return [], f"⏭️  {division_name_from_api} - {flight_name}: skipped (not U10-U19)"

    # Create division info for normalization
    division_info = {
        "divisionID": flight_id,
        "divisionName": division_name_from_api,
        "divisionGender": flight_division.get("divisionGender"),
        "ageGroup": age_group,
    }

    # Step 3: Generate records for each game (both home and away perspectives)
    games_added = 0
    games_skipped_future = 0

    for game in games:
        # Home perspective
        home_record = normalize_api_game(game, event_id, event_name, division_info, "H", SCRAPE_RUN_ID, SCRAPE_TS)

        # Skip future games (haven't been played yet)
        if is_future_game(home_record.get("game_date", "")):
            games_skipped_future += 1
            continue

        records.append(home_record)

        # Away perspective (same game, so we know it's not future)
        away_record = normalize_api_game(game, event_id, event_name, division_info, "A", SCRAPE_RUN_ID, SCRAPE_TS)
        records.append(away_record)
        games_added += 1

    # Build status message
    if games_skipped_future > 0:
        status = (
            f"✅ {division_name_from_api} - {flight_name}: {games_added} games (+{games_skipped_future} future skipped)"
        )
    else:
        status = f"✅ {division_name_from_api} - {flight_name}: {games_added} games"

    return records, status


def scrape_event(event_id: int, config: Dict, records: List[Dict]) -> None:
    """Scrape a single event using parallel flight processing.

    Only includes games that have already been played (game_date <= today).
    Future scheduled games are skipped.

    Uses ThreadPoolExecutor for parallel flight processing (8x speedup typical).
    """
    event_start = time.time()
    print(f"\n📌 EVENT {event_id}")

    # Get event details to extract event name
    event_details = get_event_details(event_id)
    event_name = event_details.get("eventName", f"Event {event_id}") if event_details else f"Event {event_id}"
    print(f"  Event Name: {event_name}")

    # Step 1: Get event navigation to discover flights
    nav_data = get_event_nav(event_id)
    if not nav_data:
        print("❌ Event nav not found")
        return

    # Extract flight list from schedule/standings endpoint
    schedule_url = f"{BASE}/Event/get-event-schedule-or-standings/{event_id}"
    headers = {
        "Origin": "https://public.totalglobalsports.com",
        "Referer": "https://public.totalglobalsports.com/",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        r = requests.get(schedule_url, headers=headers, timeout=20)
        if r.status_code != 200:
            print(f"⚠️ Could not get schedule structure: {r.status_code}")
            return
        schedule_data = r.json()
    except Exception as e:
        print(f"⚠️ Error getting schedule structure: {e}")
        return

    # Extract divisions and flights
    data = schedule_data.get("data", {}) if isinstance(schedule_data, dict) else {}
    girls_divs = data.get("girlsDivAndFlightList", [])
    boys_divs = data.get("boysDivAndFlightList", [])
    all_divisions = girls_divs + boys_divs

    # Build list of active flights with their parent division info
    active_flights = []
    for division in all_divisions:
        division_name = division.get("divisionName", "")
        flight_list = division.get("flightList", [])

        for flight in flight_list:
            if flight.get("hasActiveSchedule", False):
                active_flights.append({"flight": flight, "division_name": division_name})

    print(f"✅ Found {len(all_divisions)} divisions, {len(active_flights)} active flights")

    if not active_flights:
        print("  ⚠️ No active flights to process")
        return

    # Process flights in PARALLEL using ThreadPoolExecutor
    max_workers = config.get("max_workers", 8)
    flight_records = []
    status_messages = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all flight processing tasks
        future_to_flight = {
            executor.submit(
                process_single_flight, flight_info["flight"], event_id, event_name, flight_info["division_name"]
            ): flight_info
            for flight_info in active_flights
        }

        # Collect results as they complete
        for future in as_completed(future_to_flight):
            try:
                flight_recs, status = future.result()
                if flight_recs:
                    flight_records.extend(flight_recs)
                status_messages.append(status)
            except Exception as e:
                flight_info = future_to_flight[future]
                status_messages.append(f"❌ {flight_info['flight'].get('flightName', 'Unknown')}: {e}")

    # Add all flight records to main records list
    records.extend(flight_records)

    # Print status messages (sorted for readability)
    for msg in sorted(status_messages):
        print(f"  {msg}")

    event_duration = time.time() - event_start
    games_count = len(flight_records) // 2  # Divide by 2 since each game has home+away records
    print(
        f"⏱️  Event {event_id} completed in {event_duration:.1f}s "
        f"({games_count} games from {len(active_flights)} flights)"
    )


# -----------------------------
# VALIDATION + OUTPUT
# -----------------------------


def validate_records(records: List[Dict]) -> None:
    """Validate all records have required columns"""
    if not records:
        return

    for i, r in enumerate(records):
        missing = [col for col in REQUIRED_COLUMNS if col not in r]
        if missing:
            raise ValueError(f"Record {i} missing columns: {missing}")


def write_output(records: List[Dict], output_dir: str, start_event: int, end_event: int) -> None:
    """Write records to CSV file"""
    os.makedirs(output_dir, exist_ok=True)

    # Format timestamp for filename
    timestamp = SCRAPE_TS.replace(":", "-").replace(".", "-")
    fname = f"tgs_events_{start_event}_{end_event}_{timestamp}.csv"
    path = os.path.join(output_dir, fname)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    print(f"\n✅ OUTPUT: {path}")


# -----------------------------
# ENTRYPOINT
# -----------------------------


def main():
    """Main entry point"""
    global SCRAPE_TS, SCRAPE_RUN_ID, U_FORMAT_BEFORE_CUTOVER

    # Generate scrape run identifiers
    SCRAPE_TS = datetime.now(timezone.utc).isoformat()
    SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"

    config = resolve_config()
    U_FORMAT_BEFORE_CUTOVER = config["u_format_before_cutover"]
    records = []

    start_event = config["start_event"]
    end_event = config["end_event"]
    max_workers = config.get("max_workers", 8)
    total_events = end_event - start_event + 1

    print("🚀 TGS API Scraper (PARALLEL MODE)")
    print(f"📅 Event range: {start_event} - {end_event} ({total_events} events)")
    print(f"🔄 Max parallel workers: {max_workers}")
    if U_FORMAT_BEFORE_CUTOVER:
        print(f"⚠️  Taking U-age labels at face value for events before {U_FORMAT_CUTOVER_DATE}")
    print(f"🆔 Scrape run ID: {SCRAPE_RUN_ID}")

    # Track overall timing
    scrape_start = time.time()

    # Scrape each event in range
    for i, event_id in enumerate(range(start_event, end_event + 1), 1):
        scrape_event(event_id, config, records)

        # Progress update every 10 events
        if i % 10 == 0:
            elapsed = time.time() - scrape_start
            events_per_min = (i / elapsed) * 60
            remaining_events = total_events - i
            eta_min = remaining_events / events_per_min if events_per_min > 0 else 0
            print(
                f"\n📊 Progress: {i}/{total_events} events ({i / total_events * 100:.0f}%) | "
                f"{len(records) // 2} games | {events_per_min:.1f} events/min | ETA: {eta_min:.1f} min"
            )

        time.sleep(0.3)  # Reduced delay between events (was 0.5)

    scrape_duration = time.time() - scrape_start

    # Validate records (if any)
    if records:
        validate_records(records)

    # Always write output (even if 0 records) so downstream workflow steps can find the CSV
    # This prevents the "Could not find scraped CSV file" error in GitHub Actions
    if not config["dry_run"]:
        write_output(records, config["output_dir"], start_event, end_event)
        if not records:
            print("⚠️  No games scraped — empty CSV written (headers only)")
    else:
        print(f"\n🔍 DRY RUN — {len(records)} records validated (not written)")

    # Exit early with summary if no records
    if not records:
        print(f"\n{'=' * 60}")
        print("⚠️  SCRAPE COMPLETE — NO GAMES FOUND")
        print(f"{'=' * 60}")
        print(f"  📅 Events scraped: {total_events}")
        print(f"  ⏱️  Total time: {scrape_duration:.1f}s")
        print("  💡 Possible reasons: no active flights, all divisions outside U10-U19,")
        print("     all games are future-dated, or event IDs don't exist")
        print(f"{'=' * 60}")
        return

    # Final summary
    games_count = len(records) // 2  # Each game has home + away records
    print(f"\n{'=' * 60}")
    print("✅ SCRAPE COMPLETE")
    print(f"{'=' * 60}")
    print(f"  📊 Total records: {len(records)} ({games_count} games × 2 perspectives)")
    print(f"  📅 Events scraped: {total_events}")
    print(f"  ⏱️  Total time: {scrape_duration:.1f}s ({scrape_duration / 60:.1f} min)")
    print(
        f"  ⚡ Rate: {total_events / scrape_duration * 60:.1f} events/min, "
        f"{games_count / scrape_duration:.1f} games/sec"
    )
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
