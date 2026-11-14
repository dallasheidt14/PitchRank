#!/usr/bin/env python3
"""Register the Heartland Soccer Premier league's teams and import its scored games.

Heartland Soccer Association (heartlandsoccer.net) runs the Kansas City league, with clubs on
both sides of the Kansas/Missouri line. One public CGI page per division and subdivision feeds
this script:

- ``reports/cgi-jrb/subdiv_results.cgi?level=Premier&b_g=<Boys|Girls>&age=<U-12>&subdivison=<n>``
  lists the subdivision's teams, then one row per game: the date (``Aug 9 (Sun)``, no year,
  printed on the first game of its day), the game number, the time, the home team and its score,
  the visitor and its score. Every team reads ``<4-character team number> <name>``. A division
  and subdivision the league does not run answers a "Select Subdivision Error" page.

Only the Premier level is read, never the Recreational one. The site's other pages are never
fetched: its seedings and member-club pages list coaches', managers' and club officers' names,
emails and phone numbers, and nothing this script needs is there.

A team number belongs to one team for one half-season and is issued again the next, so the
provider team id is the half-season and the number (``2026fall-7210``), and a new season's team
starts unlinked and re-matches by name. A date's year is the season's year for its month, or the
year before, whichever puts it on the weekday the page prints.

A team's age comes from its own name; a name stating no age takes its division's age when the
division is one cohort (owner, 2026-11-14), and is left out in one spanning two (Boys U-14/15).
A bare or glued two-digit number (``15``, ``10B``) is not read as an age: Heartland names use
them for U-ages ("Manhattan Surf Blue 10B" plays U-10) as often as for birth years, so such a name
takes its division's age like a name with none (one with two of them is left out). A four-digit
year (``2016B``) is still the name's own.
Its club is the one ``HEARTLAND_CLUBS`` files its leading words under, else the words before its
age. Every team is matched against the stored teams of Kansas, Missouri and none, so a team linked
to one keeps that team's state. A team that would be created takes its club's state: one set in
that table, the club-state registry's Kansas or Missouri home, or the one state the club's stored
teams agree on there. A new team whose club has none of those is held for the owner (owner,
2026-11-14).

A game between two boards is imported and also listed in a cross-age file: a team playing up is
ordinary, and each side resolves through its own alias.

Dry run by default; ``--execute`` writes teams, aliases, review rows and games. The importer's games
CSV, and the team report, held and cross-age lists the owner reviews, are written either way (owner,
2026-11-14).

Usage:
    python scripts/import_heartland.py [--division "Boys U-12"] [--since 2026-08-01] [--execute]
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode

from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.table import Table  # noqa: E402

from scripts.import_athletes2events_event import _U_AGE, age_from_name, board_cohort  # noqa: E402
from scripts.import_demosphere import club_states  # noqa: E402
from scripts.import_tourneycentral_event import (  # noqa: E402
    CROSS_AGE_COLUMNS,
    LINKED_OUTCOMES,
    NAME_WITHOUT_AN_AGE,
    REQUIRED_COLUMNS,
    Division,
    Event,
    EventGame,
    Outcome,
    ScrapeFetchError,
    TeamRow,
    _clean_name,
    _division_fallback,
    _fetch,
    _for_spreadsheets,
    build_csv_rows,
    club_for,
    existing_aliases,
    make_session,
    off_board_links,
    pending_reviews,
    shared_links,
    teams_by_id,
    unsaved_links,
    unsaved_reviews,
    write_csv,
)
from src.models.heartland_matcher import REGION, HeartlandGameMatcher  # noqa: E402
from src.utils.club_state_registry import home_state, requires_review  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

PROVIDER_CODE = "heartland"
PROVIDER_NAME = "Heartland Soccer"
LEAGUE_NAME = "Heartland Soccer Premier League"
HOST = "heartlandsoccer.net"
RESULTS_URL = f"https://{HOST}/reports/cgi-jrb/subdiv_results.cgi"
OUTPUT_DIR = Path("data/raw/heartland")
SUBDIVISIONS = range(1, 14)
# No game before this date is imported, whatever season the pages or --since name (owner, 2026-11-14).
MIN_GAME_DATE = date(2026, 8, 1)

# Every Premier division with a board, as the site's own form spells it; U-9 has no board.
_AGES = ("U-10", "U-11", "U-12", "U-13", "U-14", "U-14/15", "U-15", "U-16", "U-17", "U-18/19")
DIVISIONS: Tuple[Tuple[str, str], ...] = tuple((gender, age) for gender in ("Boys", "Girls") for age in _AGES)
_GENDERS = {"Boys": "Male", "Girls": "Female"}

REPORT_COLUMNS = [
    "heartland_team_id",
    "team_name",
    "club_name",
    "club_source",
    "division",
    "division_age",
    "age_group",
    "age_source",
    "gender",
    "state_code",
    "state_source",
    "outcome",
    "team_id_master",
    "pitchrank_team_name",
    "confidence",
    "reason",
]
HELD_COLUMNS = ["reason", *CROSS_AGE_COLUMNS]

# What ``age_from_name`` reports for a name with two U-ages.
TWO_U_AGES = "two U-ages, left out"
_NO_SUCH_DIVISION = "Select Subdivision Error"
_RESULTS_HEADER = "Subdivision Results"
# ASCII-bound: a team number, a game number and a score reach a database write.
_TEAM_CELL = re.compile(r"([0-9A-Z]{4})\s+(\S.*)", re.ASCII)
_GAME_NO = re.compile(r"[0-9]{1,6}", re.ASCII)
_SCORE = re.compile(r"[0-9]{1,2}", re.ASCII)
_DAY = re.compile(r"([A-Za-z]{3})[A-Za-z]*\.?\s+([0-9]{1,2})\s+\(([A-Za-z]{2,9})\)", re.ASCII)
_DIVISION_AGES = re.compile(r"U-([0-9]{1,2})(?:/([0-9]{1,2}))?", re.ASCII)
# The site writes Thursday "Thr".
_WEEKDAYS = {
    spelling: index
    for index, spellings in enumerate(
        (("mon",), ("tue", "tues"), ("wed",), ("thu", "thr", "thur", "thurs"), ("fri",), ("sat",), ("sun",))
    )
    for spelling in spellings
}
_MONTHS = {name: number for number, name in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


@dataclass(frozen=True)
class HeartlandClub:
    """The club a team name's leading words are filed under.

    ``spellings`` are the other names the same club is stored under. Where the state falls to the
    stored teams, their states count with the club's own, so a club stored under two names in two
    states is held for the owner rather than filed by whichever spelling the name happens to use.
    ``state`` is one the owner set.
    """

    stored: str
    spellings: Tuple[str, ...] = ()
    state: Optional[str] = None


# Leading words of Heartland team names -> the club PitchRank stores, read from the stored teams of
# Kansas and Missouri on 2026-11-14.
HEARTLAND_CLUBS: Dict[str, HeartlandClub] = {
    "Sporting BV": HeartlandClub("Sporting Blue Valley", ("SPORTING BV", "SPORTING BV IP")),
    "SBV": HeartlandClub("Sporting Blue Valley", ("SPORTING BV", "SPORTING BV IP")),
    "Sporting City": HeartlandClub("Sporting City Soccer Club", ("Sporting City",)),
    "KC Athletics": HeartlandClub("Kansas City Athletics", ("KC Athletics",)),
    "KCA": HeartlandClub("Kansas City Athletics", ("KC Athletics",)),
    "Union KC": HeartlandClub("Union KC", ("Union KC Soccer Club",)),
    "KC Surf": HeartlandClub("Kansas City Surf", ("KC Surf",)),
    "KCL": HeartlandClub("KC Legends"),
    "KC Legends": HeartlandClub("KC Legends"),
    "Toca Fusion": HeartlandClub("Toca Fusion Athletic Club"),
    "BSSA": HeartlandClub("Blue Springs Soccer Academy"),
    "TSC": HeartlandClub("Topeka SC"),
    "Captains SC": HeartlandClub("Captains Soccer Club"),
    "OP": HeartlandClub("OP Soccer Club", ("OPSC",)),
    "Kansas Rush": HeartlandClub("Kansas Rush"),
    "Jambars FC": HeartlandClub("Jambars Futbol Club"),
    "SKV": HeartlandClub("Sporting Kaw Valley Soccer Club"),
    "Sporting Kaw": HeartlandClub("Sporting Kaw Valley Soccer Club"),
    "SportingKawValley": HeartlandClub("Sporting Kaw Valley Soccer Club"),
    "Alliance FC": HeartlandClub("Alliance Futbol Club (MO)"),
    "Virtus FC": HeartlandClub("Virtus Futbol Club"),
    "SLS": HeartlandClub("Sporting Lees Summit"),
    "SWMO Rush": HeartlandClub("Southwest MO Rush"),
    "KCFC": HeartlandClub("Kansas City FC"),
}


@dataclass
class HeartlandTeamRow(TeamRow):
    club_source: str = ""
    state_source: str = ""


@dataclass
class ResultsPage:
    """A subdivision's page: ``teams`` is its own team list, ``opponents`` the others its games name."""

    division: Division
    teams: Dict[str, str]
    games: List[EventGame]
    unscored: int
    problems: List[str]
    opponents: Dict[str, str] = field(default_factory=dict)


