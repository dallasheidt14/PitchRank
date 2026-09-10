# MatchBalance Exact Event Structure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Walk a played GotSport event, capture its exact structure (pools with membership, every fixture including knockout games), and match its teams to the PitchRank database without writing a single row to that database.

**Architecture:** A pure parser reads pools and fixtures out of the division-schedule HTML the existing walker already fetches; the walker returns them as a new additive field on `EventRoster`; a storage module persists them as `event_structure.json`; a new Backtest-view intake surface drives the walk and runs the Seeding tab's read-only resolver over the teams.

**Tech Stack:** Python 3.11, BeautifulSoup4, Streamlit, pytest. No new dependencies.

**Spec:** `.turbo/specs/matchbalance-exact-event-structure.md`

## Global Constraints

- **No writes to the PitchRank database anywhere in this flow.** No `insert`, `upsert`, `update`, `delete`, or `rpc`. Never import `src/tournaments/alias_writer.py` or `src/tournaments/seeding_enqueue.py` from any file this plan creates or modifies.
- **Never infer structure.** Pools come from standings tables only; they are never reconstructed from fixtures. A division whose standings tables cannot be read is recorded as unreadable.
- **No new page fetches.** The parser runs on HTML the walker already retrieves. A walk must cost exactly what it costs today.
- **Additive only on `EventRoster`.** `teams`, `warnings`, all counters and `is_complete` are untouched, so the Seeding tab cannot regress.
- Branch off `origin/main`; never commit to `main`. This checkout is shared — stage only the paths each task names, never `git add -A`.
- Lint gate: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`.
- Test gate: `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`. `pytest` and `ruff` are not on PATH — always invoke through `python -m`.
- Age groups are stored lowercase (`u14`); gender is canonical `Male` / `Female`.

---

### Task 1: Pool parsing

**Files:**
- Create: `src/tournaments/gotsport_event_structure.py`
- Test: `tests/unit/test_gotsport_event_structure.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PoolMember(registration_id: str, team_name: str, standings_position: int)`, `Pool(pool_id: str, label: str, members: tuple[PoolMember, ...])`, `parse_pools(html: str) -> tuple[Pool, ...]`, `standings_table_found(html: str) -> bool`.

**Background the implementer needs:** A GotSport division-schedule page renders one standings table per pool. Each sits inside `div.panel-collapse` whose sibling `div.panel-heading` holds the pool's name (`Bracket A`), and whose `id` is `collapse-<digits>` — a stable GotSport pool id. Verified against all 52 standings tables in `tests/fixtures/gotsport/`: every one has both. Team cells link `?team=<registration_id>`, the same id the fixture rows use, which is how pools join to fixtures without name matching.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the GotSport division-structure parser."""

from __future__ import annotations

from pathlib import Path

from src.tournaments.gotsport_event_structure import (
    parse_pools,
    standings_table_found,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gotsport"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_parse_pools_reads_two_labelled_brackets():
    pools = parse_pools(_html("event_42433__group_365847.html"))

    assert [pool.label for pool in pools] == ["Bracket A", "Bracket B"]
    assert [pool.pool_id for pool in pools] == ["501350", "501351"]
    assert [len(pool.members) for pool in pools] == [4, 4]


def test_parse_pools_numbers_members_from_one_in_table_order():
    pools = parse_pools(_html("event_42433__group_365847.html"))

    positions = [member.standings_position for member in pools[0].members]
    assert positions == [1, 2, 3, 4]
    assert pools[0].members[0].team_name == "Rush Soccer Global 2013B Rush Select Blue"
    assert pools[0].members[0].registration_id.isdigit()


def test_parse_pools_keeps_a_label_that_is_not_a_bracket_letter():
    pools = parse_pools(_html("event_49371__group_485301.html"))

    assert [pool.label for pool in pools] == ["U-12 GOLD"]


def test_parse_pools_returns_nothing_when_there_is_no_standings_table():
    assert parse_pools("<html><body><p>no tables here</p></body></html>") == ()


def test_standings_table_found_separates_an_empty_pool_from_unreadable_markup():
    assert standings_table_found(_html("event_42433__group_365847.html")) is True
    assert standings_table_found("<html><body><table></table></body></html>") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_gotsport_event_structure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tournaments.gotsport_event_structure'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_gotsport_event_structure.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Lint**

Run: `python -m ruff check src/tournaments/gotsport_event_structure.py`
Expected: no findings. If ruff rewrote the file, re-read it before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/tournaments/gotsport_event_structure.py tests/unit/test_gotsport_event_structure.py
git commit -m "Read a GotSport division's pools from its standings tables"
```

---

### Task 2: Fixture parsing

**Files:**
- Modify: `src/tournaments/gotsport_event_structure.py`
- Test: `tests/unit/test_gotsport_event_structure.py`

**Interfaces:**
- Consumes: `_squashed`, `_plain`, `_first_team_id`, `_TEAM_ID` from Task 1.
- Produces: `Fixture(match_number: str, bracket_label: str, kind: str, home_registration_id: str | None, away_registration_id: str | None, home_score: int | None, away_score: int | None, kickoff: str, location: str)`, `parse_fixtures(html: str) -> tuple[Fixture, ...]`, `fixture_table_found(html: str) -> bool`.

**Background the implementer needs:** Fixture tables carry the headings `Match #`, `Time`, `Home Team`, `Results`, `Away Team`, `Location`, `Division`. The Match # cell is a bare number for a pool game and a number plus a label for a knockout game — `56 Final`, `55 Third Place`, `53 Consolation A`, `Semi-Finals A`, `Play In Game`, `5th Place Game`. That label is the only trustworthy signal that a game is a knockout game; game-count arithmetic is not (see the spec's §2). A played event's Results cell reads `0 - 1`; an unplayed fixture has no score.

`kind` is set to `"bracket"` here when a label is present and `"unknown"` otherwise. Task 3 refines `"unknown"` into `"pool"` or `"cross_pool"` using the pool map — this function has no pools to consult.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_gotsport_event_structure.py`:

```python
from src.tournaments.gotsport_event_structure import (  # noqa: E402
    Fixture,
    fixture_table_found,
    parse_fixtures,
)


def test_parse_fixtures_reads_every_row_on_the_page():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))

    assert len(fixtures) == 16


def test_parse_fixtures_labels_the_knockout_games_verbatim():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))

    labelled = [f.bracket_label for f in fixtures if f.bracket_label]
    assert sorted(labelled) == ["Consolation A", "Consolation B", "Final", "Third Place"]
    assert all(f.kind == "bracket" for f in fixtures if f.bracket_label)


def test_parse_fixtures_leaves_a_pool_game_unlabelled_and_unclassified():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))

    plain = [f for f in fixtures if not f.bracket_label]
    assert len(plain) == 12
    assert all(f.kind == "unknown" for f in plain)
    assert all(f.match_number.isdigit() for f in plain)


def test_parse_fixtures_reads_both_team_ids_and_the_score():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))
    final = next(f for f in fixtures if f.bracket_label == "Final")

    assert final.home_registration_id is not None
    assert final.away_registration_id is not None
    assert final.home_score == 3
    assert final.away_score == 4
    assert final.location != ""


