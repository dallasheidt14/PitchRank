#!/usr/bin/env python3
"""Register a Demosphere league's teams and import its scored games.

Demosphere ("Elements", elements.demosphere.com) hosts league sites keyed by a numeric
site id; NCSL (Northern Virginia, with some DC and Maryland clubs) is 80738. Three public, server-rendered pages feed
this script:

- ``teams/club/<club>.html`` names the club (``h1.dii-hdr-cb``) and links each of its
  teams as ``teams/<season key>/<team key>-<division key>/TEAM.html``.
- ``clubs/schedule/<seed club>.html`` links the same teams; its season key picks out the
  season's links on every club page.
- ``schedules/<Season>/<division key>.html`` lists every game of a division: one
  ``tr.sch-main-gm`` per game carrying ``data-gamekey``, and per side the team's
  ``data-tmkey``, its club's ``data-cbkey``, its team code and its full name. A played
  game shows ``2-1`` and an unplayed one ``vs``.

Divisions are found by walking outward from a seed club: each division page names the
clubs of its teams, and each club page names its divisions. The ``/scripts/`` paths
(venue links) are disallowed by the site's robots.txt and are never fetched.

The provider team id is the site id, the season and the team key
(``80738-Fall2026-114577143``). A team key may outlive its season while the squad
behind it does not, so a new season's team has no link yet and re-matches by name.

A team's age comes from its own name, bounded by its division: the division fills in where
the name gives no usable age and settles a bare year that could be two cohorts. Its club is
the one the site lists when the team name opens with one of that club's words, otherwise the
club cut from the name: an association such as VISTA lists itself as the club of teams from
many clubs. Its state is the one its club's stored teams agree on, else the league's; a team
is left out when those teams disagree or its name carries another state's tag.

A game between two boards is imported and also listed in a cross-age file: a team playing up
is ordinary, and each side resolves through its own alias.

Dry run by default; ``--execute`` writes teams, aliases, review rows and games.

Usage:
    python scripts/import_demosphere.py --site-id 80738 --season Fall2026 [--execute]
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
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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

from scripts.import_athletes2events_event import (  # noqa: E402
    _BAND,
    _BARE_YEAR,
    Outcome,
    _clean_name,
    _compute_result,
    age_from_name,
    board_cohort,
    existing_aliases,
    respell_ages,
    split_club,
    teams_by_id,
    unsaved_links,
    unsaved_reviews,
    write_csv,
)
from scripts.import_tourneycentral_event import NAME_WITHOUT_AN_AGE, _for_spreadsheets  # noqa: E402
from src.models.demosphere_matcher import DemosphereGameMatcher  # noqa: E402
from src.models.tourneycentral_matcher import club_before_squad_marks  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402
from src.utils.team_utils import _soccer_season_year, calculate_age_group_from_birth_year  # noqa: E402
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

PROVIDER_CODE = "demosphere"
STATE_PAGE_SIZE = 1000
BASE_URL = "https://elements.demosphere.com"
OUTPUT_DIR = Path("data/raw/demosphere")

REQUIRED_COLUMNS = [
    "provider",
    "schedule_id",
    "competition",
    "division_name",
    "event_name",
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
    "home_away",
    "goals_for",
    "goals_against",
    "result",
    "venue",
    "source_url",
    "scraped_at",
]

REPORT_COLUMNS = [
    "provider_team_id",
    "team_key",
    "team_name",
    "team_code",
    "demosphere_club",
    "club_name",
    "club_source",
    "division",
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
HELD_COLUMNS = ["reason", *CROSS_AGE_COLUMNS]

SCRAPE_TS = datetime.now(timezone.utc).isoformat()

LINKED_OUTCOMES = frozenset({"already_linked", "linked_existing", "relinked", "created"})

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_DAY = re.compile(r"^[A-Za-z]{3,9},\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})$")
_SCORE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})$")
_UNPLAYED = frozenset({"", "vs", "vs.", "--", "-"})
_FORFEIT = re.compile(r"(?:\d{1,2}\s*-\s*\d{1,2}\s+)?(?:fft|ff|forfeit)", re.IGNORECASE)
_UNSCHEDULED = re.compile(r"tbd|to be determined|unscheduled", re.IGNORECASE)
_GENDER_WORD = re.compile(r"\b(?:Boys?|Girls?)\b", re.IGNORECASE)
_KEY = re.compile(r"[0-9]{1,12}")
_TEAM_CODE = re.compile(r"^[A-Z]{1,3}\d+$")
_DIVISION_NAME = re.compile(r"var tgname\s*=\s*'([^']*)'")
_DIVISION_AGE = re.compile(r"\b([BG])U(\d{1,2})\b", re.IGNORECASE)
_TAG_READ_AS_AGE = re.compile(r"^[BG]\d{2} read as U")
_FOUR_DIGIT_TAG = re.compile(r"(?<![A-Za-z0-9])[BG]\s*20\d{2}", re.IGNORECASE)
_CODE_GENDER = re.compile(r"^N([BG])\d", re.IGNORECASE)
_TEAM_LINK = re.compile(r"/teams/(\d+)/(\d+)-(\d+)/TEAM\.html")
_SEASON_LABEL = re.compile(r"(Fall|Spring)(20[0-9]{2})")
_STATE_TAG = re.compile(r"\(([A-Z]{2})\)")
_GENERIC_CLUB_WORDS = frozenset({"fc", "sc", "soccer", "club", "football", "futbol", "united", "youth", "the"})
_GENDERS = {"B": "Male", "G": "Female"}


@dataclass(frozen=True)
class League:
    name: str
    state_code: str
    seed_clubs: Tuple[str, ...]


LEAGUES: Dict[str, League] = {"80738": League("NCSL", "VA", ("15599479",))}


@dataclass
class TeamStub:
    team_key: str
    club_key: str
    team_code: str
    team_name: str
    division_name: str


@dataclass
class RawGame:
    game_key: str
    game_date: date
    home_key: str
    away_key: str
    home_score: Optional[int]
    away_score: Optional[int]
    venue: str
    division_name: str
    source_url: str


@dataclass
class DivisionPage:
    name: str
    teams: Dict[str, TeamStub] = field(default_factory=dict)
    games: List[RawGame] = field(default_factory=list)
    forfeits: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


@dataclass
class TeamRow:
    provider_team_id: str
    team_key: str
    team_code: str
    team_name: str
    demosphere_club: str
    club_name: Optional[str]
    club_as_written: Optional[str]
    club_source: str
    division_name: str
    age_group: Optional[str]
    age_source: str
    gender: Optional[str]
    state_code: Optional[str]
    state_source: str
    skip_reason: str = ""


class ScrapeFetchError(RuntimeError):
    """A page could not be read.

    Raised rather than returned so the run fails: a division whose page did not load
    must not read as a division with no games.
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
        response = session.get(url, timeout=60)
    except requests.RequestException as e:
        raise ScrapeFetchError(f"request failed for {url}: {e}") from e
    if response.status_code != 200:
        raise ScrapeFetchError(f"HTTP {response.status_code} for {url}")
    if "charset" not in str(response.headers.get("content-type", "")).lower():
        response.encoding = "utf-8"
    return response


