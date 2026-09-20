#!/usr/bin/env python3
"""Register an Athletes2Events event's teams and import its results.

Athletes2Events is a white-label tournament platform: each host club runs its
events on its own subdomain (``crossfire.``, ``somsports.``, ``arizonasurf.``,
and some fifty more), and one provider row covers them all, because event and
team ids are a single platform-wide sequence.  The host is therefore a parameter
here rather than a constant: the operator pastes the event URL and both the host
and the event id are read from it.

Four public pages feed this script, all server-rendered HTML:

- ``details`` carries the event's own dates, which date the season its labels
  were written in.
- ``groups`` carries every division with its birth-date cutoff
  ("Boys-U19 (Born on or after: Aug 01, 2007)") and a link per flight.
- ``schedules?flight-id=<n>`` carries one table per day of play, every team cell
  linking to that team's page.  Standings are on the same page and ignored.
- ``schedules?team-id=<n>`` is the only source of a team's state and coach.

The run has two stages.  The roster pass links each in-scope team to an existing
PitchRank team or creates it under its Athletes2Events id; a 0.75-0.90 match goes
to the review queue and is not created.  The pass is previewed without writes
first, and a new link to a PitchRank team that another team of the event also
links to is reported as a conflict and left unwritten.  The games stage then
writes the importer's CSV, holding back any game whose team is not linked and any
game whose two teams sit on different boards -- the importer validates both sides
of a game against one age group, so a cross-age game would insert half-matched.
Those are written to their own file so a later pass can repair them.

A team's age comes from its own name, never from its division; the division is an
upper bound, since a team plays up and never down.  A name that states no age, or
an odd year span, falls back to the division's.

Dry run by default: no teams, aliases, review rows or games are written until
``--execute``; the games CSV, the cross-age CSV and the team report are written
either way.

Usage:
    python scripts/import_athletes2events_event.py \
        --event-url https://crossfire.athletes2events.com/events/130 --days-back 60
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
from dataclasses import dataclass
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

from src.models.athletes2events_matcher import Athletes2EventsGameMatcher  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.team_utils import _soccer_season_year, calculate_age_group_from_band  # noqa: E402
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

PROVIDER_CODE = "athletes2events"
OUTPUT_DIR = Path("data/raw/athletes2events")

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

REPORT_COLUMNS = [
    "a2e_team_id",
    "team_name",
    "club_name",
    "division",
    "division_age",
    "age_group",
    "age_source",
    "gender",
    "state_code",
    "coach",
    "outcome",
    "team_id_master",
    "pitchrank_team_name",
    "confidence",
    "reason",
]

CROSS_AGE_COLUMNS = [
    "game_date",
    "division",
    "group",
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SCRAPE_TS = datetime.now(timezone.utc).isoformat()
SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"

LINKED_OUTCOMES = frozenset({"already_linked", "linked_existing", "relinked", "created"})

# One provider row covers every host subdomain, so the host is read from the URL
# rather than fixed. Nothing else in this repo takes a host as a parameter.
# ASCII-bound: under IGNORECASE alone the Unicode fold of U+017F matches the "s"
# of the domain literal, so "athleteſ2eventſ.com" -- a different registrable
# domain -- is accepted, and \d admits non-ASCII digits.
_EVENT_URL = re.compile(
    r"^https://([a-z0-9][a-z0-9-]*\.athletes2events\.com)/events/(\d+)/?$", re.IGNORECASE | re.ASCII
)
_EVENT_DATES = re.compile(
    r"Event Dates:\s*From\s+([A-Za-z]{3}\s+\d{1,2},\s*\d{4})\s+to\s+([A-Za-z]{3}\s+\d{1,2},\s*\d{4})"
)
_DIVISION_LABEL = re.compile(
    r"(Boys|Girls)\s*-\s*U(\d{1,2})\s*\(\s*Born on or after:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})\s*\)", re.IGNORECASE
)
_FLIGHT_ID = re.compile(r"flight-id=(\d+)")
_TEAM_ID = re.compile(r"team-id=(\d+)")
# "7 - 0", or a shootout "1 - 1 (3 - 4)" recorded at its regulation score.
_RESULT = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*(?:\(\s*(\d{1,2})\s*-\s*(\d{1,2})\s*\))?\s*$")
_DAY_HEADER = re.compile(r"^[A-Za-z]{3}\s+([A-Za-z]{3}\s+\d{1,2},\s*\d{4})$")
# "Boys-U12 NSC EBU12, Oviedo (WA)" -> gender, division age, name body, state.
_TEAM_HEADER = re.compile(r"^(Boys|Girls)\s*-\s*U(\d{1,2})\s+(.*?)\s*(?:\(([A-Z]{2})\))?$")
_TEAM_PAGE_HEADER = re.compile(
    r"Loading schedule\.\.\.\s*(.*?)\s*-\s*Matches\s*Team ID#\s*(\d+)(.*?)(?:Sat|Sun|Mon|Tue|Wed|Thu|Fri) \w{3} \d"
)
_COACH = re.compile(r"Coach:\s*(.*?)(?:\s+Managers?:|$)")

# A two-year band: B15/16, G17-18, G2012/13, B2013-2014, (B14-15), B12 - 13, 2010/09, B13 14.
_BAND = re.compile(
    r"(?<![\dA-Za-z])(?:[BG]\s*)?(?:20)?(\d{2})\s*(?:[-/]|(?<=[BG]\d\d)\s)\s*(?:20)?(\d{2})(?!\d)",
    re.IGNORECASE,
)
# A U-age: BU13, U12, GU11, B-U11D, G-U10A, EBU12, GU-12, U7/U8.
_U_AGE = re.compile(r"(?<![A-Za-z0-9])E?[BG]?-?U-?(\d{1,2})(?:/U?(\d{1,2}))?(?=[A-Z]?\b)", re.IGNORECASE)
# A single birth year: B16, G15, B2015, 2013.
_BARE_YEAR = re.compile(r"(?<![A-Za-z0-9])(?:[BG]\s*(?:20)?(\d{2})|20(\d{2}))(?![\d/-])", re.IGNORECASE)
# An age written before the club: "U11/U12 Nido Aguila Zaldivar".
_LEADING_AGE = re.compile(r"^(?:U\d{1,2}(?:/U?\d{1,2})?\s+)+", re.IGNORECASE)
# Where the club part of a name ends: an age/gender token, a tier word, or a comma.
_CLUB_STOP = re.compile(
    r",|\(|\b(?:E?[BG]-?U-?\d{1,2}[A-Z]?|U-?\d{1,2}[A-Z]?|[BG]\d{2}(?:[/-]\d{2})?[A-Z]?|[BG]?(?:19|20)\d{2}(?:[/-]\d{2,4})?"
    r"|RCL|ECNL\d*|ENCL|EA|RL|N\d)\b",
    re.IGNORECASE,
)

# Clubs a host writes in a form PitchRank stores under another name. Keyed by host
# so a new subdomain adds its own without a code change; first match wins, so the
# longer name is listed first.
HOST_CLUBS: Dict[str, Tuple[Tuple[re.Pattern, str], ...]] = {
    "crossfire.athletes2events.com": (
        (re.compile(r"^Crossfire\s+Select\b", re.IGNORECASE), "Crossfire Select Soccer Club"),
        (
            re.compile(r"^(?:XF(?:\s+Crossfire\s+Premier)?|Crossfire(?:\s+Premier)?)\b", re.IGNORECASE),
            "Crossfire Premier",
        ),
    ),
}


@dataclass
class Event:
    host: str
    event_id: int
    name: str
    start: date
    end: date

    @property
    def season(self) -> int:
        """The Aug 1 season the event was played in, never the wall clock's."""
        return _soccer_season_year(datetime(self.start.year, self.start.month, self.start.day))


