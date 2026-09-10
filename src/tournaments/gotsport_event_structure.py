"""Read a GotSport division's pools and fixtures out of its schedule page.

Pure parsing: no HTTP, no Supabase, no Streamlit. The walker in
``gotsport_event_roster`` already fetches these pages for their team list and
discards everything else on them, which is where a played event's real
structure is written down.

Pools come from standings tables and nothing else. The fixture list is never
used to reconstruct pool membership: a division exists whose two "pools" only
ever played each other, so who-played-whom says nothing reliable about who was
grouped with whom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

__all__ = [
    "Fixture",
    "fixture_table_found",
    "parse_fixtures",
    "Pool",
    "PoolMember",
    "parse_pools",
    "standings_table_found",
]

_TEAM_ID = re.compile(r"[?&]team=(\d+)")
_POOL_ID = re.compile(r"^collapse-(\d+)$")
_STANDINGS_TEAM_HEADING = "team"
_STANDINGS_POINTS_HEADING = "pts"


@dataclass(frozen=True)
class PoolMember:
    """One team's row in a pool's standings table."""

    registration_id: str
    team_name: str
    standings_position: int
    """1-based row order. This is the FINAL table position of a played event,
    never the seed the director used — nothing may read it as a seeding."""


@dataclass(frozen=True)
class Pool:
    """One standings table: a group of teams the organizer tabled together."""

    pool_id: str
    """GotSport's own id, from the panel's ``collapse-<id>``. Empty when absent."""

    label: str
    """The panel heading, e.g. ``"Bracket A"``. Empty when the page names none."""

    members: tuple[PoolMember, ...]


def _squashed(text: str) -> str:
    return " ".join(str(text or "").replace("\xa0", " ").split()).casefold()


def _plain(text: str) -> str:
    return " ".join(str(text or "").replace("\xa0", " ").split())


def _standings_column(headings: list[str]) -> int | None:
    """Index of the team column, when this heading row belongs to a standings table.

    Both ``Team`` and ``PTS`` are required. A fixture table carries ``Home Team``
    and ``Away Team`` but no points column, so it cannot match here.
    """
    if _STANDINGS_TEAM_HEADING in headings and _STANDINGS_POINTS_HEADING in headings:
        return headings.index(_STANDINGS_TEAM_HEADING)
    return None


def _first_team_id(cell) -> str:
    for anchor in cell.find_all("a", href=True):
        match = _TEAM_ID.search(anchor["href"])
        if match:
            return match.group(1)
    return ""


def _panel(table):
    return table.find_parent(class_="panel-collapse")


def _pool_label(table) -> str:
    """The panel heading naming this pool.

    Read from the panel rather than from the nearest preceding text: two real
    events put "Standings" and a tiebreaker link immediately above the table,
    and a proximity heuristic reads those as the pool's name.
    """
    panel = _panel(table)
    container = panel.parent if panel is not None else None
    heading = container.find(class_="panel-heading") if container is not None else None
    return _plain(heading.get_text(" ")) if heading is not None else ""


def _pool_id(table) -> str:
    panel = _panel(table)
    match = _POOL_ID.match(str(panel.get("id") or "")) if panel is not None else None
    return match.group(1) if match else ""


def parse_pools(html: str) -> tuple[Pool, ...]:
    """Every standings table on the page, in page order, with its members."""
    soup = BeautifulSoup(html or "", "html.parser")
    pools: list[Pool] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headings = [_squashed(cell.get_text(" ")) for cell in rows[0].find_all(["td", "th"])]
        column = _standings_column(headings)
        if column is None:
            continue
        members: list[PoolMember] = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if column >= len(cells):
                continue
            registration_id = _first_team_id(cells[column])
            team_name = _plain(cells[column].get_text(" "))
            if not registration_id or not team_name:
                continue
            members.append(
                PoolMember(
                    registration_id=registration_id,
                    team_name=team_name,
                    standings_position=len(members) + 1,
                )
            )
        pools.append(
            Pool(pool_id=_pool_id(table), label=_pool_label(table), members=tuple(members))
        )
    return tuple(pools)


def standings_table_found(html: str) -> bool:
    """Did any table carry standings headings this module reads pools from?

    Separates a division whose pools are simply empty from one whose markup this
    module no longer understands. Only the second means pools were lost.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            headings = [_squashed(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
            if _standings_column(headings) is not None:
                return True
    return False


_MATCH_NUMBER = re.compile(r"^\s*(\d+)\s*(.*)$")
_SCORE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_FIXTURE_HEADINGS = ("match #", "home team", "away team")

KIND_POOL = "pool"
KIND_CROSS_POOL = "cross_pool"
KIND_BRACKET = "bracket"
KIND_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Fixture:
    """One scheduled game, exactly as the division page published it."""

    match_number: str
    bracket_label: str
    """``"Final"``, ``"Third Place"``, ``""``. Verbatim — never normalized, because
    the label is evidence of what the organizer actually ran."""

    kind: str
    home_registration_id: str | None
    away_registration_id: str | None
    home_score: int | None
    away_score: int | None
    kickoff: str
    """Page text, unparsed. A datetime is not needed to replay a structure."""

    location: str


def _fixture_columns(headings: list[str]) -> dict[str, int] | None:
    """Column indexes for a fixture table's heading row, or ``None``."""
    if not all(heading in headings for heading in _FIXTURE_HEADINGS):
        return None
    columns = {
        "match_number": headings.index("match #"),
        "home": headings.index("home team"),
        "away": headings.index("away team"),
    }
    for name, heading in (("time", "time"), ("results", "results"), ("location", "location")):
        if heading in headings:
            columns[name] = headings.index(heading)
    return columns


def _cell(cells: list, columns: dict[str, int], name: str) -> str:
    index = columns.get(name)
    if index is None or index >= len(cells):
        return ""
    return _plain(cells[index].get_text(" "))


def _team_id_at(cells: list, columns: dict[str, int], name: str) -> str | None:
    index = columns.get(name)
    if index is None or index >= len(cells):
        return None
    return _first_team_id(cells[index]) or None


def _scores(text: str) -> tuple[int | None, int | None]:
    match = _SCORE.match(text or "")
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_fixtures(html: str) -> tuple[Fixture, ...]:
    """Every fixture row on the page, in page order.

    ``kind`` is ``"bracket"`` for a labelled game and ``"unknown"`` otherwise;
    only a pool map can tell a pool game from a cross-pool one, and this
    function has none.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    fixtures: list[Fixture] = []
    for table in soup.find_all("table"):
        columns: dict[str, int] | None = None
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            headings = [_squashed(cell.get_text(" ")) for cell in cells]
            found = _fixture_columns(headings)
            if found:
                columns = found
                continue
            if columns is None:
                continue
            raw_number = _cell(cells, columns, "match_number")
            match = _MATCH_NUMBER.match(raw_number)
            if not match:
                continue
            home_score, away_score = _scores(_cell(cells, columns, "results"))
            fixtures.append(
                Fixture(
                    match_number=match.group(1),
                    bracket_label=match.group(2).strip(),
                    kind=KIND_BRACKET if match.group(2).strip() else KIND_UNKNOWN,
                    home_registration_id=_team_id_at(cells, columns, "home"),
                    away_registration_id=_team_id_at(cells, columns, "away"),
                    home_score=home_score,
                    away_score=away_score,
                    kickoff=_cell(cells, columns, "time"),
                    location=_cell(cells, columns, "location"),
                )
            )
    return tuple(fixtures)


def fixture_table_found(html: str) -> bool:
    """Did any table carry fixture headings this module reads games from?"""
    soup = BeautifulSoup(html or "", "html.parser")
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            headings = [_squashed(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
            if _fixture_columns(headings) is not None:
                return True
    return False