def test_parse_fixtures_returns_no_score_when_none_was_published():
    html = """
    <table>
      <tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>
          <th>Away Team</th><th>Location</th></tr>
      <tr><td>7</td><td>Feb 14, 2026 9:00AM</td>
          <td><a href="/x?team=111">Home FC</a></td><td></td>
          <td><a href="/x?team=222">Away FC</a></td><td>Field 2</td></tr>
    </table>
    """
    fixtures = parse_fixtures(html)

    assert fixtures == (
        Fixture(
            match_number="7",
            bracket_label="",
            kind="unknown",
            home_registration_id="111",
            away_registration_id="222",
            home_score=None,
            away_score=None,
            kickoff="Feb 14, 2026 9:00AM",
            location="Field 2",
        ),
    )


def test_fixture_table_found_separates_no_fixtures_from_unreadable_markup():
    assert fixture_table_found(_html("event_42433__group_365847.html")) is True
    assert fixture_table_found("<html><body><table></table></body></html>") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_gotsport_event_structure.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_fixtures'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/tournaments/gotsport_event_structure.py`, and add `"Fixture"`, `"fixture_table_found"`, `"parse_fixtures"` to `__all__`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_gotsport_event_structure.py -v`
Expected: PASS, 11 tests

Note: the real page's `Time` cell repeats the timezone (`Feb 13, 2026 5:00PM MST MST`). `kickoff` keeps whatever the page said — do not strip it.

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check src/tournaments/gotsport_event_structure.py
git add src/tournaments/gotsport_event_structure.py tests/unit/test_gotsport_event_structure.py
git commit -m "Read a GotSport division's fixtures and its knockout labels"
```

---

### Task 3: Assemble a division, and classify every fixture

**Files:**
- Modify: `src/tournaments/gotsport_event_structure.py`
- Test: `tests/unit/test_gotsport_event_structure.py`

**Interfaces:**
- Consumes: `Pool`, `Fixture`, `parse_pools`, `parse_fixtures`, `standings_table_found`, `fixture_table_found` from Tasks 1-2.
- Produces: `ScrapedDivision(group_id: str, division_label: str, pools: tuple[Pool, ...], fixtures: tuple[Fixture, ...], pools_readable: bool, fixtures_readable: bool, warnings: tuple[str, ...])`, `classify_fixtures(fixtures: Sequence[Fixture], pools: Sequence[Pool]) -> tuple[Fixture, ...]`, `parse_division_structure(*, group_id: str, division_label: str, html: str) -> ScrapedDivision`.

**Background the implementer needs:** Classification is pure lookup. A fixture already marked `bracket` stays `bracket`. Otherwise both registration ids are looked up in the pool map: same pool → `pool`, different pools → `cross_pool`, either id missing → `unknown`. No arithmetic, no round-robin expectations. The golden test below runs across every real page by glob, so a page added to the fixtures directory later cannot sit outside the guard.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_gotsport_event_structure.py`:

```python
import collections  # noqa: E402

import pytest  # noqa: E402

from src.tournaments.gotsport_event_structure import (  # noqa: E402
    classify_fixtures,
    parse_division_structure,
)

REAL_PAGES = sorted(
    path
    for path in FIXTURES.glob("event_*__group_*.html")
    if "synthetic" not in path.name
)


def _structure(name: str):
    return parse_division_structure(
        group_id=name.split("__group_")[1].removesuffix(".html"),
        division_label="Test Division",
        html=_html(name),
    )


def _kinds(structure) -> dict[str, int]:
    return collections.Counter(fixture.kind for fixture in structure.fixtures)


def test_every_real_page_yields_readable_pools_and_fixtures():
    assert len(REAL_PAGES) == 39
    for path in REAL_PAGES:
        structure = _structure(path.name)
        assert structure.pools_readable, path.name
        assert structure.fixtures_readable, path.name
        assert structure.pools, path.name


def test_no_real_page_leaves_a_fixture_unclassified():
    for path in REAL_PAGES:
        structure = _structure(path.name)
        assert _kinds(structure)["unknown"] == 0, path.name


def test_two_pools_of_four_with_a_full_knockout():
    structure = _structure("event_42433__group_365847.html")

    assert [len(pool.members) for pool in structure.pools] == [4, 4]
    assert _kinds(structure) == {"pool": 12, "bracket": 4}
    assert sorted(f.bracket_label for f in structure.fixtures if f.bracket_label) == [
        "Consolation A",
        "Consolation B",
        "Final",
        "Third Place",
    ]


def test_two_pools_that_only_ever_played_each_other():
    """Nine games, none inside a pool. Game-count inference calls this pool play."""
    structure = _structure("event_49371__group_485425.html")

    assert [len(pool.members) for pool in structure.pools] == [3, 3]
    assert _kinds(structure) == {"cross_pool": 9, "bracket": 1}


def test_a_pool_of_six_that_played_nine_games_not_fifteen():
    structure = _structure("event_44692__group_391315.html")

    assert [len(pool.members) for pool in structure.pools] == [6]
    assert _kinds(structure) == {"pool": 9, "bracket": 1}


def test_a_pool_of_four_with_no_knockout_at_all():
    structure = _structure("event_49371__group_485294.html")

    assert [len(pool.members) for pool in structure.pools] == [4]
    assert _kinds(structure) == {"pool": 6}


def test_pools_are_never_reconstructed_when_the_standings_table_is_unreadable():
    html = """
    <table>
      <tr><th>Match #</th><th>Home Team</th><th>Results</th><th>Away Team</th></tr>
      <tr><td>1</td><td><a href="?team=1">A</a></td><td>1 - 0</td>
          <td><a href="?team=2">B</a></td></tr>
    </table>
    """
    structure = parse_division_structure(group_id="9", division_label="U13 Boys", html=html)

    assert structure.pools == ()
    assert structure.pools_readable is False
    assert structure.fixtures_readable is True
    assert structure.fixtures[0].kind == "unknown"
    assert any("pools could not be read" in warning for warning in structure.warnings)


@pytest.mark.parametrize(
    "home,away,expected",
    [("1", "2", "pool"), ("1", "3", "cross_pool"), ("1", "99", "unknown"), (None, "2", "unknown")],
)
def test_classify_fixtures_is_pure_lookup(home, away, expected):
    pools = (
        Pool(pool_id="a", label="Bracket A", members=(
            PoolMember(registration_id="1", team_name="One", standings_position=1),
            PoolMember(registration_id="2", team_name="Two", standings_position=2),
        )),
        Pool(pool_id="b", label="Bracket B", members=(
            PoolMember(registration_id="3", team_name="Three", standings_position=1),
        )),
    )
    fixture = Fixture(
        match_number="1", bracket_label="", kind="unknown",
        home_registration_id=home, away_registration_id=away,
        home_score=None, away_score=None, kickoff="", location="",
    )

    assert classify_fixtures((fixture,), pools)[0].kind == expected


def test_classify_fixtures_never_reclassifies_a_labelled_knockout_game():
    pools = (
        Pool(pool_id="a", label="Bracket A", members=(
            PoolMember(registration_id="1", team_name="One", standings_position=1),
            PoolMember(registration_id="2", team_name="Two", standings_position=2),
        )),
    )
    fixture = Fixture(
        match_number="9", bracket_label="Final", kind="bracket",
        home_registration_id="1", away_registration_id="2",
        home_score=None, away_score=None, kickoff="", location="",
    )

    assert classify_fixtures((fixture,), pools)[0].kind == "bracket"
```

Add `Pool`, `PoolMember` to the imports at the top of the test file if they are not there already.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_gotsport_event_structure.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify_fixtures'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/tournaments/gotsport_event_structure.py`, adding `"ScrapedDivision"`, `"classify_fixtures"`, `"parse_division_structure"` to `__all__` and `from collections.abc import Sequence` to the imports:

