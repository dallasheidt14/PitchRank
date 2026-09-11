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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

__all__ = [
    "Fixture",
    "Pool",
    "PoolMember",
    "PublishedLink",
    "ScrapedDivision",
    "classify_fixtures",
    "fixture_table_found",
    "parse_division_structure",
    "parse_fixtures",
    "parse_pools",
    "standings_table_found",
    "summarize_structure_quality",
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
    """Every standings table on the page, in page order, with its members.

    Scans every row for the heading row rather than reading ``rows[0]`` alone,
    mirroring ``parse_fixtures`` and both ``*_table_found`` detectors. A title or
    spacer row above the headings is otherwise enough to skip the whole table
    while ``standings_table_found`` — which does scan — still reports ``True``,
    and the division then claims ``pools_readable=True`` with no pools: a
    confident "publishes no pools yet" about pools that were actually lost.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    pools: list[Pool] = []
    for table in soup.find_all("table"):
        column: int | None = None
        members: list[PoolMember] = []
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            headings = [_squashed(cell.get_text(" ")) for cell in cells]
            found = _standings_column(headings)
            if found is not None:
                column = found
                continue
            if len(cells) == 1 and cells[0].get("colspan"):
                continue
            if column is None or column >= len(cells):
                continue
            registration_id = _first_team_id(cells[column])
            team_name = _plain(cells[column].get_text(" "))
            if not team_name:
                continue
            members.append(
                PoolMember(
                    registration_id=registration_id,
                    team_name=team_name,
                    standings_position=len(members) + 1,
                )
            )
        if column is None:
            continue
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
_SCORE = re.compile(
    r"^\s*(\d+)\s*-\s*(\d+)(?:\s+PKS:\s*(\d+)\s*-\s*(\d+))?\s*$",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+[0-9]{1,2},?\s+[0-9]{4}\b|\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b|"
    r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}\b",
    re.IGNORECASE,
)
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
    home_label: str = ""
    away_label: str = ""
    """Published team names or slot text, including when there is no team link."""

    result_text: str = ""
    home_shootout_score: int | None = None
    away_shootout_score: int | None = None
    winner_side: str = ""
    winner_registration_id: str | None = None
    """Observed result winner, never an inferred qualification/advancement rule.

    ``winner_side`` is ``home`` / ``away`` / empty, so an identified winning
    side survives even when the source omits its registration link. Shootout
    scores decide the winner when published; regulation scores stay separate.
    """

    result_status: str = "not_captured"
    """played / unplayed / cancelled / postponed / forfeit / unrecognized.
    ``not_captured`` marks legacy records whose raw result was not retained."""

    date_label: str = ""
    """Published date cell or date header. Never filled from the wall clock."""

    source_url: str = ""


def _fixture_columns(headings: list[str]) -> dict[str, int] | None:
    """Column indexes for a fixture table's heading row, or ``None``."""
    if not all(heading in headings for heading in _FIXTURE_HEADINGS):
        return None
    columns = {
        "match_number": headings.index("match #"),
        "home": headings.index("home team"),
        "away": headings.index("away team"),
    }
    for name, heading in (
        ("time", "time"), ("date", "date"), ("results", "results"), ("location", "location")
    ):
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
    result = _result(text or "")
    return result["home_score"], result["away_score"]


def _result(text: str) -> dict:
    """Interpret only recognized result forms; retain every other form verbatim."""
    match = _SCORE.fullmatch(text)
    if match:
        home, away = int(match.group(1)), int(match.group(2))
        home_pks = int(match.group(3)) if match.group(3) is not None else None
        away_pks = int(match.group(4)) if match.group(4) is not None else None
        deciding_home, deciding_away = (home_pks, away_pks) if home_pks is not None else (home, away)
        return {
            "home_score": home,
            "away_score": away,
            "home_shootout_score": home_pks,
            "away_shootout_score": away_pks,
            "winner_side": (
                "home" if deciding_home > deciding_away else "away" if deciding_away > deciding_home else ""
            ),
            "result_status": "played",
        }
    normalized = _squashed(text)
    status = {
        "": "unplayed", "-": "unplayed", "vs": "unplayed", "vs.": "unplayed",
        "cancelled": "cancelled", "canceled": "cancelled", "postponed": "postponed",
        "forfeit": "forfeit", "forfeited": "forfeit",
    }.get(normalized, "unrecognized")
    return {"home_score": None, "away_score": None, "result_status": status, "winner_side": ""}


def _fixture_source(cells: list, columns: dict[str, int], source_url: str) -> str:
    for name in ("results", "match_number"):
        index = columns.get(name)
        if index is None or index >= len(cells):
            continue
        for anchor in cells[index].find_all("a", href=True):
            href = str(anchor["href"])
            if re.search(r"[?&]match=[0-9]+(?:&|$)", href):
                return urljoin(source_url, href)
    return source_url


def _table_date(table) -> str:
    caption = table.find("caption")
    if caption is not None and _DATE.search(caption.get_text(" ")):
        return _plain(caption.get_text(" "))
    # Stop at the previous table rather than borrowing another fixture table's
    # date when this one publishes none. These are headings, not nearby prose.
    heading = table.find_previous(["h2", "h3", "h4", "h5", "h6", "table"])
    if (
        heading is not None and heading.name != "table" and heading.find_parent("table") is None
        and _DATE.search(heading.get_text(" "))
    ):
        return _plain(heading.get_text(" "))
    return ""


def parse_fixtures(html: str, *, source_url: str = "") -> tuple[Fixture, ...]:
    """Every fixture row on the page, in page order.

    ``kind`` is ``"bracket"`` for a labelled game and ``"unknown"`` otherwise;
    only a pool map can tell a pool game from a cross-pool one, and this
    function has none.

    A row whose Match # cell has no leading digit is still a real game, not
    table furniture, when either side carries a team id -- GotSport
    sometimes publishes a fixture with a blank Match # cell, or with a
    knockout label and no number at all. That row is kept with
    ``match_number=""`` and the cell's own text (blank, or a label like
    ``"Final"``) as ``bracket_label``. Published participant text also counts:
    ``Winner Semi-Final A`` is a real slot even without a registration link.
    A spanning date/sub-heading row is table furniture, never a fixture.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    fixtures: list[Fixture] = []
    for table in soup.find_all("table"):
        columns: dict[str, int] | None = None
        date_label = _table_date(table)
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            headings = [_squashed(cell.get_text(" ")) for cell in cells]
            found = _fixture_columns(headings)
            if found:
                columns = found
                continue
            if len(cells) == 1 and cells[0].get("colspan"):
                text = _plain(cells[0].get_text(" "))
                if _DATE.search(text):
                    date_label = text
                continue
            if columns is None:
                continue
            raw_number = _cell(cells, columns, "match_number")
            home_registration_id = _team_id_at(cells, columns, "home")
            away_registration_id = _team_id_at(cells, columns, "away")
            home_label = _cell(cells, columns, "home")
            away_label = _cell(cells, columns, "away")
            match = _MATCH_NUMBER.match(raw_number)
            if match:
                match_number = match.group(1)
                bracket_label = match.group(2).strip()
            elif home_label or away_label:
                match_number = ""
                bracket_label = raw_number.strip()
            else:
                continue
            result_text = _cell(cells, columns, "results")
            result = _result(result_text)
            winner_id = {
                "home": home_registration_id, "away": away_registration_id,
            }.get(result["winner_side"])
            kickoff = _cell(cells, columns, "time")
            kickoff_date = _DATE.search(kickoff)
            fixtures.append(
                Fixture(
                    match_number=match_number,
                    bracket_label=bracket_label,
                    kind=KIND_BRACKET if bracket_label else KIND_UNKNOWN,
                    home_registration_id=home_registration_id,
                    away_registration_id=away_registration_id,
                    **result,
                    kickoff=kickoff,
                    location=_cell(cells, columns, "location"),
                    home_label=home_label,
                    away_label=away_label,
                    result_text=result_text,
                    winner_registration_id=winner_id,
                    date_label=(
                        _cell(cells, columns, "date")
                        or (kickoff_date.group(0) if kickoff_date else date_label)
                    ),
                    source_url=_fixture_source(cells, columns, source_url),
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


@dataclass(frozen=True)
class PublishedLink:
    """A published rules/tiebreaker reference; its target has not been fetched."""

    label: str
    url: str


@dataclass(frozen=True)
class ScrapedDivision:
    """One division's structure, exactly as its schedule page published it."""

    group_id: str
    division_label: str
    pools: tuple[Pool, ...]
    fixtures: tuple[Fixture, ...]
    pools_readable: bool
    fixtures_readable: bool
    warnings: tuple[str, ...]
    age_group: str = ""
    """Lowercase ``u12``, or empty when the label names no single board. Empty
    is a real answer — the event did not say — and the display prints it as
    such rather than leaving a blank that reads as a fault.

    Defaulted, and last, so every construction that predates it still works."""

    gender: str = ""
    source_url: str = ""
    rules_links: tuple[PublishedLink, ...] = ()
    published_age_group: str = ""
    published_cohort_label: str = ""


def classify_fixtures(
    fixtures: Sequence[Fixture], pools: Sequence[Pool]
) -> tuple[Fixture, ...]:
    """Tag each fixture ``pool`` / ``cross_pool`` / ``bracket`` / ``unknown``.

    Lookup only. A labelled game keeps ``bracket`` — the organizer named it, and
    no amount of pool membership overrides that. Everything else is decided by
    whether both sides appear in the same standings table, so a division that
    played nothing inside its own pools is described as it actually was rather
    than forced into a pool-play shape.

    A team listed in multiple pools stays ambiguous. Preferring either would
    be a guess, so its unlabelled fixtures remain unclassified.
    """
    pool_by_team: dict[str, int] = {}
    ambiguous: set[str] = set()
    for index, pool in enumerate(pools):
        for member in pool.members:
            team_id = member.registration_id
            if not team_id:
                continue
            if team_id in pool_by_team and pool_by_team[team_id] != index:
                ambiguous.add(team_id)
            pool_by_team[team_id] = index
    for team_id in ambiguous:
        pool_by_team.pop(team_id)

    classified: list[Fixture] = []
    for fixture in fixtures:
        if fixture.bracket_label:
            classified.append(replace(fixture, kind=KIND_BRACKET))
            continue
        home = pool_by_team.get(fixture.home_registration_id or "")
        away = pool_by_team.get(fixture.away_registration_id or "")
        if home is None or away is None:
            kind = KIND_UNKNOWN
        elif home == away:
            kind = KIND_POOL
        else:
            kind = KIND_CROSS_POOL
        classified.append(replace(fixture, kind=kind))
    return tuple(classified)


def parse_division_structure(
    *,
    group_id: str,
    division_label: str,
    html: str,
    age_group: str = "",
    gender: str = "",
    source_url: str = "",
    published_age_group: str = "",
    published_cohort_label: str = "",
) -> ScrapedDivision:
    """The whole structure of one division, read from its schedule page."""
    pools = parse_pools(html)
    pools_readable = standings_table_found(html)
    fixtures_readable = fixture_table_found(html)
    parsed_fixtures = parse_fixtures(html, source_url=source_url)
    named = division_label or f"group {group_id}"

    warnings: list[str] = []
    if not pools_readable:
        warnings.append(
            f"Division {named}: no standings table this module recognizes, so its "
            "pools could not be read"
        )
    elif not pools:
        warnings.append(f"Division {named} publishes no pools yet")
    if not fixtures_readable:
        warnings.append(
            f"Division {named}: no fixture table this module recognizes, so its "
            "games could not be read"
        )
    missing_match_number = sum(1 for f in parsed_fixtures if f.match_number == "")
    if missing_match_number:
        warnings.append(
            f"Division {named}: {missing_match_number} fixture(s) had no match "
            "number and were kept without one"
        )
    unrecognized = sum(f.result_status == "unrecognized" for f in parsed_fixtures)
    if unrecognized:
        warnings.append(
            f"Division {named}: {unrecognized} fixture result(s) could not be interpreted; "
            "their published text was kept"
        )
    missing_pool_ids = sum(not m.registration_id for pool in pools for m in pool.members)
    if missing_pool_ids:
        warnings.append(
            f"Division {named}: {missing_pool_ids} pool member(s) had no registration link; "
            "their names and positions were kept"
        )
    missing_participants = sum(
        not f.home_registration_id or not f.away_registration_id for f in parsed_fixtures
    )
    if missing_participants:
        warnings.append(
            f"Division {named}: {missing_participants} fixture(s) had an unidentified participant; "
            "their published team or slot labels were kept"
        )

    return ScrapedDivision(
        group_id=group_id,
        division_label=division_label,
        age_group=age_group,
        gender=gender,
        pools=pools,
        fixtures=classify_fixtures(parsed_fixtures, pools),
        pools_readable=pools_readable,
        fixtures_readable=fixtures_readable,
        warnings=tuple(warnings),
        source_url=source_url,
        rules_links=_published_rules_links(html, source_url),
        published_age_group=published_age_group,
        published_cohort_label=published_cohort_label,
    )


def _published_rules_links(html: str, source_url: str) -> tuple[PublishedLink, ...]:
    links: list[PublishedLink] = []
    seen: set[tuple[str, str]] = set()
    for anchor in BeautifulSoup(html or "", "html.parser").find_all("a", href=True):
        label, href = _plain(anchor.get_text(" ")), str(anchor["href"])
        if not re.search(r"rules?|tie[-_\s]?break", label + " " + href, re.IGNORECASE):
            continue
        if urlsplit(href).scheme not in ("", "http", "https"):
            continue
        url = urljoin(source_url, href)
        if (label, url) not in seen:
            links.append(PublishedLink(label=label, url=url))
            seen.add((label, url))
    return tuple(links)


def summarize_structure_quality(divisions: Sequence[ScrapedDivision]) -> dict[str, int | bool]:
    """Capture diagnostics, not a claim about matching or replay readiness.

    Empty or unplayed tables can be faithfully captured. Conversely, finding a
    table does not mean every participant/result was readable. Fixture counters
    count affected rows, not the number of missing fields. Legacy records
    distinguish unavailable original result text from a verified unplayed game.
    """
    fixtures = [fixture for division in divisions for fixture in division.fixtures]
    unreadable_pools = sum(not d.pools_readable for d in divisions)
    unreadable_fixtures = sum(not d.fixtures_readable for d in divisions)
    return {
        "tables_readable": bool(divisions) and not unreadable_pools and not unreadable_fixtures,
        "division_count": len(divisions),
        "fixture_count": len(fixtures),
        "unreadable_pool_divisions": unreadable_pools,
        "unreadable_fixture_divisions": unreadable_fixtures,
        "empty_fixture_divisions": sum(not d.fixtures for d in divisions),
        "missing_participant_ids": sum(
            not f.home_registration_id or not f.away_registration_id for f in fixtures
        ),
        "missing_participant_labels": sum(not f.home_label or not f.away_label for f in fixtures),
        "unknown_fixtures": sum(f.kind == KIND_UNKNOWN for f in fixtures),
        "missing_match_numbers": sum(not f.match_number for f in fixtures),
        "unrecognized_results": sum(f.result_status == "unrecognized" for f in fixtures),
        "unplayed_fixtures": sum(f.result_status == "unplayed" for f in fixtures),
        "uncaptured_results": sum(f.result_status == "not_captured" for f in fixtures),
        "shootout_fixtures": sum(f.home_shootout_score is not None for f in fixtures),
        "unresolved_bracket_results": sum(
            f.kind == KIND_BRACKET and f.result_status == "played" and not f.winner_side
            for f in fixtures
        ),
        "pool_members_missing_ids": sum(
            not member.registration_id for d in divisions for pool in d.pools for member in pool.members
        ),
    }
