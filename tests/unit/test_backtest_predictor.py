from datetime import datetime

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