@dataclass
class Division:
    flight_id: int
    division_name: str
    flight_name: str
    gender: str
    division_age: int
    birth_year: int


@dataclass
class TeamRow:
    a2e_team_id: str
    team_name: str
    club_name: Optional[str]
    club_as_written: Optional[str]
    division_name: str
    division_age: int
    birth_year: Optional[int]
    age_group: Optional[str]
    age_source: str
    gender: str
    state_code: Optional[str]
    coach: str = ""
    skip_reason: Optional[str] = None


@dataclass
class Outcome:
    status: str
    team_id_master: Optional[str] = None
    confidence: Optional[float] = None
    reason: str = ""


@dataclass
class EventGame:
    flight_id: int
    division_name: str
    group: str
    game_no: str
    game_date: date
    game_time: str
    venue: str
    home_id: str
    home_score: int
    away_id: str
    away_score: int
    source_url: str


# ── Network ────────────────────────────────────────────────────────────────────


class ScrapeFetchError(RuntimeError):
    """A page could not be read.

    Raised rather than returned so the run fails: a flight whose page did not load
    must not read as a flight with no games.
    """


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


def parse_event_url(url: str) -> Tuple[str, int]:
    """``https://crossfire.athletes2events.com/events/130`` -> ``("crossfire.athletes2events.com", 130)``.

    An event requested on the wrong subdomain redirects to that host's home page,
    so the host is part of the event's address and is never guessed.
    """
    match = _EVENT_URL.match((url or "").strip())
    if not match:
        raise ValueError(
            f"not an Athletes2Events event URL: {url!r} (expected https://<host>.athletes2events.com/events/<id>)"
        )
    return match.group(1).lower(), int(match.group(2))


