"""SOM Sports / athletes2events tournament scraper.

Targets ``somsports.athletes2events.com``, initially Club America Cup
(event 72, May 23-25 2026). The CLI is event-ID-parameterized so any
future event on the same platform reuses the work.

**Why this is NOT a ``ProviderScraper`` subclass** — only ``gotsport`` uses
that ABC. SOM Sports follows the peer-script convention
(``sincsports_schedule``, ``affinity_wa``, ``playmetrics_tournament``):
pure parser functions emit dataclasses, and a thin live wrapper composes
them with a shared ``requests.Session`` for HTTP. Tests run against
committed HTML fixtures with no network.

**Wire format** — the site is server-rendered HTML with three page types:

- ``/events/{event_id}/groups`` — flight index. One table per age cohort
  (``<th class="col-age">Boys-U19</th>``); each row carries a
  ``?flight-id=N`` link plus a tier label (Oro / Plata / Bronce /
  Champions). Dual-age cohorts are flagged in the tier label
  (e.g., ``Oro (2014/15 11 v 11)``); the table heading already carries
  the canonical age (Girls-U12), so the heading wins.
- ``/events/{event_id}/schedules?flight-id={id}`` — per-flight standings
  + match list. Standings tables have ``schedule-table`` class; match
  tables have ``matches-table`` class with one ``<tr class="bg-secondary">``
  date header per day, then one ``<tr>`` per game.
- ``/events/{event_id}/schedules?team-id={id}`` — team detail. ``(XX)``
  state code lives in the page's ``<h4>``: ``Crossfire B07/08 Academy
  ECNL (WA) - Matches``.

A two-pass scrape (flights → team enrichment) yields enough metadata
for the matcher's auto-create path — team_name, club_name (parsed
downstream), age_group, gender, state_code.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from src.scrapers._age_normalization import derive_division_age_group, normalize_age
from src.scrapers._http import retry_session_get

logger = logging.getLogger(__name__)

BASE_URL = "https://somsports.athletes2events.com"
GROUPS_PATH = "/events/{event_id}/groups"
SCHEDULES_PATH = "/events/{event_id}/schedules"

_FLIGHT_ID_QS_RE = re.compile(r"flight-id=(\d+)", re.IGNORECASE)
_TEAM_ID_QS_RE = re.compile(r"team-id=(\d+)", re.IGNORECASE)
# ``Boys-U19`` / ``Girls-U10`` / ``Boys U17`` (with or without hyphen).
_AGE_HEADING_RE = re.compile(r"(Boys?|Girls?)\s*[-\s]?\s*U(\d{1,2})", re.IGNORECASE)
# Date header at top of a per-day match table: ``Sat May 23, 2026``.
_DATE_HEADER_RE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})")
# Score cell: ``3 - 1`` (also tolerates ``3-1`` / ``3:1`` / ``3 v 1``).
_SCORE_RE = re.compile(r"^\s*(\d+)\s*[-vV:]\s*(\d+)\s*$")
# Team-detail state code: ``Crossfire B07/08 Academy ECNL (WA) - Matches``.
_STATE_CODE_RE = re.compile(r"\(([A-Z]{2})\)\s*(?:-\s*Matches)?\s*$")

DEFAULT_DELAY_MIN = float(os.getenv("SOMSPORTS_DELAY_MIN", "1.0"))
DEFAULT_DELAY_MAX = float(os.getenv("SOMSPORTS_DELAY_MAX", "2.0"))
DEFAULT_TIMEOUT = int(os.getenv("SOMSPORTS_TIMEOUT", "30"))
DEFAULT_ATTEMPTS = int(os.getenv("SOMSPORTS_ATTEMPTS", "3"))
DEFAULT_RETRY_DELAY = float(os.getenv("SOMSPORTS_RETRY_DELAY", "2.0"))
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FlightRef:
    """One row of the ``/events/{id}/groups`` flight index."""

    flight_id: int
    age_group: str  # canonical lowercase ``u10``..``u19``
    gender: str  # ``Male`` / ``Female``
    tier_label: str  # ``Oro`` / ``Plata`` / ``Bronce`` / ``Champions``
    raw_division_name: str  # ``Boys-U19 - Oro``


@dataclass(frozen=True)
class ScrapedTeam:
    """One row of a per-flight standings table."""

    provider_team_id: str
    team_name: str
    group_letter: str  # ``A`` / ``B`` / ``C``
    position: Optional[int]
    mp: Optional[int]
    w: Optional[int]
    d: Optional[int]
    losses: Optional[int]
    gf: Optional[int]
    ga: Optional[int]
    gd: Optional[int]
    pts: Optional[int]


@dataclass(frozen=True)
class TournamentGame:
    """One played fixture from a per-flight match table."""

    game_id: str
    game_date: Optional[date]
    kickoff_time: Optional[str]
    home_provider_team_id: str
    home_team_name: str
    away_provider_team_id: str
    away_team_name: str
    home_score: Optional[int]
    away_score: Optional[int]
    field: Optional[str]
    venue: Optional[str]
    flight_id: int
    group_letter: Optional[str]


@dataclass(frozen=True)
class TeamDetail:
    """State / coach metadata pulled from the team detail page."""

    provider_team_id: str
    state_code: Optional[str]
    coach: Optional[str]
    manager: Optional[str]


# ── Pure parser helpers ───────────────────────────────────────────────────────


def _text(tag: Optional[Tag]) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def _int_or_none(value: str) -> Optional[int]:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def _parse_score(s: str) -> Tuple[Optional[int], Optional[int]]:
    """``"3 - 1"`` → ``(3, 1)``. Empty / dash / non-numeric → ``(None, None)``."""
    if not s:
        return (None, None)
    m = _SCORE_RE.match(s)
    if not m:
        return (None, None)
    return (int(m.group(1)), int(m.group(2)))


def _parse_date_header(text: str) -> Optional[date]:
    """``"Sat May 23, 2026"`` → ``date(2026, 5, 23)``. ``None`` if unparseable.

    Tries abbreviated month (``%b``) first, then full (``%B``). SOM Sports
    emits abbreviated weekday names (``Sat``) and the May fixture happens
    to be ambiguous (``May`` is both abbreviated and full), so we have to
    accept both forms to avoid silently dropping every game in months
    where the abbreviation matters (Jun, Sep, Feb, etc.).
    """
    m = _DATE_HEADER_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1)
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _href_id(tag: Optional[Tag], pattern: re.Pattern) -> Optional[str]:
    if not tag:
        return None
    href = tag.get("href") or ""
    m = pattern.search(href)
    return m.group(1) if m else None


def parse_event_name(html: str) -> Optional[str]:
    """Pull the event title from the page-header ``<h2>``."""
    soup = BeautifulSoup(html, "lxml")
    h2 = soup.find("h2")
    text = _text(h2)
    return text or None


def parse_groups_page(html: str) -> List[FlightRef]:
    """Parse ``/events/{id}/groups`` into a list of ``FlightRef``.

    Each flight inherits the cohort (gender + age) from the table heading
    (``<th class="col-age">Boys-U19</th>``). The tier label (``Oro``,
    ``Plata``, ``Bronce``, ``Champions``) and flight_id come from the row
    body. Dual-age divisions are flagged in the tier label
    (``Oro (2014/15 11 v 11)``); the cohort heading already carries the
    canonical age, so the heading wins and ``derive_division_age_group``
    is only consulted as a defensive cross-check.
    """
    soup = BeautifulSoup(html, "lxml")
    flights: List[FlightRef] = []

    for table in soup.find_all("table"):
        col_age = table.find("th", class_=lambda c: c and "col-age" in c)
        if not col_age:
            continue
        heading = _text(col_age)
        m = _AGE_HEADING_RE.search(heading)
        if not m:
            continue
        gender_token = m.group(1).lower()
        gender = "Male" if gender_token.startswith("boy") else "Female"
        heading_age = normalize_age(int(m.group(2)))
        if not heading_age:
            continue

        for row in table.find_all("tr"):
            link = row.find("a", href=_FLIGHT_ID_QS_RE)
            if not link:
                continue
            href = link.get("href", "")
            fid_match = _FLIGHT_ID_QS_RE.search(href)
            if not fid_match:
                continue
            flight_id = int(fid_match.group(1))

            cells = row.find_all("td")
            tier_label = _text(cells[1]) if len(cells) >= 2 else ""

            # Defensive cross-check: if the tier label embeds a dual-age
            # birth-year form, the helper returns the older cohort; this
            # SHOULD match the heading age. Logged at DEBUG so the pure
            # parser stays log-quiet — peers like sincsports_schedule
            # don't emit from inside parser functions.
            tier_age = derive_division_age_group(tier_label)
            if tier_age and tier_age != heading_age:
                logger.debug(
                    "Flight %d age mismatch: heading=%s tier=%s (%r); using heading",
                    flight_id,
                    heading_age,
                    tier_age,
                    tier_label,
                )

            flights.append(
                FlightRef(
                    flight_id=flight_id,
                    age_group=heading_age,
                    gender=gender,
                    tier_label=tier_label,
                    raw_division_name=f"{heading} - {tier_label}".strip(" -"),
                )
            )
    return flights


def _parse_standings_table(table: Tag, group_letter: str) -> List[ScrapedTeam]:
    teams: List[ScrapedTeam] = []
    for row in table.find_all("tr"):
        if row.find("th"):
            continue
        link = row.find("a", href=_TEAM_ID_QS_RE)
        if not link:
            continue
        team_id = _href_id(link, _TEAM_ID_QS_RE)
        if not team_id:
            continue
        cells = row.find_all("td")
        if len(cells) < 11:
            continue
        team_name = _text(link)
        teams.append(
            ScrapedTeam(
                provider_team_id=team_id,
                team_name=team_name,
                group_letter=group_letter,
                position=_int_or_none(_text(cells[0])),
                mp=_int_or_none(_text(cells[3])),
                w=_int_or_none(_text(cells[4])),
                d=_int_or_none(_text(cells[5])),
                losses=_int_or_none(_text(cells[6])),
                gf=_int_or_none(_text(cells[7])),
                ga=_int_or_none(_text(cells[8])),
                gd=_int_or_none(_text(cells[9])),
                pts=_int_or_none(_text(cells[10])),
            )
        )
    return teams


def _parse_matches_table(table: Tag, flight_id_fallback: int) -> List[TournamentGame]:
    games: List[TournamentGame] = []
    current_date: Optional[date] = None

    # Direct-child <tr> only — the lxml parser does not insert a <tbody>
    # wrapper for these fixtures (verified on event 72 / flight 727).
    # If a future SOM Sports markup change adds <tbody>, this loop will
    # return 0 rows and the test suite will catch it loudly.
    for row in table.find_all("tr", recursive=False):
        # Date header: single <th colspan> wrapping the day string.
        if "bg-secondary" in (row.get("class") or []):
            current_date = _parse_date_header(_text(row))
            continue
        if row.find("th"):
            continue

        cells = row.find_all("td", recursive=False)
        if len(cells) < 9:
            continue

        game_num = _text(cells[0]).lstrip("#").strip()
        if not game_num:
            continue

        flight_link = cells[1].find("a", href=_FLIGHT_ID_QS_RE)
        fid_raw = _href_id(flight_link, _FLIGHT_ID_QS_RE)
        flight_id = int(fid_raw) if fid_raw else flight_id_fallback

        group_letter = _text(cells[2]) or None
        kickoff_time = _text(cells[3]) or None

        home_link = cells[4].find("a", href=_TEAM_ID_QS_RE)
        home_id = _href_id(home_link, _TEAM_ID_QS_RE)
        home_name = _text(home_link)

        score_text = _text(cells[5])
        home_score, away_score = _parse_score(score_text)

        away_link = cells[6].find("a", href=_TEAM_ID_QS_RE)
        away_id = _href_id(away_link, _TEAM_ID_QS_RE)
        away_name = _text(away_link)

        if not home_id or not away_id:
            continue  # bracket-placeholder / TBD row

        field = _text(cells[7].find("a") or cells[7]) or None
        venue = _text(cells[8].find("a") or cells[8]) or None

        games.append(
            TournamentGame(
                game_id=game_num,
                game_date=current_date,
                kickoff_time=kickoff_time,
                home_provider_team_id=home_id,
                home_team_name=home_name,
                away_provider_team_id=away_id,
                away_team_name=away_name,
                home_score=home_score,
                away_score=away_score,
                field=field,
                venue=venue,
                flight_id=flight_id,
                group_letter=group_letter,
            )
        )
    return games


def parse_schedule_page(html: str, flight_id: int) -> Tuple[List[ScrapedTeam], List[TournamentGame]]:
    """Parse a ``?flight-id=N`` page into standings + match list.

    Standings tables (one per group A/B/C…) use class ``schedule-table``;
    each is preceded by an ``<h4>Group A</h4>`` heading. Match tables use
    class ``matches-table``; each day is a sub-table with a
    ``<tr class="bg-secondary">`` date header. Both unplayed rows (empty /
    dash score) and bracket placeholders (no team link) are dropped.
    """
    soup = BeautifulSoup(html, "lxml")
    teams: List[ScrapedTeam] = []
    games: List[TournamentGame] = []

    # Standings — walk siblings to find the nearest preceding "<h4>Group X</h4>".
    for table in soup.find_all("table", class_=lambda c: c and "schedule-table" in c):
        group_letter = ""
        prev = table.find_previous(["h4"])
        prev_text = _text(prev)
        m = re.search(r"Group\s+([A-Z])", prev_text or "")
        if m:
            group_letter = m.group(1)
        teams.extend(_parse_standings_table(table, group_letter))

    for table in soup.find_all("table", class_=lambda c: c and "matches-table" in c):
        games.extend(_parse_matches_table(table, flight_id))

    return teams, games


def parse_team_detail_page(html: str, provider_team_id: str) -> TeamDetail:
    """Pull ``(XX)`` state code from the team detail page heading.

    The page header is rendered as ``<h4>Crossfire B07/08 Academy ECNL
    (WA) - Matches</h4>``; the 2-letter state code is what we need for
    auto-create. ``coach`` / ``manager`` columns are not surfaced on the
    public team page today — we leave them ``None`` so the dataclass can
    grow into them when SOM Sports adds them.
    """
    soup = BeautifulSoup(html, "lxml")
    state_code: Optional[str] = None

    for h4 in soup.find_all("h4"):
        text = _text(h4)
        if not text:
            continue
        m = _STATE_CODE_RE.search(text)
        if m:
            state_code = m.group(1)
            break

    return TeamDetail(
        provider_team_id=str(provider_team_id),
        state_code=state_code,
        coach=None,
        manager=None,
    )


# ── Live wrapper ──────────────────────────────────────────────────────────────


class SomSportsScraper:
    """Live wrapper around the parser helpers.

    Composes a shared ``requests.Session`` (UA + connection pooling) with
    ``retry_session_get`` for 429 / timeout handling and a
    ``time.sleep(uniform(delay_min, delay_max))`` jitter between calls.
    The pure ``parse_*`` functions are tested directly against committed
    HTML fixtures with no network.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        *,
        delay_min: Optional[float] = None,
        delay_max: Optional[float] = None,
        timeout: Optional[int] = None,
        attempts: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ):
        self.session: requests.Session = session or self._build_session()
        self.delay_min: float = delay_min if delay_min is not None else DEFAULT_DELAY_MIN
        self.delay_max: float = delay_max if delay_max is not None else DEFAULT_DELAY_MAX
        self.timeout: int = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.attempts: int = attempts if attempts is not None else DEFAULT_ATTEMPTS
        self.retry_delay: float = retry_delay if retry_delay is not None else DEFAULT_RETRY_DELAY

    @staticmethod
    def _build_session() -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        return s

    def _get(self, url: str) -> str:
        response = retry_session_get(
            self.session,
            url,
            attempts=self.attempts,
            retry_delay=self.retry_delay,
            baseline_bytes=None,
            is_event_url=False,
            provider="somsports",
            timeout=self.timeout,
        )
        response.raise_for_status()
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        return response.text

    def fetch_groups(self, event_id: int) -> Tuple[Optional[str], List[FlightRef]]:
        """Fetch the groups page and return ``(event_name, flights)``."""
        url = BASE_URL + GROUPS_PATH.format(event_id=event_id)
        logger.info("Fetching SOM Sports groups: %s", url)
        html = self._get(url)
        return parse_event_name(html), parse_groups_page(html)

    def fetch_flight(self, event_id: int, flight_id: int) -> Tuple[List[ScrapedTeam], List[TournamentGame]]:
        """Fetch one ``?flight-id=N`` page and parse it."""
        url = f"{BASE_URL}{SCHEDULES_PATH.format(event_id=event_id)}?flight-id={flight_id}"
        logger.info("Fetching SOM Sports flight %d: %s", flight_id, url)
        html = self._get(url)
        return parse_schedule_page(html, flight_id)

    def fetch_team_detail(self, event_id: int, provider_team_id: str) -> TeamDetail:
        """Fetch one ``?team-id=N`` page and pull its state code."""
        url = f"{BASE_URL}{SCHEDULES_PATH.format(event_id=event_id)}?team-id={provider_team_id}"
        logger.info("Fetching SOM Sports team detail %s: %s", provider_team_id, url)
        html = self._get(url)
        return parse_team_detail_page(html, provider_team_id)


# ── URL helpers (used by tests + CLI) ─────────────────────────────────────────


def split_schedule_url(url: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """``"…/events/72/schedules?flight-id=727"`` → ``(72, 727, None)``."""
    parsed = urlparse(url)
    m = re.search(r"/events/(\d+)/", parsed.path)
    event_id = int(m.group(1)) if m else None
    qs = parse_qs(parsed.query)
    flight_id = int(qs["flight-id"][0]) if "flight-id" in qs else None
    team_id = int(qs["team-id"][0]) if "team-id" in qs else None
    return event_id, flight_id, team_id
