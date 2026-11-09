#!/usr/bin/env python3
"""Register an HTG Sports event's teams and import its results.

HTG Sports (events.htgsports.net) hosts tournaments and leagues, Heartland Soccer's among
them, each under an event id (``https://events.htgsports.net/?eventid=14130``), and one
provider row covers them all. The event page is a single-page app over a JSON API at
``/api/``. Every API call needs the ``HTGSports-Token`` header the app sends, and its value is
a constant in the app's public bundle (``/app/main.js``), so each run reads it from there.

Four endpoints feed this script:

- ``eventSummary2/<event>`` names the event and gives its first and last day, which date the
  season its labels were written in.
- ``divisions/<event>`` lists its divisions, "U12 Boys Red I (2014/15) 9v9" with the format
  in ``SizeDescr``. A division with no board (U9 and below) or of small-sided play is neither
  fetched nor imported.
- ``standings/<event>/<division>/false`` lists a division's teams: id, name, club, ``City, ST``
  and coach. Its rows also carry coach and manager phone numbers, which are never read.
- ``GamesForDivision/<event>/<division>`` lists its games: a game id unique to the event, both
  team ids, both scores (-1 until played), the day, kickoff and field, and forfeit and no-show
  flags. A forfeit or no-show is not a result, so it is counted and never imported. A game
  listed more than once is read once, and held when its copies disagree.

The run has the two stages of ``import_tourneycentral_event.py``, whose roster and output
steps it shares: the roster pass links each in-scope team to an existing PitchRank team or
creates it under its HTG id, a 0.75-0.90 match goes to the review queue, and two teams of the
event matching one PitchRank team are a conflict left unwritten; then the games stage writes
the importer's CSV, holding back a game whose team is not linked. A game between two
boards is imported and also listed in a file of its own.

A team's age comes from its own name, read by the label key: a band by its younger year
(``14/15B`` is U12), a single birth year as a band's younger year, a U-age against the event's
own season. A name that states no age, or an odd year span, takes its division's age when the
division is one cohort (U12, or U18/19, since U18 folds into U19) and the event lists the team
at no other age. A name with several birth years, or one in a division spanning more than one
cohort ("U14/15", "High School"), is left out for a person to decide. A name that states an
age keeps it whatever division the team entered, because teams play up. A standings slot
held for a team still to come ("TBD") is reported and never registered. ``--leave-out``,
``--age``, ``--gender`` and ``--state`` work as they do for Tourney Central, naming teams by
HTG team id.

Dry run by default: no teams, aliases, review rows or games are written until ``--execute``;
the games CSV, the cross-age CSV and the team report are written either way.

Usage:
    python scripts/import_htgsports_event.py --event-url "https://events.htgsports.net/?eventid=14130"
    python scripts/import_htgsports_event.py --event-url "https://events.htgsports.net/?eventid=14130" \
        --leave-out 655369 --age 657553=u12 --execute
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.table import Table  # noqa: E402

from scripts.import_tourneycentral_event import (  # noqa: E402
    _TEAM_ID,
    CROSS_AGE_COLUMNS,
    OLDEST_BOARD_AGE,
    REPORT_COLUMNS,
    REQUIRED_COLUMNS,
    Division,
    Event,
    EventGame,
    LabelSeasonError,
    Outcome,
    ScrapeFetchError,
    TeamListing,
    TeamRow,
    _age_for_team,
    _clean_name,
    _for_spreadsheets,
    _gender_for_team,
    _state_for_team,
    build_csv_rows,
    build_roster,
    existing_aliases,
    label_season_mismatch,
    make_session,
    off_board_links,
    pending_reviews,
    register_teams,
    report_rows,
    shared_links,
    skip_division,
    teams_by_id,
    unsaved_links,
    unsaved_reviews,
    write_csv,
)
from src.models.htgsports_matcher import HtgSportsGameMatcher  # noqa: E402
from src.utils.provider_ids import clean_provider_id  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

PROVIDER_CODE = "htgsports"
PROVIDER_NAME = "HTG Sports"
HOST = "events.htgsports.net"
BASE_URL = f"https://{HOST}"
OUTPUT_DIR = Path("data/raw/htgsports")

HTG_REPORT_COLUMNS = ["htg_team_id", *REPORT_COLUMNS[1:]]

# U-ages a high school division spans.
HIGH_SCHOOL_AGES = (15, 19)

# ASCII-bound: under IGNORECASE alone the Unicode fold of U+017F matches an "s", and
# \d admits non-ASCII digits. Every id reaches a URL or a database write, so each is ASCII
# digits of bounded length.
_EVENT_URL = re.compile(
    r"^https?://events\.htgsports\.net/?\?(?:[^#\s]*&)?eventid=([1-9][0-9]{0,8})(?:[&#]\S*)?$",
    re.IGNORECASE | re.ASCII,
)
_BUNDLE_SRC = re.compile(r"""<script[^>]+src=["'](/?app/main\.js(?:\?[^"'\s]*)?)["']""", re.IGNORECASE | re.ASCII)
_TOKEN = re.compile(
    r"""HTGSports-Token["']\]?\s*[:=]\s*["']"""
    r"([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})[\"']",
    re.ASCII,
)
# "U12 Boys Red I (2014/15) 9v9", "U14/15 Girls Green", "U18/19 Girls Red", "High School Boys Blue".
_DIVISION_NAME = re.compile(
    r"^(?:U([0-9]{1,2})(?:\s*/\s*U?([0-9]{1,2}))?|(High\s+School))\s+(Boys|Girls)\b", re.IGNORECASE | re.ASCII
)
_SIZE = re.compile(r"^\s*([0-9]{1,2})\s*v\s*[0-9]{1,2}\s*$", re.IGNORECASE | re.ASCII)
# A standings slot held for a team still to come; it names no team.
_PLACEHOLDER_NAME = re.compile(r"tbd|tba|to be (?:determined|announced)|bye", re.IGNORECASE | re.ASCII)
_FORFEIT_FLAGS = ("Forfeit1", "Forfeit2", "NoShow1", "NoShow2")
_IGNORED_FLAGS = ("IgnoreResult1", "IgnoreResult2")