# ── Pages ──────────────────────────────────────────────────────────────────────


def results_url(gender: str, age: str, subdivision: int) -> str:
    return f"{RESULTS_URL}?{urlencode({'level': 'Premier', 'b_g': gender, 'age': age, 'subdivison': subdivision})}"


def division_for(gender: str, age: str, subdivision: int) -> Division:
    """``("Boys", "U-14/15", 2)`` -> Male, U14 to U15, coded as the page heads it."""
    ages = _DIVISION_AGES.fullmatch(age)
    if ages is None:
        raise ValueError(f"unreadable division age {age!r}")
    young = int(ages.group(1))
    return Division(
        code=f"{age} {gender} Premier Subdivision {subdivision}",
        gender=_GENDERS[gender],
        young_age=young,
        old_age=int(ages.group(2) or young),
        players=None,
    )


def _team_cell(text: str) -> Optional[Tuple[str, str]]:
    found = _TEAM_CELL.fullmatch(text)
    return (found.group(1), found.group(2)) if found else None


def game_date(label: str, season: int) -> Optional[date]:
    """``Aug 9 (Sun)`` in the season's year for that month, or the year before, whichever makes it a Sunday.

    The year before covers a site still showing the last season after Aug 1. A weekday moves one
    or two days a year, so at most one of the two years fits; neither fitting means the label is
    not a date.
    """
    found = _DAY.fullmatch(_clean_name(label))
    month = _MONTHS.get(found.group(1).title()) if found else None
    weekday = _WEEKDAYS.get(found.group(3).lower()) if found else None
    if month is None or weekday is None:
        return None
    year_of_season = season if month >= 8 else season + 1
    matches = []
    for year in (year_of_season, year_of_season - 1):
        try:
            day = date(year, month, int(found.group(2)))
        except ValueError:
            continue
        if day.weekday() == weekday:
            matches.append(day)
    return matches[0] if len(matches) == 1 else None


