"""The preflight checker guards the figures the skill quotes -- but only the ones whose
measure name matches a RECORDED key. A measure added, renamed or dropped on one side and not
the other prints green forever, which is the failure the script exists to prevent. The names
are checked by parsing; the bodies are checked by running them over an in-memory table set,
since a name that survives with a wrong query under it guards the wrong figure.

The fake models PostgREST's filters, ordering and paging only -- not the 1,000-row cap,
projection, or the SDK's serialisation -- so a green run proves ``measure()``'s aggregation,
not the database. The ~100-id URI limit is the exception: it is asserted here, because a
reader that stops batching is wrong in production and nowhere else."""

import ast
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.check_state_skill_assumptions as checker  # noqa: E402
from src.utils.club_state_registry import CLUBS  # noqa: E402

CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check_state_skill_assumptions.py"


def _recorded_keys(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "RECORDED" for target in node.targets
        ):
            return {key.value for key in node.value.keys}
    raise AssertionError("RECORDED not found")


def _measured_names(tree):
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "measure"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(node.args[0].value)
    return names


def test_every_measure_is_recorded_and_every_recorded_figure_is_measured():
    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    recorded = _recorded_keys(tree)
    measured = _measured_names(tree)

    assert measured == recorded, {
        "measured but not recorded": sorted(measured - recorded),
        "recorded but never measured": sorted(recorded - measured),
    }


class _Query:
    """One PostgREST read over fixed rows: filters narrow, ``order`` calls are recorded and
    applied once at the read with the first call primary -- as postgrest-py appends them --
    and NULLs placed as PostgreSQL places them, first under ``desc``, unless ``nullsfirst``
    says otherwise (the trap the flag exists for); ``range`` and ``limit`` page the sorted
    rows; ``select(count="exact", head=True)`` answers with the count alone, and ``count``
    is ``None`` when it was not asked for, as the real client's."""

    def __init__(self, rows):
        self.rows = rows
        self.head = False
        self.counting = False
        self.orders = []

    def select(self, *columns, count=None, head=False):
        self.head = head
        self.counting = count is not None
        return self

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r.get(column) == value]
        return self

    def is_(self, column, value):
        assert value == "null"
        self.rows = [r for r in self.rows if r.get(column) is None]
        return self

    def in_(self, column, values):
        wanted = list(values)
        assert len(wanted) <= 100, "an in_() past ~100 ids exceeds the URI length in production"
        self.rows = [r for r in self.rows if r.get(column) in set(wanted)]
        return self

    def order(self, column, *, desc=False, nullsfirst=None):
        self.orders.append((column, desc, nullsfirst))
        return self

    def _sort(self):
        # Stable sorts applied from the last key to the first leave the first key primary.
        for column, desc, nullsfirst in reversed(self.orders):
            nulls_first = desc if nullsfirst is None else nullsfirst
            valued = sorted((r for r in self.rows if r.get(column) is not None), key=lambda r: r[column], reverse=desc)
            missing = [r for r in self.rows if r.get(column) is None]
            self.rows = missing + valued if nulls_first else valued + missing
        self.orders = []

    def range(self, start, stop):
        self._sort()
        self.rows = self.rows[start : stop + 1]
        return self

    def limit(self, n):
        self._sort()
        self.rows = self.rows[:n]
        return self

    def execute(self):
        self._sort()
        return type(
            "R", (), {"data": [] if self.head else self.rows, "count": len(self.rows) if self.counting else None}
        )()


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(list(self.tables.get(name, [])))


def _row(team_id, club, state, **fields):
    return {
        "team_id_master": team_id, "team_name": team_id, "club_name": club,
        "state_code": state, "state": None, "state_source": None, "is_deprecated": False,
        **fields,
    }


def _alias(team_id, provider_team_id, status="approved"):
    return {
        "team_id_master": team_id, "provider_team_id": provider_team_id,
        "provider_id": 7, "review_status": status, "created_at": f"2026-01-{provider_team_id:02d}",
    }