# ── Network ────────────────────────────────────────────────────────────────────


def _get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """The response at ``url``; a transport error or anything but a 200 raises :class:`ScrapeFetchError`.

    Redirects are refused rather than followed: ``requests`` strips only ``Authorization`` when a
    redirect changes host, so a followed redirect would carry the token header to wherever it led.
    """
    try:
        response = session.get(url, timeout=90, allow_redirects=False, **kwargs)
    except requests.RequestException as e:
        raise ScrapeFetchError(f"request failed for {url}: {e}") from e
    if response.status_code != 200:
        raise ScrapeFetchError(f"HTTP {response.status_code} for {url}")
    return response


def parse_event_url(url: str) -> str:
    """Any page of an event -> its event id."""
    match = _EVENT_URL.match((url or "").strip())
    if not match:
        raise ValueError(f"not an HTG Sports event URL: {url!r} (expected https://{HOST}/?eventid=<id>)")
    return match.group(1)


def event_page_url(event_id: str) -> str:
    return f"{BASE_URL}/?eventid={event_id}"


def division_page_url(event_id: str, division_id: str) -> str:
    return f"{BASE_URL}/?eventid={event_id}#/scheduleresults/{division_id}"


def read_api_token(session: requests.Session, event_id: str) -> str:
    """The ``HTGSports-Token`` the event page's app sends, read from its bundle."""
    page_url = event_page_url(event_id)
    page = _get(session, page_url).content.decode("utf-8", errors="replace")
    script = _BUNDLE_SRC.search(page)
    if not script:
        raise ScrapeFetchError(f"no app bundle on {page_url}")
    bundle_url = urljoin(f"{BASE_URL}/", script.group(1))
    tokens = set(_TOKEN.findall(_get(session, bundle_url).content.decode("utf-8", errors="replace")))
    if len(tokens) != 1:
        raise ScrapeFetchError(f"{'conflicting' if tokens else 'no'} HTGSports-Token values in {bundle_url}")
    return tokens.pop()


