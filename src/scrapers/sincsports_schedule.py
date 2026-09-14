"""SincSports tournament schedule scraper.

Parses ``schedule.aspx?tid=<TID>&div=<DIV>`` — the per-division fixture
list for a tournament. Complementary to ``sincsports.py`` (per-team
``games.aspx``) and ``sincsports_events.py`` (per-tournament team list at
``teamlist.aspx``).

**Why** — the per-team ``games.aspx`` flow respects SincSports' VIP
paywall: most events are CSS-blurred for non-paying users and the
existing parser intentionally skips them. The schedule.aspx page is
NOT subject to the same blur — every fixture across every division of
the tournament is rendered with date, time, team_ids, scores, and
status. For the 2026 Puri Cup this produces 443 played games vs. the
~224 the per-team scrape recovered; ~2× coverage with cleaner scores.

**Wire format** — each tournament root page links every active division
via ``?div=<DIV>`` query strings. Per division, every game is a
``<div class="form-row game-row">`` containing:

- date + time + game number (col-md-3)
- home team + away team links (col-md-5) with team_ids in the URL
- scores in two ``<div style='color:#A63351;...'>`` elements (col-3)
- status / venue (col-md-4) — ``<font color='red'>Cancelled</font>``
  marks cancellations

Newer events render a "sched2" layout instead. In either layout
the games list lives at ``&mode=schedule`` (league divisions otherwise open
on standings) and shows 50 games per page, linked by ``&gpage=N``. Cancelled,
postponed and forfeited sched2 games carry a ``sched2-gstat-off`` label,
sometimes alongside a recorded score.

The ``parse_division`` and ``parse_tournament_index`` functions are pure
— unit tests run against committed fixtures with no network. The
``SincSportsScheduleScraper`` class wraps them with the existing
``SincSportsClubsScraper`` HTTP session (shared SINCSPORTS_* throttle
env vars) for live fetching.
"""

from __future__ import annotations

import logging
import math
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

import requests
from bs4 import BeautifulSoup, Tag

from src.scrapers.sincsports_clubs import SincSportsClubsScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://soccer.sincsports.com"
SCHEDULE_PATH = "/schedule.aspx"

_TEAMID_HREF_RE = re.compile(r"teamid=([A-Z0-9]+)", re.IGNORECASE)
_DIV_QS_RE = re.compile(r"[?&]div=([A-Z0-9]+)", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*(?:AM|PM))")
_GAME_NUM_RE = re.compile(r"#(\d+)")
_SCHED2_TEAM_ID_RE = re.compile(r"[A-Z0-9]{1,20}")
_SCHED2_SCORE_RE = re.compile(r"[0-9]{1,3}")
_SCHED2_YEAR_RE = re.compile(r"[?&]year=([0-9]{4})")
_PAGER_CLASS_RE = re.compile(r"^sched2?-pager$")
_PAGER_INFO_CLASS_RE = re.compile(r"^sched2?-pager-info$")
_GPAGE_RE = re.compile(r"[?&]gpage=([0-9]{1,4})")
_PAGER_TOTAL_RE = re.compile(r"([0-9]{1,6})\s+games?", re.IGNORECASE)
_GAMES_PER_PAGE = 50
_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_PLACEHOLDER_DATE_RE = re.compile(r"0?1/0?1/[0-9]{4}$")


@dataclass
class TournamentGame:
    """One fixture from a tournament's schedule.aspx division page."""

    tournament_id: str
    division_code: str
    division_name: Optional[str]
    game_num: Optional[str]
    date: Optional[str]  # MM/DD/YYYY (raw); the driver normalizes to YYYY-MM-DD
    time: Optional[str]  # e.g., "10:40 AM"
    home_id: str
    home_name: Optional[str]
    home_score: Optional[int]
    away_id: str
    away_name: Optional[str]
    away_score: Optional[int]
    status: str  # "Played" | "Cancelled" | "Scheduled"
    venue: Optional[str]


