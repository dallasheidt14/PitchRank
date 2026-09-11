#!/usr/bin/env python3
"""
Scrape Oregon Youth Soccer game results from Sports Affinity (oysa.sportsaffinity.com).

Targets the OYSA Fall League (RCL/SCL) and other OR leagues hosted on the
Affinity platform.  Public schedule pages are HTML — no login needed.

Two things differ from the WA sibling and drive the code below:

- OYSA labels divisions ``BU13``/``GU14`` with no birth-year parenthetical, and
  its U-number is one BELOW PitchRank's for the same players: ``BU13`` fields
  2013-born teams, which this project calls u14.  The label is therefore read
  as a birth year (``season - u_number``) and never as a cohort.
- Unplayed fixtures are kept.  The importer inserts a future-dated row whose
  scores are both empty as a scheduled game and backfills the score on a later
  scrape (``EnhancedETLPipeline._should_accept_for_insert``).

Usage:
    python scripts/scrape_affinity_or_tournament.py \
        --age u12 --gender male --days-back 7 --days-forward 30 \
        --output data/raw/affinity_or/out.csv
"""

import argparse
import csv
import hashlib
import re
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).parent.parent))
from src.utils.team_utils import calculate_age_group_from_birth_year

# ── Known OR tournaments / leagues on Affinity ────────────────────────────────

TOURNAMENTS = [
    {
        "name": "2026 OYSA Fall League",
        "tournament_guid": "765ABB82-7406-4A4D-9446-7EA366142522",
        "base_url": "https://oysa.sportsaffinity.com",
    },
]

# ── CSV schema (must match import_games_enhanced expectations) ─────────────────

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
    return f"affinity_or:{hashlib.md5(team_name.lower().strip().encode()).hexdigest()[:12]}"


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


def _division_birth_year(age_u: int, season_year: Optional[int] = None) -> int:
    """Read an OYSA division's U-number as a birth year.

    OYSA numbers a division by ``season - birth_year``; PitchRank numbers the
    same cohort ``season - birth_year + 1``.  BU13 is therefore 2013-born and
    lands on the u14 board — taking the 13 as a cohort files every Oregon team
    a full year low.  Verified against the 2026 Fall League on 2026-09-11:
    BU11/BU12/BU13/BU14 field 15B/14B/13B/12B teams respectively.
    """
    if season_year is None:
        from src.utils.team_utils import CURRENT_YEAR

        season_year = CURRENT_YEAR
    return season_year - age_u