def parse_results_page(html: str, gender: str, age: str, subdivision: int, season: int) -> Optional[ResultsPage]:
    """A subdivision's teams and its games; None for a subdivision the league does not run.

    A page that is neither the "no such subdivision" answer nor a results page with its team list
    raises :class:`ScrapeFetchError`, so a page that did not load cannot read as a subdivision with
    no games, and its teams cannot quietly fall out of the roster.
    """
    url = results_url(gender, age, subdivision)
    if _NO_SUCH_DIVISION in html and _RESULTS_HEADER not in html:
        return None
    soup = BeautifulSoup(html, "lxml")
    games_table = soup.find("table", class_="seasonborder")
    if games_table is None or _RESULTS_HEADER not in games_table.get_text(" "):
        raise ScrapeFetchError(f"no results table in {url}")
    roster = soup.find("table", class_="text")
    if roster is None:
        raise ScrapeFetchError(f"no team list in {url}")
    division = division_for(gender, age, subdivision)
    page = ResultsPage(division=division, teams={}, games=[], unscored=0, problems=[])
    for cell in roster.find_all("td"):
        text = _clean_name(cell.get_text(" "))
        team = _team_cell(text)
        if team:
            page.teams[team[0]] = team[1]
        elif text:
            page.problems.append(f"{division.code}: unreadable team {text!r}")
    day: Optional[date] = None
    for row in games_table.find_all("tr", class_="text"):
        cells = [_clean_name(td.get_text(" ")) for td in row.find_all("td")]
        if len(cells) != 7:
            page.problems.append(f"{division.code}: unreadable game row {' | '.join(cells)[:60]!r}")
            # It may have been the first game of a new day; the games after it cannot keep the old one.
            day = None
            continue
        label, game_no, game_time, home_cell, home_score, away_cell, away_score = cells
        if label:
            day = game_date(label, season)
            if day is None:
                page.problems.append(f"{division.code}: unreadable date {label!r}")
        home, away = _team_cell(home_cell), _team_cell(away_cell)
        if day is None or not (home and away and _GAME_NO.fullmatch(game_no)):
            page.problems.append(f"{division.code}: unreadable game {game_no or home_cell[:30]!r}")
            continue
        for number, name in (home, away):
            if number not in page.teams:
                page.opponents.setdefault(number, name)
        if not home_score and not away_score:
            page.unscored += 1
            continue
        if not (_SCORE.fullmatch(home_score) and _SCORE.fullmatch(away_score)):
            page.problems.append(f"{division.code} game {game_no}: unreadable score {home_score!r}-{away_score!r}")
            continue
        page.games.append(
            EventGame(
                division_code=division.code,
                game_no=game_no,
                game_date=day,
                game_time=game_time,
                venue="",
                home_id=home[0],
                home_score=int(home_score),
                away_id=away[0],
                away_score=int(away_score),
                source_url=url,
            )
        )
    return page


