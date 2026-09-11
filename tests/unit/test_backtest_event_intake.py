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


def test_summarize_names_the_cohort_a_division_belongs_to():
    row = summarize_structure([_division(age_group="u12", gender="Male")])[0]

    assert row["cohort"] == "Boys U12"


def test_summarize_says_plainly_when_a_division_names_no_cohort():
    """Blank would read as a rendering fault; this is the event not saying."""
    row = summarize_structure([_division()])[0]

    assert row["cohort"] == "not stated"


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


def test_a_division_whose_fixtures_could_not_be_read_is_not_readable():
    """The other half of `readable`, which every other fixture here leaves True.

    Without this, narrowing `readable` to `division.pools_readable` alone keeps
    the suite green while a division whose fixture table could not be read drops
    out of the "could not be read in full" warning entirely — the operator is
    told its games were captured when they were not.
    """
    row = summarize_structure([_division(fixtures_readable=False, pools_readable=True)])[0]

    assert row["readable"] is False


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

# Two roots, not a flat hand-picked list. ``backtest_event_intake.py`` is the
# module itself. ``event_roster_intake.py`` is reached a different way:
# ``render_backtest_event_intake`` imports ``_render_seeding_event_scrape``,
# ``_render_seeding_override``, ``_render_seeding_progress_metrics`` and
# ``_render_seeding_warnings`` from ``tournament_intake.py``, and those
# functions (and what they call — ``_run_event_roster_scrape`` /
# ``_park_event_roster`` / ``_run_seeding_name_lookup``) are what actually
# reach it. ``tournament_intake.py`` is a multi-feature Streamlit hub outside
# ``src/tournaments`` that also imports genuinely-writing modules
# (``seeding_enqueue``, for the Seeding tab's own enqueue button) for tabs
# this flow never renders, so walking its full import list automatically
# would flag those too and make the derived set useless. That one hop is
# instead verified by hand, tracing every function the Backtest render path
# actually calls (Task 9 report, 2026-09-10) — confirmed ``event_roster_
# intake.py`` is genuinely reached from there.
#
# Everything else below that root is mechanically derived: every module
# reachable from either root's own import statements (module-level or nested
# in a function body), while staying inside ``src/tournaments``.
# ``test_read_only_modules_matches_the_import_closure_of_its_two_roots``
# below re-derives that closure from both roots and fails in either
# direction if this tuple drifts from it — including for a deleted root
# itself, since ``_ROOTS`` is independent of this tuple.
_ROOTS = (
    "src/tournaments/backtest_event_intake.py",
    "src/tournaments/event_roster_intake.py",
)

_READ_ONLY_MODULES = (
    "src/tournaments/backtest_event_intake.py",
    "src/tournaments/backtest_intake_state.py",
    "src/tournaments/backtest_intake_ui.py",
    "src/tournaments/backtest_link_store.py",
    "src/tournaments/gotsport_event_structure.py",
    "src/tournaments/storage/_io.py",
    "src/tournaments/storage/_file_lock.py",
    "src/tournaments/storage/event_key.py",
    "src/tournaments/storage/event_structure.py",
    "src/tournaments/storage/schema_version.py",
    "src/tournaments/gotsport_event_roster.py",
    "src/tournaments/event_roster_intake.py",
    "src/tournaments/roster_resolver.py",
    "src/tournaments/roster_paste.py",
    "src/tournaments/seeding_optimizer.py",
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

    # Pin where the double records. A builder that is constructed and dropped
    # has issued no PostgREST request, so a double that logged at `table()` or
    # `rpc()` would report a write for a caller that never executed one — and
    # `test_matching_a_walked_roster_executes_no_write` asserts on that log.
    client.table("teams").insert({"a": 1})
    client.rpc("enqueue_scrape_request", {})
    assert client.executed == []

    with pytest.raises(AssertionError):
        client.table("teams").insert({"a": 1}).execute()
    with pytest.raises(AssertionError):
        client.rpc("enqueue_scrape_request", {}).execute()
    assert client.table("teams").select("*").execute().data == []


def test_matching_a_walked_roster_executes_no_write(monkeypatch):
    """Exercise the real collaborators, so the double is actually reached.

    The first version of this test used a resolver stub missing
    ``load_merge_map`` and a ``lookup_factory`` lambda that ignored its
    client argument entirely. ``resolve_master_ids`` raised inside its own
    ``try`` the moment it called ``merge_resolver.load_merge_map()``, its
    ``except Exception`` swallowed that, and ``client.executed`` stayed
    ``[]`` — so ``all(... for op in [])`` passed vacuously. The test would
    have passed unchanged if ``resolve_master_ids`` wrote on every call.

    Giving the stub what it needs to run past that line, and leaving
    ``lookup_factory`` at its real default (``make_provider_id_lookup``)
    instead of a lambda that never touches the client, makes the call reach
    ``execute()`` for real. Asserting the exact log — not just "no write is
    in it" — makes an empty log a failure instead of a pass.
    """
    from src.tournaments.event_roster_intake import resolve_master_ids
    from src.tournaments.gotsport_event_roster import EventRosterTeam

    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")

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

    class _StubResolver:
        version = "ok"

        def load_merge_map(self):
            return None

    resolve_master_ids(
        teams,
        enabled=True,
        client_factory=lambda *_: client,
        resolver_factory=lambda _client: _StubResolver(),
    )

    # One provider id, and the real make_provider_id_lookup always starts
    # with a `providers` table select before it can look up anything else —
    # it never finds a row against this double, so that is the only call.
    # An empty log here would mean the call never reached the double at all.
    assert client.executed == ["select"]


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


def test_read_only_modules_matches_the_import_closure_of_its_two_roots():
    """A hand-copied list cannot fail for a file it omits — or notice one it
    no longer needs.

    Seeds the closure from both entries in ``_ROOTS`` rather than one:
    seeding from ``backtest_event_intake.py`` alone never walks into anything
    ``event_roster_intake.py`` imports, which is how ``roster_paste.py`` and
    ``seeding_optimizer.py`` went unscanned even after the first version of
    this test shipped (found by review, not by this test — that gap is the
    reason it now seeds from both roots).

    Checks both directions. "Missing" catches a module either root's own
    imports reach that the tuple doesn't list — including a *root* quietly
    dropped from ``_READ_ONLY_MODULES``, since ``_ROOTS`` is a separate
    constant the closure always re-seeds from regardless of what the tuple
    says. "Stale" catches the opposite: a listed module that neither root's
    closure reaches any more — a single "missing" check alone could never
    catch this for ``roster_resolver.py`` or ``gotsport_event_roster.py``,
    since a hand-edit could leave a stale name in the tuple and nothing
    would notice it had drifted loose from the real graph.
    """
    reachable: set[Path] = set()
    for relative in _ROOTS:
        reachable |= _tournaments_import_closure(PROJECT_ROOT / relative)
    reachable_relative = {str(path.relative_to(PROJECT_ROOT)).replace("\\", "/") for path in reachable}

    known = set(_READ_ONLY_MODULES)

    missing = reachable_relative - known
    assert not missing, (
        f"{_ROOTS} now reach {sorted(missing)}, which is not in _READ_ONLY_MODULES — "
        "add it, then verify by hand whether it can write."
    )

    stale = known - reachable_relative
    assert not stale, (
        f"_READ_ONLY_MODULES lists {sorted(stale)}, which neither root in _ROOTS "
        "reaches any more — confirm it is still genuinely on this path (or belongs "
        "in _ROOTS itself), then fix the tuple."
    )