def _parse_team_block(team_div: Optional[Tag]) -> tuple[Optional[str], Optional[str]]:
    if not team_div:
        return (None, None)
    team_link = team_div.find("a", href=re.compile(r"/team/team\.aspx.*teamid=", re.IGNORECASE))
    name_link = team_div.find("a", href=re.compile(r"schedule2?\.aspx.*team="))
    team_id = None
    if team_link:
        m = _TEAMID_HREF_RE.search(team_link.get("href", "") or "")
        if m:
            team_id = m.group(1).upper()
    name = name_link.get_text(strip=True) if name_link else None
    return (team_id, name)


def _parse_score_col(card: Tag) -> tuple[Optional[int], Optional[int]]:
    """Score lives in `col-3 text-right` as two color-styled <div>s."""
    score_col = card.find("div", class_=lambda c: c and "col-3" in c and "text-right" in c)
    if not score_col:
        return (None, None)
    score_divs = [d for d in score_col.find_all("div") if (d.get("style") or "").startswith("color:")]
    if len(score_divs) < 2:
        return (None, None)
    try:
        return (int(score_divs[0].get_text(strip=True)), int(score_divs[1].get_text(strip=True)))
    except ValueError:
        return (None, None)


def _parse_game_rows(soup: BeautifulSoup, tournament_id: str, division_code: str) -> List[TournamentGame]:
    games: List[TournamentGame] = []

    for card in soup.find_all("div", class_=lambda c: c and "form-row" in c and "game-row" in c):
        text = card.get_text(" ", strip=True)
        date_m = _DATE_RE.search(text)
        time_m = _TIME_RE.search(text)
        num_m = _GAME_NUM_RE.search(text)

        home_id, home_name = _parse_team_block(card.find("div", class_="hometeam"))
        away_id, away_name = _parse_team_block(card.find("div", class_="awayteam"))
        if not home_id or not away_id:
            continue  # empty / placeholder card

        division_name = None
        big = card.find("span", class_="bigOnly")
        if big:
            division_name = big.get_text(strip=True)

        home_score, away_score = _parse_score_col(card)

        cancelled = card.find("font", color="red")
        if cancelled:
            status = cancelled.get_text(strip=True) or "Cancelled"
        elif home_score is not None and away_score is not None:
            status = "Played"
        else:
            status = "Scheduled"

        # Venue is typically the second <span> in col-md-4 after the division name
        # (often a TTMap link to a numbered field). We capture the visible text.
        venue: Optional[str] = None
        col_md_4 = card.find("div", class_=lambda c: c and "col-md-4" in c)
        if col_md_4:
            venue_link = col_md_4.find("a", href=re.compile(r"TTMap\.aspx"))
            if venue_link:
                venue = venue_link.get_text(strip=True)

        games.append(
            TournamentGame(
                tournament_id=tournament_id,
                division_code=division_code,
                division_name=division_name,
                game_num=num_m.group(1) if num_m else None,
                date=date_m.group(1) if date_m else None,
                time=time_m.group(1) if time_m else None,
                home_id=home_id,
                home_name=home_name,
                home_score=home_score,
                away_id=away_id,
                away_name=away_name,
                away_score=away_score,
                status=status,
                venue=venue,
            )
        )
    return games


def _parse_sched2_team(team_div: Tag) -> tuple[Optional[str], Optional[str], Optional[int]]:
    follow = team_div.find("a", attrs={"data-team": True})
    team_id = (follow.get("data-team") or "").strip().upper() if follow else ""
    name_link = team_div.find("a", class_="sched2-team-lnk")
    score_el = team_div.find(class_="sched2-team-score")
    score_text = score_el.get_text(strip=True) if score_el else ""
    return (
        team_id if _SCHED2_TEAM_ID_RE.fullmatch(team_id) else None,
        name_link.get_text(strip=True) if name_link else None,
        int(score_text) if _SCHED2_SCORE_RE.fullmatch(score_text) else None,
    )


def _sched2_division_name(soup: BeautifulSoup, division_code: str) -> Optional[str]:
    for option in soup.select("select.sched2-select option[selected]"):
        m = _DIV_QS_RE.search(option.get("value") or "")
        if m and m.group(1).upper() == division_code.upper():
            return option.get_text(strip=True)
    return None