def collect_league(
    fetch_html: Callable[[str], str],
    divisions: Tuple[Tuple[str, str], ...],
    season: int,
    pause: Callable[[], None] = lambda: None,
) -> List[ResultsPage]:
    """Subdivisions 1-13 of each given division, those the league runs."""
    pages: List[ResultsPage] = []
    for gender, age in divisions:
        for subdivision in SUBDIVISIONS:
            html = fetch_html(results_url(gender, age, subdivision))
            pause()
            page = parse_results_page(html, gender, age, subdivision, season)
            if page is not None:
                pages.append(page)
    return pages


# ── Season ─────────────────────────────────────────────────────────────────────


def half_season(game_dates: List[date]) -> Tuple[Optional[str], List[str]]:
    """``("2026fall", [])`` for games from August to December 2026; a run spanning two halves is a problem."""
    halves = sorted({f"{d.year}fall" if d.month >= 8 else f"{d.year}spring" for d in game_dates})
    if len(halves) > 1:
        return None, [f"the pages hold games from more than one half-season: {', '.join(halves)}"]
    return (halves[0] if halves else None), []


def provider_team_id(half: str, team_number: str) -> str:
    return f"{half}-{team_number}"


def window_start(since: Optional[date], event_season: int) -> date:
    return max(since or date(event_season, 8, 1), MIN_GAME_DATE)


# ── Roster ─────────────────────────────────────────────────────────────────────


def club_for_team(team_name: str) -> Tuple[Optional[str], Optional[str], str, Optional[HeartlandClub]]:
    """``(club as stored, club as the name writes it, source, table entry)`` for one team."""
    for written in sorted(HEARTLAND_CLUBS, key=len, reverse=True):
        if re.match(rf"{re.escape(written)}(?![A-Za-z0-9])", team_name, re.IGNORECASE):
            club = HEARTLAND_CLUBS[written]
            return club.stored, team_name[: len(written)], "club table", club
    guessed, written = club_for("", team_name, HOST)
    return guessed, written, "cut from name", None