# ── Parsing ────────────────────────────────────────────────────────────────────


def _text(node) -> str:
    return _clean_name(node.get_text(" ", strip=True)) if node is not None else ""


def parse_club_page(html: str) -> Tuple[str, List[Tuple[str, str, str]]]:
    """``(club name, [(season key, team key, division key), ...])`` from a club's team page."""
    soup = BeautifulSoup(html, "lxml")
    links = [_TEAM_LINK.search(a["href"]).groups() for a in soup.find_all("a", href=_TEAM_LINK)]
    heading = soup.select_one("h1.dii-hdr-cb")
    return _clean_name(next(heading.stripped_strings, "")) if heading is not None else "", sorted(set(links))


def season_key(html: str) -> Optional[str]:
    """The season key most of a schedule page's team links carry: the page lists the current season."""
    keys = Counter(match.group(1) for match in _TEAM_LINK.finditer(html))
    return keys.most_common(1)[0][0] if keys else None


def _team_stub(cell, division_name: str) -> Optional[TeamStub]:
    words = _text(cell).split(" ", 1)
    team_key = cell.get("data-tmkey", "")
    club_key = cell.get("data-cbkey", "")
    if not _KEY.fullmatch(team_key) or (club_key and not _KEY.fullmatch(club_key)) or not words[0]:
        return None
    has_code = bool(_TEAM_CODE.match(words[0]))
    name = words[1] if has_code and len(words) > 1 else " ".join(words)
    return TeamStub(
        team_key=team_key,
        club_key=club_key,
        team_code=words[0] if has_code else "",
        team_name=name,
        division_name=division_name,
    )