def test_the_fake_orders_first_key_primary_with_nulls_last_on_request():
    """The fake is the only executor of the alias reader's two-key order, so its composition
    has to match postgrest-py's: the first ``order()`` is primary, and ``nullsfirst=False``
    puts a NULL last where PostgreSQL's ``desc`` default would put it first."""
    rows = [
        {"k": None, "t": 1}, {"k": "2026-02", "t": 9}, {"k": "2026-02", "t": 3}, {"k": "2026-01", "t": 5},
    ]
    q = _Query(list(rows)).order("k", desc=True, nullsfirst=False).order("t")
    assert [r["t"] for r in q.execute().data] == [3, 9, 5, 1]
    q = _Query(list(rows)).order("k", desc=True).order("t")
    assert [r["t"] for r in q.execute().data] == [1, 3, 9, 5]
    assert _Query(list(rows)).select("t").execute().count is None
    assert _Query(list(rows)).select("t", count="exact", head=True).execute().count == 4


def test_measure_reads_every_figure_from_the_tables_the_tool_reads():
    """Every figure comes out of a different query, so the fixture gives every count its own
    value -- no two expected figures coincide -- and a measure pointed at the wrong table,
    filter or population reads a different number, not the same one by coincidence. The
    stateless pool is 1,001 rows so the paging loop turns twice -- with a visible team on the
    last row of a full page and another on the second page, so a loop that stops early or
    reads 999 at a time miscounts -- and 152 of them are on a board so the 100-id batching
    turns twice."""
    stateless = [_row(f"n{i:04d}", "", None) for i in range(1001)]
    tables = {
        "providers": [{"id": 7, "code": "gotsport"}],
        "teams": [
            _row("a1", "Anchored FC", "OH", state_source="tier_a"),
            _row("wrong1", "Anchored FC", "WA"),  # the audit's dissenters: three, one aliased
            _row("wrong2", "Anchored FC", "NV"),
            _row("wrong3", "Anchored FC", "TX"),
            _row("q0", "Quiet FC", "WA"),  # two anchorable clubs, seven teams, five aliased
            _row("q1", "Quiet FC", "WA"),
            _row("q2", "Quiet FC", "WA"),  # quarantined alias: not counted
            _row("t0", "Second FC", "OR"),
            _row("t1", "Second FC", "OR"),
            _row("t2", "Second FC", "OR"),
            _row("t3", "Second FC", "OR"),  # no alias
            *[_row(f"s{i}", "", "WA") for i in range(6)],  # the unclubbed tail: six, four aliased
            *stateless,
            _row("d0", "Gone FC", "TX", is_deprecated=True),
        ],
        "team_alias_map": [
            _alias("wrong1", 1), _alias("q0", 2), _alias("q1", 3), _alias("q2", 4, "pending"),
            _alias("t0", 5), _alias("t1", 6), _alias("t2", 7),
            *[_alias(f"s{i}", 10 + i) for i in range(4)],
        ],
        "rankings_full": [
            *[{"team_id": f"n{i:04d}", "status": "Active"} for i in range(150)],
            {"team_id": "n0999", "status": "Active"},  # the last row of a full page
            {"team_id": "n1000", "status": "Active"},  # the second page
            {"team_id": "n0150", "status": "Inactive"},
            {"team_id": "s0", "status": "Active"},
        ],
        "team_state_audit": [{"id": i} for i in range(9)],
        "team_state_review_queue": [
            *[{"id": i, "status": "pending"} for i in range(8)],
            {"id": 99, "status": "approved"},
        ],
    }
    result = checker.Result()
    checker.measure(result, FakeSupabase(tables))
    measured = {m["name"]: m["value"] for m in result.measurements}

    expected = {
        "registry_entries": len(CLUBS),
        "registry_curated": sum(1 for entry in CLUBS.values() if entry["curate"]),
        "live_teams": 1018,
        "teams_without_state": 1001,
        "ledger_rows": 9,
        "queue_pending": 8,
        "stateless_and_visible": 152,
        "audit_candidates": 3,
        "audit_candidates_with_alias": 1,
        "anchorable_clubs": 2,
        "teams_in_anchorable_clubs": 7,
        "teams_in_anchorable_clubs_with_alias": 5,
        "unclubbed_population": 6,
        "unclubbed_with_alias": 4,
    }
    assert measured == expected
    database_figures = [v for k, v in expected.items() if not k.startswith("registry_")]
    assert len(set(database_figures)) == len(database_figures), "two figures share a value"
