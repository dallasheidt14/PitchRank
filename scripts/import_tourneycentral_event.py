#!/usr/bin/env python3
"""Register a Tourney Central tournament's teams and import its results.

Tourney Central hosts tournaments on one CGI layout, each on its own subdomain
(``wfc.``, ``buckeyecup.``, ``copadetroit.``, and some fifty more), and one provider
row covers them all, because team ids are a single platform-wide sequence. A team
gets a new id for every tournament it enters, though, so most teams are matched by
name, club and state rather than by id. The host is a parameter: the operator pastes
any page of the tournament and the host is read from it. A site shows only its
current year, so a tournament has to be imported before it moves on.

Three public pages feed this script, all server-rendered HTML:

- ``games.html`` lists every division code and the tournament's play dates, which
  date the season its labels were written in.
- ``cgi-bin/teams.cgi?fnc=adiv&t_div=<code>`` is a division's team list: each team's
  id, its name, its club, ``City, ST`` and its coach.
- ``cgi-bin/teams.cgi?fnc=sked&sny=Y&t_div=<code>`` is a division's schedule: a header row
  per day, then a row per game with its number, time, field, both team ids and both
  scores.  The game number is unique across the tournament, which keeps a final apart
  from the same day's pool game between the same two teams.

A division code reads ``<B|G><U-age>[-<U-age>][<n>v<n>]<flight>``: ``B11Gold``,
``B107v7Gold`` (U10, 7v7), ``G14-15Red`` (U14 and U15 together).  A division with no
board (U9 and below) or of small-sided play is neither fetched nor imported.

The run has two stages.  The roster pass links each in-scope team to an existing
PitchRank team or creates it under its Tourney Central id; a 0.75-0.90 match goes to
the review queue and is not created.  The pass is previewed without writes first, and
a new link to a PitchRank team that another team of the tournament also links to is
reported as a conflict and left unwritten.  The games stage then writes the
importer's CSV, holding back only a game whose team is not linked.  A game between
two boards is imported: a team playing up is ordinary and each side resolves through
its own alias, while the ranking engine reads a team's cohort from its own row rather
than from the game.  Those games are also listed in a file of their own, since the
age on the importer's row is the home team's.

A team's age comes from its own name alone, read by the label key: a band by its
younger year (``B15/16`` is U11), a single birth year as a band's younger year
(``G2016`` is U11), a U-age against the tournament's own season.  The division never
sets it -- not as a bound and not as a fallback -- because teams play up.  A name that
states no age, or two, is left out for a person to decide, and ``--leave-out`` holds back
any other team the operator names by its Tourney Central id.  ``--age`` files a named
team on the board a person gives, ``--gender`` sets the gender of a named team that entered a
division of the other gender, and ``--state`` sets a named team's state where its listed
location is wrong.  Before anything is
registered, the tournament's labels are checked against the birth-year bands in its
team names, and a tournament that labels by the coming season stops the run, since its
team names' U-ages would be read a year off.

Dry run by default: no teams, aliases, review rows or games are written until
``--execute``; the games CSV, the cross-age CSV and the team report are written
either way.

Usage:
    python scripts/import_tourneycentral_event.py \
        --event-url https://wfc.tourneycentral.com/games.html --days-back 30
    python scripts/import_tourneycentral_event.py \
        --event-url https://wfc.tourneycentral.com/games.html --leave-out 314436 --state 316490=OH
"""

from __future__ import annotations

import argparse
import codecs
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
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.table import Table  # noqa: E402

from scripts.import_athletes2events_event import (  # noqa: E402
    _BAND,
    _LEADING_AGE,
    NO_AGE_IN_NAME,
    ODD_YEAR_SPAN,
    age_from_name,
    board_cohort,
    respell_ages,
    split_club,
)
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher, club_before_squad_marks  # noqa: E402
from src.tournaments.reports.render_csv import csv_safe  # noqa: E402
from src.utils.provider_ids import clean_provider_id  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402
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

PROVIDER_CODE = "tourneycentral"
OUTPUT_DIR = Path("data/raw/tourneycentral")

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
    "tc_team_id",
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

# Fewer band-named teams than this say nothing about which season a tournament labels by.
MIN_BAND_NAMED_TEAMS = 5

# ``age_from_name`` names the division it would have fallen back to; with no division
# passed, these names state no age at all, and the team is left for a person to decide.
NAME_WITHOUT_AN_AGE = {
    NO_AGE_IN_NAME: "no age in the team name",
    ODD_YEAR_SPAN: "odd year span in the team name",
}