def resolve_state(
    club_name: Optional[str], club: Optional[HeartlandClub], stored: Dict[str, Optional[str]]
) -> Tuple[Optional[str], str]:
    """``(state, source)``: the state a team would be created with; None, with the reason, holds a new team.

    The club-state registry's home outranks the club's stored teams (owner, 2026-11-14: Sporting
    Blue Valley is Kansas though some of its teams are stored in Missouri), but only a home inside
    the region: a club cut from a name can share a registry key with a club elsewhere.
    """
    if club and club.state:
        return club.state, "set for the club"
    home = home_state(club_name)
    if home in REGION:
        return home, "club-state registry"
    if requires_review(club_name):
        return None, "the club-state registry asks a person to pick this club's state"
    states = {stored[name] for name in (club_name, *(club.spellings if club else ())) if name in stored}
    if None in states or len(states) > 1:
        return None, "the club's stored teams disagree on state"
    if states:
        return states.pop(), "club's stored teams"
    return None, "no stored team of this club in KS or MO"


def one_board_u_ages(team_name: str, event_season: int, board_season: int) -> Optional[int]:
    """The birth year a name's two U-ages give when both sit on one board (``U18/19`` on u19; owner, 2026-11-14).

    None otherwise: two U-ages on two boards are left out (owner, 2026-09-18).
    """
    pairs = [found.groups() for found in _U_AGE.finditer(team_name) if found.group(2)]
    if len(pairs) != 1:
        return None
    young, old = (event_season - int(age) + 1 for age in pairs[0])
    board = board_cohort(young, board_season)
    return young if board and board == board_cohort(old, board_season) else None


def build_roster(
    pages: List[ResultsPage],
    half: str,
    event_season: int,
    board_season: int,
    lookup_states: Callable[[List[str]], Dict[str, Optional[str]]],
) -> Tuple[List[HeartlandTeamRow], List[HeartlandTeamRow]]:
    """Split the league's teams into those to register and those left out, with a reason.

    A team takes a division's age only from a division whose team list names it; one seen only
    in another page's games is left out. No team is left out for its state: one with none is still matched, and is held
    only if it would be created (``register_teams``).
    """
    listed: Dict[str, Tuple[Division, str]] = {}
    listed_ages: Dict[str, Set[Tuple[int, int]]] = {}
    for page in pages:
        for number, name in page.teams.items():
            listed.setdefault(number, (page.division, name))
            listed_ages.setdefault(number, set()).add((page.division.young_age, page.division.old_age))
    unlisted = {
        number: (page.division, name)
        for page in pages
        for number, name in page.opponents.items()
        if number not in listed
    }
    clubs = {number: club_for_team(name) for number, (_, name) in {**unlisted, **listed}.items()}
    names = {club_name for club_name, _, _, _ in clubs.values() if club_name}
    names |= {spelling for *_, club in clubs.values() if club for spelling in club.spellings}
    stored = lookup_states(sorted(names))
    in_scope: List[HeartlandTeamRow] = []
    left_out: List[HeartlandTeamRow] = []
    for number in sorted({*listed, *unlisted}):
        division, team_name = listed.get(number) or unlisted[number]
        team_id = provider_team_id(half, number)
        birth_year, age_source = age_from_name(team_name, None, event_season)
        one_board = one_board_u_ages(team_name, event_season, board_season) if age_source == TWO_U_AGES else None
        if one_board:
            birth_year, age_source = one_board, "two U-ages on one board"
        if age_source in NAME_WITHOUT_AN_AGE and number in listed:
            birth_year, age_source = _division_fallback(
                team_name, age_source, division, listed_ages[number], event_season, board_season
            )
        age_source = NAME_WITHOUT_AN_AGE.get(age_source, age_source)
        cohort = board_cohort(birth_year, board_season) if birth_year else None
        club_name, club_as_written, club_source, club = clubs[number]
        state_code, state_source = resolve_state(club_name, club, stored)
        row = HeartlandTeamRow(
            tc_team_id=team_id,
            team_name=team_name,
            club_name=club_name,
            club_as_written=club_as_written,
            division_name=division.code,
            division_age=(
                f"u{division.young_age}"
                if division.young_age == division.old_age
                else f"u{division.young_age}-u{division.old_age}"
            ),
            birth_year=birth_year if cohort else None,
            age_group=cohort,
            age_source=age_source,
            gender=division.gender,
            state_code=state_code,
            club_source=club_source,
            state_source=state_source,
        )
        if number not in listed:
            row.skip_reason = "not on any subdivision's team list"
        elif not birth_year:
            row.skip_reason = age_source
        elif not cohort:
            row.skip_reason = f"birth year {birth_year} is on no U10-U19 board"
        elif not club_name:
            row.skip_reason = "no club could be read from the name"
        (left_out if row.skip_reason else in_scope).append(row)
    return in_scope, left_out