def event_page_url(host: str, event_id: int, page: str) -> str:
    return f"https://{host}/events/{event_id}/{page}"


def flight_page_url(host: str, event_id: int, flight_id: int) -> str:
    return event_page_url(host, event_id, f"schedules?flight-id={flight_id}")


def team_page_url(host: str, event_id: int, a2e_team_id: str) -> str:
    return event_page_url(host, event_id, f"schedules?team-id={a2e_team_id}")


def _clean_name(name: str) -> str:
    return " ".join((name or "").replace("\xa0", " ").split())


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return _clean_name((soup.find("main") or soup.body or soup).get_text(" "))


def _parse_site_date(value: str) -> date:
    return datetime.strptime(_clean_name(value), "%b %d, %Y").date()


# ── Event, divisions and teams ─────────────────────────────────────────────────


def parse_event(html: str, host: str, event_id: int) -> Event:
    """Name and dates from the ``details`` page; the start date dates the season."""
    soup = BeautifulSoup(html, "lxml")
    dates = _EVENT_DATES.search(_clean_name((soup.find("main") or soup.body or soup).get_text(" ")))
    if not dates:
        raise ScrapeFetchError(f"no event dates on the details page for event {event_id}")
    heading = soup.find("h2")
    return Event(
        host=host,
        event_id=event_id,
        name=_clean_name(heading.get_text(" ")) if heading else f"Athletes2Events event {event_id}",
        start=_parse_site_date(dates.group(1)),
        end=_parse_site_date(dates.group(2)),
    )


def division_birth_year(cutoff: date, division_age: int, event_season: int) -> Optional[int]:
    """The younger birth year of the band a division admits, or None when the label disagrees.

    A cutoff is the older edge of an Aug 1 - Jul 31 band, so the band's younger
    year is the cutoff year + 1; a cutoff on any other date means the platform
    changed convention. The U-age in the label must then agree with that birth
    year read in the event's own season.
    """
    if (cutoff.month, cutoff.day) != (8, 1):
        return None
    birth_year = cutoff.year + 1
    label = calculate_age_group_from_band(birth_year, event_season)
    if not label or label.lower() != f"u{19 if division_age == 18 else division_age}":
        return None
    return birth_year


def parse_divisions(html: str, event_season: int) -> Tuple[List[Division], List[str]]:
    """Every flight of every division on the ``groups`` page, and the divisions skipped.

    One table per division: its first row names the division and its birth cutoff,
    and each later row is a flight linking to its schedule page.
    """
    soup = BeautifulSoup(html, "lxml")
    divisions: List[Division] = []
    skipped: List[str] = []
    parents = (a.find_parent("table") for a in soup.select('a[href*="flight-id"]'))
    tables = {id(table): table for table in parents if table is not None}
    for table in tables.values():
        rows = table.find_all("tr")
        if not rows:
            skipped.append("a flight table carries no rows")
            continue
        label = _DIVISION_LABEL.search(_clean_name(rows[0].get_text(" ")))
        if not label:
            skipped.append(f"unreadable division heading {_clean_name(rows[0].get_text(' '))!r}")
            continue
        gender = "Male" if label.group(1).lower() == "boys" else "Female"
        division_age = int(label.group(2))
        division_name = f"{label.group(1)}-U{division_age}"
        birth_year = division_birth_year(_parse_site_date(label.group(3)), division_age, event_season)
        if not birth_year:
            skipped.append(f"{division_name}: cutoff {label.group(3)} does not agree with the label")
            continue
        for row in rows[1:]:
            link = row.find("a", href=_FLIGHT_ID)
            cells = row.find_all("td")
            if not link or len(cells) < 2:
                continue
            divisions.append(
                Division(
                    flight_id=int(_FLIGHT_ID.search(link["href"]).group(1)),
                    division_name=division_name,
                    flight_name=_clean_name(cells[1].get_text(" ")),
                    gender=gender,
                    division_age=division_age,
                    birth_year=birth_year,
                )
            )
    return divisions, skipped


