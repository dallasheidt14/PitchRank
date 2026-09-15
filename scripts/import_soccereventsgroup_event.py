#!/usr/bin/env python3
"""Register a Soccer Events Group event's teams and import its bracket results.

Soccer Events Group (soccereventsgroup.com) runs on the 3 Step Sports platform.
Two public surfaces feed this script:

- ``/api/team/list`` and ``/api/program/<id>`` are JSON: every registered team
  with its SEG team id, home town and state, and every division with the oldest
  birthdate it admits.
- ``/site/teams/details.aspx?TeamID=<id>`` renders the division's playoff
  bracket as HTML.  Pool play is not published anywhere, so bracket games are
  the only results there are.

The run has two stages.  The roster pass links each in-scope team to an existing
PitchRank team or creates it under its SEG id; a 0.75-0.90 match goes to the
review queue and is not created.  The pass is previewed without writes first, and
a new link to a PitchRank team that another team of the event also links to is
reported as a conflict and left unwritten.  The games stage then reads one team page per
division and writes the importer's CSV, holding back any game whose team is not
linked, because the importer would otherwise insert it half-matched.

A division's birth year comes from its birthdate cutoff, checked against its label
in the event's own season, and its teams go on the board that birth year sits on
this season.  A label naming more than one cohort ("U8/U9", "HS") is skipped
rather than guessed, and so is anything off the U10-U19 boards.

Dry run by default: no teams, aliases, review rows or games are written until
``--execute``; the games CSV and team report are written either way.

Usage:
    python scripts/import_soccereventsgroup_event.py --program-id 19206
    python scripts/import_soccereventsgroup_event.py --program-id 19206 --execute
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

from src.models.soccereventsgroup_matcher import SoccerEventsGroupGameMatcher, canonical_team_name  # noqa: E402
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

PROVIDER_CODE = "soccereventsgroup"
BASE_URL = "https://www.soccereventsgroup.com"
OUTPUT_DIR = Path("data/raw/soccereventsgroup")

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
    "seg_team_id",
    "team_name",
    "division",
    "age_group",
    "gender",
    "state_code",
    "outcome",
    "team_id_master",
    "pitchrank_team_name",
    "confidence",
    "reason",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
}

SCRAPE_TS = datetime.now(timezone.utc).isoformat()
SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"

LINKED_OUTCOMES = frozenset({"already_linked", "linked_existing", "relinked", "created"})

# ASCII and bounded: str.isdigit() also accepts "²", which int() then refuses.
_SCORE = re.compile(r"[0-9]{1,3}")
_LABEL_COHORTS = re.compile(r"^U\d{1,2}(?:\s*/\s*U?\d{1,2})*(?![\d/])", re.IGNORECASE)
_LABEL_NUMBERS = re.compile(r"(\d{1,2})")
_NAME_U_AGE = re.compile(r"\bU(\d{1,2})\b")
_BRACKET_TIME = re.compile(r"^\s*(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}:\d{2}\s*[AP]M?))?\s*,?\s*(.*)$", re.IGNORECASE)


@dataclass
class TeamRow:
    seg_team_id: str
    team_name: str
    division_id: int
    division_name: str
    age_group: Optional[str]
    birth_year: Optional[int]
    gender: str
    state_code: Optional[str]
    skip_reason: Optional[str] = None
    review_reason: Optional[str] = None


@dataclass
class Outcome:
    status: str
    team_id_master: Optional[str] = None
    confidence: Optional[float] = None
    reason: str = ""


@dataclass
class BracketGame:
    division_id: int
    title: str
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
    """A page or feed could not be read.

    Raised rather than returned so the run fails: a division whose page did not
    load must not read as a division with no bracket.
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


def fetch_json(session: requests.Session, url: str) -> Dict:
    response = _get(session, url)
    try:
        return response.json()
    except ValueError as e:
        raise ScrapeFetchError(f"non-JSON response for {url}") from e


