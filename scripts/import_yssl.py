#!/usr/bin/env python3
"""Register YSSL's teams and import its scored games.

YSSL (Young Sportsmen's Soccer League, yssl.org) is a Chicago-area boys league.
Three public, server-rendered pages feed this script:

- ``clublinks.php`` links every club as ``club.php?clu_code=<CODE>``.
- ``club.php?clu_code=<CODE>`` names the club and lists its current-season
  teams: ``<division>&nbsp;<team name>`` linking ``team.php?tea_id=<n>``, then
  the team code (``AACM121``: club code, gender letter, U-age, squad index).
- ``team.php?tea_id=<n>`` carries the team's games. A changed game shows its
  current date first and the original struck through; ``Result`` is written
  from this team's side; an unplayed game has an empty ``Result``.

Every game appears on both teams' pages, so games are merged by YSSL game
number and checked for agreement. Only the current season is published.

The provider team id is the team code scoped to its season (``2026-AACM121``).
The code carries the U-age and is reissued to the next cohort every Aug 1, so a
bare code would carry last season's link onto a different squad; scoped, a new
season's code has no link yet and re-matches by name onto the right team.

YSSL abbreviates clubs (``ECLIPSE``) and runs some branches under one club code
(``CHICAGO RUSH`` holds ``RUSH NORTH``, ``RUSH OSWEGO``), so
``config/yssl_club_map.csv`` maps each club code, or a team-name prefix inside it,
to the club name PitchRank stores. A team no decided row fits is left out and
fails the run, as does any team whose link errored or conflicted.

Dry run by default; ``--execute`` writes teams, aliases, review rows and games.

Usage:
    python scripts/import_yssl.py --days-back 14 [--club AAC --club ECL] [--execute]
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.table import Table  # noqa: E402

from config.settings import AGE_GROUPS  # noqa: E402
from src.models.yssl_matcher import YSSLGameMatcher  # noqa: E402
from src.utils.team_utils import (  # noqa: E402
    _soccer_season_year,
    calculate_age_group_from_band,
    extract_band_birth_year,
)
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

PROVIDER_CODE = "yssl"
BASE_URL = "https://www.yssl.org"
STATE_CODE = "IL"
OUTPUT_DIR = Path("data/raw/yssl")
CLUB_MAP_PATH = Path("config/yssl_club_map.csv")
SKIP_CLUB = "(skip)"

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

REPORT_COLUMNS = [
    "team_code",
    "tea_id",
    "team_name",
    "club_code",
    "club_as_written",
    "club_name",
    "division",
    "age_group",
    "age_source",
    "gender",
    "state_code",
    "outcome",
    "team_id_master",
    "pitchrank_team_name",
    "confidence",
    "reason",
]

CROSS_AGE_COLUMNS = [
    "game_date",
    "division",
    "home_team_id",
    "home_team_name",
    "home_age_group",
    "home_gender",
    "home_team_id_master",
    "away_team_id",
    "away_team_name",
    "away_age_group",
    "away_gender",
    "away_team_id_master",
    "home_score",
    "away_score",
    "source_url",
]

SCRAPE_TS = datetime.now(timezone.utc).isoformat()
SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"

LINKED_OUTCOMES = frozenset({"already_linked", "linked_existing", "relinked", "created"})

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_CLUB_LINK = re.compile(r"club\.php\?clu_code=([A-Z0-9]{2,5})\b")
_CLUB_NAME = re.compile(r"<b>Club</b></span>:\s*([^<]+?)\s*<br>", re.IGNORECASE)
_TEA_ID = re.compile(r"tea_id=(\d+)")
# A rained-out game keeps its struck dates and a stale score; it is reported but does not fail the run.
RAINED_OUT = "rained out"
_SITE_SEASON = re.compile(r"\b(Fall|Spring)\s+(20\d{2})\s+Teams\b")
_TEA_NUM = re.compile(r"tea_num=([A-Z0-9]+)")
_SITE_DATE = re.compile(r"^[A-Za-z]{3}\s+(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}:\d{2}\s*[ap]m))?$", re.IGNORECASE)
_RESULT = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})$")
_GAME_NO = re.compile(r"^(\d+)\*?$")
_GAMES_HEADER = ["Num", "Date/Time", "Opponent", "H/A", "Field", "Result"]
_DIVISION_AGE = re.compile(r"^U(\d{1,2})")
_TEAM_CODE = re.compile(r"^[A-Z0-9]{3}([A-Z])\d")
_GENDERS = {"M": "Male", "F": "Female"}
_GIRLS = re.compile(r"\bGIRLS?\b", re.IGNORECASE)
_BAND_TEXT = re.compile(r"(?<!\d)(?:20)?\d{2}\s*[/-]\s*(?:20)?\d{2}(?!\d)")


@dataclass
class Listing:
    tea_id: str
    division: str
    team_name: str
    team_code: str


@dataclass
class SideGame:
    game_no: str
    game_date: date
    game_time: str
    team_code: str
    opponent_code: str
    home_away: str
    goals_for: int
    goals_against: int
    venue: str
    source_url: str


@dataclass
class Game:
    game_no: str
    game_date: date
    game_time: str
    home_code: str
    away_code: str
    home_score: int
    away_score: int
    venue: str
    source_url: str


@dataclass
class ClubEntry:
    yssl_code: str
    yssl_name: str
    pitchrank_club_name: str
    decided_by: str
    team_prefix: str = ""
    state_code: str = STATE_CODE


@dataclass
class TeamRow:
    team_code: str
    tea_id: str
    team_name: str
    division: str
    club_code: str
    club_as_written: str
    club_name: Optional[str]
    age_group: Optional[str]
    age_source: str
    gender: Optional[str]
    state_code: str = STATE_CODE
    skip_reason: str = ""


@dataclass
class Outcome:
    status: str
    team_id_master: Optional[str] = None
    confidence: Optional[float] = None
    reason: str = ""


class ScrapeFetchError(RuntimeError):
    """A page could not be read.

    Raised rather than returned so the run fails: a team whose page did not load
    must not read as a team with no games.
    """


class StaleSeasonError(RuntimeError):
    """The site still lists another season's teams.

    Team ids are scoped to the wall-clock season, so registering last season's
    squads under this season's ids would leave each reissued code linked to the
    old squad once the site rolls over.
    """


# ── Fetching ───────────────────────────────────────────────────────────────────


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retries = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def _get(session: requests.Session, url: str) -> requests.Response:
    try:
        response = session.get(url, timeout=90)
    except requests.RequestException as e:
        raise ScrapeFetchError(f"request failed for {url}: {e}") from e
    if response.status_code != 200:
        raise ScrapeFetchError(f"HTTP {response.status_code} for {url}")
    if "charset" not in str(response.headers.get("content-type", "")).lower():
        response.encoding = "utf-8"
    return response


# ── Parsing ────────────────────────────────────────────────────────────────────


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())


def parse_club_list(html: str) -> List[str]:
    return sorted(set(_CLUB_LINK.findall(html)))


def site_season(html: str) -> Optional[int]:
    """The season a club page lists: "Fall 2026 Teams" and "Spring 2027 Teams" are both 2026."""
    found = _SITE_SEASON.search(html)
    if not found:
        return None
    year = int(found.group(2))
    return year if found.group(1) == "Fall" else year - 1


def parse_club_page(html: str) -> Tuple[str, List[Listing]]:
    found = _CLUB_NAME.search(html)
    club_name = " ".join(found.group(1).split()) if found else ""
    soup = BeautifulSoup(html, "html.parser")
    listings: List[Listing] = []
    for link in soup.select('a[href*="team.php?tea_id="]'):
        tea_id = _TEA_ID.search(link["href"]).group(1)
        division, _, team_name = link.get_text().partition("\xa0")
        cells = link.find_parent("tr").find_all("td")
        team_code = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        listings.append(Listing(tea_id, division.strip(), " ".join(team_name.split()), team_code))
    return club_name, listings


def game_date(month: int, day: int, season: int) -> date:
    """A fall date (Aug-Dec) is in the season's start year; a spring date in the next."""
    return date(season if month >= 8 else season + 1, month, day)