def parse_flight_games(html: str, division: Division, source_url: str) -> Tuple[List[EventGame], List[str]]:
    """Every scored game on a flight's schedule page, with both teams' ids.

    ``table.schedule-table`` holds the standings and is ignored. A slot the site
    never filled keeps a placeholder name with no team link; that game is reported
    rather than imported, since the placeholder names no team.
    """
    soup = BeautifulSoup(html, "lxml")
    games: List[EventGame] = []
    problems: List[str] = []
    for table in soup.select("table.matches-table"):
        game_date: Optional[date] = None
        for row in table.find_all("tr"):
            header = row.find("th", attrs={"colspan": True})
            if header:
                day = _DAY_HEADER.match(_clean_name(header.get_text(" ")))
                game_date = _parse_site_date(day.group(1)) if day else None
                if not day:
                    problems.append(f"{division.division_name}: unreadable day {_clean_name(header.get_text(' '))!r}")
                continue
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            score = _RESULT.match(_clean_name(cells[5].get_text(" ")))
            if not score or game_date is None:
                continue
            ids = []
            for index in (4, 6):
                link = cells[index].find("a", href=_TEAM_ID)
                ids.append(_TEAM_ID.search(link["href"]).group(1) if link else None)
            if not all(ids):
                names = [_clean_name(cells[i].get_text(" ")) for i in (4, 6)]
                problems.append(f"{division.division_name}: unfilled bracket slot {names}")
                continue
            games.append(
                EventGame(
                    flight_id=division.flight_id,
                    division_name=f"{division.division_name} {division.flight_name}".strip(),
                    group=_clean_name(cells[2].get_text(" ")),
                    game_no=_clean_name(cells[0].get_text(" ")),
                    game_date=game_date,
                    game_time=_clean_name(cells[3].get_text(" ")),
                    venue=_clean_name(cells[8].get_text(" ")),
                    home_id=ids[0],
                    home_score=int(score.group(1)),
                    away_id=ids[1],
                    away_score=int(score.group(2)),
                    source_url=source_url,
                )
            )
    return games, problems


def parse_team_page(html: str) -> Tuple[str, str]:
    """``(header, coach)`` from a team page, e.g. ``("Boys-U12 NSC EBU12, Oviedo (WA)", "Alejandro Oviedo")``."""
    header = _TEAM_PAGE_HEADER.search(_page_text(html))
    if not header:
        return "", ""
    coach = _COACH.search(header.group(3))
    return _clean_name(header.group(1)), _clean_name(coach.group(1)) if coach else ""


# ── Age and club ───────────────────────────────────────────────────────────────


def age_from_name(team_name: str, division_birth_year: int, event_season: int) -> Tuple[Optional[int], str]:
    """The birth year a team's own name states, with how it was read.

    The division only bounds it: a team plays up and never down, so the name's
    band may be younger than the division's but never older. Labels are read
    against the event's own season, since that is the season they were written in.
    Returns ``(None, reason)`` when the name names more than one cohort.
    """
    text = team_name
    stated: Set[int] = set()
    for match in _BAND.finditer(text):
        pair = frozenset((2000 + int(match.group(1)), 2000 + int(match.group(2))))
        if len(pair) == 2 and max(pair) - min(pair) == 1:
            if max(pair) > event_season - 6:
                # A pair too young to be players is the season written into the
                # name ("25-26", "22/23"); leave it for a later, real band.
                continue
            stated.add(max(pair))
            text = text.replace(match.group(0), " ", 1)
        elif len(pair) == 2 and max(pair) - min(pair) > 1:
            return division_birth_year, "odd year span, tournament division used"
    for match in _U_AGE.finditer(text):
        if match.group(2):
            return None, "two U-ages, left out"
        stated.add(event_season - int(match.group(1)) + 1)
        text = text.replace(match.group(0), " ", 1)
    if stated:
        if len(stated) > 1:
            return None, f"name gives several ages {sorted(stated)}"
        birth_year = stated.pop()
        if birth_year < division_birth_year:
            return None, f"name is older than its U{event_season - division_birth_year + 1} division"
        return birth_year, "name"
    found = _BARE_YEAR.findall(text)
    years = [2000 + int(y1 or y2) for y1, y2 in found]
    if len(years) == 1:
        # A single birth year sits in two bands: as a band's younger year, and as
        # the older year of the band above it.
        options = sorted({years[0], years[0] + 1})
        fits = [year for year in options if year >= division_birth_year]
        if len(fits) == 1:
            return fits[0], f"birth year {years[0]}, one reading fits the division"
        if len(fits) > 1 and len({calculate_age_group_from_band(y, event_season) for y in fits}) == 1:
            # Both readings name the same cohort, so the ambiguity does not
            # matter: U19 holds three birth years because U18 folds into it.
            return fits[0], f"birth year {years[0]}, both readings are one cohort"
        # "B12" in a U12 division: too old to be a 2012 birth year, so it is Boys U12.
        as_age = event_season - (years[0] - 2000) + 1
        if not fits and found[0][0] and as_age >= division_birth_year:
            return as_age, f"B{years[0] - 2000:02d} read as U{years[0] - 2000}"
        readings = fits or options
        return None, f"birth year {years[0]} could be {' or '.join(str(y) for y in readings)}"
    return division_birth_year, "no age in name, tournament division used"


