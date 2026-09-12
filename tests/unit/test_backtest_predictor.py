import asyncio
from datetime import datetime
from types import SimpleNamespace

import httpx
import pandas as pd

from scripts import backtest_predictor


def test_resolve_game_start_date_prefers_explicit_floor():
    resolved = backtest_predictor._resolve_game_start_date(
        lookback_days=365,
        min_game_date="2025-06-23",
    )

    assert resolved == "2025-06-23"


def test_resolve_game_start_date_uses_lookback_when_floor_missing(monkeypatch):
    class FakeDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 4, 21, 12, 0, 0)

    monkeypatch.setattr(backtest_predictor, "datetime", FakeDateTime)

    resolved = backtest_predictor._resolve_game_start_date(
        lookback_days=10,
        min_game_date=None,
    )

    assert resolved == "2026-04-11"


def test_resolve_game_start_date_anchors_lookback_to_historical_ceiling():
    resolved = backtest_predictor._resolve_game_start_date(
        lookback_days=365,
        max_game_date="2024-10-01",
    )

    assert resolved == "2023-10-02"


def test_direct_db_historical_games_enforces_import_cutoff(monkeypatch):
    captured = {}

    class Connection:
        def close(self):
            pass

    def fake_read_sql_query(sql, _connection, params):
        captured["sql"] = sql
        captured["params"] = params
        return pd.DataFrame()

    monkeypatch.setattr(backtest_predictor, "_open_direct_db_connection", Connection)
    monkeypatch.setattr(backtest_predictor.pd, "read_sql_query", fake_read_sql_query)

    backtest_predictor._fetch_historical_games_via_db(
        lookback_days=365,
        min_game_date="2025-04-10",
        max_game_date="2026-04-10",
    )

    assert "g.created_at" in captured["sql"]
    assert "g.game_date < %s AND g.created_at < %s" in captured["sql"]
    assert captured["params"] == ["2025-04-10", "2026-04-10", "2026-04-10"]


def test_rest_historical_games_enforces_import_cutoff(monkeypatch):
    calls = []

    class Query:
        def select(self, columns):
            calls.append(("select", columns))
            return self

        @property
        def not_(self):
            return self

        def is_(self, _column, _value):
            return self

        def gte(self, column, value):
            calls.append((f"gte:{column}", value))
            return self

        def lt(self, column, value):
            calls.append((f"lt:{column}", value))
            return self

        def order(self, _column, desc=False):
            return self

        def range(self, _start, _end):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class Client:
        def table(self, name):
            assert name == "games"
            return Query()

    monkeypatch.setattr(backtest_predictor, "_can_use_direct_db", lambda: False)

    asyncio.run(
        backtest_predictor.fetch_historical_games(
            Client(),
            min_game_date="2025-04-10",
            max_game_date="2026-04-10",
        )
    )

    assert ("lt:game_date", "2026-04-10") in calls
    assert ("lt:created_at", "2026-04-10") in calls
    assert "created_at" in dict(calls)["select"]


def test_direct_db_prediction_snapshots_enforce_availability_cutoff(monkeypatch):
    captured = {}

    class Connection:
        def close(self):
            pass

    def fake_read_sql_query(sql, _connection, params):
        captured["sql"] = sql
        captured["params"] = params
        return pd.DataFrame()

    monkeypatch.setattr(backtest_predictor, "_open_direct_db_connection", Connection)
    monkeypatch.setattr(backtest_predictor.pd, "read_sql_query", fake_read_sql_query)

    backtest_predictor._fetch_prediction_feature_snapshots_via_db(
        ["team-a"],
        "2025-04-10",
        "2026-04-09",
        availability_cutoff="2026-04-10",
    )

    assert "AND created_at < %s" in captured["sql"]
    assert captured["params"] == [
        "2025-04-10",
        "2026-04-09",
        ["team-a"],
        "2026-04-10",
    ]