# ASCII-bound: under IGNORECASE alone the Unicode fold of U+017F matches an "s", and
# \d admits non-ASCII digits.
_EVENT_URL = re.compile(r"^https?://(([a-z0-9][a-z0-9-]*)\.tourneycentral\.com)(?:/\S*)?$", re.IGNORECASE | re.ASCII)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# B11Gold, B107v7Gold, B129v9Red, G14-15Gold, and the U-spelling BU9Gold, GU11Premier,
# BU1415Black, and the spelled-out BoysU13Red, GirlsU1314Red. A pair written without its
# hyphen may not run into a format (B1011v11 is U10 11v11), and parse_division_code holds
# it to consecutive ages and every age to U19, so a birth-year code such as B2015Gold or
# B2021Gold is refused rather than read as ages.
_DIVISION_CODE = re.compile(
    r"^([BG])(?:oys|irls)?U?(\d{1,2})(?:-(\d{2})|(\d{2})(?!\s*v))?\s*(?:(\d{1,2})\s*v\s*\d{1,2})?(?:\D.*)?$",
    re.IGNORECASE | re.ASCII,
)
OLDEST_BOARD_AGE = 19
# A team id and a game number reach a database write, so both are ASCII digits of bounded length.
_TEAM_ID = re.compile(r"[1-9][0-9]{0,9}")
_BOARD_AGE_GROUP = re.compile(r"u1[0-9]")
_GENDERS = {"male": "Male", "female": "Female"}
_GAME_NO = re.compile(r"[0-9]{1,5}")
_TEAM_LINK_ID = re.compile(r"[?&]t=([0-9]+)")
_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)
_NO_CLUB = re.compile(r"^tournament\s+only\b", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\([^)]*\)")


@dataclass
class Event:
    host: str
    subdomain: str
    name: str
    start: date
    end: date

    @property
    def season(self) -> int:
        """The Aug 1 season the tournament was played in, never the wall clock's."""
        return _soccer_season_year(datetime(self.start.year, self.start.month, self.start.day))


@dataclass
class Division:
    code: str
    gender: str
    young_age: int
    old_age: int
    players: Optional[int]


@dataclass
class TeamListing:
    tc_team_id: str
    team_name: str
    club: str
    location: str
    coach: str


@dataclass
class TeamRow:
    tc_team_id: str
    team_name: str
    club_name: Optional[str]
    club_as_written: Optional[str]
    division_name: str
    division_age: str
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
    division_code: str
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

    Raised rather than returned so the run fails: a division whose page did not load
    must not read as a division with no games.
    """


class LabelSeasonError(RuntimeError):
    """The tournament's division labels name the season after the one it was played in."""


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retries = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def _encoding(response: requests.Response) -> str:
    """The encoding a browser would read the page with.

    Tourney Central sends a bare text/html and declares its charset only in the page's
    ``<meta>``, which ``requests`` never reads. A declared ISO-8859-1 (or ASCII) is read
    as windows-1252, as browsers read it: the registration form submits a curly
    apostrophe or dash as its windows-1252 byte, which strict ISO-8859-1 turns into a
    control character inside the team's name.
    """
    if "charset" in str(response.headers.get("content-type", "")).lower():
        name = response.encoding or "utf-8"
    else:
        meta = _META_CHARSET.search(response.content[:2048])
        name = meta.group(1).decode("ascii") if meta else "utf-8"
    try:
        name = codecs.lookup(name).name
        # Not b"": decoding nothing skips the check that refuses a non-text codec such as hex.
        b" ".decode(name, errors="replace")
    except LookupError:
        return "utf-8"
    return "cp1252" if name in ("iso8859-1", "ascii") else name


def _fetch(session: requests.Session, url: str) -> str:
    """The page at ``url`` as text; anything but a 200 raises :class:`ScrapeFetchError`."""
    try:
        response = session.get(url, timeout=90)
    except requests.RequestException as e:
        raise ScrapeFetchError(f"request failed for {url}: {e}") from e
    if response.status_code != 200:
        raise ScrapeFetchError(f"HTTP {response.status_code} for {url}")
    return response.content.decode(_encoding(response), errors="replace")


def parse_event_url(url: str) -> Tuple[str, str]:
    """Any page of a tournament -> ``("wfc.tourneycentral.com", "wfc")``."""
    match = _EVENT_URL.match((url or "").strip())
    if not match:
        raise ValueError(
            f"not a Tourney Central tournament URL: {url!r} (expected https://<tournament>.tourneycentral.com/...)"
        )
    return match.group(1).lower(), match.group(2).lower()


def games_page_url(host: str) -> str:
    return f"https://{host}/games.html"


def team_list_url(host: str, code: str) -> str:
    return f"https://{host}/cgi-bin/teams.cgi?fnc=adiv&t_div={quote(code)}"


def schedule_url(host: str, code: str) -> str:
    return f"https://{host}/cgi-bin/teams.cgi?fnc=sked&sny=Y&t_div={quote(code)}"


def _clean_name(name: str) -> str:
    return " ".join((name or "").replace("\xa0", " ").split())


# ── Tournament, divisions and teams ────────────────────────────────────────────