def board_cohort(birth_year: int, board_season: int) -> Optional[str]:
    """The ``u10``-``u19`` board a birth year sits on this season, else None.

    Boards move every Aug 1, so a team from an earlier season's event is filed by
    its age now, not by the label it played under.
    """
    age_group = normalize_age_group(calculate_age_group_from_band(birth_year, board_season))
    if not age_group or int(age_group[1:]) < 10:
        return None
    return age_group


def split_club(team_name: str, host: str) -> Tuple[Optional[str], Optional[str]]:
    """``(club as PitchRank stores it, club as this name writes it)``.

    The club is the words before the first age token, league tag or comma. The two
    differ only where the host writes a club under another name; the squad gates
    need the written form to strip it, and the stored form is what a created team
    is filed under.
    """
    body = _LEADING_AGE.sub("", team_name)
    for pattern, club in HOST_CLUBS.get(host, ()):
        match = pattern.match(body)
        if match:
            return club, _clean_name(match.group(0))
    stop = _CLUB_STOP.search(body)
    written = _clean_name((body[: stop.start()] if stop else body).replace(",", " ")).strip(" -,")
    return written or None, written or None


# ── Roster ─────────────────────────────────────────────────────────────────────


def build_roster(
    headers: Dict[str, Tuple[str, str]],
    divisions_by_team: Dict[str, Division],
    event: Event,
    board_season: int,
) -> Tuple[List[TeamRow], List[TeamRow]]:
    """Split the event's teams into those to register and those skipped, with a reason."""
    in_scope: List[TeamRow] = []
    skipped: List[TeamRow] = []
    for a2e_team_id, (header, coach) in sorted(headers.items(), key=lambda item: int(item[0])):
        division = divisions_by_team[a2e_team_id]
        parsed = _TEAM_HEADER.match(header)
        team_name = _clean_name(parsed.group(3)) if parsed else ""
        state_code = (parsed.group(4) if parsed else None) or None
        birth_year, age_source = (
            age_from_name(team_name, division.birth_year, event.season) if team_name else (None, "unreadable header")
        )
        club_name, club_as_written = split_club(team_name, event.host) if team_name else (None, None)
        cohort = board_cohort(birth_year, board_season) if birth_year else None
        row = TeamRow(
            a2e_team_id=a2e_team_id,
            team_name=team_name,
            club_name=club_name,
            club_as_written=club_as_written,
            division_name=f"{division.division_name} {division.flight_name}".strip(),
            division_age=division.division_age,
            birth_year=birth_year if cohort else None,
            age_group=cohort,
            age_source=age_source,
            gender=division.gender,
            state_code=state_code,
            coach=coach,
        )
        if not team_name:
            row.skip_reason = "team page header could not be read"
        elif not birth_year:
            row.skip_reason = age_source
        elif not cohort:
            row.skip_reason = f"birth year {birth_year} is on no U10-U19 board"
        elif not row.state_code:
            row.skip_reason = "no US state on the team page"
        (skipped if row.skip_reason else in_scope).append(row)
    return in_scope, skipped


def existing_aliases(supabase, provider_id: str, a2e_team_ids: List[str]) -> Dict[str, str]:
    """Athletes2Events team id -> team_id_master for teams already linked."""
    found: Dict[str, str] = {}
    for i in range(0, len(a2e_team_ids), 100):
        batch = a2e_team_ids[i : i + 100]
        result = (
            supabase.table("team_alias_map")
            .select("provider_team_id, team_id_master")
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
            .in_("provider_team_id", batch)
            .execute()
        )
        for row in result.data or []:
            found[str(row["provider_team_id"])] = row["team_id_master"]
    return found


