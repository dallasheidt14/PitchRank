import asyncio

import pandas as pd

import scripts.backtest_predictor as backtest_predictor
from scripts.backtest_predictor import fetch_historical_games, fetch_prediction_feature_snapshots


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, batches):
        self._batches = batches
        self._range_calls = []

    def select(self, *_args, **_kwargs):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_args, **_kwargs):
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._range_calls.append((start, end))
        return self

    def execute(self):
        if len(self._range_calls) != 1:
            raise AssertionError(f"expected one range call per query, got {self._range_calls}")
        start, _end = self._range_calls[0]
        batch_index = start // 1000
        return _FakeResponse(self._batches[batch_index] if batch_index < len(self._batches) else [])


class _FakeSupabase:
    def __init__(self, batches):
        self._batches = batches
        self.queries = []

    def table(self, name):
        assert name == "games"
        query = _FakeQuery(self._batches)
        self.queries.append(query)
        return query


class _FakeConnection:
    def close(self):
        return None


def test_fetch_historical_games_rebuilds_query_each_batch():
    backtest_predictor._database_url.cache_clear() if hasattr(backtest_predictor._database_url, "cache_clear") else None
    batches = [
        [
            {
                "id": "game-1",
                "game_date": "2026-04-01",
                "home_team_master_id": "home-1",
                "away_team_master_id": "away-1",
                "home_score": 2,
                "away_score": 1,
            }
        ]
        * 1000,
        [
            {
                "id": "game-2",
                "game_date": "2026-04-02",
                "home_team_master_id": "home-2",
                "away_team_master_id": "away-2",
                "home_score": 3,
                "away_score": 0,
            }
        ],
    ]
    supabase = _FakeSupabase(batches)
    # Force the legacy Supabase path for this regression test even if DATABASE_URL is set locally.
    import os

    original_database_url = os.environ.pop("DATABASE_URL", None)

    try:
        games_df = asyncio.run(fetch_historical_games(supabase, lookback_days=30))
    finally:
        if original_database_url is not None:
            os.environ["DATABASE_URL"] = original_database_url

    assert len(games_df) == 1001
    assert [query._range_calls for query in supabase.queries] == [[(0, 999)], [(1000, 1999)]]


def test_fetch_historical_games_prefers_direct_database_url(monkeypatch):
    calls = []

    def fake_connect(_database_url):
        return _FakeConnection()

    def fake_read_sql_query(sql, conn, params=None):
        calls.append((sql, conn, params))
        return pd.DataFrame(
            [
                {
                    "id": "game-1",
                    "game_date": "2026-04-01",
                    "home_team_master_id": "home-1",
                    "away_team_master_id": "away-1",
                    "home_score": 2,
                    "away_score": 1,
                }
            ]
        )

    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(backtest_predictor, "HAS_PSYCOPG2", True)
    monkeypatch.setattr(backtest_predictor, "psycopg2", type("Psycopg", (), {"connect": staticmethod(fake_connect)}))
    monkeypatch.setattr(backtest_predictor.pd, "read_sql_query", fake_read_sql_query)

    games_df = asyncio.run(fetch_historical_games(None, lookback_days=30, limit=10))

    assert len(games_df) == 1
    assert len(calls) == 1
    assert "FROM games g" in calls[0][0]
    assert calls[0][2][-1] == 10


def test_fetch_prediction_feature_snapshots_prefers_direct_database_url(monkeypatch):
    calls = []

    def fake_connect(_database_url):
        return _FakeConnection()

    def fake_read_sql_query(sql, conn, params=None):
        calls.append((sql, conn, params))
        return pd.DataFrame(
            [
                {
                    "snapshot_date": "2026-04-01",
                    "team_id": params[2][0],
                    "age_group": "u12",
                    "gender": "boys",
                    "status": "active",
                    "rank_in_cohort_final": 10,
                    "power_score_final": 0.7,
                    "sos_norm": 0.6,
                    "offense_norm": 0.55,
                    "defense_norm": 0.52,
                    "glicko_rating": 1500,
                    "glicko_rd": 120,
                    "glicko_volatility": 0.06,
                    "wins": 10,
                    "losses": 2,
                    "draws": 1,
                    "games_played": 13,
                    "win_percentage": 0.77,
                    "exp_margin": 1.1,
                    "exp_win_rate": 0.69,
                    "exp_goals_for": 2.3,
                    "exp_goals_against": 1.0,
                }
            ]
        )

    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(backtest_predictor, "HAS_PSYCOPG2", True)
    monkeypatch.setattr(backtest_predictor, "psycopg2", type("Psycopg", (), {"connect": staticmethod(fake_connect)}))
    monkeypatch.setattr(backtest_predictor.pd, "read_sql_query", fake_read_sql_query)

    snapshots_df = asyncio.run(
        fetch_prediction_feature_snapshots(
            None,
            team_ids=["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"],
            start_date="2026-04-01",
            end_date="2026-04-10",
        )
    )

    assert len(snapshots_df) == 1
    assert len(calls) == 1
    assert "FROM prediction_feature_history" in calls[0][0]