def parse_games_page(html: str, host: str, subdomain: str) -> Tuple[Event, List[str]]:
    """The tournament and its division codes; its play dates date the season."""
    soup = BeautifulSoup(html, "lxml")
    values = [option["value"].strip() for option in soup.find_all("option", value=True)]
    dates = sorted({date.fromisoformat(value) for value in values if _ISO_DATE.fullmatch(value)})
    if not dates:
        raise ScrapeFetchError(f"no play dates on {games_page_url(host)}")
    select = soup.find("select", attrs={"name": "t_div"})
    codes = [
        option["value"].strip()
        for option in (select.find_all("option", value=True) if select else [])
        if option["value"].strip()
    ]
    if not codes:
        raise ScrapeFetchError(f"no divisions on {games_page_url(host)}")
    title = soup.find("title")
    event = Event(
        host=host,
        subdomain=subdomain,
        name=_clean_name(title.get_text(" ")) if title else f"Tourney Central {subdomain}",
        start=dates[0],
        end=dates[-1],
    )
    return event, codes


def parse_division_code(code: str) -> Optional[Division]:
    """``G14-15Gold`` or ``GU1415Gold`` -> Female, U14 to U15; None for a code of another shape."""
    match = _DIVISION_CODE.match((code or "").strip())
    if not match:
        return None
    young_age = int(match.group(2))
    if match.group(4):
        old_age = int(match.group(4))
        if old_age != young_age + 1:
            return None
    else:
        old_age = int(match.group(3) or young_age)
    if old_age < young_age or old_age > OLDEST_BOARD_AGE:
        return None
    return Division(
        code=code.strip(),
        gender="Male" if match.group(1).upper() == "B" else "Female",
        young_age=young_age,
        old_age=old_age,
        players=int(match.group(5)) if match.group(5) else None,
    )


def skip_division(division: Division) -> Optional[str]:
    if division.old_age <= 9:
        return "U9 and below: no board"
    if division.players is not None and division.players <= 6:
        return "small-sided"
    return None


def _cell_lines(cell) -> List[str]:
    """The cell's text, one entry per ``<br>``-separated line."""
    lines: List[List[str]] = [[]]
    for node in cell.children:
        if getattr(node, "name", None) == "br":
            lines.append([])
        else:
            lines[-1].append(node.get_text(" ") if hasattr(node, "get_text") else str(node))
    return [_clean_name(" ".join(parts)) for parts in lines]


def _has_header(soup: BeautifulSoup, text: str) -> bool:
    return any(_clean_name(cell.get_text(" ")) == text for cell in soup.find_all("td"))


def parse_team_list(html: str, division: Division, source_url: str) -> Tuple[List[TeamListing], List[str]]:
    """Every team of a division's team list, and the rows that could not be read.

    The name cell is ``<b>name</b> [website link] <br> <i>club</i> <br> City, ST``;
    the club line is missing on some rows, so the location is the last line unless
    that line is the club. A page without the list's header is not a team list.
    """
    soup = BeautifulSoup(html, "lxml")
    if not _has_header(soup, "Team/Location"):
        raise ScrapeFetchError(f"{division.code}: no team list on {source_url}")
    listings: List[TeamListing] = []
    problems: List[str] = []
    for field in soup.select('input[name="t"]'):
        row = field.find_parent("tr")
        name_cell = next((cell for cell in row.find_all("td", recursive=False) if cell.find("b")), None)
        tc_team_id = clean_provider_id(field.get("value"))
        if name_cell is None or not _TEAM_ID.fullmatch(tc_team_id):
            problems.append(f"{division.code}: unreadable team row {tc_team_id!r}")
            continue
        club_tag = name_cell.find("i")
        club = _clean_name(club_tag.get_text(" ")) if club_tag else ""
        lines = _cell_lines(name_cell)
        location = lines[-1] if len(lines) > 1 and lines[-1] != club else ""
        coach_cell = name_cell.find_next_sibling("td")
        listings.append(
            TeamListing(
                tc_team_id=tc_team_id,
                team_name=_clean_name(name_cell.find("b").get_text(" ")),
                club=club,
                location=location,
                coach=_clean_name(coach_cell.get_text(" ")) if coach_cell else "",
            )
        )
    return listings, problems


def _team_id(cell) -> str:
    link = cell.find("a", href=_TEAM_LINK_ID)
    tc_team_id = _TEAM_LINK_ID.search(link["href"]).group(1) if link else ""
    return tc_team_id if _TEAM_ID.fullmatch(tc_team_id) else ""