def register_teams(matcher, provider_id: str, roster: List[TeamRow], already: Dict[str, str]) -> Dict[str, Outcome]:
    """Link or create every roster team; one :class:`Outcome` per Athletes2Events team id."""
    outcomes: Dict[str, Outcome] = {}
    for row in roster:
        if row.a2e_team_id in already:
            outcomes[row.a2e_team_id] = Outcome("already_linked", already[row.a2e_team_id], 1.0)
            continue
        try:
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=row.a2e_team_id,
                team_name=row.team_name,
                age_group=row.age_group,
                gender=row.gender,
                club_name=row.club_name,
                state_code=row.state_code,
                written_club=row.club_as_written,
            )
        except Exception as e:
            logger.error(f"match error for Athletes2Events team {row.a2e_team_id}: {e}")
            outcomes[row.a2e_team_id] = Outcome("error", reason=str(e))
            continue

        if result.get("created"):
            outcomes[row.a2e_team_id] = Outcome("created", result["team_id"], 1.0)
        elif result.get("relinked"):
            outcomes[row.a2e_team_id] = Outcome("relinked", result["team_id"], 1.0)
        elif result.get("matched"):
            status = "linked_existing" if result.get("method") == "fuzzy_auto" else "already_linked"
            outcomes[row.a2e_team_id] = Outcome(status, result["team_id"], result.get("confidence"))
        elif result.get("review"):
            outcomes[row.a2e_team_id] = Outcome("review", confidence=result.get("confidence"))
        else:
            outcomes[row.a2e_team_id] = Outcome("error", reason=f"unclassified result: method={result.get('method')}")
    return outcomes


def unsaved_links(outcomes: Dict[str, Outcome], saved: Dict[str, str]) -> Dict[str, str]:
    """Teams reported linked or created whose approved alias is missing or points elsewhere.

    The matcher logs a failed alias write and still reports the team linked, and a
    game whose one team has no alias imports half-matched.
    """
    return {
        a2e_team_id: "link was not saved"
        for a2e_team_id, outcome in outcomes.items()
        if outcome.status in ("linked_existing", "relinked", "created")
        and saved.get(a2e_team_id) != outcome.team_id_master
    }


def pending_reviews(supabase, a2e_team_ids: List[str]) -> Set[str]:
    """Athletes2Events team ids with a pending review row."""
    found: Set[str] = set()
    for i in range(0, len(a2e_team_ids), 100):
        result = (
            supabase.table("team_match_review_queue")
            .select("provider_team_id")
            .eq("provider_id", PROVIDER_CODE)
            .eq("status", "pending")
            .in_("provider_team_id", a2e_team_ids[i : i + 100])
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
        a2e_team_id: "review item was not saved"
        for a2e_team_id, outcome in outcomes.items()
        if outcome.status == "review" and a2e_team_id not in pending
    }


def shared_links(outcomes: Dict[str, Outcome]) -> Dict[str, str]:
    """Teams of this event that matched the same PitchRank team as another one.

    Two registrations in one event are two squads, so at most one of them can be
    that team. Every fuzzy-linked team in such a group is reported; a team whose
    alias was already approved, or whose own row carries its provider id, keeps it.
    """
    by_team: Dict[str, List[str]] = {}
    for a2e_team_id, outcome in outcomes.items():
        if outcome.status in ("already_linked", "linked_existing", "relinked"):
            by_team.setdefault(outcome.team_id_master, []).append(a2e_team_id)
    conflicts: Dict[str, str] = {}
    for _, a2e_team_ids in by_team.items():
        if len(a2e_team_ids) < 2:
            continue
        for a2e_team_id in a2e_team_ids:
            if outcomes[a2e_team_id].status == "linked_existing":
                others = ", ".join(sorted(set(a2e_team_ids) - {a2e_team_id}))
                conflicts[a2e_team_id] = f"same PitchRank team as Athletes2Events team {others}"
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
        outcome = outcomes[row.a2e_team_id]
        if outcome.status not in ("already_linked", "linked_existing", "relinked"):
            continue
        team = teams.get(outcome.team_id_master)
        if team is None:
            refused[row.a2e_team_id] = "linked team not found"
            continue
        team_age = (team.get("age_group") or "").lower()
        if team_age and team_age != row.age_group:
            refused[row.a2e_team_id] = f"linked team is on the {team_age} board, this team is {row.age_group}"
        elif team.get("gender") and team["gender"] != row.gender:
            refused[row.a2e_team_id] = f"linked team is {team['gender']}, this team is {row.gender}"
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