def register_teams(
    matcher, provider_id: str, roster: List[HeartlandTeamRow], already: Dict[str, str]
) -> Dict[str, Outcome]:
    """Link or create every roster team; one :class:`Outcome` per provider team id.

    A team with no state the matcher could neither link nor send to review is ``held``, with
    its state's reason: the matcher never creates a team without a state, and the owner
    decides where a new team of a split or unknown club belongs. An exception stays an
    ``error``, so a failed lookup never reads as a quiet hold.
    """
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
            logger.error(f"match error for {PROVIDER_NAME} team {row.tc_team_id}: {e}")
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
        elif not row.state_code:
            outcomes[row.tc_team_id] = Outcome("held", reason=row.state_source)
        else:
            outcomes[row.tc_team_id] = Outcome("error", reason=f"unclassified result: method={result.get('method')}")
    return outcomes


def league_games(pages: List[ResultsPage], half: str, since: date, today: date) -> Tuple[List[EventGame], List[str]]:
    """The scored games dated ``since`` to ``today``, each once, under season-scoped team ids.

    A game listed on two subdivisions' pages is read once. Listed twice with different details,
    it is a problem and neither version is imported, so page order cannot pick the stored result.
    """
    seen: Dict[str, EventGame] = {}
    disputed: Set[str] = set()
    problems: List[str] = []

    def details(game: EventGame) -> Tuple:
        return game.game_date, game.home_id, game.home_score, game.away_id, game.away_score

    for page in pages:
        for game in page.games:
            first = seen.setdefault(game.game_no, game)
            if first is not game and details(first) != details(game):
                disputed.add(game.game_no)
                problems.append(
                    f"game {game.game_no}: listed in {first.division_code} and {game.division_code}"
                    " with different details"
                )
    games = [
        replace(game, home_id=provider_team_id(half, game.home_id), away_id=provider_team_id(half, game.away_id))
        for game in seen.values()
        if game.game_no not in disputed and since <= game.game_date <= today
    ]
    return games, problems


# ── Output ─────────────────────────────────────────────────────────────────────


def held_rows(held: List[EventGame], roster: List[HeartlandTeamRow], outcomes: Dict[str, Outcome]) -> List[Dict]:
    """The games held back, each with the reason a person needs to release it."""
    rows_by_id = {row.tc_team_id: row for row in roster}

    def reason(team_id: str) -> Optional[str]:
        row = rows_by_id.get(team_id)
        outcome = outcomes.get(team_id, Outcome("missing"))
        if row is None or row.skip_reason:
            return f"a team is left out: {row.skip_reason if row else 'not in the roster'}"
        if outcome.status == "held":
            return f"a team is held for its state: {outcome.reason}"
        if outcome.status not in LINKED_OUTCOMES:
            return f"a team is not linked: {outcome.status}"
        return None

    rows = []
    for game in held:
        home, away = rows_by_id.get(game.home_id), rows_by_id.get(game.away_id)
        rows.append(
            {
                "reason": "; ".join(r for r in (reason(game.home_id), reason(game.away_id)) if r),
                "game_date": game.game_date.isoformat(),
                "division": game.division_code,
                "home_team_id": game.home_id,
                "home_team_name": home.team_name if home else "",
                "home_age_group": (home.age_group or "") if home else "",
                "home_gender": home.gender if home else "",
                "home_team_id_master": outcomes.get(game.home_id, Outcome("missing")).team_id_master or "",
                "away_team_id": game.away_id,
                "away_team_name": away.team_name if away else "",
                "away_age_group": (away.age_group or "") if away else "",
                "away_gender": away.gender if away else "",
                "away_team_id_master": outcomes.get(game.away_id, Outcome("missing")).team_id_master or "",
                "home_score": game.home_score,
                "away_score": game.away_score,
                "source_url": game.source_url,
            }
        )
    return rows