def parse_schedule(html: str, division: Division, source_url: str) -> Tuple[List[EventGame], List[str]]:
    """Every scored game of a division's schedule, with both teams' ids.

    The columns are blank, No., Div, Time, Field, Home, home score, away score, Away,
    a separator and Type. A team cell's text carries the pool seed ("A2 - ..."), so
    only its link is read; names come from the team list. A page without the
    schedule's header is not a schedule, so it stops the run rather than reading as
    a division with no games. A page can print a game twice (Party on the Pitch's
    BU10Bronze lists games 37 and 40 twice); the game number is unique to the
    tournament, so the repeat is dropped, and reported when its details differ.
    """
    soup = BeautifulSoup(html, "lxml")
    games: List[EventGame] = []
    by_number: Dict[str, EventGame] = {}
    problems: List[str] = []
    header = next((cell for cell in soup.find_all("td") if _clean_name(cell.get_text(" ")) == "No."), None)
    if header is None:
        raise ScrapeFetchError(f"{division.code}: no schedule on {source_url}")
    game_date: Optional[date] = None
    for row in header.find_parent("table").find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) == 1 and cells[0].get("colspan") and cells[0].find("b"):
            heading = _clean_name(cells[0].get_text(" "))
            try:
                game_date = datetime.strptime(heading, "%A, %b %d, %Y").date()
            except ValueError:
                game_date = None
                problems.append(f"{division.code}: unreadable day {heading!r}")
            continue
        if len(cells) < 9 or not _GAME_NO.fullmatch(_clean_name(cells[1].get_text(" "))):
            continue
        game_no = _clean_name(cells[1].get_text(" "))
        home_id, away_id = _team_id(cells[5]), _team_id(cells[8])
        home_score, away_score = (_clean_name(cells[i].get_text(" ")) for i in (6, 7))
        if not (home_id and away_id):
            problems.append(f"{division.code} game {game_no}: unfilled bracket slot")
            continue
        if not (re.fullmatch(r"[0-9]{1,2}", home_score) and re.fullmatch(r"[0-9]{1,2}", away_score)):
            problems.append(f"{division.code} game {game_no}: no score")
            continue
        if game_date is None:
            problems.append(f"{division.code} game {game_no}: no date")
            continue
        game = EventGame(
            division_code=division.code,
            game_no=game_no,
            game_date=game_date,
            game_time=_clean_name(cells[3].get_text(" ")),
            venue=_clean_name(cells[4].get_text(" ")),
            home_id=home_id,
            home_score=int(home_score),
            away_id=away_id,
            away_score=int(away_score),
            source_url=source_url,
        )
        if game_no in by_number:
            if game != by_number[game_no]:
                problems.append(f"{division.code} game {game_no}: listed twice with different details")
            continue
        by_number[game_no] = game
        games.append(game)
    return games, problems


# ── Age, club and state ────────────────────────────────────────────────────────


def _band_younger_year(team_name: str, event_season: int) -> Optional[int]:
    for match in _BAND.finditer(respell_ages(team_name)):
        pair = {2000 + int(match.group(1)), 2000 + int(match.group(2))}
        if len(pair) == 2 and max(pair) - min(pair) == 1 and max(pair) <= event_season - 6:
            return max(pair)
    return None


def label_season_mismatch(listings: List[Tuple[Division, TeamListing]], event_season: int) -> Optional[str]:
    """Why the tournament's labels read as the coming season, or None.

    A band in a team name ("B15/16") names birth years, so it reads the same in any
    season, while a division label names a cohort only against the season it was
    written in. Most teams play their own age and some play up, so under the right
    season the bands sit mostly at their division's age. A tournament labelled by the
    coming season puts most of them one year below it instead. Judged over the whole
    tournament: one division is too small to tell playing up from mislabelling.
    """
    band_named = at_age = one_below = 0
    for division, listing in listings:
        younger = _band_younger_year(listing.team_name, event_season)
        if younger is None:
            continue
        band_named += 1
        u_age = event_season - younger + 1
        if division.young_age <= u_age <= division.old_age:
            at_age += 1
        elif u_age == division.young_age - 1:
            one_below += 1
    if band_named < MIN_BAND_NAMED_TEAMS or one_below <= at_age:
        return None
    return (
        f"{one_below} band-named teams sit one year below their division and {at_age} at it, "
        f"so the labels read as the season after {event_season}-{(event_season + 1) % 100:02d}"
    )


def club_for(club_cell: str, team_name: str, host: str) -> Tuple[Optional[str], Optional[str]]:
    """``(club the team is filed under, club as its name writes it)``.

    The team list's club field is the club, except where it is blank or says the
    team was entered for this tournament only; the name's own club stands in then.

    The written club is what the squad gates strip from both names, so taking too
    much of the name strips the squad marks with it: "Worthington United Navy 1 U14"
    must lose "Worthington United", not "Navy 1". Where the club field opens the name,
    that prefix is the written club, whole. Otherwise it is guessed: the words before the
    first age token, league tag or comma, a bare band such as "13/14" included, then cut
    back before any squad mark.
    """
    _, guessed = split_club(respell_ages(team_name), host)
    band = _BAND.search(guessed or "")
    if band:
        guessed = _clean_name(guessed[: band.start()]).strip(" -,") or None
    club = _clean_name(club_cell)
    if not club or _NO_CLUB.match(club):
        return guessed, club_before_squad_marks(guessed)
    body = _LEADING_AGE.sub("", team_name)
    for spelling in (club, _clean_name(_PARENTHETICAL.sub(" ", club))):
        if spelling and re.match(rf"{re.escape(spelling)}(?![A-Za-z0-9])", body, re.IGNORECASE):
            return club, body[: len(spelling)]
    return club, club_before_squad_marks(guessed)