def build_csv_rows(
    games: List[EventGame], roster: List[TeamRow], outcomes: Dict[str, Outcome], event: Event
) -> Tuple[List[Dict], List[EventGame], List[Dict]]:
    """Two importer rows per game whose teams are both linked; the rest are held back.

    A team playing up is ordinary youth soccer and the result is worth more than a
    same-age one, so a cross-age game is imported rather than held. Both sides
    resolve through their own alias -- ``_match_by_provider_id`` on this provider
    does not re-check the age -- and the ranking engine reads each team's cohort
    from ``teams.age_group``, never from the game. Such games are still listed in
    their own file, because the age stamped on the row is the home team's and an
    operator auditing a board will want to know which games span two.
    """
    rows_by_id = {row.a2e_team_id: row for row in roster}
    records: List[Dict] = []
    held: List[EventGame] = []
    cross_age: List[Dict] = []
    for game in games:
        if any(outcomes.get(i, Outcome("missing")).status not in LINKED_OUTCOMES for i in (game.home_id, game.away_id)):
            held.append(game)
            continue
        home = rows_by_id[game.home_id]
        away = rows_by_id[game.away_id]
        if home.age_group != away.age_group or home.gender != away.gender:
            cross_age.append(
                {
                    "game_date": game.game_date.isoformat(),
                    "division": game.division_name,
                    "group": game.group,
                    "home_team_id": home.a2e_team_id,
                    "home_team_name": home.team_name,
                    "home_age_group": home.age_group,
                    "home_gender": home.gender,
                    "home_team_id_master": outcomes[home.a2e_team_id].team_id_master or "",
                    "away_team_id": away.a2e_team_id,
                    "away_team_name": away.team_name,
                    "away_age_group": away.age_group,
                    "away_gender": away.gender,
                    "away_team_id_master": outcomes[away.a2e_team_id].team_id_master or "",
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "source_url": game.source_url,
                }
            )
        base = {
            "provider": PROVIDER_CODE,
            "scrape_run_id": SCRAPE_RUN_ID,
            "event_id": event.event_id,
            "event_name": f"{event.name} - {game.division_name}",
            "schedule_id": f"{game.flight_id}-{game.game_no}-{game.game_date.isoformat()}",
            "age_year": home.birth_year,
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
                    "team_id": team.a2e_team_id,
                    "team_id_source": team.a2e_team_id,
                    "team_name": team.team_name,
                    "club_name": team.club_name or "",
                    "opponent_id": opponent.a2e_team_id,
                    "opponent_id_source": opponent.a2e_team_id,
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
    in_scope: List[TeamRow], skipped: List[TeamRow], outcomes: Dict[str, Outcome], names: Dict[str, str]
) -> List[Dict]:
    rows = []
    for row in in_scope + skipped:
        outcome = outcomes.get(row.a2e_team_id, Outcome("skipped", reason=row.skip_reason or ""))
        rows.append(
            {
                "a2e_team_id": row.a2e_team_id,
                "team_name": row.team_name,
                "club_name": row.club_name or "",
                "division": row.division_name,
                "division_age": f"u{row.division_age}",
                "age_group": row.age_group or "",
                "age_source": row.age_source,
                "gender": row.gender,
                "state_code": row.state_code or "",
                "coach": row.coach,
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
    p.add_argument(
        "--event-url",
        required=True,
        help="Event URL, e.g. https://crossfire.athletes2events.com/events/130",
    )
    p.add_argument("--days-back", type=int, default=14, help="Import games dated within this many days (default 14)")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the CSVs and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between page fetches")
    p.add_argument("--delay-max", type=float, default=3.0, help="Maximum seconds between page fetches")
    p.add_argument("--execute", action="store_true", help="Write teams, aliases and games (default is a dry run)")
    return p.parse_args()


def collect_event(
    fetch_html: Callable[[str], str],
    host: str,
    event_id: int,
    board_season: int,
    days_back: int,
    today: date,
    pause: Callable[[], None] = lambda: None,
) -> Tuple[Event, List[TeamRow], List[TeamRow], List[EventGame], List[str]]:
    """Fetch the event, its flights and its team pages; return the roster and the games in window."""
    event = parse_event(fetch_html(event_page_url(host, event_id, "details")), host, event_id)
    pause()
    divisions, problems = parse_divisions(fetch_html(event_page_url(host, event_id, "groups")), event.season)
    pause()

    games: List[EventGame] = []
    divisions_by_team: Dict[str, Division] = {}
    for division in divisions:
        url = flight_page_url(host, event_id, division.flight_id)
        flight_games, flight_problems = parse_flight_games(fetch_html(url), division, url)
        pause()
        problems.extend(flight_problems)
        games.extend(flight_games)
        for game in flight_games:
            divisions_by_team.setdefault(game.home_id, division)
            divisions_by_team.setdefault(game.away_id, division)

    headers: Dict[str, Tuple[str, str]] = {}
    for a2e_team_id in sorted(divisions_by_team, key=int):
        headers[a2e_team_id] = parse_team_page(fetch_html(team_page_url(host, event_id, a2e_team_id)))
        pause()
        if not headers[a2e_team_id][0]:
            problems.append(f"team {a2e_team_id}: team page header could not be read")

    in_scope, skipped = build_roster(headers, divisions_by_team, event, board_season)
    earliest = today - timedelta(days=days_back)
    in_window = [g for g in games if earliest <= g.game_date <= today]
    return event, in_scope, skipped, in_window, problems


def main() -> int:
    args = parse_args()
    dry_run = not args.execute
    try:
        host, event_id = parse_event_url(args.event_url)
    except ValueError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        return 1

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

    event, in_scope, skipped, games, problems = collect_event(
        lambda url: _get(session, url).text,
        host,
        event_id,
        _soccer_season_year(),
        args.days_back,
        date.today(),
        pause,
    )
    console.print(
        f"[bold]{escape(event.name)}[/bold] ({event.start.isoformat()} to {event.end.isoformat()}) — "
        f"{len(in_scope) + len(skipped)} teams, {len(in_scope)} in scope, {len(skipped)} left out"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )

    already = existing_aliases(supabase, provider_id, [row.a2e_team_id for row in in_scope])
    preview = register_teams(
        Athletes2EventsGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
    )
    conflicts = shared_links(preview)
    if dry_run:
        outcomes = preview
    else:
        writer = Athletes2EventsGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer, provider_id, [row for row in in_scope if row.a2e_team_id not in conflicts], already
        )
        saved = existing_aliases(supabase, provider_id, list(outcomes))
        for a2e_team_id, reason in unsaved_links(outcomes, saved).items():
            outcomes[a2e_team_id] = Outcome("error", outcomes[a2e_team_id].team_id_master, reason=reason)
        queued = pending_reviews(supabase, [i for i, o in outcomes.items() if o.status == "review"])
        for a2e_team_id, reason in unsaved_reviews(outcomes, queued).items():
            outcomes[a2e_team_id] = Outcome("error", confidence=outcomes[a2e_team_id].confidence, reason=reason)
    for a2e_team_id, reason in conflicts.items():
        proposed = preview[a2e_team_id]
        outcomes[a2e_team_id] = Outcome("conflict", proposed.team_id_master, proposed.confidence, reason)
    teams = teams_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    for a2e_team_id, reason in off_board_links(in_scope, outcomes, teams).items():
        outcomes[a2e_team_id] = Outcome("error", outcomes[a2e_team_id].team_id_master, reason=reason)

    records, held, cross_age = build_csv_rows(games, in_scope + skipped, outcomes, event)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    games_csv = args.output_dir / f"{event_id}_{stamp}_games.csv"
    cross_age_csv = args.output_dir / f"{event_id}_{stamp}_cross_age.csv"
    report_csv = args.output_dir / f"{event_id}_{stamp}_teams.csv"
    names = {team_id: team["team_name"] for team_id, team in teams.items()}
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    write_csv(cross_age_csv, CROSS_AGE_COLUMNS, cross_age)
    write_csv(report_csv, REPORT_COLUMNS, report_rows(in_scope, skipped, outcomes, names))

    summary = Table(title=f"Athletes2Events event {event_id} ({host})")
    summary.add_column("")
    summary.add_column("Count", justify="right")
    for status in ("already_linked", "linked_existing", "relinked", "created", "review", "conflict", "error"):
        summary.add_row(status, str(sum(1 for o in outcomes.values() if o.status == status)))
    summary.add_row("teams left out", str(len(skipped)))
    summary.add_row("games in window", str(len(games)))
    summary.add_row("games to import", str(len(records) // 2))
    summary.add_row("games held back", str(len(held)))
    summary.add_row("cross-age games held", str(len(cross_age)))
    summary.add_row("problems", str(len(problems)))
    console.print(summary)
    for problem in problems:
        console.print(f"  [yellow]{escape(problem)}[/yellow]")
    console.print(f"Team report:  {report_csv}\nGames CSV:    {games_csv}\nCross-age CSV: {cross_age_csv}")

    if dry_run:
        console.print("\n[yellow]Dry run — no teams, aliases, review rows or games were written.[/yellow]")
        return 0
    if not records:
        console.print("\nNo games to import.")
        return 0
    import_command = [sys.executable, "scripts/import_games_enhanced.py", str(games_csv), PROVIDER_CODE]
    return subprocess.run(import_command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