def fetch_program(session: requests.Session, program_id: int) -> Dict:
    return fetch_json(session, f"{BASE_URL}/api/program/{program_id}")


def fetch_team_list(session: requests.Session, affiliation_id: int, program_id: int) -> Dict:
    return fetch_json(session, f"{BASE_URL}/api/team/list?affiliationId={affiliation_id}&programIds={program_id}")


def team_page_url(seg_team_id: str) -> str:
    return f"{BASE_URL}/site/teams/details.aspx?TeamID={seg_team_id}"


# ── Roster ─────────────────────────────────────────────────────────────────────


def event_season(program: Dict) -> int:
    """The Aug 1 season the event was played in, never the wall clock's."""
    return _soccer_season_year(datetime.fromisoformat(program["start"]))


def division_birth_year(division: Dict, event_season: int) -> Optional[int]:
    """The younger birth year of the oldest band a single-cohort division admits, else None.

    The label ("U11 Gold", "U18/19 Showcase") must name a single cohort, and the
    birthdate cutoff read against the event's season must agree with it. A cutoff
    is the older edge of an Aug 1 - Jul 31 band, so the band's younger year is the
    cutoff year + 1; a cutoff on any other date means SEG changed convention.
    """
    label = _LABEL_COHORTS.match((division.get("sessionName") or "").strip())
    if not label:
        return None
    cohorts = {19 if n == 18 else n for n in (int(x) for x in _LABEL_NUMBERS.findall(label.group(0)))}
    if len(cohorts) != 1:
        return None
    try:
        cutoff = datetime.fromisoformat(division.get("oldestEligibleBirthdate") or "")
    except ValueError:
        return None
    if (cutoff.month, cutoff.day) != (8, 1):
        return None
    from_cutoff = calculate_age_group_from_birth_year(cutoff.year + 1, event_season)
    if not from_cutoff or from_cutoff.lower() != f"u{cohorts.pop()}":
        return None
    return cutoff.year + 1


def board_cohort(birth_year: int, board_season: int) -> Optional[str]:
    """The ``u10``-``u19`` board a birth year sits on this season, else None.

    Boards move every Aug 1, so a team from an earlier season's event is filed by
    its age now, not by the label it played under.
    """
    age_group = calculate_age_group_from_birth_year(birth_year, board_season)
    if not age_group or int(age_group[1:]) < 10:
        return None
    return age_group.lower()


def name_age_mismatch(team_name: str, birth_year: int, event_season: int) -> Optional[str]:
    """Why a team whose name states a different U-age than its division needs review, else None.

    A team playing up names its own age inside an older division, and would
    otherwise be linked to its club's older squad or created on the wrong board.
    Names are compared with the labels of the event's own season, since that is
    the season they were written in.
    """
    label_age = min(event_season - birth_year + 1, 19)
    label_age = 19 if label_age == 18 else label_age
    name_ages = {19 if n == 18 else n for n in (int(x) for x in _NAME_U_AGE.findall(canonical_team_name(team_name)))}
    if name_ages and name_ages != {label_age}:
        return f"name says U{'/'.join(str(n) for n in sorted(name_ages))}, division is U{label_age}"
    return None


def parse_origin_state(team: Dict) -> Optional[str]:
    """Two-letter US state from SEG's ``state`` field, else the ``", ST"`` tail of ``origin``."""
    for candidate in (team.get("state"), (team.get("origin") or "").rsplit(",", 1)[-1]):
        code = (candidate or "").strip().upper()
        if code in STATE_CODE_TO_NAME:
            return code
    return None


def _clean_name(name: str) -> str:
    return " ".join((name or "").replace("\xa0", " ").split())