def fetch_api(session: requests.Session, token: str, path: str) -> Any:
    """The parsed JSON at ``/api/<path>``; an empty or non-JSON body raises :class:`ScrapeFetchError`.

    The token goes on this request alone, never on the session, so nothing else carries it.
    The body is parsed from its bytes, so a name decodes as UTF-8 whatever charset the response
    declares, or fails to declare.
    """
    url = f"{BASE_URL}/api/{path}"
    response = _get(
        session, url, params={"format": "json"}, headers={"HTGSports-Token": token, "Accept": "application/json"}
    )
    if not response.content.strip():
        raise ScrapeFetchError(f"empty response for {url}")
    try:
        return json.loads(response.content)
    except ValueError as e:
        raise ScrapeFetchError(f"non-JSON response for {url}") from e


def summary_path(event_id: str) -> str:
    return f"eventSummary2/{event_id}"


def divisions_path(event_id: str) -> str:
    return f"divisions/{event_id}"


def standings_path(event_id: str, division_id: str) -> str:
    return f"standings/{event_id}/{division_id}/false"


def games_path(event_id: str, division_id: str) -> str:
    return f"GamesForDivision/{event_id}/{division_id}"


# ── Event, divisions, teams and games ──────────────────────────────────────────


def _id(value: Any) -> str:
    """An id from the API as plain ASCII digits; anything else is ``""``."""
    text = clean_provider_id(value)
    return text if _TEAM_ID.fullmatch(text) else ""


def _text(row: Dict, key: str) -> str:
    value = row.get(key)
    return _clean_name(value) if isinstance(value, str) else ""