```python
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


def classify_fixtures(
    fixtures: Sequence[Fixture], pools: Sequence[Pool]
) -> tuple[Fixture, ...]:
    """Tag each fixture ``pool`` / ``cross_pool`` / ``bracket`` / ``unknown``.

    Lookup only. A labelled game keeps ``bracket`` — the organizer named it, and
    no amount of pool membership overrides that. Everything else is decided by
    whether both sides appear in the same standings table, so a division that
    played nothing inside its own pools is described as it actually was rather
    than forced into a pool-play shape.

    A team listed in two pools resolves to the last one seen. That is a
    malformed page rather than a real format, and preferring either pool would
    be a guess.
    """
    pool_by_team: dict[str, int] = {}
    for index, pool in enumerate(pools):
        for member in pool.members:
            pool_by_team[member.registration_id] = index

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
    *, group_id: str, division_label: str, html: str
) -> ScrapedDivision:
    """The whole structure of one division, read from its schedule page."""
    pools = parse_pools(html)
    pools_readable = standings_table_found(html)
    fixtures_readable = fixture_table_found(html)
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

    return ScrapedDivision(
        group_id=group_id,
        division_label=division_label,
        pools=pools,
        fixtures=classify_fixtures(parse_fixtures(html), pools),
        pools_readable=pools_readable,
        fixtures_readable=fixtures_readable,
        warnings=tuple(warnings),
    )
```

Add `replace` to the dataclasses import: `from dataclasses import dataclass, replace`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_gotsport_event_structure.py -v`
Expected: PASS, 21 tests

- [ ] **Step 5: Mutation-check the classifier one branch at a time**

Not a hunk revert — each conjunct separately. Copy the module to a scratch file, apply each mutation, confirm a test fails, restore.

```bash
python -m pytest tests/unit/test_gotsport_event_structure.py -q
```

Mutations to apply one at a time, each of which MUST turn a test red:
1. `if home is None or away is None:` → `if home is None:` (a fixture whose away team is absent misclassifies)
2. `elif home == away:` → `elif True:` (cross-pool games read as pool games — the `event_49371__group_485425` test must catch this)
3. `if fixture.bracket_label:` → `if False:` (knockout games get reclassified)
4. In `_standings_column`, drop the `_STANDINGS_POINTS_HEADING` requirement (fixture tables start parsing as pools)

If any mutation leaves the suite green, the test is not testing what it claims — fix the test before continuing. Restore the file afterwards and confirm with `git diff --exit-code src/tournaments/gotsport_event_structure.py`.

Note: a restore that copies a file back can leave a stale `.pyc` newer than the restored source. After restoring, run `python -c "import pathlib,shutil; [shutil.rmtree(p) for p in pathlib.Path('src').rglob('__pycache__')]"` before re-running the suite.

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check src/tournaments/gotsport_event_structure.py
git add src/tournaments/gotsport_event_structure.py tests/unit/test_gotsport_event_structure.py
git commit -m "Assemble a division's structure and classify every fixture by pool lookup"
```

---

### Task 4: Return structure from the walker

**Files:**
- Modify: `src/tournaments/gotsport_event_roster.py:872-877` (`_Division`), `:922-973` (`_read_divisions`), `:858-868` (the `EventRoster` construction), `:159-169` (`EventRoster`)
- Test: `tests/unit/test_gotsport_event_roster.py`

**Interfaces:**
- Consumes: `parse_division_structure`, `ScrapedDivision` from Task 3.
- Produces: `EventRoster.divisions: tuple[ScrapedDivision, ...]` — populated for the divisions actually kept, in the same order as their teams.

**Background the implementer needs:** `_read_divisions` already holds each division's HTML in `group_html`; the parser call goes there, so no page is fetched twice and a walk costs exactly what it costs today. `_wanted_divisions` filters divisions after that, and only kept divisions contribute teams — so only kept divisions contribute structure, keeping `divisions` and `teams` describing the same set. `divisions` gets a default of `()` so every existing `EventRoster(...)` construction in the codebase and tests keeps working unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_gotsport_event_roster.py`:

```python
def test_scrape_event_roster_returns_each_kept_division_s_structure():
    landing = '<a href="/org_event/events/1/schedules?group=501350">U13 Boys Red</a>'
    division = _html_fixture("event_42433__group_365847.html")

    def fetch(url: str) -> str:
        if "schedules?group=" in url:
            return division
        if "/teams/" in url or "team=" in url:
            return "<html></html>"
        return landing

    roster = scrape_event_roster("1", fetch=fetch)

    assert len(roster.divisions) == 1
    structure = roster.divisions[0]
    assert structure.group_id == "501350"
    assert [len(pool.members) for pool in structure.pools] == [4, 4]
    assert sum(1 for f in structure.fixtures if f.kind == "bracket") == 4


def test_scrape_event_roster_reports_no_structure_for_a_division_it_skipped():
    landing = '<a href="/org_event/events/1/schedules?group=501350">any text</a>'
    division = _html_fixture("event_42433__group_365847.html")

    def fetch(url: str) -> str:
        if "schedules?group=" in url:
            return division
        return landing

    roster = scrape_event_roster("1", fetch=fetch, wanted_cohorts={"u10"})

    assert roster.divisions == ()
    assert roster.teams == ()
```

Add a helper beside `FIXTURES` if the file has none:

```python
def _html_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")
```

The cohort is read from the DIVISION page, never from the landing page's anchor text — `_read_divisions` calls `parse_division_label(group_html)`. That fixture's page states `U13 Boys Red`, so `resolve_cohort` returns `("u13", "Male")` and the landing anchor's wording is irrelevant to both tests. The second test restricts `wanted_cohorts` to `u10`, which makes `names_cohort_outside("U13 Boys Red", {"u10"})` true and `_wanted_divisions` drop the division. Verified against the real fixture before this plan was written.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_gotsport_event_roster.py -k structure -v`
Expected: FAIL — `AttributeError: 'EventRoster' object has no attribute 'divisions'`

- [ ] **Step 3: Write minimal implementation**

In `src/tournaments/gotsport_event_roster.py`:

Add the import:

```python
from src.tournaments.gotsport_event_structure import ScrapedDivision, parse_division_structure
```

Add the field to `EventRoster`, last so it defaults cleanly:

```python
    divisions: tuple[ScrapedDivision, ...] = ()
    """Per-division structure, for the divisions this walk kept. Additive: every
    counter and ``is_complete`` ignore it."""
```

Add the field to `_Division`:

```python
    structure: ScrapedDivision
```

In `_read_divisions`, build it from the HTML already in hand and pass it in:

```python
        divisions.append(
            _Division(
                group_id=group_id,
                label=label,
                age_group=age_group,
                gender=gender,
                teams=teams,
                structure=parse_division_structure(
                    group_id=group_id, division_label=label, html=group_html
                ),
            )
        )
```

In `scrape_event_roster`, after `_wanted_divisions` has filtered and before the return, collect the structure warnings and pass the structures through:

```python
    for division in divisions:
        warnings.extend(division.structure.warnings)
```

Place that loop immediately after the existing `if not division.age_group:` loop, then add to the `EventRoster(...)` construction:

```python
        divisions=tuple(division.structure for division in divisions),
```

- [ ] **Step 4: Run the walker's whole suite**

