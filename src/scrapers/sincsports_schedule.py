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

The ``parse_division`` and ``parse_tournament_index`` functions are pure
— unit tests run against committed fixtures with no network. The
``SincSportsScheduleScraper`` class wraps them with the existing
``SincSportsClubsScraper`` HTTP session (shared SINCSPORTS_* throttle
env vars) for live fetching.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
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
    name_link = team_div.find("a", href=re.compile(r"schedule\.aspx.*team="))
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


def parse_division(html: str, tournament_id: str, division_code: str) -> List[TournamentGame]:
    """Pure parser for one ``schedule.aspx?tid=X&div=Y`` page.

    Returns one ``TournamentGame`` per fixture with both team_ids resolved.
    Empty modal cards (no team links) are dropped silently. Status is
    ``"Cancelled"`` when a red ``<font>`` tag is present, ``"Played"`` when
    a numeric score is present, else ``"Scheduled"``.
    """
    soup = BeautifulSoup(html, "html.parser")
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
        """Fetch and parse one (tournament, division) schedule page."""
        url = f"{BASE_URL}{SCHEDULE_PATH}?tid={tid}&year={year}&stid={tid}&syear={year}&div={division_code}"
        logger.info(f"Fetching division: {url}")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        return parse_division(resp.text, tid, division_code)

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