def build_roster(program: Dict, team_list: Dict, board_season: int) -> Tuple[List[TeamRow], List[TeamRow]]:
    """Split the event's teams into those to register and those skipped, with a reason."""
    season = event_season(program)
    divisions = {d["id"]: d for d in program.get("divisions", [])}
    in_scope: List[TeamRow] = []
    skipped: List[TeamRow] = []
    for program_teams in team_list.get("programTeams", []):
        for division in program_teams.get("divisions", []):
            birth_year = division_birth_year(divisions.get(division["divisionId"], {}), season)
            cohort = board_cohort(birth_year, board_season) if birth_year else None
            for team in division.get("teams", []):
                row = TeamRow(
                    seg_team_id=str(team["teamId"]),
                    team_name=_clean_name(team.get("teamName", "")),
                    division_id=division["divisionId"],
                    division_name=_clean_name(division.get("divisionName", "")),
                    age_group=cohort,
                    birth_year=birth_year if cohort else None,
                    gender="Male" if division.get("gender") else "Female",
                    state_code=parse_origin_state(team),
                )
                if not cohort:
                    row.skip_reason = "division names no single U10-U19 cohort"
                elif not row.state_code:
                    row.skip_reason = "no US state on the registration"
                else:
                    row.review_reason = name_age_mismatch(row.team_name, birth_year, season)
                (skipped if row.skip_reason else in_scope).append(row)
    return in_scope, skipped


def existing_aliases(supabase, provider_id: str, seg_team_ids: List[str]) -> Dict[str, str]:
    """SEG team id -> team_id_master for teams already linked."""
    found: Dict[str, str] = {}
    for i in range(0, len(seg_team_ids), 100):
        batch = seg_team_ids[i : i + 100]
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
    """Link, queue or create every roster team; one :class:`Outcome` per SEG team id."""
    outcomes: Dict[str, Outcome] = {}
    for row in roster:
        if row.seg_team_id in already:
            outcomes[row.seg_team_id] = Outcome("already_linked", already[row.seg_team_id], 1.0)
            continue
        try:
            if row.review_reason:
                result = matcher.queue_for_review(
                    provider_id=provider_id,
                    provider_team_id=row.seg_team_id,
                    team_name=row.team_name,
                    age_group=row.age_group,
                    gender=row.gender,
                    state_code=row.state_code,
                    reason=row.review_reason,
                )
                outcomes[row.seg_team_id] = Outcome(
                    "review", confidence=result.get("confidence"), reason=row.review_reason
                )
                continue
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=row.seg_team_id,
                team_name=row.team_name,
                age_group=row.age_group,
                gender=row.gender,
                state_code=row.state_code,
            )
        except Exception as e:
            logger.error(f"match error for SEG team {row.seg_team_id}: {e}")
            outcomes[row.seg_team_id] = Outcome("error", reason=str(e))
            continue

        if result.get("created"):
            outcomes[row.seg_team_id] = Outcome("created", result["team_id"], 1.0)
        elif result.get("relinked"):
            outcomes[row.seg_team_id] = Outcome("relinked", result["team_id"], 1.0)
        elif result.get("matched"):
            status = "linked_existing" if result.get("method") == "fuzzy_auto" else "already_linked"
            outcomes[row.seg_team_id] = Outcome(status, result["team_id"], result.get("confidence"))
        elif result.get("review"):
            outcomes[row.seg_team_id] = Outcome("review", confidence=result.get("confidence"))
        else:
            outcomes[row.seg_team_id] = Outcome("error", reason=f"unclassified result: method={result.get('method')}")
    return outcomes


def unsaved_links(outcomes: Dict[str, Outcome], saved: Dict[str, str]) -> Dict[str, str]:
    """Teams reported linked or created whose approved alias is missing or points elsewhere.

    The matcher logs a failed alias write and still reports the team linked, and a
    game whose one team has no alias imports half-matched.
    """
    return {
        seg_team_id: "link was not saved"
        for seg_team_id, outcome in outcomes.items()
        if outcome.status in ("linked_existing", "relinked", "created")
        and saved.get(seg_team_id) != outcome.team_id_master
    }


