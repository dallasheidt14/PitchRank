#!/usr/bin/env python3
"""
Scrape WA Youth Soccer game results from Sports Affinity (sctour.sportsaffinity.com).

Targets the 25-26 Regional Club League (RCL) and other WA leagues hosted on
the Affinity platform.  Public schedule pages are HTML — no login needed.

Usage:
    python scripts/scrape_affinity_wa_tournament.py \
        --age u12 --gender male --days-back 7 --output data/raw/affinity_wa/out.csv
"""
import argparse
import csv
import hashlib
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

sys.path.append(str(Path(__file__).parent.parent))
from src.utils.team_utils import calculate_age_group_from_birth_year

# ── Known WA tournaments / leagues on Affinity ────────────────────────────────

TOURNAMENTS = [
    {
        "name": "25-26 Regional Club League",
        "tournament_guid": "535DB887-CE7E-43DB-90BC-55F7D6349BF9",
        "base_url": "https://wys-25-26rcl.sportsaffinity.com",
    },
]

FALLBACK_BASE = "https://washingtonyouthsoccer.sportsaffinity.com"

# ── CSV schema (must match import_games_enhanced expectations) ─────────────────

REQUIRED_COLUMNS = [
    "provider", "scrape_run_id", "event_id", "event_name",
    "schedule_id", "age_year", "age_group", "gender",
    "team_id", "team_id_source", "team_name", "club_name",
    "opponent_id", "opponent_id_source", "opponent_name", "opponent_club_name",
    "state", "state_code", "game_date", "game_time",
    "home_away", "goals_for", "goals_against", "result",
    "venue", "source_url", "scraped_at",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SCRAPE_TS = datetime.now(timezone.utc).isoformat()
SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _team_hash(team_name: str) -> str:
    """Deterministic provider-side team ID."""
    return f"affinity_wa:{hashlib.md5(team_name.lower().strip().encode()).hexdigest()[:12]}"


def _parse_date_header(text: str) -> Optional[datetime]:
    """Parse 'Bracket - Saturday,  March 14, 2026' into a datetime."""
    m = re.search(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
        r",\s+(\w+ \d{1,2},\s*\d{4})",
        text,
    )
    if m:
        try:
            return datetime.strptime(m.group(1).strip(), "%B %d, %Y")
        except ValueError:
            pass
    return None


def _compute_result(gf: Optional[int], ga: Optional[int]) -> str:
    if gf is None or ga is None:
        return "U"
    if gf > ga:
        return "W"
    if gf < ga:
        return "L"
    return "D"


def _extract_age_gender_from_division(div_name: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Parse 'Boys Under 12 Div 1 (2014)' → (gender='Male', age_u=12, birth_year=2014).
    Also handles 'Spring Boys U10 North (2016/17)'.
    """
    gender = None
    if re.search(r"\bBoys?\b", div_name, re.I):
        gender = "Male"
    elif re.search(r"\bGirls?\b", div_name, re.I):
        gender = "Female"

    age_u = None
    m = re.search(r"Under\s*(\d{1,2})", div_name, re.I)
    if m:
        age_u = int(m.group(1))
    else:
        m = re.search(r"\bU(\d{1,2})\b", div_name, re.I)
        if m:
            age_u = int(m.group(1))

    birth_year = None
    m = re.search(r"\((\d{4})", div_name)
    if m:
        birth_year = int(m.group(1))

    return gender, age_u, birth_year


def _age_label_to_int(label: str) -> int:
    """'u12' → 12, 'U14' → 14."""
    return int(re.sub(r"[^0-9]", "", label))


def _gender_label_to_canonical(label: str) -> str:
    """'male' → 'Male', 'female' → 'Female'."""
    return "Male" if label.lower() in ("male", "boys", "boy", "b", "m") else "Female"


def _age_u_to_birth_year(age_u: int) -> int:
    """Derive birth year from U-age. Season year rolls over Aug 1."""
    from src.utils.team_utils import CURRENT_YEAR
    return CURRENT_YEAR - age_u + 1


# ── Network ────────────────────────────────────────────────────────────────────

def _fetch(url: str, retries: int = 3) -> Optional[str]:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
            print(f"  HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  Request error (attempt {attempt + 1}): {e}")
        if attempt < retries - 1:
            time.sleep(1 + attempt)
    return None


# ── Stage 1: Discover flights from the accepted-list page ─────────────────────

def discover_flights(
    tournament: Dict, target_age: int, target_gender: str
) -> List[Dict]:
    """Return list of {flight_guid, division_name, birth_year, age_u, gender}.

    The accepted_list page has Boys/Girls tabs.  The default view only shows
    one gender, so we fetch the appropriate tab directly via ``&show=boys``
    or ``&show=girls``.

    Each flight is a table row where:
      - The first cell holds the division name ("Boys Under 12 Div 1 (2014)")
      - A later cell holds a "Schedule & Results" link with the flightguid
    """
    base = tournament["base_url"]
    tguid = tournament["tournament_guid"]
    show = "boys" if target_gender == "Male" else "girls"
    url = (
        f"{base}/tour/public/info/accepted_list.asp"
        f"?sessionguid=&tournamentguid={tguid}&show={show}"
    )
    html = _fetch(url)
    if not html:
        print(f"  Could not fetch accepted list for {tournament['name']}")
        return []

    soup = BeautifulSoup(html, "lxml")
    flights: List[Dict] = []
    seen_guids: set = set()

    for row in soup.find_all("tr"):
        schedule_link = row.find("a", href=re.compile(r"schedule_results2\.asp", re.I))
        if not schedule_link:
            continue
        href = schedule_link["href"]
        fg_match = re.search(r"flightguid=([0-9A-Fa-f-]{36})", href, re.I)
        if not fg_match:
            continue
        flight_guid = fg_match.group(1)
        if flight_guid in seen_guids:
            continue
        seen_guids.add(flight_guid)

        first_cell = row.find("td")
        if not first_cell:
            continue
        div_text = first_cell.get_text(strip=True)
        if not div_text:
            continue

        gender, age_u, birth_year = _extract_age_gender_from_division(div_text)

        if gender is None:
            gender = target_gender
        if age_u is None:
            continue
        if age_u != target_age or gender != target_gender:
            continue

        if birth_year is None:
            birth_year = _age_u_to_birth_year(age_u)

        flights.append({
            "flight_guid": flight_guid,
            "division_name": div_text,
            "birth_year": birth_year,
            "age_u": age_u,
            "gender": gender,
        })

    return flights


# ── Stage 2: Scrape games from a single flight ────────────────────────────────

def scrape_flight_games(
    tournament: Dict,
    flight: Dict,
    min_date: datetime,
    max_date: datetime,
) -> List[Dict]:
    """Fetch schedule_results2 page and extract played games within date window."""
    base = tournament["base_url"]
    tguid = tournament["tournament_guid"]
    fguid = flight["flight_guid"]
    url = (
        f"{base}/tour/public/info/schedule_results2.asp"
        f"?sessionguid=&flightguid={fguid}&tournamentguid={tguid}"
    )
    html = _fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    records: List[Dict] = []

    current_date: Optional[datetime] = None

    for element in soup.find_all(["center", "table"]):
        if element.name == "center":
            parsed = _parse_date_header(element.get_text())
            if parsed:
                current_date = parsed
            continue

        if element.name != "table" or current_date is None:
            continue

        if current_date < min_date or current_date > max_date:
            continue

        rows = element.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
            cell_text = [c.get_text(strip=True) for c in cells]

            game_id_str = cell_text[0]
            if not game_id_str.isdigit():
                continue

            venue = cell_text[1]
            game_time = cell_text[2]
            home_name = cell_text[5]
            home_score_str = cell_text[6]
            away_name = cell_text[8]
            away_score_str = cell_text[9] if len(cell_text) > 9 else ""

            if not home_score_str.strip() or not away_score_str.strip():
                continue
            if not home_score_str.isdigit() or not away_score_str.isdigit():
                continue

            home_score = int(home_score_str)
            away_score = int(away_score_str)
            game_date_str = current_date.strftime("%Y-%m-%d")

            division_name = flight["division_name"]
            birth_year = flight.get("birth_year")
            age_group = ""
            if birth_year:
                ag = calculate_age_group_from_birth_year(birth_year)
                if ag:
                    age_group = ag.lower()

            gender_display = "Boys" if flight["gender"] == "Male" else "Girls"
            source_url = url

            base_record = {
                "provider": "affinity_wa",
                "scrape_run_id": SCRAPE_RUN_ID,
                "event_id": tguid,
                "event_name": f"{tournament['name']} - {division_name}",
                "schedule_id": game_id_str,
                "age_year": birth_year or "",
                "age_group": age_group,
                "gender": gender_display,
                "state": "Washington",
                "state_code": "WA",
                "game_date": game_date_str,
                "game_time": game_time if game_time != "--" else "",
                "venue": venue if venue != "TBD" else "",
                "source_url": source_url,
                "scraped_at": SCRAPE_TS,
            }

            home_record = {
                **base_record,
                "team_id": _team_hash(home_name),
                "team_id_source": _team_hash(home_name),
                "team_name": home_name,
                "club_name": "",
                "opponent_id": _team_hash(away_name),
                "opponent_id_source": _team_hash(away_name),
                "opponent_name": away_name,
                "opponent_club_name": "",
                "home_away": "H",
                "goals_for": home_score,
                "goals_against": away_score,
                "result": _compute_result(home_score, away_score),
            }
            away_record = {
                **base_record,
                "team_id": _team_hash(away_name),
                "team_id_source": _team_hash(away_name),
                "team_name": away_name,
                "club_name": "",
                "opponent_id": _team_hash(home_name),
                "opponent_id_source": _team_hash(home_name),
                "opponent_name": home_name,
                "opponent_club_name": "",
                "home_away": "A",
                "goals_for": away_score,
                "goals_against": home_score,
                "result": _compute_result(away_score, home_score),
            }
            records.append(home_record)
            records.append(away_record)

    return records


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Affinity WA game scraper")
    parser.add_argument("--age", required=True, help="Age group, e.g. u12")
    parser.add_argument("--gender", required=True, help="male or female")
    parser.add_argument("--days-back", type=int, default=7, help="Days to look back")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    target_age = _age_label_to_int(args.age)
    target_gender = _gender_label_to_canonical(args.gender)
    days_back = args.days_back
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    min_date = now - timedelta(days=days_back)
    max_date = now

    print(f"Affinity WA Scraper")
    print(f"  Age: U{target_age}  Gender: {target_gender}")
    print(f"  Window: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
    print(f"  Run ID: {SCRAPE_RUN_ID}")

    all_records: List[Dict] = []

    for tournament in TOURNAMENTS:
        print(f"\n  Tournament: {tournament['name']}")
        flights = discover_flights(tournament, target_age, target_gender)
        print(f"  Matched flights: {len(flights)}")

        for flight in flights:
            print(f"    {flight['division_name']} ...", end=" ", flush=True)
            records = scrape_flight_games(tournament, flight, min_date, max_date)
            games_count = len(records) // 2
            print(f"{games_count} games")
            all_records.extend(records)
            time.sleep(0.5)

    if not all_records:
        print(f"\nNo games found for U{target_age} {target_gender} in last {days_back} days.")
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(all_records)

    games_total = len(all_records) // 2
    print(f"\nDone: {games_total} games ({len(all_records)} rows) -> {output_path}")


if __name__ == "__main__":
    main()
