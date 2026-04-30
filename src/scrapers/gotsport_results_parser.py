"""Game-result and standings parser for gotsport schedule pages.

Same HTML source as ``gotsport_pool_parser`` — the
``/schedules?group={group_id}`` page renders three layers:

1. Pool standings tables (already parsed by ``gotsport_pool_parser`` for
   ``pool_assignments.json``).
2. Per-day match tables — one row per game with home/away team links,
   score, time, location, and the gotsport ``match_id``. This module
   extracts those into ``GameResult`` records for the backtest pipeline,
   eliminating the dependency on the Supabase ``games`` table.
3. Per-pool W/L/D/GF/GA/GD/PTS standings — useful for backtest seeding
   analysis (computed standings vs. ranking-implied standings).

Pure HTML inspection — no HTTP, no captcha logic. Callers fetch via
``GotsportScraper.fetch_schedule_html`` and feed the response into the
parsers here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

__all__ = [
    "GameResult",
    "Standing",
    "parse_game_results_from_html",
    "parse_standings_from_html",
]


# Match table header signature — distinguishes per-day match tables from
# the standings tables (which share table.table-bordered styling).
_MATCH_HEADER = "Match #"

# Score cell format on completed games: ``"{home} - {away}"``. Pre-game
# rows have an empty cell. Forfeits / W-L marks are tolerated as
# ``None`` scores (the result is still a real game from a backtest
# perspective; downstream callers decide how to handle).
_SCORE_PATTERN = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$")
_TEAM_ID_PATTERN = re.compile(r"team=(\d+)")
_MATCH_ID_PATTERN = re.compile(r"match=(\d+)")


@dataclass(frozen=True)
class GameResult:
    """One scheduled or played game inside a tier.

    ``match_id`` is gotsport's per-match primary key (from the score cell's
    href). It's the natural dedupe key — re-scraping the same event
    re-emits the same ``match_id`` for a given matchup, even if the score
    changes (e.g., a forfeit reversal). ``home_score`` / ``away_score``
    are ``None`` for unplayed / TBD games. ``date_text`` is the page's
    raw date string (``"Feb 13, 2026"``); the caller normalizes if it
    needs an ISO date.
    """

    match_id: str
    home_provider_team_id: str
    home_team_name: str
    away_provider_team_id: str
    away_team_name: str
    home_score: int | None
    away_score: int | None
    date_text: str
    time_text: str
    location: str | None
    division_label: str | None


@dataclass(frozen=True)
class Standing:
    """One team's pool standings row (W/L/D/GF/GA/GD/PTS).

    ``rank`` is the on-page row number (finishing position for completed
    pools). ``provider_team_id`` is gotsport's team identity from the
    team-link href. All count fields are ``None`` if the cell is blank
    (rare; pre-tournament standings render as zeros, not blanks).
    """

    rank: int
    provider_team_id: str
    team_name: str
    matches_played: int | None
    wins: int | None
    losses: int | None
    draws: int | None
    goals_for: int | None
    goals_against: int | None
    goal_diff: int | None
    points: int | None


def parse_game_results_from_html(html: str) -> list[GameResult]:
    """Extract every game row from the schedule page's match tables.

    Returns one ``GameResult`` per row across ALL match tables on the
    page (gotsport renders one table per day per pool/bracket — they're
    all flat from our perspective). Rows missing both team IDs are
    skipped (placeholder / TBD pairings).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[GameResult] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if _MATCH_HEADER not in headers:
            continue
        for tr in table.find_all("tr"):
            if tr.find("th"):
                continue
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 7:
                continue
            game = _parse_match_row(cells)
            if game is not None:
                results.append(game)

    return results


def parse_standings_from_html(html: str) -> list[Standing]:
    """Extract every team's standings row across all pool standings tables."""
    soup = BeautifulSoup(html, "html.parser")
    standings: list[Standing] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if "PTS" not in headers or "Team" not in headers:
            continue
        for tr in table.find_all("tr"):
            if tr.find("th"):
                continue
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 10:
                continue
            standing = _parse_standings_row(cells)
            if standing is not None:
                standings.append(standing)

    return standings


def _parse_match_row(cells) -> GameResult | None:
    time_cell = cells[1]
    home_cell = cells[2]
    score_cell = cells[3]
    away_cell = cells[4]
    location_cell = cells[5]
    division_cell = cells[6]

    score_anchor = score_cell.find("a")
    score_text = (score_anchor.get_text(strip=True) if score_anchor else score_cell.get_text(strip=True)) or ""
    match_id = ""
    if score_anchor:
        match = _MATCH_ID_PATTERN.search(score_anchor.get("href") or "")
        if match:
            match_id = match.group(1)
    if not match_id:
        return None

    home_id, home_name = _extract_team(home_cell)
    away_id, away_name = _extract_team(away_cell)
    if not home_id or not away_id:
        return None

    home_score: int | None = None
    away_score: int | None = None
    score_match = _SCORE_PATTERN.match(score_text)
    if score_match:
        home_score = int(score_match.group(1))
        away_score = int(score_match.group(2))

    date_text, time_text = _split_date_time(time_cell)
    location = _first_link_text(location_cell)
    division_label = _first_link_text(division_cell) or division_cell.get_text(" ", strip=True) or None

    return GameResult(
        match_id=match_id,
        home_provider_team_id=home_id,
        home_team_name=home_name,
        away_provider_team_id=away_id,
        away_team_name=away_name,
        home_score=home_score,
        away_score=away_score,
        date_text=date_text,
        time_text=time_text,
        location=location,
        division_label=division_label,
    )


def _parse_standings_row(cells) -> Standing | None:
    try:
        rank = int(cells[0].get_text(strip=True))
    except ValueError:
        return None
    team_id, team_name = _extract_team(cells[1])
    if not team_id:
        return None
    return Standing(
        rank=rank,
        provider_team_id=team_id,
        team_name=team_name,
        matches_played=_safe_int(cells[2]),
        wins=_safe_int(cells[3]),
        losses=_safe_int(cells[4]),
        draws=_safe_int(cells[5]),
        goals_for=_safe_int(cells[6]),
        goals_against=_safe_int(cells[7]),
        goal_diff=_safe_int(cells[8]),
        points=_safe_int(cells[9]),
    )


def _extract_team(cell) -> tuple[str, str]:
    link = cell.find("a", href=_TEAM_ID_PATTERN)
    if not link:
        return ("", "")
    match = _TEAM_ID_PATTERN.search(link.get("href") or "")
    team_id = match.group(1) if match else ""
    return (team_id, link.get_text(strip=True))


def _split_date_time(cell) -> tuple[str, str]:
    """Pull ``Feb 13, 2026`` (date) and ``5:00PM MST`` (time) out of a time cell.

    Cell layout::

        <td>
        Feb 13, 2026
        <div class="text-color"> 5:00PM MST MST</div>
        ...
        </td>
    """
    time_div = cell.find("div", class_="text-color")
    time_text = time_div.get_text(" ", strip=True) if time_div else ""
    if time_div:
        time_div.extract()
    date_text = cell.get_text(" ", strip=True)
    return (date_text, time_text)


def _first_link_text(cell) -> str | None:
    link = cell.find("a")
    return link.get_text(strip=True) if link else None


def _safe_int(cell) -> int | None:
    text = cell.get_text(strip=True)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None