def state_from_location(location: str) -> Optional[str]:
    """The one US state a ``City, ST`` location names; None for none, or for two."""
    codes = {part.strip().upper() for part in (location or "").split(",")[1:]}
    states = {code for code in codes if code in STATE_CODE_TO_NAME}
    return states.pop() if len(states) == 1 else None


# ── Roster ─────────────────────────────────────────────────────────────────────


def build_roster(
    listings: List[Tuple[Division, TeamListing]],
    event: Event,
    board_season: int,
    leave_out: FrozenSet[str] = frozenset(),
    states: Optional[Dict[str, str]] = None,
    age_groups: Optional[Dict[str, str]] = None,
    genders: Optional[Dict[str, str]] = None,
) -> Tuple[List[TeamRow], List[TeamRow]]:
    """Split the tournament's teams into those to register and those skipped, with a reason.

    The operator names teams by Tourney Central id: ``leave_out`` holds them back, such as a
    name whose age only a person can settle, and ``states`` sets a team's state where its
    location is wrong (CUSC West entered Party on the Pitch from "Fairfield, AL"; Fairfield
    is a city in both states, so no rule can see it). ``age_groups`` files a team whose name
    states no age on the board a person named, and ``genders`` sets the gender of a girls or boys
    team entered in a division of the other gender.
    """
    states = states or {}
    age_groups = age_groups or {}
    genders = genders or {}
    in_scope: List[TeamRow] = []
    skipped: List[TeamRow] = []
    seen: Set[str] = set()
    for division, listing in sorted(listings, key=lambda item: int(item[1].tc_team_id or 0)):
        if not listing.tc_team_id or listing.tc_team_id in seen:
            continue
        seen.add(listing.tc_team_id)
        team_name = _clean_name(listing.team_name)
        birth_year, age_source = (
            age_from_name(respell_ages(team_name), None, event.season) if team_name else (None, "unreadable team name")
        )
        age_source = NAME_WITHOUT_AN_AGE.get(age_source, age_source)
        if listing.tc_team_id in age_groups:
            birth_year = _birth_year_on_board(age_groups[listing.tc_team_id], event.season)
            age_source = "set by the operator"
        club_name, club_as_written = club_for(listing.club, team_name, event.host) if team_name else (None, None)
        cohort = board_cohort(birth_year, board_season) if birth_year else None
        ages = (
            f"u{division.young_age}"
            if division.young_age == division.old_age
            else f"u{division.young_age}-u{division.old_age}"
        )
        row = TeamRow(
            tc_team_id=listing.tc_team_id,
            team_name=team_name,
            club_name=club_name,
            club_as_written=club_as_written,
            division_name=division.code,
            division_age=ages,
            birth_year=birth_year if cohort else None,
            age_group=cohort,
            age_source=age_source,
            gender=genders.get(listing.tc_team_id, division.gender),
            state_code=states.get(listing.tc_team_id) or state_from_location(listing.location),
            coach=listing.coach,
        )
        if listing.tc_team_id in leave_out:
            row.skip_reason = "left out by the operator"
        elif not team_name:
            row.skip_reason = "team name could not be read"
        elif not birth_year:
            row.skip_reason = age_source
        elif not cohort:
            row.skip_reason = f"birth year {birth_year} is on no U10-U19 board"
        elif not row.state_code:
            row.skip_reason = f"no US state in the location {listing.location!r}"
        (skipped if row.skip_reason else in_scope).append(row)
    return in_scope, skipped


def _birth_year_on_board(age_group: str, season: int) -> int:
    """The band's younger year that sits on ``u10``-``u19`` in ``season``."""
    return season - int(age_group[1:]) + 1


def existing_aliases(supabase, provider_id: str, tc_team_ids: List[str]) -> Dict[str, str]:
    """Tourney Central team id -> team_id_master for teams already linked."""
    found: Dict[str, str] = {}
    for i in range(0, len(tc_team_ids), 100):
        batch = tc_team_ids[i : i + 100]
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
    """Link or create every roster team; one :class:`Outcome` per Tourney Central team id."""
    outcomes: Dict[str, Outcome] = {}
    for row in roster:
        if row.tc_team_id in already:
            outcomes[row.tc_team_id] = Outcome("already_linked", already[row.tc_team_id], 1.0)
            continue
        try:
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=row.tc_team_id,
                team_name=row.team_name,
                age_group=row.age_group,
                gender=row.gender,
                club_name=row.club_name,
                state_code=row.state_code,
                written_club=row.club_as_written,
            )
        except Exception as e:
            logger.error(f"match error for Tourney Central team {row.tc_team_id}: {e}")
            outcomes[row.tc_team_id] = Outcome("error", reason=str(e))
            continue

        if result.get("created"):
            outcomes[row.tc_team_id] = Outcome("created", result["team_id"], 1.0)
        elif result.get("relinked"):
            outcomes[row.tc_team_id] = Outcome("relinked", result["team_id"], 1.0)
        elif result.get("matched"):
            status = "linked_existing" if result.get("method") == "fuzzy_auto" else "already_linked"
            outcomes[row.tc_team_id] = Outcome(status, result["team_id"], result.get("confidence"))
        elif result.get("review"):
            outcomes[row.tc_team_id] = Outcome("review", confidence=result.get("confidence"))
        else:
            outcomes[row.tc_team_id] = Outcome("error", reason=f"unclassified result: method={result.get('method')}")
    return outcomes