def _day(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date() if isinstance(value, str) else None
    except ValueError:
        return None


def parse_event_summary(data: Any, event_id: str) -> Event:
    """The event, named and dated by its own summary."""
    if not isinstance(data, dict):
        raise ScrapeFetchError(f"no summary for event {event_id}")
    name = _text(data, "Name")
    start, end = _day(data.get("StartDateAsString")), _day(data.get("EndDateAsString"))
    if not name or start is None or end is None:
        raise ScrapeFetchError(f"event {event_id} has no name or no dates")
    return Event(host=HOST, subdomain=f"htg{event_id}", name=name, start=start, end=end)


def parse_division(item: Any) -> Optional[Tuple[str, Division]]:
    """``(division id, division)`` for a division of a known shape no older than U19, else None."""
    if not isinstance(item, dict):
        return None
    name = _text(item, "Name")
    division_id = _id(item.get("Id"))
    match = _DIVISION_NAME.match(name)
    if not match or not division_id:
        return None
    if match.group(3):
        young_age, old_age = HIGH_SCHOOL_AGES
    else:
        young_age = int(match.group(1))
        old_age = int(match.group(2) or young_age)
        if match.group(2) and old_age != young_age + 1:
            return None
    if old_age > OLDEST_BOARD_AGE:
        return None
    size = _SIZE.match(_text(item, "SizeDescr"))
    return division_id, Division(
        code=name,
        gender="Male" if match.group(4).lower() == "boys" else "Female",
        young_age=young_age,
        old_age=old_age,
        players=int(size.group(1)) if size else None,
    )


def parse_standings(rows: Any, division: Division, source_url: str) -> Tuple[List[TeamListing], List[str]]:
    """Every team of a division's standings, and the rows that could not be read.

    Only the id, name, club, location and coach are read; the phone and manager fields are not.
    A slot held for a team still to come ("TBD") is reported, not registered, so the games it
    played wait for a person instead of creating a team of that name.
    """
    if not isinstance(rows, list):
        raise ScrapeFetchError(f"{division.code}: no standings at {source_url}")
    listings: List[TeamListing] = []
    problems: List[str] = []
    for row in rows:
        team_id = _id(row.get("Id")) if isinstance(row, dict) else ""
        if not team_id:
            raw = clean_provider_id(row.get("Id")) if isinstance(row, dict) else ""
            problems.append(f"{division.code}: unreadable team row {raw!r}")
            continue
        team_name = _text(row, "Name")
        if _PLACEHOLDER_NAME.fullmatch(team_name):
            problems.append(f"{division.code}: team {team_id} is the placeholder {team_name!r}, not registered")
            continue
        listings.append(
            TeamListing(
                tc_team_id=team_id,
                team_name=team_name,
                club=_text(row, "ClubName"),
                location=_text(row, "Location"),
                coach=_text(row, "Coach"),
            )
        )
    return listings, problems


def _score(value: Any) -> Optional[int]:
    """A played score; ``-1`` (unplayed), a bool and anything that is not a small integer are None."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 99:
        return value
    return None


def parse_games(
    rows: Any, division: Division, source_url: str
) -> Tuple[List[EventGame], List[str], Dict[str, Set[str]]]:
    """Every scored game of a division, the games that could not be read, and the flagged ones.

    Every copy of a listed game is returned; ``collect_event`` reads a game once and holds one
    whose copies disagree. The flagged ids are ``forfeits`` (a forfeit or no-show on either side:
    not a result, never imported) and ``ignored`` (a result the site leaves out of its standings:
    imported).
    """
    if not isinstance(rows, list):
        raise ScrapeFetchError(f"{division.code}: no games at {source_url}")
    games: List[EventGame] = []
    problems: List[str] = []
    flagged = _no_flags()
    for row in rows:
        game_no = _id(row.get("Id")) if isinstance(row, dict) else ""
        if not game_no:
            problems.append(f"{division.code}: unreadable game row")
            continue
        if any(row.get(flag) is True for flag in _FORFEIT_FLAGS):
            flagged["forfeits"].add(game_no)
            continue
        home_id, away_id = _id(row.get("Team1Id")), _id(row.get("Team2Id"))
        if not (home_id and away_id):
            problems.append(f"{division.code} game {game_no}: unfilled bracket slot")
            continue
        home_score, away_score = _score(row.get("HomeTeamScore")), _score(row.get("VisitingTeamScore"))
        if home_score is None or away_score is None:
            problems.append(f"{division.code} game {game_no}: no score")
            continue
        game_date = _day(row.get("Date"))
        if game_date is None:
            problems.append(f"{division.code} game {game_no}: no date")
            continue
        if any(row.get(flag) is True for flag in _IGNORED_FLAGS):
            flagged["ignored"].add(game_no)
        games.append(
            EventGame(
                division_code=division.code,
                game_no=game_no,
                game_date=game_date,
                game_time=_text(row, "Time"),
                venue=_text(row, "Field"),
                home_id=home_id,
                home_score=home_score,
                away_id=away_id,
                away_score=away_score,
                source_url=source_url,
            )
        )
    return games, problems, flagged


def _no_flags() -> Dict[str, Set[str]]:
    return {"forfeits": set(), "disputed": set(), "ignored": set()}


def _same_game(a: EventGame, b: EventGame) -> bool:
    """Whether two copies of a game agree on everything but the division and its page."""
    keys = ("game_date", "game_time", "venue", "home_id", "home_score", "away_id", "away_score")
    return all(getattr(a, key) == getattr(b, key) for key in keys)


# ── Main ───────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--event-url", required=True, help=f"The event's page, e.g. https://{HOST}/?eventid=14130")
    p.add_argument("--days-back", type=int, default=14, help="Import games dated within this many days (default 14)")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Where the CSVs and team report go")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum seconds between API calls")
    p.add_argument("--delay-max", type=float, default=2.0, help="Maximum seconds between API calls")
    p.add_argument("--execute", action="store_true", help="Write teams, aliases and games (default is a dry run)")
    p.add_argument(
        "--leave-out",
        nargs="+",
        default=[],
        type=_leave_out_id,
        metavar="TEAM_ID",
        help="HTG team ids to leave out, such as a name whose age a person must settle",
    )
    p.add_argument(
        "--state",
        nargs="+",
        default=[],
        type=_state_for_team,
        metavar="TEAM_ID=ST",
        help="Set a team's US state where its listed location is wrong, e.g. 655369=MO",
    )
    p.add_argument(
        "--age",
        nargs="+",
        default=[],
        type=_age_for_team,
        metavar="TEAM_ID=uNN",
        help="File a team whose age cannot be read on a board a person named, e.g. 655369=u12",
    )
    p.add_argument(
        "--gender",
        nargs="+",
        default=[],
        type=_gender_for_team,
        metavar="TEAM_ID=Male|Female",
        help="Set a team's gender where it entered a division of the other gender, e.g. 655369=Female",
    )
    return p.parse_args()


def _leave_out_id(value: str) -> str:
    if not _TEAM_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not an HTG team id: {value!r}")
    return value


def collect_event(
    fetch: Callable[[str], Any],
    event_id: str,
    board_season: int,
    days_back: int,
    today: date,
    pause: Callable[[], None] = lambda: None,
    leave_out: FrozenSet[str] = frozenset(),
    states: Optional[Dict[str, str]] = None,
    age_groups: Optional[Dict[str, str]] = None,
    genders: Optional[Dict[str, str]] = None,
) -> Tuple[Event, List[TeamRow], List[TeamRow], List[EventGame], List[str], List[str], Dict[str, Set[str]]]:
    """Fetch the event and its divisions; return the roster, the games in window, the problems
    found, the divisions skipped and the flagged game ids.

    A forfeit or a disputed game is held however many divisions list it, and whichever copy is
    read first. ``fetch`` takes an API path and returns its parsed JSON. Raises
    :class:`LabelSeasonError` before returning any roster when the event's labels name the
    coming season.
    """
    event = parse_event_summary(fetch(summary_path(event_id)), event_id)
    pause()
    items = fetch(divisions_path(event_id))
    pause()
    if not isinstance(items, list) or not items:
        raise ScrapeFetchError(f"no divisions for event {event_id}")

    problems: List[str] = []
    division_skips: List[str] = []
    listings: List[Tuple[Division, TeamListing]] = []
    games: Dict[str, EventGame] = {}
    flagged = _no_flags()
    for item in items:
        parsed = parse_division(item)
        if parsed is None:
            name = _text(item, "Name") if isinstance(item, dict) else ""
            problems.append(f"{name or repr(item)}: unreadable division")
            continue
        division_id, division = parsed
        if item.get("Publish") is False:
            division_skips.append(f"{division.code}: not published")
            continue
        reason = skip_division(division)
        if reason:
            division_skips.append(f"{division.code}: {reason}")
            continue
        source_url = division_page_url(event_id, division_id)
        division_listings, list_problems = parse_standings(
            fetch(standings_path(event_id, division_id)), division, source_url
        )
        pause()
        division_games, game_problems, division_flagged = parse_games(
            fetch(games_path(event_id, division_id)), division, source_url
        )
        pause()
        listings.extend((division, listing) for listing in division_listings)
        for game in division_games:
            seen = games.setdefault(game.game_no, game)
            if seen is not game and not _same_game(seen, game):
                problems.append(
                    f"game {game.game_no}: listed in {seen.division_code} and {game.division_code}"
                    " with different details"
                )
                flagged["disputed"].add(game.game_no)
        problems.extend(list_problems + game_problems)
        for kind, game_ids in division_flagged.items():
            flagged[kind] |= game_ids

    mismatch = label_season_mismatch(listings, event.season)
    if mismatch:
        raise LabelSeasonError(mismatch)

    in_scope, skipped = build_roster(
        listings, event, board_season, leave_out, states, age_groups, genders, division_age_fallback=True
    )
    held = flagged["forfeits"] | flagged["disputed"]
    earliest = today - timedelta(days=days_back)
    in_window = [g for g in games.values() if g.game_no not in held and earliest <= g.game_date <= today]
    return event, in_scope, skipped, in_window, problems, division_skips, flagged


def htg_report_rows(rows: List[Dict]) -> List[Dict]:
    """The shared team report with its id column named for HTG."""
    return [{"htg_team_id": row["tc_team_id"], **{k: v for k, v in row.items() if k != "tc_team_id"}} for row in rows]


def main() -> int:
    args = parse_args()
    dry_run = not args.execute
    try:
        event_id = parse_event_url(args.event_url)
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
        token = read_api_token(session, event_id)
        event, in_scope, skipped, games, problems, division_skips, flagged = collect_event(
            lambda path: fetch_api(session, token, path),
            event_id,
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
        console.print(f"[yellow]Team ids named but not in this event: {', '.join(unknown)}[/yellow]")
    console.print(
        f"[bold]{escape(event.name)}[/bold] ({event.start.isoformat()} to {event.end.isoformat()}) — "
        f"{len(in_scope) + len(skipped)} teams, {len(in_scope)} in scope, {len(skipped)} left out"
        f"{'  [yellow]DRY RUN[/yellow]' if dry_run else ''}"
    )

    already = existing_aliases(supabase, provider_id, [row.tc_team_id for row in in_scope])
    preview = register_teams(
        HtgSportsGameMatcher(supabase, provider_id=provider_id, registration_mode=True, dry_run=True),
        provider_id,
        in_scope,
        already,
        provider_name=PROVIDER_NAME,
    )
    conflicts = shared_links(preview, provider_name=PROVIDER_NAME)
    if dry_run:
        outcomes = preview
    else:
        writer = HtgSportsGameMatcher(supabase, provider_id=provider_id, registration_mode=True)
        outcomes = register_teams(
            writer,
            provider_id,
            [row for row in in_scope if row.tc_team_id not in conflicts],
            already,
            provider_name=PROVIDER_NAME,
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
    teams = teams_by_id(supabase, sorted({o.team_id_master for o in outcomes.values() if o.team_id_master}))
    for team_id, reason in off_board_links(in_scope, outcomes, teams).items():
        outcomes[team_id] = Outcome("error", outcomes[team_id].team_id_master, reason=reason)

    records, held, cross_age = build_csv_rows(games, in_scope + skipped, outcomes, event, provider_code=PROVIDER_CODE)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{event.subdomain}_{event.season}_{stamp}"
    games_csv = args.output_dir / f"{prefix}_games.csv"
    cross_age_csv = args.output_dir / f"{prefix}_cross_age.csv"
    report_csv = args.output_dir / f"{prefix}_teams.csv"
    names = {team_id: team["team_name"] for team_id, team in teams.items()}
    write_csv(games_csv, REQUIRED_COLUMNS, records)
    # The two files a person opens carry registrant-typed names, so a leading = + - @ is defanged
    # there; the importer's own file keeps every name as written.
    write_csv(cross_age_csv, CROSS_AGE_COLUMNS, _for_spreadsheets(cross_age))
    write_csv(
        report_csv,
        HTG_REPORT_COLUMNS,
        _for_spreadsheets(htg_report_rows(report_rows(in_scope, skipped, outcomes, names))),
    )

    summary = Table(title=f"HTG Sports: {escape(event.name)} (event {event_id})")
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
    summary.add_row("forfeits and no-shows (not imported)", str(len(flagged["forfeits"])))
    summary.add_row("games listed twice with different details (held)", str(len(flagged["disputed"])))
    summary.add_row("results the site's standings ignore (imported)", str(len(flagged["ignored"])))
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
