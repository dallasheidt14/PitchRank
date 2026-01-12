import os
import re
import csv
import uuid
import time
import argparse
import hashlib
import requests
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
from src.utils.team_utils import calculate_age_group_from_birth_year

BASE = "https://api.athleteone.com/api"
OUTPUT_DIR = "data/raw/tgs"

# Global scrape identifiers (set in main())
SCRAPE_TS = None
SCRAPE_RUN_ID = None

REQUIRED_COLUMNS = [
    "provider",
    "scrape_run_id",
    "event_id",
    "event_name",
    "schedule_id",
    "age_year",
    "age_group",  # Calculated from age_year
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
    "scraped_at"
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
    
    args = parser.parse_args()
    
    # CLI > ENV > Default
    start_event = args.start_event or int(os.getenv("TGS_START_EVENT", "3900"))
    end_event = args.end_event or int(os.getenv("TGS_END_EVENT", "4000"))
    output_dir = args.output_dir or os.getenv("TGS_OUTPUT_DIR", OUTPUT_DIR)
    
    return {
        "start_event": start_event,
        "end_event": end_event,
        "output_dir": output_dir,
        "dry_run": args.dry_run
    }


# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def extract_year(division_name: str) -> Optional[int]:
    """Extract birth year from division name (e.g., 'B2012' -> 2012).

    Only returns years in the valid range for tracked age groups:
    - U10-U18 corresponds to birth years 2008-2016 (for 2025 season)
    """
    match = re.search(r'(\d{4})', division_name)
    if match:
        year = int(match.group(1))
        # Only accept birth years 2008-2016 (U18-U10 for 2025 season)
        if 2008 <= year <= 2016:
            return year
    return None


def extract_gender(division_name: str) -> Optional[str]:
    """Extract gender from division name (e.g., 'B2012' -> 'Boys', 'G2013' -> 'Girls')
    
    Returns normalized gender values that match validator expectations:
    - 'Boys' for B divisions
    - 'Girls' for G divisions
    """
    division_upper = division_name.upper()
    if division_upper.startswith('B'):
        return 'Boys'
    elif division_upper.startswith('G'):
        return 'Girls'
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
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
    """Get division info for a flight (age_year, gender)"""
    url = f"{BASE}/Event/get-flight-division-by-flightID/{flight_id}"
    headers = {
        "Origin": "https://public.totalglobalsports.com",
        "Referer": "https://public.totalglobalsports.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("data", {}) if isinstance(data, dict) else data
    except Exception as e:
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
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
    except Exception as e:
        pass
    return []


# Function moved above - get_games_for_flight now uses correct endpoint


# -----------------------------
# NORMALIZATION
# -----------------------------

def normalize_api_game(
    game: Dict,
    event_id: int,
    event_name: str,
    division: Dict,
    home_away: str,
    scrape_run_id: str,
    scrape_ts: str
) -> Dict:
    """Map API game data to canonical CSV schema"""
    division_id = division.get("divisionID")
    division_name = division.get("divisionName", "")
    
    # Extract age_year and gender from division name
    age_year = extract_year(division_name)
    gender = extract_gender(division_name)
    
    # Calculate age_group from age_year
    age_group = ""
    if age_year:
        try:
            birth_year = int(age_year)
            age_group_calculated = calculate_age_group_from_birth_year(birth_year)
            if age_group_calculated:
                age_group = age_group_calculated.lower()  # Normalize to lowercase (u12 instead of U12)
        except (ValueError, TypeError):
            pass  # Keep age_group empty if conversion fails
    
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
        "age_year": age_year,
        "age_group": age_group,  # Calculated from age_year
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
        "scraped_at": scrape_ts
    }


# -----------------------------
# SCRAPER CORE
# -----------------------------

def scrape_event(event_id: int, config: Dict, records: List[Dict]) -> None:
    """Scrape a single event using the correct API chain.

    Only includes games that have already been played (game_date <= today).
    Future scheduled games are skipped.
    """
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
    # Use get-event-schedule-or-standings to get the flight structure
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
    
    print(f"✅ Found {len(all_divisions)} divisions")
    
    # Step 2 & 3: For each flight, get division info and games
    total_flights = 0
    for division in all_divisions:
        division_name = division.get("divisionName", "")
        flight_list = division.get("flightList", [])
        
        for flight in flight_list:
            if not flight.get("hasActiveSchedule", False):
                continue
            
            flight_id = flight.get("flightID")
            flight_name = flight.get("flightName", "")
            total_flights += 1
            
            # Step 2a: Get division info (age_year, gender)
            flight_division = get_flight_division(flight_id)
            if not flight_division:
                print(f"  ⚠️ Could not get division info for flight {flight_name} ({flight_id})")
                continue
            
            division_name_from_api = flight_division.get("divisionName", division_name)
            
            # Step 2b: Get games for this flight (THE MONEY ENDPOINT)
            games = get_games_for_flight(event_id, flight_id)
            if not games:
                print(f"  ⚠️ No games found for {division_name_from_api} - {flight_name} ({flight_id})")
                continue
            
            # Create division info for normalization
            division_info = {
                "divisionID": flight_id,  # Use flightID as schedule_id
                "divisionName": division_name_from_api  # Use division name for age/gender extraction
            }

            # Check if this division has a valid age group (U10-U18 / birth years 2008-2016)
            age_year = extract_year(division_name_from_api)
            if not age_year:
                print(f"  ⏭️  Skipping {division_name_from_api} - {flight_name}: age group not in U10-U18 range")
                continue

            # Step 3: Generate records for each game (both home and away perspectives)
            # Filter out future games - we only want games that have already been played
            games_added = 0
            games_skipped_future = 0

            for game in games:
                # Home perspective
                home_record = normalize_api_game(
                    game, event_id, event_name, division_info, "H",
                    SCRAPE_RUN_ID, SCRAPE_TS
                )

                # Skip future games (haven't been played yet)
                if is_future_game(home_record.get("game_date", "")):
                    games_skipped_future += 1
                    continue

                records.append(home_record)

                # Away perspective (same game, so we know it's not future)
                away_record = normalize_api_game(
                    game, event_id, event_name, division_info, "A",
                    SCRAPE_RUN_ID, SCRAPE_TS
                )
                records.append(away_record)
                games_added += 1

            # Log results for this flight
            if games_skipped_future > 0:
                print(f"  ✅ {division_name_from_api} - {flight_name}: {games_added} games added, {games_skipped_future} future games skipped")
            else:
                print(f"  ✅ {division_name_from_api} - {flight_name}: {games_added} games")

            # Small delay between flights
            time.sleep(0.3)

    print(f"✅ Processed {total_flights} flights")


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
    global SCRAPE_TS, SCRAPE_RUN_ID
    
    # Generate scrape run identifiers
    SCRAPE_TS = datetime.now(timezone.utc).isoformat()
    SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"
    
    config = resolve_config()
    records = []
    
    start_event = config["start_event"]
    end_event = config["end_event"]
    
    print(f"🚀 TGS API Scraper")
    print(f"📅 Event range: {start_event} - {end_event}")
    print(f"🆔 Scrape run ID: {SCRAPE_RUN_ID}")
    
    # Scrape each event in range
    for event_id in range(start_event, end_event + 1):
        scrape_event(event_id, config, records)
        time.sleep(0.5)  # Delay between events
    
    if not records:
        print("❌ No games scraped")
        return
    
    # Validate records
    validate_records(records)
    
    # Write output (unless dry-run)
    if not config["dry_run"]:
        write_output(records, config["output_dir"], start_event, end_event)
    else:
        print(f"\n🔍 DRY RUN — {len(records)} records validated (not written)")
    
    print(f"\n✅ SCRAPE COMPLETE — {len(records)} total records")


if __name__ == "__main__":
    main()