def _sched2_day_date(day: Tag, event_year: int) -> Optional[str]:
    """Resolve a yearless day header (``SAT`` / ``Feb 14``) to ``M/D/YYYY``.

    Of the event year and the years either side, at most one puts that month
    and day on the printed weekday; when none does, the date stays blank.
    """
    date_el = day.find(class_="sched2-dayhd-date")
    dow_el = day.find(class_="sched2-dayhd-dow")
    if not date_el or not dow_el:
        return None
    try:
        month_day = datetime.strptime(f"{date_el.get_text(strip=True)} 2000", "%b %d %Y")
    except ValueError:
        return None
    weekday = dow_el.get_text(strip=True).upper()[:3]
    for year in (event_year, event_year + 1, event_year - 1):
        try:
            d = date(year, month_day.month, month_day.day)
        except ValueError:
            continue
        if _WEEKDAYS[d.weekday()] == weekday:
            return f"{d.month}/{d.day}/{d.year}"
    return None


def _parse_sched2_games(soup: BeautifulSoup, tournament_id: str, division_code: str) -> List[TournamentGame]:
    year_link = soup.find("a", href=_SCHED2_YEAR_RE)
    event_year = int(_SCHED2_YEAR_RE.search(year_link["href"]).group(1)) if year_link else None
    if event_year is None:
        logger.warning(f"{tournament_id} {division_code}: no event year on page; game dates left blank")

    division_name = _sched2_division_name(soup, division_code)
    games: List[TournamentGame] = []

    for day in soup.find_all("div", class_="sched2-daygroup"):
        game_date = _sched2_day_date(day, event_year) if event_year else None

        for card in day.find_all("div", class_="sched2-game"):
            teams = card.find_all("div", class_="sched2-team")
            if len(teams) < 2:
                continue
            home_id, home_name, home_score = _parse_sched2_team(teams[0])
            away_id, away_name, away_score = _parse_sched2_team(teams[1])
            if not home_id or not away_id:
                continue  # unfilled bracket slot or unreadable team id

            off_label = card.find(class_="sched2-gstat-off")
            if off_label:
                status = off_label.get_text(" ", strip=True) or "Cancelled"
            elif home_score is not None and away_score is not None:
                status = "Played"
            else:
                status = "Scheduled"

            time_el = card.find(class_="sched2-game-time")
            num_el = card.find(class_="sched2-game-num")
            venue_el = card.find("a", class_="sched2-field-link")
            games.append(
                TournamentGame(
                    tournament_id=tournament_id,
                    division_code=division_code,
                    division_name=division_name,
                    game_num=num_el.get_text(strip=True).lstrip("#") if num_el else None,
                    date=game_date,
                    time=time_el.get_text(strip=True) if time_el else None,
                    home_id=home_id,
                    home_name=home_name,
                    home_score=home_score,
                    away_id=away_id,
                    away_name=away_name,
                    away_score=away_score,
                    status=status,
                    venue=venue_el.get_text(strip=True) if venue_el else None,
                )
            )
    return games


def parse_division_pages(pages: List[str], tournament_id: str, division_code: str) -> List[TournamentGame]:
    """Pure parser for every page of one ``schedule.aspx?tid=X&div=Y`` division, in ``gpage`` order.

    Returns one ``TournamentGame`` per fixture with both team_ids resolved.
    Empty modal cards and unfilled bracket slots (no readable team ids) are dropped
    silently, and a game repeated across pages (the schedule shifting between
    fetches) is kept once. Status is the site's own label for a cancelled,
    postponed or forfeited game, ``"Played"`` when both scores are present,
    else ``"Scheduled"``. A game dated 1 January is left undated: SincSports
    files games with no real date there, some of them scored.
    """
    games: List[TournamentGame] = []
    seen = set()
    for html in pages:
        soup = BeautifulSoup(html or "", "html.parser")
        if soup.find("div", class_="sched2-game"):
            page_games = _parse_sched2_games(soup, tournament_id, division_code)
        else:
            page_games = _parse_game_rows(soup, tournament_id, division_code)
        for g in page_games:
            if g.date and _PLACEHOLDER_DATE_RE.match(g.date):
                g.date = None
            key = (g.date, g.time, g.home_id, g.away_id, g.game_num)
            if key not in seen:
                seen.add(key)
                games.append(g)
    return games