Run: `python -m pytest tests/unit/test_gotsport_event_roster.py -v`
Expected: PASS, including every pre-existing test. If an existing test constructs `_Division(...)` positionally it will need `structure=` added — search for `_Division(` before assuming.

- [ ] **Step 5: Prove the Seeding tab did not regress**

Run: `python -m pytest tests/unit/test_seeding_event_intake.py tests/unit/test_event_roster_intake.py tests/unit/test_roster_resolver.py -v`
Expected: PASS, unchanged.

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check src/tournaments/gotsport_event_roster.py
git add src/tournaments/gotsport_event_roster.py src/tournaments/gotsport_event_structure.py tests/unit/test_gotsport_event_roster.py
git commit -m "Return each walked division's structure from the event roster walk"
```

---

### Task 5: Persist the structure

**Files:**
- Create: `src/tournaments/storage/event_structure.py`
- Test: `tests/unit/test_event_structure_storage.py`

**Interfaces:**
- Consumes: `ScrapedDivision`, `Pool`, `PoolMember`, `Fixture` from Tasks 1-3.
- Produces: `EventStructure(event_id: str, walked_at: str, is_complete: bool, divisions: tuple[ScrapedDivision, ...], schema_version: int = 1)`, `write_event_structure(event_key: str, structure: EventStructure, *, base_dir: Path | str = "reports") -> None`, `read_event_structure(event_key: str, *, base_dir: Path | str = "reports") -> EventStructure`, `event_structure_path(event_key: str, *, base_dir: Path | str = "reports") -> Path`.

**Background the implementer needs:** Follow `src/tournaments/storage/frozen_medians.py` exactly — it is the closest sibling. Writers stamp `schema_version` through `stamp_schema_version` and write atomically through `_io.write_json`; readers use `read_versioned_json`, which raises `SchemaVersionError` on a payload from a future schema. The file is per-event, not per-scenario, so it belongs under `intake_dir(event_key)` beside `raw_scrape.jsonl`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for event-structure persistence."""

from __future__ import annotations

import json

import pytest

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)
from src.tournaments.storage.event_structure import (
    EventStructure,
    event_structure_path,
    read_event_structure,
    write_event_structure,
)
from src.tournaments.storage.schema_version import SchemaVersionError


def _structure() -> EventStructure:
    return EventStructure(
        event_id="51783",
        walked_at="2026-09-10T00:00:00+00:00",
        is_complete=True,
        divisions=(
            ScrapedDivision(
                group_id="501350",
                division_label="U13 Boys Red",
                pools=(
                    Pool(
                        pool_id="501350",
                        label="Bracket A",
                        members=(
                            PoolMember(registration_id="1", team_name="One", standings_position=1),
                        ),
                    ),
                ),
                fixtures=(
                    Fixture(
                        match_number="56",
                        bracket_label="Final",
                        kind="bracket",
                        home_registration_id="1",
                        away_registration_id="2",
                        home_score=3,
                        away_score=4,
                        kickoff="Feb 16, 2026 12:45PM MST MST",
                        location="West Field #16",
                    ),
                ),
                pools_readable=True,
                fixtures_readable=True,
                warnings=(),
            ),
        ),
    )


def test_write_then_read_round_trips_every_field(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)

    assert read_event_structure("gotsport__51783__2026", base_dir=tmp_path) == _structure()


def test_the_file_lands_beside_the_other_intake_artifacts(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)
    path = event_structure_path("gotsport__51783__2026", base_dir=tmp_path)

    assert path == tmp_path / "gotsport__51783__2026" / "intake" / "event_structure.json"
    assert path.exists()


def test_the_payload_is_stamped_with_a_schema_version(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)
    payload = json.loads(
        event_structure_path("gotsport__51783__2026", base_dir=tmp_path).read_text(encoding="utf-8")
    )

    assert payload["schema_version"] == 1


def test_a_future_schema_is_refused_rather_than_half_read(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)
    path = event_structure_path("gotsport__51783__2026", base_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaVersionError):
        read_event_structure("gotsport__51783__2026", base_dir=tmp_path)


def test_reading_an_absent_structure_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_event_structure("gotsport__51783__2026", base_dir=tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_event_structure_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tournaments.storage.event_structure'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The exact structure a played event was run under, as scraped.

Per-event and scenario-shared, so it lives in the intake tier beside
``raw_scrape.jsonl`` rather than under a scenario. It holds facts — pools with
their members, and every fixture with the label the organizer gave it — and
deliberately holds no format name: a replay consumes the fixture graph, and a
name would be a summary that can disagree with it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)
from src.tournaments.storage._io import read_versioned_json, write_json
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "EventStructure",
    "division_from_dict",
    "event_structure_path",
    "read_event_structure",
    "write_event_structure",
]

_FILENAME = "event_structure.json"


@dataclass(frozen=True)
class EventStructure:
    """Every division's structure from one walk of one event."""

    event_id: str
    walked_at: str
    is_complete: bool
    divisions: tuple[ScrapedDivision, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventStructure":
        return cls(
            event_id=str(payload["event_id"]),
            walked_at=str(payload["walked_at"]),
            is_complete=bool(payload["is_complete"]),
            divisions=tuple(division_from_dict(item) for item in payload.get("divisions") or ()),
            schema_version=int(payload.get("schema_version", 1)),
        )


def division_from_dict(payload: dict[str, Any]) -> ScrapedDivision:
    """Rebuild one division from its persisted form.

    Public because the crash-recovery reader in ``tournament_intake`` rebuilds
    the same shape out of ``last_walk.json``. Two rebuilders would drift, and
    the one that drifts loses a walk that was paid for.
    """
    return ScrapedDivision(
        group_id=str(payload["group_id"]),
        division_label=str(payload["division_label"]),
        pools=tuple(_pool(item) for item in payload.get("pools") or ()),
        fixtures=tuple(_fixture(item) for item in payload.get("fixtures") or ()),
        pools_readable=bool(payload["pools_readable"]),
        fixtures_readable=bool(payload["fixtures_readable"]),
        warnings=tuple(str(warning) for warning in payload.get("warnings") or ()),
    )


def _pool(payload: dict[str, Any]) -> Pool:
    return Pool(
        pool_id=str(payload.get("pool_id") or ""),
        label=str(payload.get("label") or ""),
        members=tuple(
            PoolMember(
                registration_id=str(member["registration_id"]),
                team_name=str(member["team_name"]),
                standings_position=int(member["standings_position"]),
            )
            for member in payload.get("members") or ()
        ),
    )


def _fixture(payload: dict[str, Any]) -> Fixture:
    return Fixture(
        match_number=str(payload.get("match_number") or ""),
        bracket_label=str(payload.get("bracket_label") or ""),
        kind=str(payload["kind"]),
        home_registration_id=_optional_str(payload.get("home_registration_id")),
        away_registration_id=_optional_str(payload.get("away_registration_id")),
        home_score=_optional_int(payload.get("home_score")),
        away_score=_optional_int(payload.get("away_score")),
        kickoff=str(payload.get("kickoff") or ""),
        location=str(payload.get("location") or ""),
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def event_structure_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / _FILENAME


def write_event_structure(
    event_key: str, structure: EventStructure, *, base_dir: Path | str = "reports"
) -> None:
    write_json(
        event_structure_path(event_key, base_dir=base_dir),
        stamp_schema_version(structure.to_dict()),
    )


def read_event_structure(
    event_key: str, *, base_dir: Path | str = "reports"
) -> EventStructure:
    return EventStructure.from_dict(
        read_versioned_json(event_structure_path(event_key, base_dir=base_dir))
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_event_structure_storage.py -v`
Expected: PASS, 6 tests