def parse_division_page(html: str, division_key: str, source_url: str) -> DivisionPage:
    """Every team and every game of a division page; an unplayed game keeps ``None`` scores."""
    name_match = _DIVISION_NAME.search(html)
    page = DivisionPage(name=_clean_name(name_match.group(1)) if name_match else "")
    soup = BeautifulSoup(html, "lxml")
    day: Optional[date] = None
    unscheduled = False
    for row in soup.select("table#tblListGames2 tr"):
        classes = row.get("class") or []
        if "gm-hdr-5d1h" in classes:
            header = _DAY.match(_text(row))
            unscheduled = bool(_UNSCHEDULED.fullmatch(_text(row)))
            day = datetime.strptime(header.group(1), "%B %d, %Y").date() if header else None
            if not header and not unscheduled:
                page.problems.append(f"{division_key}: unreadable day header {_text(row)!r}")
            continue
        if "sch-main-gm" not in classes:
            continue
        home = row.select_one("td.schedtm1")
        away = row.select_one("td.schedtm2")
        home_stub = _team_stub(home, page.name) if home is not None else None
        away_stub = _team_stub(away, page.name) if away is not None else None
        game_key = row.get("data-gamekey", "")
        if not (home_stub and away_stub and _KEY.fullmatch(game_key)) or (day is None and not unscheduled):
            page.problems.append(f"{division_key}: unreadable game row {game_key or _text(row)[:40]!r}")
            continue
        page.teams.setdefault(home_stub.team_key, home_stub)
        page.teams.setdefault(away_stub.team_key, away_stub)
        if day is None:
            continue
        score_text = _text(row.select_one("td.sch-main-sc"))
        score = _SCORE.match(score_text)
        if not score and _FORFEIT.fullmatch(score_text):
            page.forfeits.append(game_key)
        elif not score and score_text.lower() not in _UNPLAYED:
            page.problems.append(f"{division_key} game {game_key}: unreadable score {score_text!r}")
        page.games.append(
            RawGame(
                game_key=game_key,
                game_date=day,
                home_key=home_stub.team_key,
                away_key=away_stub.team_key,
                home_score=int(score.group(1)) if score else None,
                away_score=int(score.group(2)) if score else None,
                venue=_text(row.select_one("span.gm-fac")),
                division_name=page.name,
                source_url=source_url,
            )
        )
    if soup.select_one("table#tblListGames2") is None and not name_match:
        page.problems.append(f"{division_key}: no schedule table or division name in the page")
    return page


# ── Collection ─────────────────────────────────────────────────────────────────


def collect_league(
    fetch_html: Callable[[str], str],
    site_id: str,
    season_label: str,
    seed_clubs: List[str],
    pause: Callable[[], None] = lambda: None,
    max_divisions: Optional[int] = None,
) -> Tuple[Dict[str, str], Dict[str, DivisionPage], List[str]]:
    """Walk outward from the seed clubs: ``({club key: name}, {division key: page}, problems)``."""
    base = f"{BASE_URL}/{site_id}"
    seed_schedule = fetch_html(f"{base}/clubs/schedule/{seed_clubs[0]}.html")
    pause()
    if f"/schedules/{season_label}/" not in seed_schedule:
        raise ScrapeFetchError(f"club {seed_clubs[0]}'s schedule links no {season_label} divisions")
    key = season_key(seed_schedule)
    if key is None:
        raise ScrapeFetchError(f"club {seed_clubs[0]} links no teams; cannot tell the {season_label} season key")
    clubs: Dict[str, str] = {}
    divisions: Dict[str, DivisionPage] = {}
    problems: List[str] = []
    queue = deque(seed_clubs)
    while queue:
        club = queue.popleft()
        if club in clubs:
            continue
        name, links = parse_club_page(fetch_html(f"{base}/teams/club/{club}.html"))
        pause()
        if not name and not links:
            problems.append(f"club {club}: no club name or teams in the page")
        clubs[club] = name
        for division_key in sorted({division for season, _, division in links if season == key}):
            if division_key in divisions or (max_divisions is not None and len(divisions) >= max_divisions):
                continue
            url = f"{base}/schedules/{season_label}/{division_key}.html"
            divisions[division_key] = parse_division_page(fetch_html(url), division_key, url)
            pause()
            problems.extend(divisions[division_key].problems)
            queue.extend(stub.club_key for stub in divisions[division_key].teams.values() if stub.club_key)
    return clubs, divisions, problems