def unsaved_links(outcomes: Dict[str, Outcome], saved: Dict[str, str]) -> Dict[str, str]:
    """Teams reported linked or created whose approved alias is missing or points elsewhere.

    The matcher logs a failed alias write and still reports the team linked, and a
    game whose one team has no alias imports half-matched.
    """
    return {
        tc_team_id: "link was not saved"
        for tc_team_id, outcome in outcomes.items()
        if outcome.status in ("linked_existing", "relinked", "created")
        and saved.get(tc_team_id) != outcome.team_id_master
    }


def pending_reviews(supabase, tc_team_ids: List[str]) -> Set[str]:
    """Tourney Central team ids with a pending review row."""
    found: Set[str] = set()
    for i in range(0, len(tc_team_ids), 100):
        result = (
            supabase.table("team_match_review_queue")
            .select("provider_team_id")
            .eq("provider_id", PROVIDER_CODE)
            .eq("status", "pending")
            .in_("provider_team_id", tc_team_ids[i : i + 100])
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
        tc_team_id: "review item was not saved"
        for tc_team_id, outcome in outcomes.items()
        if outcome.status == "review" and tc_team_id not in pending
    }


def shared_links(outcomes: Dict[str, Outcome]) -> Dict[str, str]:
    """Teams of this tournament that matched the same PitchRank team as another one.

    Two registrations in one tournament are two squads, so at most one of them can
    be that team. Every fuzzy-linked team in such a group is reported; a team whose
    alias was already approved, or whose own row carries its provider id, keeps it.
    """
    by_team: Dict[str, List[str]] = {}
    for tc_team_id, outcome in outcomes.items():
        if outcome.status in ("already_linked", "linked_existing", "relinked"):
            by_team.setdefault(outcome.team_id_master, []).append(tc_team_id)
    conflicts: Dict[str, str] = {}
    for _, tc_team_ids in by_team.items():
        if len(tc_team_ids) < 2:
            continue
        for tc_team_id in tc_team_ids:
            if outcomes[tc_team_id].status == "linked_existing":
                others = ", ".join(sorted(set(tc_team_ids) - {tc_team_id}))
                conflicts[tc_team_id] = f"same PitchRank team as Tourney Central team {others}"
    return conflicts