If `read_versioned_json` raises something other than `FileNotFoundError` for an absent file, adjust the reader to `Path.exists()`-check and raise `FileNotFoundError(str(path))` explicitly rather than weaken the test.

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check src/tournaments/storage/event_structure.py
git add src/tournaments/storage/event_structure.py tests/unit/test_event_structure_storage.py
git commit -m "Persist a walked event's exact structure beside its intake artifacts"
```

---

### Task 6: Carry structure through the crash-recovery file

**Files:**
- Modify: `tournament_intake.py:3769-3813` (`_write_event_roster_recovery`), `:3830-3889` (`_recovered_walk`), `:3891-3897` (`_recovered_team`)
- Test: `tests/unit/test_seeding_event_intake.py`

**Interfaces:**
- Consumes: `ScrapedDivision` and the storage rebuilders from Tasks 3 and 5.
- Produces: `_recovered_division(payload: Any) -> ScrapedDivision` in `tournament_intake.py`; `last_walk.json` gains a `divisions` key.

**Background the implementer needs:** `_write_event_roster_recovery` exists so a walk that was *paid for* survives a stray click — Streamlit's default `fastReruns` kills the running script on any widget interaction. If `divisions` is not persisted there, recovering a walk silently loses its structure and the event has to be bought again. `_recovered_walk` already refuses every field it cannot rebuild faithfully rather than coercing it; the new field follows the same rule — a malformed division refuses the whole payload, because a half-recovered walk that looks complete stops the operator looking for the one that cost money.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_seeding_event_intake.py`:

```python
def test_recovery_file_carries_the_walked_structure(tmp_path, monkeypatch):
    import tournament_intake

    monkeypatch.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    division = ScrapedDivision(
        group_id="501350",
        division_label="U13 Boys Red",
        pools=(Pool(pool_id="501350", label="Bracket A", members=(
            PoolMember(registration_id="1", team_name="One", standings_position=1),
        )),),
        fixtures=(Fixture(
            match_number="56", bracket_label="Final", kind="bracket",
            home_registration_id="1", away_registration_id="2",
            home_score=3, away_score=4, kickoff="", location="",
        ),),
        pools_readable=True,
        fixtures_readable=True,
        warnings=(),
    )
    roster = EventRoster(
        event_id="51783",
        teams=(),
        warnings=(),
        divisions_found=1,
        divisions_walked=1,
        divisions=(division,),
    )

    tournament_intake._write_event_roster_recovery(roster)
    recovered, _limit = tournament_intake._recovered_walk("51783")

    assert recovered.divisions == (division,)


def test_a_malformed_division_refuses_the_whole_recovery(tmp_path, monkeypatch):
    import json

    import tournament_intake

    monkeypatch.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    roster = EventRoster(
        event_id="51783", teams=(), warnings=(),
        divisions_found=0, divisions_walked=0,
    )
    tournament_intake._write_event_roster_recovery(roster)
    path = tournament_intake._event_recovery_path("51783")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["divisions"] = [{"group_id": "1"}]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert tournament_intake._recovered_walk("51783") is None
```

Import `Fixture`, `Pool`, `PoolMember`, `ScrapedDivision` at the top of the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_seeding_event_intake.py -k recovery -v`
Expected: FAIL — the recovered roster's `divisions` is `()`.

- [ ] **Step 3: Write minimal implementation**

In `tournament_intake.py`, import the rebuilder rather than writing a second one:

```python
from src.tournaments.gotsport_event_structure import ScrapedDivision
from src.tournaments.storage.event_structure import division_from_dict
```

Do not write a second rebuilder here — two of them drift, and the one that drifts loses a paid walk.

In `_write_event_roster_recovery`, add to the payload dict, after `"warnings"`:

```python
                "divisions": [asdict(division) for division in roster.divisions],
```

Add the helper beside `_recovered_team`:

```python
def _recovered_division(payload: Any) -> ScrapedDivision:
    """One division's structure from the recovery file.

    Raises rather than coerces. ``_recovered_walk`` catches, and refusing the
    whole payload is right: a walk that comes back missing its structure looks
    finished, which stops the operator recovering the one that cost money.
    """
    if not isinstance(payload, dict):
        raise TypeError("division payload is not a mapping")
    return division_from_dict(payload)
```

In `_recovered_walk`, inside the existing `try:` that builds `EventRoster`, add the field:

```python
            divisions=tuple(_recovered_division(item) for item in payload.get("divisions") or ()),
```

and widen the existing guard above it:

```python
    if not isinstance(payload.get("divisions", []), list):
        return None
```

The existing `except (TypeError, ValueError)` already catches what `_recovered_division` raises; add `KeyError` to that tuple, since the storage rebuilder indexes required keys directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_seeding_event_intake.py -v`
Expected: PASS, including every pre-existing test.

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check tournament_intake.py src/tournaments/storage/event_structure.py
git add tournament_intake.py src/tournaments/storage/event_structure.py tests/unit/test_seeding_event_intake.py
git commit -m "Keep a walked event's structure in the crash-recovery file"
```

---

### Task 7: Let both views drive a paid walk

**Files:**
- Modify: `tournament_intake.py:3662-3763` (`_park_event_roster`, `_scrape_still_running`), `:4323-4390` (`_render_recovered_walk`, `_park_seeding_result`, `_parked_roster_size`)
- Test: `tests/unit/test_seeding_event_intake.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_WalkKeys(prefix: str)` with properties `result`, `result_event_id`, `overrides`, `sheet_html`, `probe`, `resolution_failed`, `lock_key`, `loaded_slug`, `structure`; module constants `_SEEDING_KEYS = _WalkKeys("_seeding")` and `_BACKTEST_KEYS = _WalkKeys("_backtest")`. Every function listed above takes `keys: _WalkKeys = _SEEDING_KEYS` as a keyword-only argument.

**Background the implementer needs:** The walk machinery carries correctness that was learned expensively — a cross-tab file lock, a recovery file written before anything interruptible, a probe that must price an event before the full-walk button unlocks, and defences against Streamlit killing the script mid-walk. The Backtest view needs all of it. Copying it would mean two copies of those defences drifting apart, so the session-state key names become a parameter and the logic stays single.

`_scrape_still_running` is the delicate one: `_scrape_in_progress` is shared with the Backtest surface's existing text inputs, which feed it straight to `st.text_input(disabled=...)` — a bool protobuf field that raises `TypeError` on a string or `None`. It must keep writing a bool. Only the *lock key* entry becomes per-view.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_seeding_event_intake.py`:

```python
def test_walk_keys_never_collide_between_the_two_views():
    from tournament_intake import _BACKTEST_KEYS, _SEEDING_KEYS, _WalkKeys

    fields = ("result", "result_event_id", "overrides", "sheet_html", "probe",
              "resolution_failed", "lock_key", "loaded_slug", "structure")
    seeding = {getattr(_SEEDING_KEYS, field) for field in fields}
    backtest = {getattr(_BACKTEST_KEYS, field) for field in fields}

    assert len(seeding) == len(fields)
    assert seeding.isdisjoint(backtest)
    assert isinstance(_WalkKeys("_x").result, str)


def test_the_seeding_view_keeps_the_session_key_names_it_already_used():
    """These names are load-bearing: `_init_session_state` seeds them and the
    Seeding tab reads them directly."""
    from tournament_intake import _SEEDING_KEYS

    assert _SEEDING_KEYS.result == "_seeding_result"
    assert _SEEDING_KEYS.result_event_id == "_seeding_result_event_id"
    assert _SEEDING_KEYS.overrides == "_seeding_overrides"
    assert _SEEDING_KEYS.sheet_html == "_seeding_sheet_html"
    assert _SEEDING_KEYS.probe == "_seeding_event_probe"
    assert _SEEDING_KEYS.resolution_failed == "_seeding_resolution_failed"
    assert _SEEDING_KEYS.lock_key == "_seeding_scrape_lock_key"
    assert _SEEDING_KEYS.loaded_slug == "_seeding_loaded_slug"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_seeding_event_intake.py -k walk_keys -v`
Expected: FAIL — `ImportError: cannot import name '_WalkKeys'`

- [ ] **Step 3: Write minimal implementation**

Add near `_VIEWS` in `tournament_intake.py`:

```python
@dataclass(frozen=True)
class _WalkKeys:
    """Session-state key names for one view's paid event walk.

    Both views run the same walk with the same protections — a cross-tab lock, a
    recovery file written before anything interruptible, a probe that must price
    the event before the full-walk button unlocks. Only the session entries
    differ, so they are the parameter and the logic stays single. Two copies of
    those protections would drift, and the one that drifts costs a paid walk.
    """

    prefix: str

    @property
    def result(self) -> str:
        return f"{self.prefix}_result"

    @property
    def result_event_id(self) -> str:
        return f"{self.prefix}_result_event_id"

    @property
    def overrides(self) -> str:
        return f"{self.prefix}_overrides"

    @property
    def sheet_html(self) -> str:
        return f"{self.prefix}_sheet_html"

    @property
    def probe(self) -> str:
        return f"{self.prefix}_event_probe"

    @property
    def resolution_failed(self) -> str:
        return f"{self.prefix}_resolution_failed"

    @property
    def lock_key(self) -> str:
        return f"{self.prefix}_scrape_lock_key"

    @property
    def loaded_slug(self) -> str:
        return f"{self.prefix}_loaded_slug"

    @property
    def structure(self) -> str:
        """The walked divisions' structure. New in this change; the Seeding view
        parks it too and simply does not read it."""
        return f"{self.prefix}_structure"


_SEEDING_KEYS = _WalkKeys("_seeding")
_BACKTEST_KEYS = _WalkKeys("_backtest")
```

Then convert every literal session-state access in these functions to go through `keys`, adding `*, keys: _WalkKeys = _SEEDING_KEYS` to each signature: `_run_event_roster_scrape`, `_park_event_roster`, `_park_seeding_result`, `_parked_roster_size`, `_seeding_event_probe_for`, `_render_recovered_walk`, `_render_seeding_event_scrape`, `_run_seeding_name_lookup`, `_render_seeding_override`.

Two rules while converting:

1. `st.session_state._seeding_result` becomes `st.session_state[keys.result]` — attribute access does not accept a computed name.
2. In `_park_event_roster`, park the structure alongside the probe counters, before the roster is parked:

```python
    st.session_state[keys.structure] = roster.divisions
```

   It goes with the counters rather than after the roster because both describe the same walk, and a stop landing between them must not leave one view's structure sitting against another walk's teams.

3. `_render_seeding_override` is on that list for a reason that is easy to miss. It writes the operator's decision into a hardcoded `st.session_state._seeding_overrides` and then calls `_autosave_seeding_run()`. Called from the Backtest view unthreaded, every "Use this team" click would land in the *Seeding* view's overrides — invisible to the Backtest counters and corrupting the other view's state. Thread `keys`, write to `st.session_state[keys.overrides]`, and guard the autosave, which saves a *seeding* run and means nothing here:

```python
        if keys is _SEEDING_KEYS:
            _autosave_seeding_run()
```

   Its widget keys (`_seed_fix_{index}`, `_seed_use_{index}`) must become prefix-derived too, or the same team's box collides across the two views.

4. `_scrape_still_running` reads `keys.lock_key` but keeps writing the shared bool `_scrape_in_progress` unchanged. Do not make that entry per-view; the Backtest surface's `st.text_input(disabled=...)` reads it and raises `TypeError` on a non-bool.

Widget keys (`_seeding_event_probe_run`, `_seeding_event_full_run`, `_seeding_event_reload_walk`, `_seeding_retry_lookup`, `seeding_event_url`) must also become prefix-derived, or the two views' buttons collide in Streamlit's widget registry. Derive them as `f"{keys.prefix}_event_probe_run"` and so on, and note that this renames the seeding widgets from `_seeding_event_probe_run` to the identical string — verify by test above that the prefix is `_seeding`, so the names do not actually change.

- [ ] **Step 4: Run the full Streamlit-facing suite**