# ── Roster ─────────────────────────────────────────────────────────────────────


def season_start_year(season_label: str) -> int:
    """``Fall2026`` and ``Spring2027`` are both the 2026 season."""
    found = _SEASON_LABEL.fullmatch(season_label)
    if not found:
        raise ValueError(f"season {season_label!r} is not Fall<year> or Spring<year>")
    year = int(found.group(2))
    return year if found.group(1) == "Fall" else year - 1


def current_season_label(today: Optional[date] = None) -> str:
    """The season label the site is showing now."""
    today = today or date.today()
    return f"{'Fall' if today.month >= 8 else 'Spring'}{today.year}"


def provider_team_id(site_id: str, season_label: str, team_key: str) -> str:
    return f"{site_id}-{season_label}-{team_key}"


def _significant_words(text: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _GENERIC_CLUB_WORDS}


def _before_age(name: str) -> str:
    """``name`` up to its first band, birth year or Boys/Girls word; split_club leaves "2011G" and "Boys 13/14" in."""
    cuts = [found.start() for found in (p.search(name) for p in (_BAND, _BARE_YEAR, _GENDER_WORD)) if found]
    if not cuts:
        return name
    return name[: min(cuts)].strip(" -,") or name


def club_for(listed_club: str, team_name: str) -> Tuple[Optional[str], Optional[str], str]:
    """``(club as stored, club as the name writes it, source)`` for one team.

    The site's club is the stored club when the team name opens with one of its words;
    an association's name shares none with the clubs under it, so there the club is cut
    from the name itself.
    """
    guessed, _ = split_club(respell_ages(_before_age(team_name)), "")
    if guessed:
        guessed = _before_age(guessed)
    written = club_before_squad_marks(guessed)
    first = re.match(r"[A-Za-z0-9]+", team_name)
    if listed_club and first and first.group(0).lower() in _significant_words(listed_club):
        return listed_club, written, "listed club"
    return guessed, written, "cut from name"


def team_age(team_name: str, division_name: str, event_season: int) -> Tuple[Optional[int], str]:
    """The birth year the name states, else the one the division's U-age implies; None where neither settles it.

    Where the name states an age, the division bounds it: a team plays up and never down, so a
    bare year or a ``B12`` tag is read as the division's cohort or younger, and a four-digit
    ``B2012`` older than its division is refused rather than read as an age. A bare year that
    fits the division's own year and the next birth year up is the division's, since a team
    usually plays its own age.
    """
    division = _DIVISION_AGE.search(division_name or "")
    division_birth_year = event_season - int(division.group(2)) + 1 if division else None
    birth_year, source = age_from_name(respell_ages(team_name), division_birth_year, event_season)
    if source in NAME_WITHOUT_AN_AGE:
        if division_birth_year is None:
            return None, f"{NAME_WITHOUT_AN_AGE[source]}, and no age in the division name"
        return division_birth_year, f"{NAME_WITHOUT_AN_AGE[source]}, division {division_name} used"
    tag = _FOUR_DIGIT_TAG.search(team_name)
    if tag and _TAG_READ_AS_AGE.match(source):
        return None, f"birth year tag {''.join(tag.group(0).split())} is older than its division"
    if birth_year is None and division_birth_year and source.startswith(f"birth year {division_birth_year} could be "):
        return division_birth_year, f"birth year {division_birth_year}, division {division_name} used"
    return birth_year, source


def team_cohort(birth_year: Optional[int], age_source: str, board_season: int) -> Optional[str]:
    """The ``u10``-``u19`` board for a birth year: a band's younger year, or a lone year as the player's own.

    ``board_cohort`` reads every year as a band's younger year, which puts the oldest lone year
    (2007 in 2026-27) on no board; a lone year is the player's birth year, which u19 still holds.
    """
    if not birth_year:
        return None
    cohort = board_cohort(birth_year, board_season)
    if cohort or not age_source.startswith("birth year"):
        return cohort
    single = normalize_age_group(calculate_age_group_from_birth_year(birth_year, board_season))
    return single if single in {f"u{n}" for n in range(10, 20)} else None


def team_gender(division_name: str, team_code: str) -> Optional[str]:
    division = _DIVISION_AGE.search(division_name or "")
    if division:
        return _GENDERS[division.group(1).upper()]
    code = _CODE_GENDER.match(team_code or "")
    return _GENDERS[code.group(1).upper()] if code else None