def test_serial_prediction_snapshots_enforce_availability_cutoff(monkeypatch):
    calls = []

    class Query:
        def select(self, columns):
            calls.append(("select", columns))
            return self

        def in_(self, _column, _value):
            return self

        def gte(self, _column, _value):
            return self

        def lte(self, _column, _value):
            return self

        def order(self, _column, desc=False):
            return self

        def range(self, start, end):
            calls.append(("range", (start, end)))
            return self

        def lt(self, column, value):
            calls.append((f"lt:{column}", value))
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class Client:
        def table(self, name):
            assert name == "prediction_feature_history"
            return Query()

    async def failed_concurrent_fetch(*_args, **_kwargs):
        raise RuntimeError("use serial fallback")

    monkeypatch.setattr(backtest_predictor, "_can_use_direct_db", lambda: False)
    monkeypatch.setattr(
        backtest_predictor,
        "_fetch_prediction_feature_snapshots_via_rest",
        failed_concurrent_fetch,
    )

    asyncio.run(
        backtest_predictor.fetch_prediction_feature_snapshots(
            Client(),
            ["team-a"],
            "2025-04-10",
            "2026-04-09",
            availability_cutoff="2026-04-10",
        )
    )

    assert ("lt:created_at", "2026-04-10") in calls
    assert "created_at" in dict(calls)["select"]
    assert ("range", (0, 999)) in calls


def test_serial_prediction_snapshots_paginate_past_row_cap(monkeypatch):
    ranges = []

    class Query:
        def __init__(self):
            self.start = 0

        def select(self, _columns):
            return self

        def in_(self, _column, _value):
            return self

        def gte(self, _column, _value):
            return self

        def lte(self, _column, _value):
            return self

        def order(self, _column, desc=False):
            return self

        def range(self, start, end):
            self.start = start
            ranges.append((start, end))
            return self

        def execute(self):
            count = 1000 if self.start == 0 else 1
            return SimpleNamespace(
                data=[{"team_id": "team-a", "snapshot_date": "2025-04-10"}] * count
            )

    class Client:
        def table(self, _name):
            return Query()

    async def failed_concurrent_fetch(*_args, **_kwargs):
        raise RuntimeError("use serial fallback")

    monkeypatch.setattr(backtest_predictor, "_can_use_direct_db", lambda: False)
    monkeypatch.setattr(
        backtest_predictor,
        "_fetch_prediction_feature_snapshots_via_rest",
        failed_concurrent_fetch,
    )

    result = asyncio.run(
        backtest_predictor.fetch_prediction_feature_snapshots(
            Client(), ["team-a"], "2025-04-10", "2026-04-09"
        )
    )

    assert len(result) == 1001
    assert ranges == [(0, 999), (1000, 1999)]


def test_concurrent_rest_prediction_snapshots_enforce_availability_cutoff(monkeypatch):
    captured_params = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, _endpoint, *, params, headers):
            captured_params.extend(params)
            return Response()

    monkeypatch.setattr(
        backtest_predictor,
        "_supabase_rest_credentials",
        lambda: ("https://example.test", "key"),
    )
    monkeypatch.setattr(backtest_predictor.httpx, "AsyncClient", AsyncClient)

    result = asyncio.run(
        backtest_predictor._fetch_prediction_feature_snapshots_via_rest(
            ["team-a"],
            "2025-04-10",
            "2026-04-09",
            availability_cutoff="2026-04-10",
        )
    )

    assert result.empty
    assert ("created_at", "lt.2026-04-10") in captured_params


def test_concurrent_rest_prediction_snapshots_retry_transient_page_failure(monkeypatch):
    attempts = 0

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, _endpoint, *, params, headers):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise httpx.ReadTimeout("transient")
            return Response()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(
        backtest_predictor,
        "_supabase_rest_credentials",
        lambda: ("https://example.test", "key"),
    )
    monkeypatch.setattr(backtest_predictor.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(backtest_predictor.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        backtest_predictor._fetch_prediction_feature_snapshots_via_rest(
            ["team-a"], "2025-04-10", "2026-04-09"
        )
    )

    assert result.empty
    assert attempts == 3