def pending_reviews(supabase, seg_team_ids: List[str]) -> Set[str]:
    """SEG team ids with a pending review row."""
    found: Set[str] = set()
    for i in range(0, len(seg_team_ids), 100):
        result = (
            supabase.table("team_match_review_queue")
            .select("provider_team_id")
            .eq("provider_id", PROVIDER_CODE)
            .eq("status", "pending")
            .in_("provider_team_id", seg_team_ids[i : i + 100])
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
        seg_team_id: "review item was not saved"
        for seg_team_id, outcome in outcomes.items()
        if outcome.status == "review" and seg_team_id not in pending
    }


def shared_links(outcomes: Dict[str, Outcome]) -> Dict[str, str]:
    """SEG teams of this event that matched the same PitchRank team as another one.

    Two registrations in one event are two squads, so at most one of them can be
    that team. Every fuzzy-linked team in such a group is reported; a team whose
    alias was already approved, or whose own row carries its SEG id, keeps it.
    """
    by_team: Dict[str, List[str]] = {}
    for seg_team_id, outcome in outcomes.items():
        if outcome.status in ("already_linked", "linked_existing", "relinked"):
            by_team.setdefault(outcome.team_id_master, []).append(seg_team_id)
    conflicts: Dict[str, str] = {}
    for team_id_master, seg_team_ids in by_team.items():
        if len(seg_team_ids) < 2:
            continue
        for seg_team_id in seg_team_ids:
            if outcomes[seg_team_id].status == "linked_existing":
                others = ", ".join(sorted(set(seg_team_ids) - {seg_team_id}))
                conflicts[seg_team_id] = f"same PitchRank team as SEG team {others}"
    return conflicts