def parse_division(html: str, tournament_id: str, division_code: str) -> List[TournamentGame]:
    """Pure parser for one ``schedule.aspx?tid=X&div=Y`` page; see ``parse_division_pages``."""
    return parse_division_pages([html], tournament_id, division_code)


def parse_page_count(html: str) -> int:
    """Return how many ``gpage`` pages a division's games list spans; 1 when it has no pager.

    The pager (``sched-pager`` in the old layout, ``sched2-pager`` in sched2)
    links only the pages near the current one, so the count comes from its
    "N games" total as well as its links.
    """
    pager = BeautifulSoup(html or "", "html.parser").find("div", class_=_PAGER_CLASS_RE)
    if not pager:
        return 1
    info = pager.find(class_=_PAGER_INFO_CLASS_RE)
    total_m = _PAGER_TOTAL_RE.search(info.get_text(" ", strip=True)) if info else None
    pages_by_total = math.ceil(int(total_m.group(1)) / _GAMES_PER_PAGE) if total_m else 1
    linked_pages = [int(m.group(1)) for a in pager.find_all("a", href=True) if (m := _GPAGE_RE.search(a["href"]))]
    return max([pages_by_total, *linked_pages])


def parse_tournament_index(html: str) -> List[str]:
    """Return the deduped list of division codes referenced from the tournament root.

    Drops the special ``N`` placeholder (a dropdown sentinel).
    """
    codes = {m.group(1).upper() for m in _DIV_QS_RE.finditer(html or "")}
    codes.discard("N")
    return sorted(codes)


class SincSportsScheduleScraper:
    """Live wrapper for ``schedule.aspx`` parsing.

    Reuses ``SincSportsClubsScraper``'s requests session so all SincSports
    scrapers share the same UA, retry adapter, and SINCSPORTS_DELAY_MIN/MAX
    throttle knobs. The class adds a fetch-and-parse loop; tests hit the
    pure ``parse_*`` functions directly without any network.
    """

    def __init__(
        self,
        delay_min: Optional[float] = None,
        delay_max: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self._http = SincSportsClubsScraper(delay_min=delay_min, delay_max=delay_max, timeout=timeout)
        self.session: requests.Session = self._http.session
        self.delay_min: float = self._http.delay_min
        self.delay_max: float = self._http.delay_max
        self.timeout: int = self._http.timeout
        self.errors: List[dict] = []

    def fetch_division_codes(self, tid: str, year: int = 2026) -> List[str]:
        """Fetch the tournament root and return every active division code."""
        url = f"{BASE_URL}{SCHEDULE_PATH}?tid={tid}&year={year}&stid={tid}&syear={year}"
        logger.info(f"Fetching tournament index: {url}")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        return parse_tournament_index(resp.text)

    def fetch_division(self, tid: str, division_code: str, year: int = 2026) -> List[TournamentGame]:
        """Fetch and parse every games page of one (tournament, division) schedule."""
        url = (
            f"{BASE_URL}{SCHEDULE_PATH}?tid={tid}&year={year}&stid={tid}&syear={year}&div={division_code}&mode=schedule"
        )
        pages = [self._fetch_division_page(url)]
        for page in range(2, parse_page_count(pages[0]) + 1):
            pages.append(self._fetch_division_page(f"{url}&gpage={page}"))
        return parse_division_pages(pages, tid, division_code)

    def _fetch_division_page(self, url: str) -> str:
        logger.info(f"Fetching division: {url}")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        return resp.text

    def fetch_tournament(self, tid: str, year: int = 2026) -> List[TournamentGame]:
        """Iterate every division in a tournament and return all games.

        Per-division failures are recorded on ``self.errors`` and the loop
        continues — partial results are preferable to losing the whole run.
        """
        codes = self.fetch_division_codes(tid, year=year)
        logger.info(f"Tournament {tid}: {len(codes)} divisions to scrape")
        all_games: List[TournamentGame] = []
        for code in codes:
            try:
                all_games.extend(self.fetch_division(tid, code, year=year))
            except Exception as e:
                logger.error(f"Division {code} failed: {e}")
                self.errors.append({"division": code, "error": str(e)})
        return all_games