def report_rows(
    in_scope: List[HeartlandTeamRow],
    left_out: List[HeartlandTeamRow],
    outcomes: Dict[str, Outcome],
    names: Dict[str, str],
) -> List[Dict]:
    rows = []
    for row in in_scope + left_out:
        outcome = outcomes.get(row.tc_team_id, Outcome("skipped", reason=row.skip_reason or ""))
        rows.append(
            {
                "heartland_team_id": row.tc_team_id,
                "team_name": row.team_name,
                "club_name": row.club_name or "",
                "club_source": row.club_source,
                "division": row.division_name,
                "division_age": row.division_age,
                "age_group": row.age_group or "",
                "age_source": row.age_source,
                "gender": row.gender,
                "state_code": row.state_code or "",
                "state_source": row.state_source,
                "outcome": outcome.status,
                "team_id_master": outcome.team_id_master or "",
                "pitchrank_team_name": names.get(outcome.team_id_master or "", ""),
                "confidence": "" if outcome.confidence is None else outcome.confidence,
                "reason": outcome.reason,
            }
        )
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────


def _division(value: str) -> Tuple[str, str]:
    gender, _, age = value.partition(" ")
    if (gender, age) not in DIVISIONS:
        raise argparse.ArgumentTypeError(f"not a Premier division with a board: {value!r} (e.g. 'Boys U-12')")
    return gender, age


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--division",
        type=_division,
        action="append",
        default=None,
        help="Walk only this division, e.g. 'Boys U-12' (repeatable; default every division)",
    )
    p.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Import games on or after this date (default August 1 of the season)",
    )
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the CSVs and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between page fetches")
    p.add_argument("--delay-max", type=float, default=1.8, help="Maximum seconds between page fetches")
    p.add_argument(
        "--execute", action="store_true", help="Write teams, aliases, review rows and games (default is a dry run)"
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = not args.execute
    today = date.today()
    season = _soccer_season_year(datetime(today.year, today.month, today.day))

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
        pages = collect_league(lambda url: _fetch(session, url), tuple(args.division or DIVISIONS), season, pause)
    except ScrapeFetchError as e:
        console.print(f"[red]{escape(str(e))}[/red]\nNothing was registered or written.")
        return 1
    problems = [problem for page in pages for problem in page.problems]
    scored = [game for page in pages for game in page.games]
    half, half_problems = half_season([game.game_date for game in scored])
    problems += half_problems
    console.print(
        f"Games scraped: {len(scored) + sum(page.unscored for page in pages)} ({len(scored)} played)"
        f" in {len(pages)} subdivisions"
    )
    if half is None:
        for problem in problems:
            console.print(f"  [yellow]{escape(problem)}[/yellow]")
        cause = "The pages span two half-seasons" if half_problems else "No scored games to read a half-season from"
        console.print(f"{cause}; nothing was registered or written.")
        return 1 if problems else 0
    event = Event(
        host=HOST,
        subdomain=f"{PROVIDER_CODE}-{half}",
        name=f"{LEAGUE_NAME} {half[4:].title()} {half[:4]}",
        start=min(game.game_date for game in scored),
        end=max(game.game_date for game in scored),
    )
    since = window_start(args.since, event.season)

    in_scope, left_out = build_roster(
        pages, half, event.season, season, lambda names: club_states(supabase, names, REGION)
    )
    already = existing_aliases(supabase, provider_id, [row.tc_team_id for row in in_scope])
    games, game_problems = league_games(pages, half, since, today)
    problems += game_problems
    console.print(
        f"[bold]{escape(event.name)}[/bold] ({event.start.isoformat()} to {event.end.isoformat()}) — "
        f"{len(in_scope) + len(left_out)} teams, {len(in_scope)} in scope, {len(left_out)} left out"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )

    preview = register_teams(
        HeartlandGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
    )
    conflicts = shared_links(preview, provider_name=PROVIDER_NAME)
    if dry_run:
        outcomes = preview
    else:
        writer = HeartlandGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer, provider_id, [row for row in in_scope if row.tc_team_id not in conflicts], already
        )
        saved = existing_aliases(supabase, provider_id, list(outcomes))
        for team_id, reason in unsaved_links(outcomes, saved).items():
            outcomes[team_id] = Outcome("error", outcomes[team_id].team_id_master, reason=reason)
        queued = pending_reviews(
            supabase, [i for i, o in outcomes.items() if o.status == "review"], provider_code=PROVIDER_CODE
        )
        for team_id, reason in unsaved_reviews(outcomes, queued).items():
            outcomes[team_id] = Outcome("error", confidence=outcomes[team_id].confidence, reason=reason)
    for team_id, reason in conflicts.items():
        proposed = preview[team_id]
        outcomes[team_id] = Outcome("conflict", proposed.team_id_master, proposed.confidence, reason)
    linked = teams_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    for team_id, reason in off_board_links(in_scope, outcomes, linked).items():
        outcomes[team_id] = Outcome("error", outcomes[team_id].team_id_master, reason=reason)

    records, held, cross_age = build_csv_rows(games, in_scope + left_out, outcomes, event, provider_code=PROVIDER_CODE)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{half}_{stamp}"
    games_csv = args.output_dir / f"{prefix}_games.csv"
    held_csv = args.output_dir / f"{prefix}_held.csv"
    cross_age_csv = args.output_dir / f"{prefix}_cross_age.csv"
    report_csv = args.output_dir / f"{prefix}_teams.csv"
    names = {team_id: team["team_name"] for team_id, team in linked.items()}
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    write_csv(held_csv, HELD_COLUMNS, _for_spreadsheets(held_rows(held, in_scope + left_out, outcomes)))
    write_csv(cross_age_csv, CROSS_AGE_COLUMNS, _for_spreadsheets(cross_age))
    write_csv(report_csv, REPORT_COLUMNS, _for_spreadsheets(report_rows(in_scope, left_out, outcomes, names)))

    failed = sorted(key for key, o in outcomes.items() if o.status == "error")
    conflicted = sorted(key for key, o in outcomes.items() if o.status == "conflict")
    must_fail = bool(failed or problems)
    summary = Table(title=f"{escape(event.name)} ({PROVIDER_NAME})")
    summary.add_column("")
    summary.add_column("Count", justify="right")
    for status in ("already_linked", "linked_existing", "relinked", "created", "review", "held", "conflict", "error"):
        summary.add_row(status, str(sum(1 for o in outcomes.values() if o.status == status)))
    summary.add_row("teams left out", str(len(left_out)))
    summary.add_row("games in window", str(len(games)))
    summary.add_row("games to import", str(len(records) // 2))
    summary.add_row("games held back", str(len(held)))
    summary.add_row("cross-age games imported", str(len(cross_age)))
    summary.add_row("problems", str(len(problems)))
    console.print(summary)
    for problem in problems:
        console.print(f"  [yellow]{escape(problem)}[/yellow]")
    console.print(f"Team report:   {report_csv}\nGames CSV:     {games_csv}")
    console.print(f"Held games:    {held_csv}\nCross-age CSV: {cross_age_csv}")
    if conflicted:
        console.print(
            f"[yellow]{len(conflicted)} teams matched a team another Heartland squad matched and are held; "
            f"see the team report: {', '.join(conflicted)}[/yellow]"
        )
    held_count = sum(1 for o in outcomes.values() if o.status == "held")
    if held_count:
        console.print(
            f"[yellow]{held_count} new teams wait for the owner to settle their club's state; "
            "see the team report.[/yellow]"
        )
    if failed:
        console.print(f"[red]{len(failed)} teams errored; see the team report: {', '.join(failed)}[/red]")
    if problems:
        console.print(f"[red]{len(problems)} rows could not be read and were left out; see the problems above.[/red]")

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
