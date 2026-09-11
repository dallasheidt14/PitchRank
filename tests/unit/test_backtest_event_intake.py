"""Tests for the Backtest event-intake surface."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.tournaments.backtest_event_intake import summarize_structure
from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


def test_summarize_surfaces_unclassified_games():
    """classify_fixtures marks a game 'unknown' when a side is missing from
    every pool's standings table. A fully readable division can still have
    one, and a count that only ever adds pool + cross_pool + knockout would
    under-report how many games were played without ever saying so."""
    row = summarize_structure([_division(fixtures=(_fixture("pool"), _fixture("unknown")))])[0]

    assert row["unclassified_games"] == 1
    assert row["readable"] is True, "an unclassified game is not the same failure as an unreadable page"


# --- Task 9: prove the flow writes nothing to the database ---------------------
#
# The owner's hard requirement for this feature is that it reads the team
# database and writes nothing back to it. The *existing* Backtest scrape
# violates that today by routing through ``src/tournaments/alias_writer.py``,
# which inserts rows into ``team_alias_map`` and ``team_match_review_queue`` on
# every run. Everything below is the guard that keeps the new flow honest.

_WRITE_METHODS = ("insert", "upsert", "update", "delete", "rpc")
_FORBIDDEN_IMPORTS = ("alias_writer", "seeding_enqueue")

# Two groups, not one hand-picked list. The first six entries below are every
# module reachable from ``backtest_event_intake.py``'s own import statements
# while staying inside ``src/tournaments`` — ``test_read_only_modules_covers_
# every_module_backtest_intake_itself_imports`` below re-derives that set and
# fails if this tuple ever falls behind it.
#
# ``gotsport_event_roster.py``, ``event_roster_intake.py`` and
# ``roster_resolver.py`` are reached a different way: ``render_backtest_event_
# intake`` imports ``_render_seeding_event_scrape``, ``_render_seeding_override``,
# ``_render_seeding_progress_metrics`` and ``_render_seeding_warnings`` from
# ``tournament_intake.py``, and those functions (and what they call —
# ``_run_event_roster_scrape`` / ``_park_event_roster`` / ``_run_seeding_name_
# lookup`` / ``_render_seeding_override``) are what actually reach these three.
# ``tournament_intake.py`` is a multi-feature Streamlit hub outside
# ``src/tournaments`` that also imports genuinely-writing modules
# (``seeding_enqueue``, for the Seeding tab's own enqueue button) for tabs this
# flow never renders, so walking its full import list automatically would flag
# those too and make the derived set useless. This leg was instead verified by
# hand, tracing every function the Backtest render path actually calls (Task 9
# report, 2026-09-10) — confirmed none of the three imports a writer or calls a
# write method, and none of them is reached from anywhere except that traced
# path.
_READ_ONLY_MODULES = (
    "src/tournaments/backtest_event_intake.py",
    "src/tournaments/gotsport_event_structure.py",
    "src/tournaments/storage/_io.py",
    "src/tournaments/storage/event_key.py",
    "src/tournaments/storage/event_structure.py",
    "src/tournaments/storage/schema_version.py",
    "src/tournaments/gotsport_event_roster.py",
    "src/tournaments/event_roster_intake.py",
    "src/tournaments/roster_resolver.py",
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


# roster_resolver.py was flagged as a possible false-positive risk for this
# scan (a dict .update() call would trip it). Verified 2026-09-10 by AST-parsing
# every module in _READ_ONLY_MODULES: none of them calls .insert/.upsert/.update/
# .delete/.rpc on anything, dict or otherwise, so the bare scan below is left as
# specified rather than narrowed to a supabase/client receiver. If a future
# change trips this test on a genuine dict.update(), narrow the check then —
# do not delete the assertion or exclude the file.
@pytest.mark.parametrize("relative", _READ_ONLY_MODULES)
def test_no_module_on_this_path_calls_a_write_method(relative):
    source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert called.isdisjoint(_WRITE_METHODS), f"{relative} calls {sorted(called & set(_WRITE_METHODS))}"


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
            source_index=0,
            group_id="1",
            division_label="U13 Boys Red",
            age_group="u13",
            gender="Male",
            team_name="One",
            registration_id="1",
            provider_team_id="521426",
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


def _module_path_for(dotted: str) -> Path | None:
    """Resolve a dotted import name to a project file, if one exists."""
    candidate = PROJECT_ROOT / Path(*dotted.split(".")).with_suffix(".py")
    return candidate if candidate.is_file() else None


def _is_under_tournaments(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT / "src" / "tournaments")
    except ValueError:
        return False
    return True


def _imported_dotted_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def _tournaments_import_closure(entry: Path) -> set[Path]:
    """Every ``src/tournaments`` module reachable from ``entry``'s own imports.

    Follows an import (module-level or nested in a function body) recursively
    as long as it resolves to a file under ``src/tournaments``, and stops
    without recursing the moment it resolves outside that package. That is a
    deliberate boundary, not a shortcut: the one file this flow reaches outside
    the package, ``tournament_intake.py``, is a multi-feature hub that also
    imports modules which genuinely write (``seeding_enqueue``, for a tab this
    flow never renders) — pulling in everything it imports would make the
    closure flag those as "on this path" too.
    """
    seen = {entry}
    frontier = [entry]
    while frontier:
        current = frontier.pop()
        for dotted in _imported_dotted_names(current):
            resolved = _module_path_for(dotted)
            if resolved is None or not _is_under_tournaments(resolved):
                continue
            if resolved not in seen:
                seen.add(resolved)
                frontier.append(resolved)
    return seen


def test_read_only_modules_covers_every_module_backtest_intake_itself_imports():
    """A hand-copied list cannot fail for a file it omits.

    This re-derives the part of ``_READ_ONLY_MODULES`` that is mechanically
    safe to derive — every ``src/tournaments`` module reachable from
    ``backtest_event_intake.py``'s own imports — and fails the moment that file
    gains an import (at any nesting depth) that the tuple above does not know
    about. It does not, and cannot safely, chase the three modules reached only
    through ``tournament_intake.py``; those stay a hand-verified addition (see
    the comment above ``_READ_ONLY_MODULES``).
    """
    entry = PROJECT_ROOT / "src/tournaments/backtest_event_intake.py"
    closure = _tournaments_import_closure(entry)

    known = set(_READ_ONLY_MODULES)
    missing = {str(path.relative_to(PROJECT_ROOT)).replace("\\", "/") for path in closure} - known
    assert not missing, (
        f"backtest_event_intake.py now reaches {sorted(missing)}, which is not in "
        "_READ_ONLY_MODULES — add it, then verify by hand whether it can write."
    )