def team_names_by_id(supabase, team_ids: List[str]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for i in range(0, len(team_ids), 100):
        result = (
            supabase.table("teams")
            .select("team_id_master, team_name")
            .in_("team_id_master", team_ids[i : i + 100])
            .execute()
        )
        for row in result.data or []:
            names[row["team_id_master"]] = row["team_name"]
    return names


# ── Brackets ───────────────────────────────────────────────────────────────────


def resolve_game_date(month: int, day: int, program: Dict) -> date:
    """A bracket prints month/day only; the year is the event's, rolled over a New Year."""
    start = datetime.fromisoformat(program["start"]).date()
    resolved = date(start.year, month, day)
    return resolved if resolved >= start else date(start.year + 1, month, day)


def parse_bracket_games(html: str) -> List[Dict]:
    """Every scored bracket game on a team page, as raw sides plus the time line.

    A side is ``(name, score)``. A slot not yet filled, or a game with a
    non-numeric score, is left out. A game with no winner marked is still a game:
    level scores are a draw, including 0-0.
    """
    soup = BeautifulSoup(html, "lxml")
    panel = soup.find(id=re.compile(r"BracketPanel$"))
    if panel is None:
        return []
    games = []
    for table in panel.select("table.game"):
        sides = []
        title = ""
        when = ""
        for row in table.find_all("tr"):
            team_cell = row.find("td", class_="team")
            score_cell = row.find("td", class_="score")
            if team_cell is None or score_cell is None:
                continue
            sides.append((_clean_name(team_cell.get_text()), score_cell.get_text(strip=True)))
            title_cell = row.find("td", class_="title")
            time_cell = row.find("td", class_="time")
            title = title or (title_cell.get_text(strip=True) if title_cell else "")
            when = when or (time_cell.get_text(strip=True) if time_cell else "")
        if len(sides) != 2 or not all(name and _SCORE.fullmatch(score) for name, score in sides):
            continue
        games.append({"title": title, "when": when, "sides": sides})
    return games


def collect_games(
    fetch_html: Callable[[str], str],
    roster: List[TeamRow],
    program: Dict,
    days_back: int,
    today: date,
    pause: Callable[[], None] = lambda: None,
) -> Tuple[List[BracketGame], List[str]]:
    """One team page per division with a cohort, mapped to SEG ids and bounded to the window.

    ``roster`` is every team, skipped ones included, so a bracket game against a
    team that was skipped still maps and is held back later rather than lost.
    Returns the games and a list of problems: bracket names that match no team
    in their division, and time lines that cannot be read.
    """
    by_division: Dict[int, List[TeamRow]] = {}
    for row in roster:
        by_division.setdefault(row.division_id, []).append(row)

    earliest = today - timedelta(days=days_back)
    games: List[BracketGame] = []
    problems: List[str] = []
    seen = set()
    for division_id, teams in by_division.items():
        if not teams[0].age_group:
            continue
        url = team_page_url(teams[0].seg_team_id)
        html = fetch_html(url)
        pause()
        ids_by_name = {t.team_name.lower(): t.seg_team_id for t in teams}
        for raw in parse_bracket_games(html):
            ids = [ids_by_name.get(name.lower()) for name, _ in raw["sides"]]
            if not all(ids):
                problems.append(f"{teams[0].division_name}: bracket names not in the division {raw['sides']}")
                continue
            when = _BRACKET_TIME.match(raw["when"])
            if not when:
                problems.append(f"{teams[0].division_name}: unreadable time {raw['when']!r}")
                continue
            game_date = resolve_game_date(int(when.group(1)), int(when.group(2)), program)
            if not earliest <= game_date <= today:
                continue
            key = (division_id, tuple(sorted(ids)), game_date)
            if key in seen:
                continue
            seen.add(key)
            (_, home_score), (_, away_score) = raw["sides"]
            games.append(
                BracketGame(
                    division_id=division_id,
                    title=raw["title"],
                    game_date=game_date,
                    game_time=(when.group(3) or "").strip(),
                    venue=when.group(4).strip(),
                    home_id=ids[0],
                    home_score=int(home_score),
                    away_id=ids[1],
                    away_score=int(away_score),
                    source_url=url,
                )
            )
    return games, problems


def _compute_result(goals_for: int, goals_against: int) -> str:
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


def build_csv_rows(
    games: List[BracketGame], roster: List[TeamRow], outcomes: Dict[str, Outcome], program: Dict
) -> Tuple[List[Dict], List[BracketGame]]:
    """Two importer rows per game whose teams are both linked; the rest are held back."""
    rows_by_id = {row.seg_team_id: row for row in roster}
    records: List[Dict] = []
    held: List[BracketGame] = []
    for game in games:
        if any(outcomes.get(i, Outcome("missing")).status not in LINKED_OUTCOMES for i in (game.home_id, game.away_id)):
            held.append(game)
            continue
        home = rows_by_id[game.home_id]
        away = rows_by_id[game.away_id]
        base = {
            "provider": PROVIDER_CODE,
            "scrape_run_id": SCRAPE_RUN_ID,
            "event_id": program["id"],
            "event_name": f"{_clean_name(program['name'])} - {home.division_name}",
            "schedule_id": f"{game.division_id}-{game.title}-{game.game_date.isoformat()}",
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
                    "team_id": team.seg_team_id,
                    "team_id_source": team.seg_team_id,
                    "team_name": team.team_name,
                    "club_name": "",
                    "opponent_id": opponent.seg_team_id,
                    "opponent_id_source": opponent.seg_team_id,
                    "opponent_name": opponent.team_name,
                    "opponent_club_name": "",
                    "state": STATE_CODE_TO_NAME.get(team.state_code, ""),
                    "state_code": team.state_code,
                    "home_away": home_away,
                    "goals_for": goals_for,
                    "goals_against": goals_against,
                    "result": _compute_result(goals_for, goals_against),
                }
            )
    return records, held