def club_states(supabase, club_names: List[str]) -> Dict[str, Optional[str]]:
    """Club name -> the one state its stored teams state; None when they disagree.

    A club with no stated team is absent, as is a placeholder such as "No Club Selection",
    which pools unrelated teams and says nothing about any one of them.
    """
    found: Dict[str, Optional[str]] = {}
    for club in sorted(set(club_names)):
        if is_placeholder_club(club):
            continue
        rows: List[Dict] = []
        offset = 0
        while True:
            page = (
                supabase.table("teams")
                .select("state_code")
                .eq("club_name", club)
                .eq("is_deprecated", False)
                .not_.is_("state_code", "null")
                .neq("state_code", "")
                .order("team_id_master")
                .range(offset, offset + STATE_PAGE_SIZE - 1)
                .execute()
            ).data or []
            rows.extend(page)
            if len(page) < STATE_PAGE_SIZE:
                break
            offset += STATE_PAGE_SIZE
        states = {row["state_code"] for row in rows}
        if states:
            found[club] = states.pop() if len(states) == 1 else None
    return found


def resolve_state(
    team_name: str, club_name: Optional[str], stored: Dict[str, Optional[str]], league_state: str
) -> Tuple[Optional[str], str]:
    """``(state, source)``; state None means the team is held back, with the reason as the source.

    A club with no stored state takes the league's. A club whose stored teams disagree is held
    instead: a guess here becomes the value every later heuristic agrees with.
    """
    tag = _STATE_TAG.search(team_name)
    if tag and tag.group(1) in STATE_CODE_TO_NAME and tag.group(1) != league_state:
        return None, f"name carries the {tag.group(1)} tag, not {league_state}"
    if club_name and club_name in stored:
        if stored[club_name] is None:
            return None, "the club's stored teams disagree on state"
        return stored[club_name], "club's stored teams"
    return league_state, "league state"


def build_roster(
    teams: Dict[str, TeamStub],
    club_names: Dict[str, str],
    lookup_states: Callable[[List[str]], Dict[str, Optional[str]]],
    site_id: str,
    season_label: str,
    league_state: str,
    board_season: int,
) -> Tuple[List[TeamRow], List[TeamRow]]:
    """Split the walked teams into those to register and those left out, with a reason."""
    event_season = season_start_year(season_label)
    ordered = sorted(teams.items(), key=lambda item: int(item[0]))
    clubs = {team_key: club_for(club_names.get(stub.club_key, ""), stub.team_name) for team_key, stub in ordered}
    stored_states = lookup_states(sorted({club[0] for club in clubs.values() if club[0]}))
    in_scope: List[TeamRow] = []
    left_out: List[TeamRow] = []
    for team_key, stub in ordered:
        listed_club = club_names.get(stub.club_key, "")
        club_name, club_as_written, club_source = clubs[team_key]
        birth_year, age_source = team_age(stub.team_name, stub.division_name, event_season)
        cohort = team_cohort(birth_year, age_source, board_season)
        gender = team_gender(stub.division_name, stub.team_code)
        state_code, state_source = resolve_state(stub.team_name, club_name, stored_states, league_state)
        row = TeamRow(
            provider_team_id=provider_team_id(site_id, season_label, team_key),
            team_key=team_key,
            team_code=stub.team_code,
            team_name=stub.team_name,
            demosphere_club=listed_club,
            club_name=club_name,
            club_as_written=club_as_written,
            club_source=club_source,
            division_name=stub.division_name,
            age_group=cohort,
            age_source=age_source,
            gender=gender,
            state_code=state_code,
            state_source=state_source,
        )
        if not birth_year:
            row.skip_reason = age_source
        elif not cohort:
            row.skip_reason = f"birth year {birth_year} is on no U10-U19 board"
        elif not gender:
            row.skip_reason = "division and team code name no gender"
        elif not club_name:
            row.skip_reason = "no club could be read from the name"
        elif not state_code:
            row.skip_reason = state_source
        (left_out if row.skip_reason else in_scope).append(row)
    return in_scope, left_out


def merge_teams(divisions: Dict[str, DivisionPage]) -> Dict[str, TeamStub]:
    """Every team once; one listed in several divisions keeps the first division by key."""
    teams: Dict[str, TeamStub] = {}
    for division_key in sorted(divisions):
        for team_key, stub in divisions[division_key].teams.items():
            teams.setdefault(team_key, stub)
    return teams


