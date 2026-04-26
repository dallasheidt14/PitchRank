"""Unit tests for ``src.tournaments.storage.games_import``.

Uses the in-test fake-Supabase pattern from
``tests/unit/test_alias_writer.py:21-101``.
"""

from __future__ import annotations

from typing import Any

from src.tournaments.storage.games_import import check_games_import_status


class _FakeQuery:
    def __init__(self, table: "_FakeTable"):
        self._table = table
        self._filters: list[tuple[str, Any]] = []
        self._select: str | None = None

    def select(self, columns: str = "*") -> "_FakeQuery":
        self._select = columns
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self._filters.append((column, value))
        return self

    def execute(self) -> Any:
        matched = [row for row in self._table._rows if all(row.get(c) == v for c, v in self._filters)]
        return _FakeExecResult(matched)


class _FakeExecResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def select(self, columns: str = "*") -> _FakeQuery:
        return _FakeQuery(self).select(columns)


class _FakeSupabase:
    def __init__(self, games: list[dict[str, Any]]):
        self._games = _FakeTable(games)

    def table(self, name: str) -> _FakeTable:
        assert name == "games"
        return self._games


def test_zero_rows_is_not_imported():
    supabase = _FakeSupabase(games=[])
    status = check_games_import_status(
        "Phoenix Cup",
        ["m1", "m2"],
        supabase_client=supabase,
    )
    assert status == "not_imported"


def test_full_team_coverage_is_complete():
    games = [
        {
            "event_name": "Phoenix Cup",
            "is_excluded": False,
            "home_team_master_id": "m1",
            "away_team_master_id": "m2",
        },
        {
            "event_name": "Phoenix Cup",
            "is_excluded": False,
            "home_team_master_id": "m2",
            "away_team_master_id": "m3",
        },
    ]
    supabase = _FakeSupabase(games=games)
    status = check_games_import_status(
        "Phoenix Cup",
        ["m1", "m2", "m3"],
        supabase_client=supabase,
    )
    assert status == "complete"


def test_partial_coverage_is_partial():
    games = [
        {
            "event_name": "Phoenix Cup",
            "is_excluded": False,
            "home_team_master_id": "m1",
            "away_team_master_id": "m2",
        },
    ]
    supabase = _FakeSupabase(games=games)
    status = check_games_import_status(
        "Phoenix Cup",
        ["m1", "m2", "m3"],
        supabase_client=supabase,
    )
    assert status == "partial"


def test_excluded_games_filtered_out():
    games = [
        {
            "event_name": "Phoenix Cup",
            "is_excluded": True,  # filtered
            "home_team_master_id": "m1",
            "away_team_master_id": "m2",
        },
    ]
    supabase = _FakeSupabase(games=games)
    status = check_games_import_status(
        "Phoenix Cup",
        ["m1", "m2"],
        supabase_client=supabase,
    )
    assert status == "not_imported"


def test_other_event_games_filtered_out():
    games = [
        {
            "event_name": "Other Event",
            "is_excluded": False,
            "home_team_master_id": "m1",
            "away_team_master_id": "m2",
        },
    ]
    supabase = _FakeSupabase(games=games)
    status = check_games_import_status(
        "Phoenix Cup",
        ["m1"],
        supabase_client=supabase,
    )
    assert status == "not_imported"
