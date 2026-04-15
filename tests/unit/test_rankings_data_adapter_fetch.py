import pandas as pd
import pytest

from src.rankings import data_adapter


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, client, table_name: str):
        self.client = client
        self.table_name = table_name
        self.select_columns = None
        self.offset = 0
        self.limit_end = 0
        self.in_values = []

    @property
    def not_(self):
        return self

    def select(self, columns):
        self.select_columns = columns
        if self.table_name == "games":
            self.client.last_games_select = columns
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def lte(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def is_(self, *_args, **_kwargs):
        return self

    def in_(self, _column, values):
        self.in_values = list(values)
        return self

    def range(self, start, end):
        clone = _FakeQuery(self.client, self.table_name)
        clone.select_columns = self.select_columns
        clone.offset = start
        clone.limit_end = end
        clone.in_values = self.in_values
        return clone

    def execute(self):
        if self.table_name == "games":
            page = self.client.games_pages.get(self.offset)
            if isinstance(page, Exception):
                raise page
            return _FakeResult(page or [])

        if self.table_name == "teams":
            return _FakeResult([self.client.team_rows[team_id] for team_id in self.in_values if team_id in self.client.team_rows])

        raise AssertionError(f"Unexpected table {self.table_name}")


class _FakeSupabase:
    def __init__(self, games_pages=None, team_rows=None):
        self.games_pages = games_pages or {}
        self.team_rows = team_rows or {}
        self.last_games_select = None

    def table(self, table_name: str):
        return _FakeQuery(self, table_name)


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_raises_instead_of_returning_partial_snapshot(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    first_page = [
        {
            "id": f"game-{idx}",
            "game_date": "2026-04-01",
            "home_team_master_id": "team-home",
            "away_team_master_id": "team-away",
            "home_score": 2,
            "away_score": 1,
            "provider_id": "provider-1",
        }
        for idx in range(1000)
    ]
    fake_db = _FakeSupabase(
        games_pages={
            0: first_page,
            1000: RuntimeError("JSON could not be generated"),
        }
    )

    with pytest.raises(RuntimeError, match="partial 1,000-game snapshot"):
        await data_adapter.fetch_games_for_rankings(
            fake_db,
            today=pd.Timestamp("2026-04-14", tz="UTC"),
        )

    assert "game_uid" not in fake_db.last_games_select


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_uses_id_when_game_uid_is_not_selected(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                {
                    "id": "game-1",
                    "game_date": "2026-04-01",
                    "home_team_master_id": "team-home",
                    "away_team_master_id": "team-away",
                    "home_score": 3,
                    "away_score": 2,
                    "provider_id": "provider-1",
                }
            ]
        },
        team_rows={
            "team-home": {
                "team_id_master": "team-home",
                "age_group": "u12",
                "gender": "Male",
                "is_deprecated": False,
                "league": None,
            },
            "team-away": {
                "team_id_master": "team-away",
                "age_group": "u12",
                "gender": "Male",
                "is_deprecated": False,
                "league": None,
            },
        },
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
    )

    assert len(result) == 2
    assert set(result["game_id"]) == {"game-1"}
    assert "game_uid" not in fake_db.last_games_select