def register_teams(matcher, provider_id: str, roster: List[TeamRow], already: Dict[str, str]) -> Dict[str, Outcome]:
    """Link or create every roster team; one :class:`Outcome` per provider team id."""
    outcomes: Dict[str, Outcome] = {}
    for row in roster:
        if row.provider_team_id in already:
            outcomes[row.provider_team_id] = Outcome("already_linked", already[row.provider_team_id], 1.0)
            continue
        try:
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=row.provider_team_id,
                team_name=row.team_name,
                age_group=row.age_group,
                gender=row.gender,
                club_name=row.club_name,
                state_code=row.state_code,
                written_club=row.club_as_written,
            )
        except Exception as e:
            logger.error(f"match error for Demosphere team {row.provider_team_id}: {e}")
            outcomes[row.provider_team_id] = Outcome("error", reason=str(e))
            continue

        if result.get("created"):
            outcomes[row.provider_team_id] = Outcome("created", result["team_id"], 1.0)
        elif result.get("relinked"):
            outcomes[row.provider_team_id] = Outcome("relinked", result["team_id"], 1.0)
        elif result.get("matched"):
            status = "linked_existing" if result.get("method") == "fuzzy_auto" else "already_linked"
            outcomes[row.provider_team_id] = Outcome(status, result["team_id"], result.get("confidence"))
        elif result.get("review"):
            outcomes[row.provider_team_id] = Outcome("review", confidence=result.get("confidence"))
        else:
            outcomes[row.provider_team_id] = Outcome(
                "error", reason=f"unclassified result: method={result.get('method')}"
            )
    return outcomes


def shared_links(outcomes: Dict[str, Outcome]) -> Dict[str, str]:
    """Teams that matched the same PitchRank team as another Demosphere team.

    Two Demosphere teams are two squads, so at most one of them can be that team. Every
    fuzzy-linked team in such a group is reported; a team whose alias was already
    approved, or whose own row carries its Demosphere id, keeps it.
    """
    by_team: Dict[str, List[str]] = {}
    for team_id, outcome in outcomes.items():
        if outcome.status in ("already_linked", "linked_existing", "relinked"):
            by_team.setdefault(outcome.team_id_master, []).append(team_id)
    conflicts: Dict[str, str] = {}
    for team_ids in by_team.values():
        if len(team_ids) < 2:
            continue
        for team_id in team_ids:
            if outcomes[team_id].status == "linked_existing":
                others = ", ".join(sorted(set(team_ids) - {team_id}))
                conflicts[team_id] = f"same PitchRank team as Demosphere team {others}"
    return conflicts


def pending_reviews(supabase, provider_team_ids: List[str]) -> Set[str]:
    """Demosphere team ids with a pending review row."""
    found: Set[str] = set()
    for i in range(0, len(provider_team_ids), 100):
        result = (
            supabase.table("team_match_review_queue")
            .select("provider_team_id")
            .eq("provider_id", PROVIDER_CODE)
            .eq("status", "pending")
            .in_("provider_team_id", provider_team_ids[i : i + 100])
            .execute()
        )
        found.update(str(row["provider_team_id"]) for row in result.data or [])
    return found


def off_board_links(roster: List[TeamRow], outcomes: Dict[str, Outcome], teams: Dict[str, Dict]) -> Dict[str, str]:
    """Linked teams whose stored row disagrees with this team: no row, another board or another gender.

    The game import does not re-check a link's age or gender (``_match_by_provider_id``
    on this provider skips both), so a link to another board or gender is refused here and
    its games wait for a person. A team this run creates takes this run's board.
    """
    refused: Dict[str, str] = {}
    for row in roster:
        outcome = outcomes[row.provider_team_id]
        if outcome.status not in ("already_linked", "linked_existing", "relinked"):
            continue
        team = teams.get(outcome.team_id_master)
        if team is None:
            refused[row.provider_team_id] = "linked team not found"
            continue
        team_age_group = (team.get("age_group") or "").lower()
        if team_age_group and team_age_group != row.age_group:
            refused[row.provider_team_id] = (
                f"linked team is on the {team_age_group} board, this team is {row.age_group}"
            )
        elif team.get("gender") and team["gender"] != row.gender:
            refused[row.provider_team_id] = f"linked team is {team['gender']}, this team is {row.gender}"
    return refused


# ── Output ─────────────────────────────────────────────────────────────────────