# ── Output ─────────────────────────────────────────────────────────────────────


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
        outcome = outcomes.get(row.seg_team_id, Outcome("skipped", reason=row.skip_reason or ""))
        rows.append(
            {
                "seg_team_id": row.seg_team_id,
                "team_name": row.team_name,
                "division": row.division_name,
                "age_group": row.age_group or "",
                "gender": row.gender,
                "state_code": row.state_code or "",
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
    p.add_argument("--program-id", type=int, required=True, help="SEG event (ProgramID), e.g. 19206")
    p.add_argument("--days-back", type=int, default=14, help="Import games dated within this many days (default 14)")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the games CSV and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between team page fetches")
    p.add_argument("--delay-max", type=float, default=3.0, help="Maximum seconds between team page fetches")
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
    program = fetch_program(session, args.program_id)
    info = program["program"]
    info["divisions"] = program.get("divisions", [])
    team_list = fetch_team_list(session, info["affiliationId"], args.program_id)
    in_scope, skipped = build_roster(info, team_list, _soccer_season_year())
    console.print(
        f"[bold]{escape(_clean_name(info['name']))}[/bold] ({escape(info.get('dateRangeString', ''))}) — "
        f"{len(in_scope) + len(skipped)} teams, {len(in_scope)} in scope, {len(skipped)} skipped"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )

    already = existing_aliases(supabase, provider_id, [row.seg_team_id for row in in_scope])
    preview = register_teams(
        SoccerEventsGroupGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
    )
    conflicts = shared_links(preview)
    if dry_run:
        outcomes = preview
    else:
        writer = SoccerEventsGroupGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer, provider_id, [row for row in in_scope if row.seg_team_id not in conflicts], already
        )
        saved = existing_aliases(supabase, provider_id, list(outcomes))
        for seg_team_id, reason in unsaved_links(outcomes, saved).items():
            outcomes[seg_team_id] = Outcome("error", outcomes[seg_team_id].team_id_master, reason=reason)
        queued = pending_reviews(supabase, [i for i, o in outcomes.items() if o.status == "review"])
        for seg_team_id, reason in unsaved_reviews(outcomes, queued).items():
            outcomes[seg_team_id] = Outcome("error", confidence=outcomes[seg_team_id].confidence, reason=reason)
    for seg_team_id, reason in conflicts.items():
        proposed = preview[seg_team_id]
        outcomes[seg_team_id] = Outcome("conflict", proposed.team_id_master, proposed.confidence, reason)

    def pause() -> None:
        time.sleep(random.uniform(args.delay_min, args.delay_max))

    games, problems = collect_games(
        lambda url: _get(session, url).text, in_scope + skipped, info, args.days_back, date.today(), pause
    )
    records, held = build_csv_rows(games, in_scope + skipped, outcomes, info)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    games_csv = args.output_dir / f"{args.program_id}_{stamp}_games.csv"
    report_csv = args.output_dir / f"{args.program_id}_{stamp}_teams.csv"
    names = team_names_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    write_csv(report_csv, REPORT_COLUMNS, report_rows(in_scope, skipped, outcomes, names))

    summary = Table(title=f"SEG program {args.program_id}")
    summary.add_column("")
    summary.add_column("Count", justify="right")
    for status in ("already_linked", "linked_existing", "relinked", "created", "review", "conflict", "error"):
        summary.add_row(status, str(sum(1 for o in outcomes.values() if o.status == status)))
    summary.add_row("skipped teams", str(len(skipped)))
    summary.add_row("bracket games in window", str(len(games)))
    summary.add_row("games to import", str(len(records) // 2))
    summary.add_row("games held back", str(len(held)))
    summary.add_row("problems", str(len(problems)))
    console.print(summary)
    for problem in problems:
        console.print(f"  [yellow]{escape(problem)}[/yellow]")
    console.print(f"Team report: {report_csv}\nGames CSV:   {games_csv}")

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