def off_board_links(roster: List[TeamRow], outcomes: Dict[str, Outcome], teams: Dict[str, Dict]) -> Dict[str, str]:
    """Linked teams whose stored row disagrees with this team: no row, another board or another gender.

    The game import does not re-check a link's age or gender (``_match_by_provider_id``
    on this provider skips both), so the check happens here: a linked team whose stored board differs
    from the board this team's name puts it on is a link to the wrong squad, or a
    stored age the name contradicts, and either way its games wait for a person. A
    team this run creates takes the name's board.
    """
    refused: Dict[str, str] = {}
    for row in roster:
        outcome = outcomes[row.tc_team_id]
        if outcome.status not in ("already_linked", "linked_existing", "relinked"):
            continue
        team = teams.get(outcome.team_id_master)
        if team is None:
            refused[row.tc_team_id] = "linked team not found"
            continue
        team_age = (team.get("age_group") or "").lower()
        if team_age and team_age != row.age_group:
            refused[row.tc_team_id] = f"linked team is on the {team_age} board, this team is {row.age_group}"
        elif team.get("gender") and team["gender"] != row.gender:
            refused[row.tc_team_id] = f"linked team is {team['gender']}, this team is {row.gender}"
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
    rows_by_id = {row.tc_team_id: row for row in roster}
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
                    "division": game.division_code,
                    "home_team_id": home.tc_team_id,
                    "home_team_name": home.team_name,
                    "home_age_group": home.age_group,
                    "home_gender": home.gender,
                    "home_team_id_master": outcomes[home.tc_team_id].team_id_master or "",
                    "away_team_id": away.tc_team_id,
                    "away_team_name": away.team_name,
                    "away_age_group": away.age_group,
                    "away_gender": away.gender,
                    "away_team_id_master": outcomes[away.tc_team_id].team_id_master or "",
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "source_url": game.source_url,
                }
            )
        base = {
            "provider": PROVIDER_CODE,
            "scrape_run_id": SCRAPE_RUN_ID,
            "event_id": f"{event.subdomain}-{event.season}",
            "event_name": f"{event.name} - {game.division_code}",
            "schedule_id": f"{event.subdomain}-{game.game_no}",
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
                    "team_id": team.tc_team_id,
                    "team_id_source": team.tc_team_id,
                    "team_name": team.team_name,
                    "club_name": team.club_name or "",
                    "opponent_id": opponent.tc_team_id,
                    "opponent_id_source": opponent.tc_team_id,
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


def _for_spreadsheets(rows: List[Dict]) -> List[Dict]:
    return [{column: csv_safe(value) for column, value in row.items()} for row in rows]


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
        outcome = outcomes.get(row.tc_team_id, Outcome("skipped", reason=row.skip_reason or ""))
        rows.append(
            {
                "tc_team_id": row.tc_team_id,
                "team_name": row.team_name,
                "club_name": row.club_name or "",
                "division": row.division_name,
                "division_age": row.division_age,
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
        help="Any page of the tournament, e.g. https://wfc.tourneycentral.com/games.html",
    )
    p.add_argument("--days-back", type=int, default=14, help="Import games dated within this many days (default 14)")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the CSVs and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between page fetches")
    p.add_argument("--delay-max", type=float, default=2.0, help="Maximum seconds between page fetches")
    p.add_argument("--execute", action="store_true", help="Write teams, aliases and games (default is a dry run)")
    p.add_argument(
        "--leave-out",
        nargs="+",
        default=[],
        type=_leave_out_id,
        metavar="TEAM_ID",
        help="Tourney Central team ids to leave out, such as a name whose age a person must settle",
    )
    p.add_argument(
        "--state",
        nargs="+",
        default=[],
        type=_state_for_team,
        metavar="TEAM_ID=ST",
        help="Set a team's US state where its listed location is wrong, e.g. 316490=OH",
    )
    p.add_argument(
        "--age",
        nargs="+",
        default=[],
        type=_age_for_team,
        metavar="TEAM_ID=uNN",
        help="File a team whose name states no age on a board a person named, e.g. 314847=u10",
    )
    p.add_argument(
        "--gender",
        nargs="+",
        default=[],
        type=_gender_for_team,
        metavar="TEAM_ID=Male|Female",
        help="Set a team's gender where it entered a division of the other gender, e.g. 317937=Female",
    )
    return p.parse_args()


def _leave_out_id(value: str) -> str:
    if not _TEAM_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not a Tourney Central team id: {value!r}")
    return value


def _state_for_team(value: str) -> Tuple[str, str]:
    team_id, _, state = value.partition("=")
    state = state.upper()
    if not _TEAM_ID.fullmatch(team_id) or state not in STATE_CODE_TO_NAME:
        raise argparse.ArgumentTypeError(f"not TEAM_ID=ST with a US state code: {value!r}")
    return team_id, state


def _age_for_team(value: str) -> Tuple[str, str]:
    team_id, _, age_group = value.partition("=")
    age_group = age_group.lower()
    if not _TEAM_ID.fullmatch(team_id) or not _BOARD_AGE_GROUP.fullmatch(age_group):
        raise argparse.ArgumentTypeError(f"not TEAM_ID=uNN with an age from u10 to u19: {value!r}")
    return team_id, age_group


def _gender_for_team(value: str) -> Tuple[str, str]:
    team_id, _, gender = value.partition("=")
    if not _TEAM_ID.fullmatch(team_id) or gender.lower() not in _GENDERS:
        raise argparse.ArgumentTypeError(f"not TEAM_ID=Male or TEAM_ID=Female: {value!r}")
    return team_id, _GENDERS[gender.lower()]


def collect_event(
    fetch_html: Callable[[str], str],
    host: str,
    subdomain: str,
    board_season: int,
    days_back: int,
    today: date,
    pause: Callable[[], None] = lambda: None,
    leave_out: FrozenSet[str] = frozenset(),
    states: Optional[Dict[str, str]] = None,
    age_groups: Optional[Dict[str, str]] = None,
    genders: Optional[Dict[str, str]] = None,
) -> Tuple[Event, List[TeamRow], List[TeamRow], List[EventGame], List[str], List[str]]:
    """Fetch the tournament and its divisions; return the roster, the games in window,
    the problems found and the divisions skipped.

    Raises :class:`LabelSeasonError` before returning any roster when the
    tournament's labels name the coming season.
    """
    event, codes = parse_games_page(fetch_html(games_page_url(host)), host, subdomain)
    pause()

    problems: List[str] = []
    division_skips: List[str] = []
    listings: List[Tuple[Division, TeamListing]] = []
    games: List[EventGame] = []
    for code in codes:
        division = parse_division_code(code)
        if division is None:
            problems.append(f"{code}: unreadable division code")
            continue
        reason = skip_division(division)
        if reason:
            division_skips.append(f"{code}: {reason}")
            continue
        url = team_list_url(host, code)
        division_listings, list_problems = parse_team_list(fetch_html(url), division, url)
        pause()
        url = schedule_url(host, code)
        division_games, schedule_problems = parse_schedule(fetch_html(url), division, url)
        pause()
        listings.extend((division, listing) for listing in division_listings)
        games.extend(division_games)
        problems.extend(list_problems + schedule_problems)

    mismatch = label_season_mismatch(listings, event.season)
    if mismatch:
        raise LabelSeasonError(mismatch)

    in_scope, skipped = build_roster(listings, event, board_season, leave_out, states, age_groups, genders)
    earliest = today - timedelta(days=days_back)
    in_window = [g for g in games if earliest <= g.game_date <= today]
    return event, in_scope, skipped, in_window, problems, division_skips


def main() -> int:
    args = parse_args()
    dry_run = not args.execute
    try:
        host, subdomain = parse_event_url(args.event_url)
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

    try:
        event, in_scope, skipped, games, problems, division_skips = collect_event(
            lambda url: _fetch(session, url),
            host,
            subdomain,
            _soccer_season_year(),
            args.days_back,
            date.today(),
            pause,
            frozenset(args.leave_out),
            dict(args.state),
            dict(args.age),
            dict(args.gender),
        )
    except (ScrapeFetchError, LabelSeasonError) as e:
        console.print(f"[red]{escape(str(e))}[/red]\nNothing was registered or written.")
        return 1
    named = set(args.leave_out)
    for option in (args.state, args.age, args.gender):
        named |= {team_id for team_id, _ in option}
    unknown = sorted(named - {row.tc_team_id for row in in_scope + skipped})
    if unknown:
        console.print(f"[yellow]Team ids named but not in this tournament: {', '.join(unknown)}[/yellow]")
    console.print(
        f"[bold]{escape(event.name)}[/bold] ({event.start.isoformat()} to {event.end.isoformat()}) — "
        f"{len(in_scope) + len(skipped)} teams, {len(in_scope)} in scope, {len(skipped)} left out"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )

    already = existing_aliases(supabase, provider_id, [row.tc_team_id for row in in_scope])
    preview = register_teams(
        TourneyCentralGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
    )
    conflicts = shared_links(preview)
    if dry_run:
        outcomes = preview
    else:
        writer = TourneyCentralGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer, provider_id, [row for row in in_scope if row.tc_team_id not in conflicts], already
        )
        saved = existing_aliases(supabase, provider_id, list(outcomes))
        for tc_team_id, reason in unsaved_links(outcomes, saved).items():
            outcomes[tc_team_id] = Outcome("error", outcomes[tc_team_id].team_id_master, reason=reason)
        queued = pending_reviews(supabase, [i for i, o in outcomes.items() if o.status == "review"])
        for tc_team_id, reason in unsaved_reviews(outcomes, queued).items():
            outcomes[tc_team_id] = Outcome("error", confidence=outcomes[tc_team_id].confidence, reason=reason)
    for tc_team_id, reason in conflicts.items():
        proposed = preview[tc_team_id]
        outcomes[tc_team_id] = Outcome("conflict", proposed.team_id_master, proposed.confidence, reason)
    teams = teams_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    for tc_team_id, reason in off_board_links(in_scope, outcomes, teams).items():
        outcomes[tc_team_id] = Outcome("error", outcomes[tc_team_id].team_id_master, reason=reason)

    records, held, cross_age = build_csv_rows(games, in_scope + skipped, outcomes, event)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{subdomain}_{event.season}_{stamp}"
    games_csv = args.output_dir / f"{prefix}_games.csv"
    cross_age_csv = args.output_dir / f"{prefix}_cross_age.csv"
    report_csv = args.output_dir / f"{prefix}_teams.csv"
    names = {team_id: team["team_name"] for team_id, team in teams.items()}
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    # The two files a person opens carry registrant-typed names, so a leading = + - @ is defanged
    # there; the importer's own file keeps every name as written.
    write_csv(cross_age_csv, CROSS_AGE_COLUMNS, _for_spreadsheets(cross_age))
    write_csv(report_csv, REPORT_COLUMNS, _for_spreadsheets(report_rows(in_scope, skipped, outcomes, names)))

    summary = Table(title=f"Tourney Central: {escape(event.name)} ({host})")
    summary.add_column("")
    summary.add_column("Count", justify="right")
    for status in ("already_linked", "linked_existing", "relinked", "created", "review", "conflict", "error"):
        summary.add_row(status, str(sum(1 for o in outcomes.values() if o.status == status)))
    summary.add_row("teams left out", str(len(skipped)))
    summary.add_row("divisions skipped", str(len(division_skips)))
    summary.add_row("games in window", str(len(games)))
    summary.add_row("games to import", str(len(records) // 2))
    summary.add_row("games held back", str(len(held)))
    summary.add_row("cross-age games imported", str(len(cross_age)))
    summary.add_row("problems", str(len(problems)))
    console.print(summary)
    for line in division_skips + problems:
        console.print(f"  [yellow]{escape(line)}[/yellow]")
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