def build_csv_rows(
    games: List[RawGame],
    roster: List[TeamRow],
    outcomes: Dict[str, Outcome],
    site_id: str,
    season_label: str,
    league_name: str,
    since: date,
    today: date,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Two importer rows per played game between ``since`` and ``today`` whose teams are both linked.

    Returns ``(records, held, cross_age)``. A game with a team that is left out or not linked is
    held with its reason. A team playing up is ordinary youth soccer, so a cross-age game is
    imported: both sides resolve through their own alias, and the ranking engine reads each
    team's cohort from ``teams.age_group``, never from the game. Such games are also listed
    in a file of their own, because the age and gender stamped on the row are the home team's.
    """
    rows_by_key = {row.team_key: row for row in roster}
    records: List[Dict] = []
    held: List[Dict] = []
    cross_age: List[Dict] = []
    for game in games:
        if game.home_score is None or game.away_score is None or not since <= game.game_date <= today:
            continue
        home = rows_by_key.get(game.home_key)
        away = rows_by_key.get(game.away_key)
        reason = ""
        if home is None or away is None:
            reason = "a team is left out of the roster"
        elif any(
            outcomes.get(r.provider_team_id, Outcome("missing")).status not in LINKED_OUTCOMES for r in (home, away)
        ):
            reason = "a team is not linked"
        summary = {
            "game_date": game.game_date.isoformat(),
            "division": game.division_name,
            "home_team_id": home.provider_team_id if home else game.home_key,
            "home_team_name": home.team_name if home else "",
            "home_age_group": home.age_group if home else "",
            "home_gender": home.gender if home else "",
            "home_team_id_master": (outcomes.get(home.provider_team_id, Outcome("missing")).team_id_master or "")
            if home
            else "",
            "away_team_id": away.provider_team_id if away else game.away_key,
            "away_team_name": away.team_name if away else "",
            "away_age_group": away.age_group if away else "",
            "away_gender": away.gender if away else "",
            "away_team_id_master": (outcomes.get(away.provider_team_id, Outcome("missing")).team_id_master or "")
            if away
            else "",
            "home_score": game.home_score,
            "away_score": game.away_score,
            "source_url": game.source_url,
        }
        if reason:
            held.append({"reason": reason, **summary})
            continue
        if home.age_group != away.age_group or home.gender != away.gender:
            cross_age.append(summary)
        base = {
            "provider": PROVIDER_CODE,
            "schedule_id": f"demosphere-{site_id}-{game.game_key}",
            "competition": league_name,
            "division_name": game.division_name,
            "event_name": f"{league_name} {season_label} - {game.division_name}",
            "age_group": home.age_group,
            "gender": "Boys" if home.gender == "Male" else "Girls",
            "game_date": game.game_date.isoformat(),
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
                    "team_id": team.provider_team_id,
                    "team_id_source": team.provider_team_id,
                    "team_name": team.team_name,
                    "club_name": team.club_name or "",
                    "opponent_id": opponent.provider_team_id,
                    "opponent_id_source": opponent.provider_team_id,
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


def report_rows(
    in_scope: List[TeamRow], left_out: List[TeamRow], outcomes: Dict[str, Outcome], names: Dict[str, str]
) -> List[Dict]:
    rows = []
    for row in in_scope + left_out:
        outcome = outcomes.get(row.provider_team_id, Outcome("skipped", reason=row.skip_reason))
        rows.append(
            {
                "provider_team_id": row.provider_team_id,
                "team_key": row.team_key,
                "team_name": row.team_name,
                "team_code": row.team_code,
                "demosphere_club": row.demosphere_club,
                "club_name": row.club_name or "",
                "club_source": row.club_source,
                "division": row.division_name,
                "age_group": row.age_group or "",
                "age_source": row.age_source,
                "gender": row.gender or "",
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--site-id", default="80738", choices=sorted(LEAGUES), help="Demosphere site id (default NCSL)")
    p.add_argument("--season", default=current_season_label(), help="Season label on the schedule pages, e.g. Fall2026")
    p.add_argument("--since", type=date.fromisoformat, default=None, help="Import games on or after this date")
    p.add_argument("--max-divisions", type=int, default=None, help="Walk at most this many divisions (pilots)")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the CSVs and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between page fetches")
    p.add_argument("--delay-max", type=float, default=2.0, help="Maximum seconds between page fetches")
    p.add_argument(
        "--execute", action="store_true", help="Write teams, aliases, review rows and games (default is a dry run)"
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = not args.execute

    league = LEAGUES[args.site_id]
    try:
        season_start = season_start_year(args.season)
    except ValueError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        return 1
    since = args.since or date(season_start, 8, 1)

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
        clubs, divisions, problems = collect_league(
            lambda url: _get(session, url).text,
            args.site_id,
            args.season,
            list(league.seed_clubs),
            pause,
            args.max_divisions,
        )
    except ScrapeFetchError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        return 1
    teams = merge_teams(divisions)
    games = [game for key in sorted(divisions) for game in divisions[key].games]
    played = [game for game in games if game.home_score is not None]

    in_scope, left_out = build_roster(
        teams,
        clubs,
        lambda names: club_states(supabase, names),
        args.site_id,
        args.season,
        league.state_code,
        _soccer_season_year(),
    )
    console.print(
        f"[bold]{escape(league.name)} {args.season}[/bold] — {len(clubs)} clubs, {len(divisions)} divisions, "
        f"{len(teams)} teams, {len(in_scope)} in scope, {len(left_out)} left out"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )
    console.print(f"Games scraped: {len(games)} ({len(played)} played)")

    already = existing_aliases(supabase, provider_id, [row.provider_team_id for row in in_scope])
    preview = register_teams(
        DemosphereGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
    )
    conflicts = shared_links(preview)
    if dry_run:
        outcomes = preview
    else:
        writer = DemosphereGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer, provider_id, [row for row in in_scope if row.provider_team_id not in conflicts], already
        )
        saved = existing_aliases(supabase, provider_id, list(outcomes))
        for team_id, reason in unsaved_links(outcomes, saved).items():
            outcomes[team_id] = Outcome("error", outcomes[team_id].team_id_master, reason=reason)
        queued = pending_reviews(supabase, [key for key, outcome in outcomes.items() if outcome.status == "review"])
        for team_id, reason in unsaved_reviews(outcomes, queued).items():
            outcomes[team_id] = Outcome("error", confidence=outcomes[team_id].confidence, reason=reason)
    for team_id, reason in conflicts.items():
        proposed = preview[team_id]
        outcomes[team_id] = Outcome("conflict", proposed.team_id_master, proposed.confidence, reason)
    linked = teams_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    for team_id, reason in off_board_links(in_scope, outcomes, linked).items():
        outcomes[team_id] = Outcome("error", outcomes[team_id].team_id_master, reason=reason)

    records, held, cross_age = build_csv_rows(
        games, in_scope, outcomes, args.site_id, args.season, league.name, since, date.today()
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    games_csv = args.output_dir / f"{stamp}_games.csv"
    held_csv = args.output_dir / f"{stamp}_held.csv"
    cross_age_csv = args.output_dir / f"{stamp}_cross_age.csv"
    report_csv = args.output_dir / f"{stamp}_teams.csv"
    names = {team_id: team["team_name"] for team_id, team in linked.items()}
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    write_csv(held_csv, HELD_COLUMNS, _for_spreadsheets(held))
    write_csv(cross_age_csv, CROSS_AGE_COLUMNS, _for_spreadsheets(cross_age))
    write_csv(report_csv, REPORT_COLUMNS, _for_spreadsheets(report_rows(in_scope, left_out, outcomes, names)))

    failed = sorted(key for key, o in outcomes.items() if o.status in ("error", "conflict"))
    must_fail = bool(failed or problems)
    summary = Table(title=f"{league.name} (Demosphere)")
    summary.add_column("")
    summary.add_column("Count", justify="right")
    for status in ("already_linked", "linked_existing", "relinked", "created", "review", "conflict", "error"):
        summary.add_row(status, str(sum(1 for o in outcomes.values() if o.status == status)))
    summary.add_row("teams left out", str(len(left_out)))
    summary.add_row("games to import", str(len(records) // 2))
    summary.add_row("games held back", str(len(held)))
    summary.add_row("cross-age games imported", str(len(cross_age)))
    summary.add_row("forfeits (no score, not imported)", str(sum(len(page.forfeits) for page in divisions.values())))
    summary.add_row("problems", str(len(problems)))
    console.print(summary)
    for problem in problems:
        console.print(f"  [yellow]{escape(problem)}[/yellow]")
    console.print(f"Team report:   {report_csv}\nGames CSV:     {games_csv}")
    console.print(f"Held games:    {held_csv}\nCross-age CSV: {cross_age_csv}")
    if failed:
        console.print(f"[red]{len(failed)} teams errored or conflicted; see the team report: {', '.join(failed)}[/red]")
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