def _games_table(soup):
    for table in soup.find_all("table"):
        if [th.get_text(strip=True) for th in table.find_all("th")][:6] == _GAMES_HEADER:
            return table
    return None


def parse_team_games(html: str, team_code: str, season: int, source_url: str) -> Tuple[List[SideGame], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = _games_table(soup)
    if table is None:
        return [], [f"{team_code}: games table not found"]
    games: List[SideGame] = []
    problems: List[str] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        number = _GAME_NO.match(_text(cells[0]))
        result = _RESULT.match(_text(cells[5]))
        if not number or not result:
            continue  # the header row, or a game not yet played
        for struck in cells[1].find_all("del") + cells[4].find_all("del"):
            struck.decompose()
        when = _SITE_DATE.match(_text(cells[1]))
        opponent = cells[2].find("a", href=_TEA_NUM)
        home_away = _text(cells[3])
        if not when and "rainout" in _text(cells[1]).lower():
            problems.append(f"{team_code} game {number.group(1)}: {RAINED_OUT}")
            continue
        if not when or not opponent or home_away not in ("H", "A"):
            problems.append(f"{team_code} game {number.group(1)}: unreadable row")
            continue
        games.append(
            SideGame(
                game_no=number.group(1),
                game_date=game_date(int(when.group(1)), int(when.group(2)), season),
                game_time=(when.group(3) or "").replace(" ", ""),
                team_code=team_code,
                opponent_code=_TEA_NUM.search(opponent["href"]).group(1),
                home_away=home_away,
                goals_for=int(result.group(1)),
                goals_against=int(result.group(2)),
                venue=_text(cells[4]).removesuffix("[away]").strip(),
                source_url=source_url,
            )
        )
    return games, problems


def _as_home_view(side: SideGame) -> Tuple:
    if side.home_away == "H":
        return (side.team_code, side.opponent_code, side.goals_for, side.goals_against, side.game_date)
    return (side.opponent_code, side.team_code, side.goals_against, side.goals_for, side.game_date)


def merge_games(sides: List[SideGame]) -> Tuple[List[Game], List[str]]:
    """One game per YSSL game number; when both teams' pages list it, they must agree."""
    by_number: Dict[str, List[SideGame]] = {}
    for side in sides:
        by_number.setdefault(side.game_no, []).append(side)
    games: List[Game] = []
    problems: List[str] = []
    for game_no, seen in sorted(by_number.items(), key=lambda item: int(item[0])):
        if len(seen) > 2:
            problems.append(f"game {game_no}: listed {len(seen)} times")
            continue
        views = {_as_home_view(side) for side in seen}
        if len(views) != 1:
            problems.append(f"game {game_no}: the two teams' pages disagree")
            continue
        home, away, home_score, away_score, day = views.pop()
        first = seen[0]
        games.append(
            Game(game_no, day, first.game_time, home, away, home_score, away_score, first.venue, first.source_url)
        )
    return games, problems


# ── Collection ─────────────────────────────────────────────────────────────────


def collect_league(
    fetch_html: Callable[[str], str],
    clubs: Optional[List[str]],
    season: int,
    pause: Callable[[], None] = lambda: None,
) -> Tuple[Dict[str, Tuple[str, List[Listing]]], List[SideGame], List[str]]:
    """Fetch the club list, the named clubs (all when none are named) and each of their team pages."""
    listed = parse_club_list(fetch_html(f"{BASE_URL}/clublinks.php"))
    pause()
    problems = [f"club {code} is not on the club list" for code in (clubs or []) if code not in listed]
    found: Dict[str, Tuple[str, List[Listing]]] = {}
    sides: List[SideGame] = []
    for code in listed:
        if clubs and code not in clubs:
            continue
        html = fetch_html(f"{BASE_URL}/club.php?clu_code={code}")
        listed_season = site_season(html)
        if listed_season is not None and listed_season != season:
            raise StaleSeasonError(f"yssl.org lists the {listed_season} season's teams; this run's season is {season}")
        found[code] = parse_club_page(html)
        pause()
        for listing in found[code][1]:
            url = f"{BASE_URL}/team.php?tea_id={listing.tea_id}"
            team_games, team_problems = parse_team_games(fetch_html(url), listing.team_code, season, url)
            pause()
            sides.extend(team_games)
            problems.extend(team_problems)
    return found, sides, problems


# ── Roster ─────────────────────────────────────────────────────────────────────


def load_club_map(path: Path) -> Dict[str, List[ClubEntry]]:
    """Decided rows only, grouped by club code. A blank name or decider is undecided, never "no club"."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    club_map: Dict[str, List[ClubEntry]] = {}
    for row in rows:
        if not (row["pitchrank_club_name"].strip() and row["decided_by"].strip()):
            continue
        entry = ClubEntry(
            row["yssl_code"].strip(),
            row["yssl_name"].strip(),
            row["pitchrank_club_name"].strip(),
            row["decided_by"].strip(),
            (row.get("team_prefix") or "").strip(),
            (row.get("state_code") or "").strip() or STATE_CODE,
        )
        club_map.setdefault(entry.yssl_code, []).append(entry)
    return club_map


def club_entry_for(entries: List[ClubEntry], team_name: str) -> Optional[ClubEntry]:
    """The longest team-name prefix row that fits, else the club's own row."""
    name = team_name.upper()
    branches = [e for e in entries if e.team_prefix and name.startswith(e.team_prefix.upper())]
    if branches:
        return max(branches, key=lambda e: len(e.team_prefix))
    return next((e for e in entries if not e.team_prefix), None)


def season_id(team_code: str, season: int) -> str:
    return f"{season}-{team_code}"


def scope_games(games: List[Game], season: int) -> List[Game]:
    return [
        replace(g, home_code=season_id(g.home_code, season), away_code=season_id(g.away_code, season)) for g in games
    ]


def _board(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    cohort = "u19" if label.lower() == "u18" else label.lower()
    return cohort if cohort in AGE_GROUPS else None


def team_age(team_name: str, division: str, board_season: int) -> Tuple[Optional[str], str]:
    """The band in the name wins, even for a team playing up; the division only fills a nameless gap."""
    younger = extract_band_birth_year(team_name, board_season)
    if younger:
        band = _BAND_TEXT.search(team_name)
        source = f"band {band.group(0).replace(' ', '')}" if band else f"band {younger}"
        return _board(calculate_age_group_from_band(younger, board_season)), source
    age = _DIVISION_AGE.match(division or "")
    if age:
        return _board(f"U{int(age.group(1))}"), f"division U{int(age.group(1))}"
    return None, "no band in name and no division age"


def written_club(team_name: str, club_name_on_site: str, entry: Optional[ClubEntry]) -> str:
    """The club as this team's own name writes it, for the matcher to strip before reading squad marks.

    YSSL names a team by a shorter form of its club ("HAWTHORN WOODS ELITE" for
    "HAWTHORN WOODS ELITE SOCCER CLUB"), so the full name is often absent from the
    team name, and a club word left behind reads as a squad mark: "ELITE" as a tier.
    The leading run of club words is that shorter form. A branch row's prefix is
    not used: its branch words ("NORTH SHORE") are what keep a branch squad
    off its sister branch's teams filed under the same PitchRank club.
    """
    names = [club_name_on_site] + ([entry.yssl_name, entry.pitchrank_club_name] if entry else [])
    club_words = {w for name in names for w in re.findall(r"[a-z0-9]+", name.lower())}
    leading: List[str] = []
    for token in team_name.split():
        word = re.sub(r"[^a-z0-9]", "", token.lower())
        if word and word not in club_words:
            break
        leading.append(token)
    while leading and not re.sub(r"[^A-Za-z0-9]", "", leading[-1]):
        leading.pop()
    return " ".join(leading) or club_name_on_site


def team_gender(team_name: str, code_letter: str) -> Optional[str]:
    """The code's letter, unless the name says GIRLS: girls teams also play in this boys league."""
    if _GIRLS.search(team_name):
        return "Female"
    return _GENDERS.get(code_letter)


def build_roster(
    clubs: Dict[str, Tuple[str, List[Listing]]], club_map: Dict[str, List[ClubEntry]], board_season: int
) -> Tuple[List[TeamRow], List[TeamRow]]:
    """Split the walked teams into those to register and those left out, with a reason."""
    in_scope: List[TeamRow] = []
    left_out: List[TeamRow] = []
    for club_code, (club_name_on_site, listings) in sorted(clubs.items()):
        entries = club_map.get(club_code, [])
        for listing in listings:
            entry = club_entry_for(entries, listing.team_name)
            age_group, age_source = team_age(listing.team_name, listing.division, board_season)
            code = _TEAM_CODE.match(listing.team_code)
            row = TeamRow(
                team_code=season_id(listing.team_code, board_season),
                tea_id=listing.tea_id,
                team_name=listing.team_name,
                division=listing.division,
                club_code=club_code,
                club_as_written=written_club(listing.team_name, club_name_on_site, entry),
                club_name=entry.pitchrank_club_name if entry else None,
                age_group=age_group,
                age_source=age_source,
                gender=team_gender(listing.team_name, code.group(1) if code else ""),
                state_code=entry.state_code if entry else STATE_CODE,
            )
            if not entries:
                row.skip_reason = f"club {club_code} not in club map"
            elif not entry:
                row.skip_reason = f"no {club_code} club-map row fits this team"
            elif entry.pitchrank_club_name == SKIP_CLUB:
                row.skip_reason = f"club {club_code} is skipped in the club map"
            elif not row.gender:
                row.skip_reason = f"team code {listing.team_code} names no gender"
            elif not age_group:
                row.skip_reason = f"no U10-U19 board ({age_source})"
            (left_out if row.skip_reason else in_scope).append(row)
    return in_scope, left_out


def existing_aliases(supabase, provider_id: str, team_codes: List[str]) -> Dict[str, str]:
    """YSSL team code -> team_id_master for teams already linked."""
    found: Dict[str, str] = {}
    for i in range(0, len(team_codes), 100):
        result = (
            supabase.table("team_alias_map")
            .select("provider_team_id, team_id_master")
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
            .in_("provider_team_id", team_codes[i : i + 100])
            .execute()
        )
        for row in result.data or []:
            found[str(row["provider_team_id"])] = row["team_id_master"]
    return found


def register_teams(matcher, provider_id: str, roster: List[TeamRow], already: Dict[str, str]) -> Dict[str, Outcome]:
    """Link or create every roster team; one :class:`Outcome` per YSSL team code."""
    outcomes: Dict[str, Outcome] = {}
    for row in roster:
        if row.team_code in already:
            outcomes[row.team_code] = Outcome("already_linked", already[row.team_code], 1.0)
            continue
        try:
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=row.team_code,
                team_name=row.team_name,
                age_group=row.age_group,
                gender=row.gender,
                club_name=row.club_name,
                state_code=row.state_code,
                written_club=row.club_as_written,
            )
        except Exception as e:
            logger.error(f"match error for YSSL team {row.team_code}: {e}")
            outcomes[row.team_code] = Outcome("error", reason=str(e))
            continue

        if result.get("created"):
            outcomes[row.team_code] = Outcome("created", result["team_id"], 1.0)
        elif result.get("relinked"):
            outcomes[row.team_code] = Outcome("relinked", result["team_id"], 1.0)
        elif result.get("matched"):
            status = "linked_existing" if result.get("method") == "fuzzy_auto" else "already_linked"
            outcomes[row.team_code] = Outcome(status, result["team_id"], result.get("confidence"))
        elif result.get("review"):
            outcomes[row.team_code] = Outcome("review", confidence=result.get("confidence"))
        else:
            outcomes[row.team_code] = Outcome("error", reason=f"unclassified result: method={result.get('method')}")
    return outcomes


def unsaved_links(outcomes: Dict[str, Outcome], saved: Dict[str, str]) -> Dict[str, str]:
    """Teams reported linked or created whose approved alias is missing or points elsewhere.

    The matcher logs a failed alias write and still reports the team linked, and a
    game whose one team has no alias imports half-matched.
    """
    return {
        team_code: "link was not saved"
        for team_code, outcome in outcomes.items()
        if outcome.status in ("linked_existing", "relinked", "created")
        and saved.get(team_code) != outcome.team_id_master
    }


def pending_reviews(supabase, team_codes: List[str]) -> Set[str]:
    """YSSL team codes with a pending review row."""
    found: Set[str] = set()
    for i in range(0, len(team_codes), 100):
        result = (
            supabase.table("team_match_review_queue")
            .select("provider_team_id")
            .eq("provider_id", PROVIDER_CODE)
            .eq("status", "pending")
            .in_("provider_team_id", team_codes[i : i + 100])
            .execute()
        )
        found.update(str(row["provider_team_id"]) for row in result.data or [])
    return found


def unsaved_reviews(outcomes: Dict[str, Outcome], pending: Set[str]) -> Dict[str, str]:
    """Teams reported queued for review with no pending row.

    The matcher logs a failed review write and still reports the team queued, and
    its games are then held back with nothing in the queue to release them.
    """
    return {
        team_code: "review item was not saved"
        for team_code, outcome in outcomes.items()
        if outcome.status == "review" and team_code not in pending
    }


def shared_links(outcomes: Dict[str, Outcome]) -> Dict[str, str]:
    """Teams that matched the same PitchRank team as another YSSL team.

    Two YSSL teams are two squads, so at most one of them can be that team. Every
    fuzzy-linked team in such a group is reported; a team whose alias was already
    approved, or whose own row carries its YSSL code, keeps it.
    """
    by_team: Dict[str, List[str]] = {}
    for team_code, outcome in outcomes.items():
        if outcome.status in ("already_linked", "linked_existing", "relinked"):
            by_team.setdefault(outcome.team_id_master, []).append(team_code)
    conflicts: Dict[str, str] = {}
    for team_codes in by_team.values():
        if len(team_codes) < 2:
            continue
        for team_code in team_codes:
            if outcomes[team_code].status == "linked_existing":
                others = ", ".join(sorted(set(team_codes) - {team_code}))
                conflicts[team_code] = f"same PitchRank team as YSSL team {others}"
    return conflicts


def off_board_links(roster: List[TeamRow], outcomes: Dict[str, Outcome], teams: Dict[str, Dict]) -> Dict[str, str]:
    """Linked teams the importer will refuse: no team row, or a stored age group or gender not the roster's.

    The importer re-checks every link against its game's age group and gender with
    ``GameHistoryMatcher._validate_team_age_group`` and leaves a refused side blank,
    so the game would insert half-matched. A linked team's stored board can differ
    from the board this team's name puts it on; a team this run creates takes it.
    """
    refused: Dict[str, str] = {}
    for row in roster:
        outcome = outcomes[row.team_code]
        if outcome.status not in ("already_linked", "linked_existing", "relinked"):
            continue
        team = teams.get(outcome.team_id_master)
        if team is None:
            refused[row.team_code] = "linked team not found"
            continue
        team_age = (team.get("age_group") or "").lower()
        if team_age and team_age != row.age_group:
            refused[row.team_code] = f"linked team is on the {team_age} board, this team is {row.age_group}"
        elif team.get("gender") and team["gender"] != row.gender:
            refused[row.team_code] = f"linked team is {team['gender']}, this team is {row.gender}"
    return refused


def teams_by_id(supabase, team_ids: List[str]) -> Dict[str, Dict]:
    teams: Dict[str, Dict] = {}
    for i in range(0, len(team_ids), 100):
        result = (
            supabase.table("teams")
            .select("team_id_master, team_name, age_group, gender")
            .in_("team_id_master", team_ids[i : i + 100])
            .execute()
        )
        for row in result.data or []:
            teams[row["team_id_master"]] = row
    return teams


# ── Output ─────────────────────────────────────────────────────────────────────


def _compute_result(goals_for: int, goals_against: int) -> str:
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


def _season_label(day: date) -> str:
    return f"{'Fall' if day.month >= 8 else 'Spring'} {day.year}"


def build_csv_rows(
    games: List[Game], roster: List[TeamRow], outcomes: Dict[str, Outcome], days_back: int, today: date
) -> Tuple[List[Dict], List[Game], List[Dict]]:
    """Two importer rows per in-window game whose teams are both linked; the rest are held back.

    A team playing up is ordinary youth soccer, so a cross-age game is imported:
    both sides resolve through their own alias, and the ranking engine reads each
    team's cohort from ``teams.age_group``, never from the game. Such games are
    also listed in a file of their own, because the age stamped on the row is the
    home team's.
    """
    rows_by_code = {row.team_code: row for row in roster}
    earliest = today - timedelta(days=days_back)
    records: List[Dict] = []
    held: List[Game] = []
    cross_age: List[Dict] = []
    for game in games:
        if not earliest <= game.game_date <= today:
            continue
        codes = (game.home_code, game.away_code)
        if any(
            code not in rows_by_code or outcomes.get(code, Outcome("missing")).status not in LINKED_OUTCOMES
            for code in codes
        ):
            held.append(game)
            continue
        home = rows_by_code[game.home_code]
        away = rows_by_code[game.away_code]
        if home.age_group != away.age_group or home.gender != away.gender:
            cross_age.append(
                {
                    "game_date": game.game_date.isoformat(),
                    "division": home.division,
                    "home_team_id": home.team_code,
                    "home_team_name": home.team_name,
                    "home_age_group": home.age_group,
                    "home_gender": home.gender,
                    "home_team_id_master": outcomes[home.team_code].team_id_master or "",
                    "away_team_id": away.team_code,
                    "away_team_name": away.team_name,
                    "away_age_group": away.age_group,
                    "away_gender": away.gender,
                    "away_team_id_master": outcomes[away.team_code].team_id_master or "",
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "source_url": game.source_url,
                }
            )
        base = {
            "provider": PROVIDER_CODE,
            "scrape_run_id": SCRAPE_RUN_ID,
            "event_id": "",
            "event_name": f"YSSL {_season_label(game.game_date)} - {home.division}",
            "schedule_id": f"yssl-{game.game_no}",
            "age_year": "",
            "age_group": home.age_group,
            "gender": "Boys" if home.gender == "Male" else "Girls",
            "game_date": game.game_date.isoformat(),
            "game_time": game.game_time,
            "venue": game.venue,
            "source_url": game.source_url,
            "scraped_at": SCRAPE_TS,
        }
        for team, opponent, goals_for, goals_against, home_away in (
            (home, away, game.home_score, game.away_score, "H"),
            (away, home, game.away_score, game.home_score, "A"),
        ):
            records.append(
                {
                    **base,
                    "team_id": team.team_code,
                    "team_id_source": team.team_code,
                    "team_name": team.team_name,
                    "club_name": team.club_name or "",
                    "opponent_id": opponent.team_code,
                    "opponent_id_source": opponent.team_code,
                    "opponent_name": opponent.team_name,
                    "opponent_club_name": opponent.club_name or "",
                    "state": STATE_CODE_TO_NAME.get(team.state_code, ""),
                    "state_code": team.state_code,
                    "home_away": home_away,
                    "goals_for": goals_for,
                    "goals_against": goals_against,
                    "result": _compute_result(goals_for, goals_against),
                }
            )
    return records, held, cross_age


def write_csv(path: Path, columns: List[str], rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def report_rows(
    in_scope: List[TeamRow], left_out: List[TeamRow], outcomes: Dict[str, Outcome], names: Dict[str, str]
) -> List[Dict]:
    rows = []
    for row in in_scope + left_out:
        outcome = outcomes.get(row.team_code, Outcome("skipped", reason=row.skip_reason))
        rows.append(
            {
                "team_code": row.team_code,
                "tea_id": row.tea_id,
                "team_name": row.team_name,
                "club_code": row.club_code,
                "club_as_written": row.club_as_written,
                "club_name": row.club_name or "",
                "division": row.division,
                "age_group": row.age_group or "",
                "age_source": row.age_source,
                "gender": row.gender or "",
                "state_code": row.state_code,
                "outcome": outcome.status,
                "team_id_master": outcome.team_id_master or "",
                "pitchrank_team_name": names.get(outcome.team_id_master or "", ""),
                "confidence": "" if outcome.confidence is None else outcome.confidence,
                "reason": outcome.reason,
            }
        )
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days-back", type=int, default=14, help="Import games dated within this many days (default 14)")
    p.add_argument("--club", action="append", default=None, help="Walk only this club code (repeatable; pilots)")
    p.add_argument("--club-map", type=Path, default=CLUB_MAP_PATH, help="YSSL club -> PitchRank club map")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the CSVs and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between page fetches")
    p.add_argument("--delay-max", type=float, default=2.0, help="Maximum seconds between page fetches")
    p.add_argument("--execute", action="store_true", help="Write teams, aliases and games (default is a dry run)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = not args.execute

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        console.print("[red]SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return 1
    supabase = create_client(supabase_url, supabase_key)
    provider = supabase.table("providers").select("id").eq("code", PROVIDER_CODE).execute().data
    if not provider:
        console.print(f"[red]No '{PROVIDER_CODE}' row in providers; apply its seed migration first[/red]")
        return 1
    provider_id = provider[0]["id"]

    session = make_session()

    def pause() -> None:
        time.sleep(random.uniform(args.delay_min, args.delay_max))

    season = _soccer_season_year()
    try:
        clubs, sides, problems = collect_league(lambda url: _get(session, url).text, args.club, season, pause)
    except StaleSeasonError as e:
        console.print(f"[yellow]{escape(str(e))}. Nothing registered or imported until it rolls over.[/yellow]")
        return 0
    games, merge_problems = merge_games(sides)
    games = scope_games(games, season)
    problems.extend(merge_problems)
    in_scope, left_out = build_roster(clubs, load_club_map(args.club_map), season)
    console.print(
        f"[bold]YSSL[/bold] — {len(clubs)} clubs, {len(in_scope) + len(left_out)} teams, "
        f"{len(in_scope)} in scope, {len(left_out)} left out"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )
    console.print(f"Games scraped: {len(games)}")

    already = existing_aliases(supabase, provider_id, [row.team_code for row in in_scope])
    preview = register_teams(
        YSSLGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
    )
    conflicts = shared_links(preview)
    if dry_run:
        outcomes = preview
    else:
        writer = YSSLGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer, provider_id, [row for row in in_scope if row.team_code not in conflicts], already
        )
        saved = existing_aliases(supabase, provider_id, list(outcomes))
        for team_code, reason in unsaved_links(outcomes, saved).items():
            outcomes[team_code] = Outcome("error", outcomes[team_code].team_id_master, reason=reason)
        queued = pending_reviews(supabase, [code for code, outcome in outcomes.items() if outcome.status == "review"])
        for team_code, reason in unsaved_reviews(outcomes, queued).items():
            outcomes[team_code] = Outcome("error", confidence=outcomes[team_code].confidence, reason=reason)
    for team_code, reason in conflicts.items():
        proposed = preview[team_code]
        outcomes[team_code] = Outcome("conflict", proposed.team_id_master, proposed.confidence, reason)
    teams = teams_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    for team_code, reason in off_board_links(in_scope, outcomes, teams).items():
        outcomes[team_code] = Outcome("error", outcomes[team_code].team_id_master, reason=reason)

    records, held, cross_age = build_csv_rows(games, in_scope, outcomes, args.days_back, date.today())

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    games_csv = args.output_dir / f"{stamp}_games.csv"
    cross_age_csv = args.output_dir / f"{stamp}_cross_age.csv"
    report_csv = args.output_dir / f"{stamp}_teams.csv"
    names = {team_id: team["team_name"] for team_id, team in teams.items()}
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    write_csv(cross_age_csv, CROSS_AGE_COLUMNS, cross_age)
    write_csv(report_csv, REPORT_COLUMNS, report_rows(in_scope, left_out, outcomes, names))

    unmapped = sorted({row.club_code for row in left_out if row.club_name is None})
    failed = sorted(code for code, o in outcomes.items() if o.status in ("error", "conflict"))
    unread = [problem for problem in problems if not problem.endswith(RAINED_OUT)]
    must_fail = bool(unmapped or failed or unread)
    summary = Table(title="YSSL")
    summary.add_column("")
    summary.add_column("Count", justify="right")
    for status in ("already_linked", "linked_existing", "relinked", "created", "review", "conflict", "error"):
        summary.add_row(status, str(sum(1 for o in outcomes.values() if o.status == status)))
    summary.add_row("teams left out", str(len(left_out)))
    summary.add_row("clubs not in club map", str(len(unmapped)))
    summary.add_row("games to import", str(len(records) // 2))
    summary.add_row("games held back", str(len(held)))
    summary.add_row("cross-age games imported", str(len(cross_age)))
    summary.add_row("problems", str(len(problems)))
    console.print(summary)
    for problem in problems:
        console.print(f"  [yellow]{escape(problem)}[/yellow]")
    console.print(f"Team report:  {report_csv}\nGames CSV:    {games_csv}\nCross-age CSV: {cross_age_csv}")
    if unmapped:
        console.print(
            f"[red]Clubs not in the club map, teams left out: {', '.join(unmapped)}. Add them to {CLUB_MAP_PATH}.[/red]"
        )
    if failed:
        console.print(f"[red]{len(failed)} teams errored or conflicted; see the team report: {', '.join(failed)}[/red]")
    if unread:
        console.print(f"[red]{len(unread)} games could not be read and were left out; see the problems above.[/red]")

    if dry_run:
        console.print("\n[yellow]Dry run — no teams, aliases, review rows or games were written.[/yellow]")
        return 1 if must_fail else 0
    if not records:
        console.print("\nNo games to import.")
        return 1 if must_fail else 0
    import_command = [sys.executable, "scripts/import_games_enhanced.py", str(games_csv), PROVIDER_CODE]
    returncode = subprocess.run(import_command, check=False).returncode
    return returncode or (1 if must_fail else 0)


if __name__ == "__main__":
    sys.exit(main())
