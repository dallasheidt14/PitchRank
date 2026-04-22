import argparse
import csv
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.utils.team_utils import calculate_age_group_from_birth_year, extract_birth_year_from_name  # noqa: E402

API_BASE = "https://api.gb.playmetrics.com/external/lss"
OUTPUT_DIR = "data/raw/playmetrics"

# Global scrape identifiers (set in main())
SCRAPE_TS = None
SCRAPE_RUN_ID = None

# governing_body_id → 2-letter state code.
# Add entries here as PlayMetrics leagues are onboarded.
GB_STATE_MAP: Dict[int, str] = {
    1014: "WI",
}

# state_code → full state name (for the `state` CSV column).
STATE_CODE_TO_NAME: Dict[str, str] = {
    "WI": "Wisconsin",
}

# state_code → IANA timezone for local-date conversion of ``start_datetime``
# (which is UTC). Without this, a 9pm CT kickoff rolls past midnight UTC and
# the naive [:10] slice returns the wrong calendar date.
STATE_CODE_TO_TIMEZONE: Dict[str, str] = {
    "WI": "America/Chicago",
}

# Canonical 27-column CSV (matches scripts/scrape_tgs_event.py REQUIRED_COLUMNS),
# plus `division_name` appended as column 28. The importer reads `division_name`
# into `games.division_name` when present.
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

# -----------------------------
# CONFIG LOADER
# -----------------------------


def _parse_league_url(url: str) -> Optional[Tuple[int, int, str]]:
    """Parse a PlayMetrics league URL into (governing_body_id, league_id, key).

    Expected shape:
        https://playmetricssports.com/g/leagues/{gb}-{league}-{key}/league_view.html
    """
    m = re.search(r"/leagues/(\d+)-(\d+)-([0-9a-fA-F]+)/", url)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3)