def _extract_age_gender_from_division(div_name: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Parse 'BU13 RCL North 2' → (gender='Male', age_u=13).
    Also handles the spelled-out Affinity form, 'Boys Under 12 Div 1'.

    ``age_u`` is the provider's own number, not a PitchRank cohort — see
    :func:`_division_birth_year`.
    """
    compact = re.match(r"^\s*([BG])U(\d{1,2})\b", div_name, re.I)
    if compact:
        gender = "Male" if compact.group(1).upper() == "B" else "Female"
        return gender, int(compact.group(2))

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

    return gender, age_u


def _roster_birth_year(team_names: List[str]) -> Optional[int]:
    """Most common birth year named by a flight's teams, e.g. 'LFC 13B Red' → 2013.

    Used only to veto a division label, never to replace it: a provider's
    cohort is safe to disagree with and unsafe to write from.  Returns None
    when fewer than three teams carry a year token, which is too thin to
    overrule anything.
    """
    years = Counter()
    for name in team_names:
        for token in re.findall(r"\b(\d{2})[BG]\b", name, re.I):
            years[2000 + int(token)] += 1

    if not years or sum(years.values()) < 3:
        return None
    return years.most_common(1)[0][0]


def _age_label_to_int(label: str) -> int:
    """'u12' → 12, 'U14' → 14."""
    return int(re.sub(r"[^0-9]", "", label))


def _gender_label_to_canonical(label: str) -> str:
    """'male' → 'Male', 'female' → 'Female'."""
    return "Male" if label.lower() in ("male", "boys", "boy", "b", "m") else "Female"


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


def discover_flights(tournament: Dict, target_age: int, target_gender: str) -> List[Dict]:
    """Return list of {flight_guid, division_name, birth_year, age_u, gender}.

    ``target_age`` is a PitchRank cohort (u13), so it is compared against the
    cohort the division's birth year resolves to, not against OYSA's number.

    The accepted_list page has Boys/Girls tabs.  The default view only shows
    one gender, so we fetch the appropriate tab directly via ``&show=boys``
    or ``&show=girls``.

    Each flight is a table row where:
      - The first cell holds the division name ("BU13 RCL North 2")
      - A later cell holds a "Schedule & Results" link with the flightguid
    """
    base = tournament["base_url"]
    tguid = tournament["tournament_guid"]
    show = "boys" if target_gender == "Male" else "girls"
    url = f"{base}/tour/public/info/accepted_list.asp?sessionguid=&tournamentguid={tguid}&show={show}"
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

        gender, age_u = _extract_age_gender_from_division(div_text)

        if gender is None:
            gender = target_gender
        if age_u is None:
            continue
        if gender != target_gender:
            continue

        birth_year = _division_birth_year(age_u)
        age_group = calculate_age_group_from_birth_year(birth_year)
        if not age_group or _age_label_to_int(age_group) != target_age:
            continue

        flights.append(
            {
                "flight_guid": flight_guid,
                "division_name": div_text,
                "birth_year": birth_year,
                "age_u": age_u,
                "gender": gender,
            }
        )

    return flights


# ── Stage 2: Scrape games from a single flight ────────────────────────────────


def scrape_flight_games(
    tournament: Dict,
    flight: Dict,
    min_date: datetime,
    max_date: datetime,
) -> List[Dict]:
    """Fetch schedule_results2 page and extract games within the date window.

    Unplayed fixtures are emitted with both scores empty; the importer keeps
    the future-dated ones as scheduled games.  Rows where only one score is
    present are dropped — the importer rejects that shape, so passing it on
    would only add noise.
    """
    base = tournament["base_url"]
    tguid = tournament["tournament_guid"]
    fguid = flight["flight_guid"]
    url = f"{base}/tour/public/info/schedule_results2.asp?sessionguid=&flightguid={fguid}&tournamentguid={tguid}"
    html = _fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    records: List[Dict] = []
    roster_names: List[str] = []

    current_date: Optional[datetime] = None

    for element in soup.find_all(["center", "table"]):
        if element.name == "center":
            parsed = _parse_date_header(element.get_text())
            if parsed:
                current_date = parsed
            continue

        if element.name != "table" or current_date is None:
            continue

        in_window = min_date <= current_date <= max_date

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

            roster_names.extend((home_name, away_name))

            if not in_window:
                continue

            home_blank = not home_score_str.strip()
            away_blank = not away_score_str.strip()
            if home_blank != away_blank:
                continue
            if home_blank:
                home_score: object = ""
                away_score: object = ""
                result_home = result_away = "U"
            else:
                if not home_score_str.isdigit() or not away_score_str.isdigit():
                    continue
                home_score = int(home_score_str)
                away_score = int(away_score_str)
                result_home = _compute_result(home_score, away_score)
                result_away = _compute_result(away_score, home_score)

            game_date_str = current_date.strftime("%Y-%m-%d")

            division_name = flight["division_name"]
            birth_year = flight.get("birth_year")
            age_group = ""
            if birth_year:
                ag = calculate_age_group_from_birth_year(birth_year)
                if ag:
                    age_group = ag.lower()

            gender_display = "Boys" if flight["gender"] == "Male" else "Girls"

            base_record = {
                "provider": "affinity_or",
                "scrape_run_id": SCRAPE_RUN_ID,
                "event_id": tguid,
                "event_name": f"{tournament['name']} - {division_name}",
                "schedule_id": game_id_str,
                "age_year": birth_year or "",
                "age_group": age_group,
                "gender": gender_display,
                "state": "Oregon",
                "state_code": "OR",
                "game_date": game_date_str,
                "game_time": game_time if game_time != "--" else "",
                "venue": venue if venue != "TBD" else "",
                "source_url": url,
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
                "result": result_home,
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
                "result": result_away,
            }
            records.append(home_record)
            records.append(away_record)

    roster_year = _roster_birth_year(roster_names)
    if roster_year is not None and roster_year != flight["birth_year"]:
        print(
            f"      SKIPPED: '{flight['division_name']}' reads as {flight['birth_year']} "
            f"but its teams are named {roster_year} — OYSA may have changed how it "
            f"numbers divisions; confirm before importing Oregon."
        )
        return []

    return records


# ── Main ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Affinity OR game scraper")
    parser.add_argument("--age", required=True, help="Age group, e.g. u12")
    parser.add_argument("--gender", required=True, help="male or female")
    parser.add_argument("--days-back", type=int, default=7, help="Days to look back")
    parser.add_argument(
        "--days-forward",
        type=int,
        default=0,
        help="Days to look ahead for unplayed fixtures (scheduled games)",
    )
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    target_age = _age_label_to_int(args.age)
    target_gender = _gender_label_to_canonical(args.gender)
    days_back = args.days_back
    days_forward = args.days_forward
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    min_date = now - timedelta(days=days_back)
    max_date = now + timedelta(days=days_forward)

    print("Affinity OR Scraper")
    print(f"  Age: U{target_age}  Gender: {target_gender}")
    print(f"  Window: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
    print(f"  Run ID: {SCRAPE_RUN_ID}")

    all_records: List[Dict] = []

    for tournament in TOURNAMENTS:
        print(f"\n  Tournament: {tournament['name']}")
        flights = discover_flights(tournament, target_age, target_gender)
        print(f"  Matched flights: {len(flights)}")
        print(f"FLIGHTS_MATCHED:{len(flights)}:{tournament['name']}")

        for flight in flights:
            print(f"    {flight['division_name']} ...", end=" ", flush=True)
            records = scrape_flight_games(tournament, flight, min_date, max_date)
            games_count = len(records) // 2
            print(f"{games_count} games")
            all_records.extend(records)
            time.sleep(0.5)

    if not all_records:
        print(f"\nNo games found for U{target_age} {target_gender} in the window.")
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(all_records)

    scheduled = sum(1 for r in all_records if r["goals_for"] == "") // 2
    games_total = len(all_records) // 2
    print(
        f"\nDone: {games_total} games ({len(all_records)} rows, "
        f"{scheduled} unplayed) -> {output_path}"
    )


if __name__ == "__main__":
    main()