Run: `python -m pytest tests/unit/test_seeding_event_intake.py tests/unit/test_tournament_intake_helpers.py tests/unit/test_seeding_csv_injection.py -v`
Expected: PASS, unchanged. Any failure here is a real regression in the Seeding tab — fix it rather than adjusting the test.

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check tournament_intake.py
git add tournament_intake.py tests/unit/test_seeding_event_intake.py
git commit -m "Let either view drive a paid event walk without duplicating its protections"
```

---

### Task 8: The Backtest event intake surface

**Files:**
- Create: `src/tournaments/backtest_event_intake.py`
- Modify: `tournament_intake.py` (`_render_backtest_tab`, around `:4569`)
- Test: `tests/unit/test_backtest_event_intake.py`

**Interfaces:**
- Consumes: `EventStructure`, `write_event_structure` (Task 5); `_BACKTEST_KEYS`, `_run_event_roster_scrape`, `_render_seeding_event_scrape`, `_render_seeding_override` (Task 7); `resolve_master_ids`, `to_seeding_rows`, `resolve_unlinked`, `needs_name_lookup`.
- Produces: `summarize_structure(divisions: Sequence[ScrapedDivision]) -> list[dict[str, Any]]` and `render_backtest_event_intake(supabase_client: Any) -> None`.

**Background the implementer needs:** The display logic is separated from Streamlit so it can be tested without a running app — `summarize_structure` is pure and takes the divisions, and the render function is thin. This mirrors how `src/tournaments/reports/ui.py` and `division_render.py` already sit outside the 4,635-line app file.

Matching is the Seeding tab's path, called unchanged: `resolve_master_ids` maps published GotSport ids to `team_id_master`, `to_seeding_rows` converts the walk, `needs_name_lookup` finds what is still unlinked, `resolve_unlinked` runs the free name pass. Nothing in that path writes to the database (Task 9 proves it).

Provider-authored text — division labels, pool labels, team names — must never reach `st.markdown` unescaped: `tournament_intake._as_plain_text` exists for exactly this, because Streamlit renders every message as Markdown and an organizer's label is free to carry a working link or an image that fetches on sight.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the Backtest event-intake surface."""

from __future__ import annotations

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)
from src.tournaments.backtest_event_intake import summarize_structure


def _fixture(kind: str, label: str = "") -> Fixture:
    return Fixture(
        match_number="1", bracket_label=label, kind=kind,
        home_registration_id="1", away_registration_id="2",
        home_score=None, away_score=None, kickoff="", location="",
    )


def _division(**overrides) -> ScrapedDivision:
    base = dict(
        group_id="501350",
        division_label="U13 Boys Red",
        pools=(
            Pool(pool_id="1", label="Bracket A", members=(
                PoolMember(registration_id="1", team_name="One", standings_position=1),
            )),
            Pool(pool_id="2", label="Bracket B", members=(
                PoolMember(registration_id="2", team_name="Two", standings_position=1),
            )),
        ),
        fixtures=(_fixture("pool"), _fixture("cross_pool"), _fixture("bracket", "Final")),
        pools_readable=True,
        fixtures_readable=True,
        warnings=(),
    )
    base.update(overrides)
    return ScrapedDivision(**base)


def test_summarize_counts_pools_and_every_kind_of_game():
    row = summarize_structure([_division()])[0]

    assert row["division"] == "U13 Boys Red"
    assert row["pools"] == "Bracket A (1), Bracket B (1)"
    assert row["pool_games"] == 1
    assert row["cross_pool_games"] == 1
    assert row["knockout_games"] == 1
    assert row["knockout"] == "Final"
    assert row["readable"] is True


def test_summarize_reports_an_unreadable_division_as_unreadable_not_absent():
    row = summarize_structure([_division(pools=(), pools_readable=False)])[0]

    assert row["readable"] is False
    assert row["pools"] == "could not be read"
    assert row["note"] != ""


def test_summarize_never_drops_a_division():
    rows = summarize_structure([_division(), _division(pools_readable=False, pools=())])

    assert len(rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_backtest_event_intake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tournaments.backtest_event_intake'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The Backtest tab's event intake: walk a played event, show what it really was.

Kept out of ``tournament_intake.py`` so the app file does not grow another few
hundred lines, following ``division_render`` and ``reports.ui``. Everything that
decides what the operator sees is pure and lives in ``summarize_structure``; the
render function only draws it.

Reads the PitchRank database to match teams and writes nothing to it. That is a
requirement of this surface, not an accident of the current implementation —
``tests/unit/test_backtest_event_intake.py`` fails if a write appears.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.tournaments.gotsport_event_structure import (
    KIND_BRACKET,
    KIND_CROSS_POOL,
    KIND_POOL,
    ScrapedDivision,
)

__all__ = ["summarize_structure"]


def summarize_structure(divisions: Sequence[ScrapedDivision]) -> list[dict[str, Any]]:
    """One display row per division. Never drops one, never invents one.

    A division whose pools could not be read says so. It is not omitted, and its
    pools are not reconstructed from its fixtures — a division exists whose two
    pools only ever played each other, so the fixture list is not evidence of
    who was grouped with whom.
    """
    rows: list[dict[str, Any]] = []
    for division in divisions:
        kinds = [fixture.kind for fixture in division.fixtures]
        labels = [fixture.bracket_label for fixture in division.fixtures if fixture.bracket_label]
        if division.pools_readable:
            pools = ", ".join(
                f"{pool.label or 'unnamed'} ({len(pool.members)})" for pool in division.pools
            ) or "none published yet"
        else:
            pools = "could not be read"
        rows.append(
            {
                "division": division.division_label or f"group {division.group_id}",
                "group_id": division.group_id,
                "pools": pools,
                "pool_games": kinds.count(KIND_POOL),
                "cross_pool_games": kinds.count(KIND_CROSS_POOL),
                "knockout_games": kinds.count(KIND_BRACKET),
                "knockout": ", ".join(labels),
                "readable": division.pools_readable and division.fixtures_readable,
                "note": "; ".join(division.warnings),
            }
        )
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_backtest_event_intake.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Wire the surface into the Backtest tab**

Add to `src/tournaments/backtest_event_intake.py`, and add `"render_backtest_event_intake"` to `__all__`:

```python
def render_backtest_event_intake(supabase_client: Any) -> None:
    """Walk a played event and show the structure it was actually run under.

    Imports from ``tournament_intake`` inside the function: the app module
    imports this one, so a module-scope import would be circular.
    """
    import pandas as pd
    import streamlit as st

    from tournament_intake import (
        _BACKTEST_KEYS,
        _as_plain_text,
        _render_seeding_event_scrape,
        _render_seeding_override,
        _SEEDING_NEEDS_DECISION,
    )
    from src.tournaments.storage.event_key import event_key
    from src.tournaments.storage.event_structure import EventStructure, write_event_structure
    from src.tournaments.storage._io import utc_now_iso

    st.markdown("### Scrape a played event")
    st.caption(
        "Reads every division's pools and games, including the semis, final and "
        "consolation games, exactly as the event published them. Every page is paid "
        "for, so check a couple of divisions first."
    )
    _render_seeding_event_scrape(supabase_client, keys=_BACKTEST_KEYS)

    result = st.session_state.get(_BACKTEST_KEYS.result)
    if not result:
        return
    parsed, resolved = result

    divisions = st.session_state.get(_BACKTEST_KEYS.structure) or ()
    if divisions:
        rows = summarize_structure(divisions)
        st.markdown("#### Structure this event was run under")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        unreadable = [row for row in rows if not row["readable"]]
        if unreadable:
            st.warning(
                f"{len(unreadable)} division(s) could not be read in full. They are listed "
                "above rather than dropped, and their pools are not guessed from the games."
            )
            for row in unreadable:
                st.caption(_as_plain_text(f"{row['division']}: {row['note']}"))

    overrides = st.session_state[_BACKTEST_KEYS.overrides]
    by_index = {item.source_index: item for item in resolved}
    outstanding = [
        row
        for row in parsed.rows
        if by_index[row.source_index].status in _SEEDING_NEEDS_DECISION
        and row.source_index not in overrides
    ]

    st.markdown("#### Teams matched to your database")
    columns = st.columns(4)
    columns[0].metric("Teams", len(parsed.rows))
    columns[1].metric("Matched", len(parsed.rows) - len(outstanding))
    columns[2].metric("You fixed", len(overrides))
    columns[3].metric("Still open", len(outstanding))

    for row in outstanding:
        _render_seeding_override(row, by_index[row.source_index], supabase_client)

    event_id = st.session_state.get(_BACKTEST_KEYS.result_event_id)
    probe = st.session_state.get(_BACKTEST_KEYS.probe) or {}
    if not event_id or not divisions:
        return
    if st.button("Save this event's structure", key="_backtest_save_structure"):
        write_event_structure(
            event_key("gotsport", event_id, None),
            EventStructure(
                event_id=event_id,
                walked_at=utc_now_iso(),
                is_complete=bool(probe.get("complete")),
                divisions=tuple(divisions),
            ),
        )
        st.success("Saved.")
```

In `tournament_intake._render_backtest_tab`, call it immediately after `_render_intake_section(supabase_client)`:

```python
    render_backtest_event_intake(supabase_client)