def resolve_config():
    """Load configuration with precedence: CLI > ENV > Defaults"""
    parser = argparse.ArgumentParser(description="PlayMetrics League Scraper")

    parser.add_argument("--league-url", type=str, help="Full league URL (alternative to explicit IDs)")
    parser.add_argument("--governing-body-id", type=int, help="Governing body ID (e.g. 1014 for WI)")
    parser.add_argument("--league-id", type=int, help="League ID")
    parser.add_argument("--key", type=str, help="League key token")
    parser.add_argument("--output-dir", type=str, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing output")

    args = parser.parse_args()

    # Resolve league identity: CLI --league-url > CLI explicit IDs > ENV --league-url
    league_url = args.league_url or os.getenv("PLAYMETRICS_LEAGUE_URL")
    gb_id = args.governing_body_id
    league_id = args.league_id
    key = args.key

    if league_url and not (gb_id and league_id and key):
        parsed = _parse_league_url(league_url)
        if not parsed:
            print(f"❌ Could not parse league URL: {league_url}")
            sys.exit(1)
        gb_id, league_id, key = parsed

    if not (gb_id and league_id and key):
        print("❌ Must provide --league-url OR all three of --governing-body-id/--league-id/--key")
        sys.exit(1)

    if gb_id not in GB_STATE_MAP:
        raise ValueError(
            f"Unknown PlayMetrics governing_body_id {gb_id}. "
            f"Add an entry to GB_STATE_MAP in scripts/scrape_playmetrics_league.py."
        )

    output_dir = args.output_dir or os.getenv("PLAYMETRICS_OUTPUT_DIR", OUTPUT_DIR)
    delay_sec = float(os.getenv("PLAYMETRICS_DELAY_SEC", "0.3"))

    return {
        "governing_body_id": gb_id,
        "league_id": league_id,
        "key": key,
        "output_dir": output_dir,
        "dry_run": args.dry_run,
        "delay_sec": delay_sec,
    }


# -----------------------------
# HELPER FUNCTIONS
# -----------------------------


def compute_result(goals_for: Optional[int], goals_against: Optional[int]) -> str:
    """Compute result from a team's perspective: W / L / D / U"""
    if goals_for is None or goals_against is None:
        return "U"
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


def map_min_age_to_age_group(min_age: Optional[int]) -> Optional[str]:
    """Map PlayMetrics division.min_age to PitchRank age_group.

    PitchRank slots dual-age divisions to the younger cohort; U18 merges into U19
    (config/settings.py:86-96 _BIRTH_YEARS skips 18). This is a *fallback* only —
    ``derive_team_age_group`` is preferred because PlayMetrics reports min_age
    as the play-up gate (e.g. ``min_age=10`` on an "11U A" division that admits
    10-year-olds), which would incorrectly bucket an 11U team into u10.
    """
    if min_age is None:
        return None
    try:
        age = int(min_age)
    except (ValueError, TypeError):
        return None
    if 10 <= age <= 17:
        return f"u{age}"
    if age in (18, 19):
        return "u19"
    return None


# "U11", "u-11", "11U", "11u" — PitchRank tracks u10-u17 and u19 (u18 merges into u19).
_TEAM_U_AGE_RE = re.compile(r"\b(?:[Uu]-?(\d{1,2})|(\d{1,2})[Uu])\b")


def derive_team_age_group(team_name: str, fallback_age_group: Optional[str]) -> Optional[str]:
    """Derive age_group from the team's own name; fall back to the division value.

    Priority:
      1. 4-digit birth year (``2015`` → u11 for season 2025).
      2. ``U11`` / ``11U`` token.
      3. Division-level ``min_age`` mapping (``fallback_age_group``).

    u18 is always remapped to u19 to match PitchRank's age cohorts.
    """
    if team_name:
        birth_year = extract_birth_year_from_name(team_name)
        if birth_year:
            ag = calculate_age_group_from_birth_year(birth_year)
            if ag:
                ag = ag.lower()
                return "u19" if ag == "u18" else ag

        m = _TEAM_U_AGE_RE.search(team_name)
        if m:
            num = int(m.group(1) or m.group(2))
            if 10 <= num <= 17:
                return f"u{num}"
            if num in (18, 19):
                return "u19"
    return fallback_age_group


def parse_int_or_none(v) -> Optional[int]:
    """Parse a game score. Only whole integers in 0..50 are accepted; else None.

    Filters malformed scores (``"2.5"``, ``"-1"``, ``"999"``) at scrape time so
    they don't surface as bogus W/L/D rows. Matches the importer's validation
    window (``src/utils/enhanced_validators.py``: 0..50).
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


def parse_utc_to_local_date(iso_utc: str, state_code: str) -> str:
    """Convert a UTC ISO timestamp to ``YYYY-MM-DD`` in the state's local zone.

    Falls back to a UTC slice if the timestamp is unparseable or the state has
    no tz mapping — the calendar-date error for unmapped states is no worse
    than what we had before this helper existed.
    """
    if not iso_utc:
        return ""
    tz_name = STATE_CODE_TO_TIMEZONE.get(state_code)
    if not tz_name:
        return iso_utc[:10]
    try:
        dt_iso = iso_utc.rstrip("Z")
        dt = datetime.fromisoformat(dt_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_utc[:10]


# -----------------------------
# API FUNCTIONS
# -----------------------------


def _post(endpoint: str, body: Dict, retries: int = 3, timeout: int = 30) -> Dict:
    """POST to a PlayMetrics LSS endpoint with exponential-backoff retry.

    Raises ``RuntimeError`` on exhausted retries so the workflow aborts loudly
    instead of silently emitting an incomplete CSV (a transient 5xx dropping a
    whole division is worse than failing the run and retrying next cycle).
    """
    url = f"{API_BASE}/{endpoint}"
    headers = {"content-type": "text/plain;charset=UTF-8"}
    payload = json.dumps(body)
    last_error: Optional[str] = None

    for attempt in range(retries):
        try:
            r = requests.post(url, data=payload, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last_error = f"HTTP {r.status_code}"
            print(f"  ⚠️ {last_error} for {endpoint} (attempt {attempt + 1}/{retries})")
        except requests.RequestException as e:
            last_error = str(e)
            print(f"  ⚠️ Request error for {endpoint} (attempt {attempt + 1}/{retries}): {e}")
        if attempt < retries - 1:
            time.sleep(1 * (attempt + 1))
    raise RuntimeError(f"PlayMetrics API call failed after {retries} attempts: {endpoint} ({last_error})")


def get_league(gb_id: int, league_id: int, key: str) -> Dict:
    """Fetch league metadata (name, dates, divisions)."""
    body = {"governing_body_id": gb_id, "league_id": league_id, "key": key}
    return _post("league", body)


def get_division(gb_id: int, league_id: int, key: str, division_id: int) -> Dict:
    """Fetch a single division (teams, schedule, sport_configuration, standings)."""
    body = {
        "governing_body_id": gb_id,
        "league_id": league_id,
        "key": key,
        "division_id": division_id,
    }
    return _post("division", body)


# -----------------------------
# NORMALIZATION
# -----------------------------


def _build_source_url(gb_id: int, league_id: int, key: str, division_id: int) -> str:
    return (
        f"https://playmetricssports.com/g/leagues/{gb_id}-{league_id}-{key}/divisions/{division_id}/division_view.html"
    )


def _build_venue(field: Optional[Dict]) -> str:
    """Join field.name + field.address into a single venue string."""
    if not field:
        return ""
    name = str(field.get("name") or "").strip()
    address = str(field.get("address") or "").strip()
    return f"{name} {address}".strip()


def normalize_game(
    game: Dict,
    team_lookup: Dict[str, Dict],
    division: Dict,
    league_name: str,
    gb_id: int,
    league_id: int,
    key: str,
    age_group: str,
    gender: str,
    state_code: str,
) -> Optional[List[Dict]]:
    """Map a PlayMetrics schedule game to canonical CSV rows (home + away perspective).

    Returns a 2-element list (home row, away row) or None if the game should be skipped.
    The ``status != "Played"`` and orphan-team-id gates live in the caller
    (``scrape_division``) so it can increment per-reason counters; this helper
    only handles normalization once those gates have passed.
    """
    home_key = str(game.get("home_team_id"))
    away_key = str(game.get("away_team_id"))
    home_entry = team_lookup[home_key]
    away_entry = team_lookup[away_key]

    home_score = parse_int_or_none(game.get("home_team_score"))
    away_score = parse_int_or_none(game.get("away_team_score"))

    start_dt_raw = str(game.get("start_datetime") or "").strip()
    game_date = parse_utc_to_local_date(start_dt_raw, state_code)
    game_time = str(game.get("time") or "").strip()

    division_id = division.get("id")
    division_name = str(division.get("name") or "").strip()
    source_url = _build_source_url(gb_id, league_id, key, division_id) if division_id is not None else ""
    venue = _build_venue(game.get("field"))
    state_name = STATE_CODE_TO_NAME.get(state_code, "")

    home_team_name = home_entry.get("team_name", "")
    away_team_name = away_entry.get("team_name", "")
    home_age_group = derive_team_age_group(home_team_name, age_group)
    away_age_group = derive_team_age_group(away_team_name, age_group)

    base = {
        "provider": "playmetrics",
        "scrape_run_id": SCRAPE_RUN_ID,
        "event_id": "",
        "event_name": league_name,
        "schedule_id": str(game.get("id") or ""),
        "age_year": "",
        "gender": gender,
        "state": state_name,
        "state_code": state_code,
        "game_date": game_date,
        "game_time": game_time,
        "venue": venue,
        "source_url": source_url,
        "scraped_at": SCRAPE_TS,
        "division_name": division_name,
    }

    home_row = {
        **base,
        "age_group": home_age_group,
        "team_id": home_key,
        "team_id_source": home_key,
        "team_name": home_team_name,
        "club_name": home_entry.get("club_name", ""),
        "opponent_id": away_key,
        "opponent_id_source": away_key,
        "opponent_name": away_team_name,
        "opponent_club_name": away_entry.get("club_name", ""),
        "home_away": "H",
        "goals_for": home_score if home_score is not None else "",
        "goals_against": away_score if away_score is not None else "",
        "result": compute_result(home_score, away_score),
    }
    away_row = {
        **base,
        "age_group": away_age_group,
        "team_id": away_key,
        "team_id_source": away_key,
        "team_name": away_team_name,
        "club_name": away_entry.get("club_name", ""),
        "opponent_id": home_key,
        "opponent_id_source": home_key,
        "opponent_name": home_team_name,
        "opponent_club_name": home_entry.get("club_name", ""),
        "home_away": "A",
        "goals_for": away_score if away_score is not None else "",
        "goals_against": home_score if home_score is not None else "",
        "result": compute_result(away_score, home_score),
    }
    return [home_row, away_row]


# -----------------------------
# SCRAPER CORE
# -----------------------------


def scrape_division(
    division: Dict,
    league_name: str,
    config: Dict,
) -> Tuple[List[Dict], Dict[str, int]]:
    """Scrape a single division.

    Returns ``(records, counts)``. ``counts["futsal"]`` is ``1`` when the
    division was skipped as futsal, ``0`` otherwise; the caller uses it to
    bump the league-level ``futsal_dropped`` tally.
    """
    counts = {
        "games_emitted": 0,
        "skipped_non_played": 0,
        "skipped_forfeit": 0,
        "skipped_other_status": 0,
        "skipped_orphan": 0,
        "futsal": 0,
    }

    division_id = division.get("id")
    division_name = str(division.get("name") or "").strip()
    if division_id is None:
        print(f"  ⚠️ Division missing id: {division_name}")
        return [], counts

    age_group = map_min_age_to_age_group(division.get("min_age"))
    if not age_group:
        print(f"  ⏭️  {division_name}: skipping (min_age={division.get('min_age')} not in tracked range)")
        return [], counts

    gender_raw = str(division.get("gender") or "").strip().upper()
    gender = "Male" if gender_raw == "M" else "Female"

    gb_id = config["governing_body_id"]
    league_id = config["league_id"]
    key = config["key"]
    state_code = GB_STATE_MAP[gb_id]

    div_data = get_division(gb_id, league_id, key, division_id)

    sport_config = div_data.get("sport_configuration")
    sport_name = ""
    if isinstance(sport_config, dict):
        sport_name = str(sport_config.get("name") or "").strip()
    if not sport_name:
        print(f"  ⚠️ {division_name}: sport_configuration missing or unnamed (not skipped)")
    elif "futsal" in sport_name.lower():
        print(f"  ⏭️  {division_name}: skipping (futsal)")
        counts["futsal"] = 1
        return [], counts

    teams = div_data.get("teams") or []
    schedule = div_data.get("schedule") or []

    team_lookup: Dict[str, Dict] = {}
    for entry in teams:
        team = entry.get("team") or {}
        club = entry.get("club") or {}
        team_id = team.get("id")
        if team_id is None:
            continue
        team_lookup[str(team_id)] = {
            "team_name": str(team.get("name") or "").strip(),
            "club_id": club.get("id"),
            "club_name": str(club.get("name") or "").strip(),
        }

    records: List[Dict] = []
    for game in schedule:
        status = str(game.get("status") or "").strip()
        if status != "Played":
            counts["skipped_non_played"] += 1
            if status.lower() == "forfeit":
                counts["skipped_forfeit"] += 1
            else:
                counts["skipped_other_status"] += 1
            continue

        home_id = game.get("home_team_id")
        away_id = game.get("away_team_id")
        if home_id is None or away_id is None or str(home_id) not in team_lookup or str(away_id) not in team_lookup:
            counts["skipped_orphan"] += 1
            print(f"  ⚠️ {division_name}: orphan game id={game.get('id')} home={home_id} away={away_id}")
            continue

        rows = normalize_game(
            game,
            team_lookup,
            division,
            league_name,
            gb_id,
            league_id,
            key,
            age_group,
            gender,
            state_code,
        )
        if rows:
            records.extend(rows)
            counts["games_emitted"] += 1

    print(
        f"  ✅ {division_name} ({age_group}, {gender}): {counts['games_emitted']} games "
        f"({counts['skipped_non_played']} non-played, {counts['skipped_orphan']} orphan)"
    )
    return records, counts


def scrape_league(config: Dict) -> Tuple[List[Dict], Dict]:
    """Scrape a full PlayMetrics league. Returns (records, summary)."""
    gb_id = config["governing_body_id"]
    league_id = config["league_id"]
    key = config["key"]

    summary = {
        "league_name": "",
        "division_total": 0,
        "division_processed": 0,
        "futsal_dropped": 0,
        "games_emitted": 0,
        "skipped_non_played": 0,
        "skipped_forfeit": 0,
        "skipped_other_status": 0,
        "skipped_orphan": 0,
    }

    league_data = get_league(gb_id, league_id, key)
    league_name = str(league_data.get("name") or f"League {league_id}").strip()
    divisions = league_data.get("divisions") or []
    summary["league_name"] = league_name
    summary["division_total"] = len(divisions)

    print(f"\n📌 LEAGUE: {league_name}")
    print(f"  Divisions: {len(divisions)}")

    all_records: List[Dict] = []
    for division in divisions:
        records, counts = scrape_division(division, league_name, config)
        # Pace regardless of outcome — futsal-classified divisions still issued
        # an API call, so they should be subject to the same rate-limit window.
        time.sleep(config["delay_sec"])
        if counts["futsal"]:
            summary["futsal_dropped"] += 1
            continue
        all_records.extend(records)
        summary["division_processed"] += 1
        summary["games_emitted"] += counts["games_emitted"]
        summary["skipped_non_played"] += counts["skipped_non_played"]
        summary["skipped_forfeit"] += counts["skipped_forfeit"]
        summary["skipped_other_status"] += counts["skipped_other_status"]
        summary["skipped_orphan"] += counts["skipped_orphan"]

    return all_records, summary


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


def write_output(records: List[Dict], config: Dict) -> Path:
    """Write records to CSV. Always writes header, even on 0 records."""
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = SCRAPE_TS.replace(":", "-").replace(".", "-")
    fname = f"playmetrics_{config['governing_body_id']}_{config['league_id']}_{config['key']}_{timestamp}.csv"
    path = output_dir / fname

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    print(f"\n✅ OUTPUT: {path}")
    return path


# -----------------------------
# ENTRYPOINT
# -----------------------------


def main():
    global SCRAPE_TS, SCRAPE_RUN_ID

    SCRAPE_TS = datetime.now(timezone.utc).isoformat()
    SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"

    config = resolve_config()

    print("🚀 PlayMetrics League Scraper")
    print(f"🏛️  Governing body: {config['governing_body_id']} ({GB_STATE_MAP[config['governing_body_id']]})")
    print(f"🆔 League: {config['league_id']}-{config['key']}")
    print(f"🆔 Scrape run ID: {SCRAPE_RUN_ID}")

    scrape_start = time.time()
    records, summary = scrape_league(config)
    scrape_duration = time.time() - scrape_start

    if records:
        validate_records(records)

    if not config["dry_run"]:
        write_output(records, config)
        if not records:
            print("⚠️  No games scraped — empty CSV written (headers only)")
    else:
        print(f"\n🔍 DRY RUN — {len(records)} rows validated (not written)")

    print(
        f"\n📊 Scraped {summary['games_emitted']} games across {summary['division_processed']} divisions; "
        f"{summary['skipped_non_played']} non-played games dropped "
        f"({summary['skipped_forfeit']} forfeits, {summary['skipped_other_status']} other statuses); "
        f"{summary['futsal_dropped']} futsal divisions skipped."
    )
    print(f"⏱️  Total time: {scrape_duration:.1f}s")


if __name__ == "__main__":
    main()
