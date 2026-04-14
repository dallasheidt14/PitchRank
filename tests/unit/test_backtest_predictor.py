import asyncio

from scripts.backtest_predictor import fetch_historical_games


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


def test_fetch_historical_games_rebuilds_query_each_batch():
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

    games_df = asyncio.run(fetch_historical_games(supabase, lookback_days=30))

    assert len(games_df) == 1001
    assert [query._range_calls for query in supabase.queries] == [[(0, 999)], [(1000, 1999)]]