```

Import it at the top of `tournament_intake.py`:

```python
from src.tournaments.backtest_event_intake import render_backtest_event_intake
```

Leave `_render_intake_section` and everything below it untouched — the triage list, the division editor and Run backtest keep reading the old intake's `raw_scrape.jsonl` for now.

Two rules while writing this:

1. Every division label, pool label and team name that reaches `st.markdown` or `st.caption` goes through `_as_plain_text` first. Streamlit renders every message as Markdown, and an organizer's label is free to carry a working link or an image that fetches on sight. Values inside `st.dataframe` do not need it — the dataframe does not render Markdown.
2. `_SEEDING_NEEDS_DECISION` is a module constant in `tournament_intake.py`; import it rather than restating `("review", "unresolved")`, so the two surfaces cannot disagree about what still needs a decision.

- [ ] **Step 6: Verify by hand**

```bash
python -m streamlit run tournament_intake.py
```

Switch to the Backtest view. Confirm: the new section renders, the full-walk button is disabled before a probe, and the Seeding view still works exactly as before (paste a roster, resolve, save). Stop the server when done — it holds its port after the process is told to stop, so kill it by PID if a later run reports the port busy.

- [ ] **Step 7: Lint and commit**

```bash
python -m ruff check src/tournaments/backtest_event_intake.py tournament_intake.py
git add src/tournaments/backtest_event_intake.py tournament_intake.py tests/unit/test_backtest_event_intake.py
git commit -m "Add the Backtest tab's played-event intake and structure summary"
```

---

### Task 9: Prove the flow writes nothing to the database

**Files:**
- Test: `tests/unit/test_backtest_event_intake.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8.
- Produces: nothing importable — this task's deliverable is the guard.

**Background the implementer needs:** This is the spec's one hard constraint, and it is not self-enforcing: the Backtest tab's *existing* scrape writes to `team_alias_map` and `team_match_review_queue` through `src/tournaments/alias_writer.py` on every run. The guard has two halves — a double that fails on any write, and a source check that the modules on this path never import a writer.

The double must record at `.execute()`, not at builder construction. `supabase.table(...).select(...)` and `supabase.rpc(...)` build a request that does nothing until `.execute()`, so a fake that logs inside `rpc()` reports a write for a caller that never executed one, and — worse — a fake that never gets to `execute()` reports nothing for a caller that did.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_backtest_event_intake.py`:

```python
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_WRITE_METHODS = ("insert", "upsert", "update", "delete", "rpc")
_FORBIDDEN_IMPORTS = ("alias_writer", "seeding_enqueue")

# Derived from the modules this flow actually runs, not hand-picked: every
# module the Backtest intake path imports from src/tournaments must be here.
_READ_ONLY_MODULES = (
    "src/tournaments/backtest_event_intake.py",
    "src/tournaments/gotsport_event_structure.py",
    "src/tournaments/gotsport_event_roster.py",
    "src/tournaments/event_roster_intake.py",
    "src/tournaments/roster_resolver.py",
    "src/tournaments/storage/event_structure.py",
)


class _RefusesWrites:
    """A Supabase double that raises when a write is executed.

    Records at ``execute()`` because that is where a PostgREST request actually
    happens; a builder that is constructed and dropped has written nothing.
    """

    def __init__(self):
        self.executed: list[str] = []

    def table(self, _name):
        return _Builder(self, "select")

    def rpc(self, name, _params=None):
        return _Builder(self, f"rpc:{name}")


class _Builder:
    def __init__(self, client, operation):
        self._client = client
        self._operation = operation

    def __getattr__(self, name):
        if name in _WRITE_METHODS:
            self._operation = name
        return lambda *args, **kwargs: self

    def execute(self):
        self._client.executed.append(self._operation)
        if self._operation.startswith("rpc:") or self._operation in _WRITE_METHODS:
            raise AssertionError(f"this flow must not write: {self._operation}")
        return type("Result", (), {"data": []})()


@pytest.mark.parametrize("relative", _READ_ONLY_MODULES)
def test_no_module_on_this_path_imports_a_database_writer(relative):
    source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    for forbidden in _FORBIDDEN_IMPORTS:
        assert not any(forbidden in name for name in imported), (
            f"{relative} imports {forbidden}, which writes to the database"
        )


@pytest.mark.parametrize("relative", _READ_ONLY_MODULES)
def test_no_module_on_this_path_calls_a_write_method(relative):
    source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert called.isdisjoint(_WRITE_METHODS), (
        f"{relative} calls {sorted(called & set(_WRITE_METHODS))}"
    )


def test_the_double_itself_fails_on_a_write():
    """Without this the two tests above could pass against a permissive double."""
    client = _RefusesWrites()

    with pytest.raises(AssertionError):
        client.table("teams").insert({"a": 1}).execute()
    with pytest.raises(AssertionError):
        client.rpc("enqueue_scrape_request", {}).execute()
    assert client.table("teams").select("*").execute().data == []


def test_matching_a_walked_roster_executes_no_write():
    from src.tournaments.event_roster_intake import resolve_master_ids
    from src.tournaments.gotsport_event_roster import EventRosterTeam

    client = _RefusesWrites()
    teams = (
        EventRosterTeam(
            source_index=0, group_id="1", division_label="U13 Boys Red",
            age_group="u13", gender="Male", team_name="One",
            registration_id="1", provider_team_id="521426",
        ),
    )

    resolve_master_ids(
        teams,
        enabled=True,
        client_factory=lambda *_: client,
        resolver_factory=lambda _client: type("R", (), {"resolve": staticmethod(lambda x: x)})(),
        lookup_factory=lambda _client, _resolver: (lambda ids: {}),
    )

    assert all(not op.startswith("rpc:") and op not in _WRITE_METHODS for op in client.executed)
```

Note on `test_no_module_on_this_path_calls_a_write_method`: `roster_resolver.py` calls `.update(` on Python dicts in places. If the AST check trips on a dict method rather than a PostgREST builder, narrow the check to calls whose receiver chain starts at a name containing `supabase` or `client` — do **not** delete the assertion or add the file to an exclusion list.

- [ ] **Step 2: Run test to verify it fails or passes for the right reason**

Run: `python -m pytest tests/unit/test_backtest_event_intake.py -v`
Expected: the import and double tests PASS; if a write-method test fails, that is a real finding — either narrow the receiver check as noted, or remove the write from the flow.

- [ ] **Step 3: Mutation-check the guard**

Each of these MUST turn a test red. Apply one at a time, then revert:

1. Add `from src.tournaments.alias_writer import write_alias  # noqa: F401` to `src/tournaments/backtest_event_intake.py` → the import test fails.
2. Add `from src.tournaments.seeding_enqueue import enqueue_resolved_teams  # noqa: F401` to the same file → the import test fails.
3. Make `_Builder.execute` return without raising → `test_the_double_itself_fails_on_a_write` fails.

- [ ] **Step 4: Run the full gate**

```bash
python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py
python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py
```

Expected: both clean. These are the two required CI checks this change can break.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_backtest_event_intake.py
git commit -m "Guard the backtest intake against writing to the team database"
```

---

## Acceptance: walk event 51783

Not a code task — the owner runs this, and it spends money (roughly one to two dollars for a mid-sized event; a page that has to be retried bills up to three times).

- [ ] Start the app, open the Backtest view, paste `https://system.gotsport.com/org_event/events/51783`.
- [ ] Probe two divisions. Confirm the price caption appears and the full-walk button unlocks only after the probe read a division.
- [ ] Walk the whole event. Confirm every division appears with its pools and their sizes, that knockout games show the labels the pages gave them, and that any unreadable division is named as unreadable rather than missing.
- [ ] Confirm the fixture counts per division add up to that division's total.
- [ ] Confirm the match counts appear and every unmatched team is listed and fixable by pasting a link.
- [ ] Save the structure and confirm `reports/gotsport__51783__*/intake/event_structure.json` reproduces what the screen showed.
- [ ] Confirm no rows were written: check `team_alias_map`, `team_match_review_queue` and `scrape_requests` for rows created during the run.
- [ ] Open the Seeding view and resolve a pasted roster, confirming it still behaves exactly as before.
