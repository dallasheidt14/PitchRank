from pathlib import Path

import pandas as pd
import pytest

import scripts.calculate_rankings as calc


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table_name: str, team_id: str):
        self.table_name = table_name
        self.team_id = team_id
        self._select = None
        self._eq_filters = {}

    def select(self, columns):
        self._select = columns
        return self

    def in_(self, _column, _values):
        return self

    def eq(self, column, value):
        self._eq_filters[column] = value
        return self

    def execute(self):
        if self.table_name != "teams":
            raise AssertionError(f"Unexpected table access in test double: {self.table_name}")

        if self._select == "team_id_master" and self._eq_filters.get("is_deprecated") is True:
            return _FakeResult([])

        if self._select == "team_id_master, age_group, gender, state_code":
            return _FakeResult(
                [
                    {
                        "team_id_master": self.team_id,
                        "age_group": "u12",
                        "gender": "Male",
                        "state_code": "AZ",
                    }
                ]
            )

        raise AssertionError(f"Unexpected query shape: select={self._select!r}, filters={self._eq_filters!r}")


class _FakeSupabase:
    def __init__(self, team_id: str):
        self.team_id = team_id

    def table(self, table_name: str):
        return _FakeQuery(table_name, self.team_id)


def _sample_rankings_full_df(team_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "team_id": team_id,
                "age_group": "u12",
                "gender": "Male",
                "state_code": "AZ",
                "power_score_true": 0.75,
                "power_score_final": 0.63,
                "exp_margin": 0.7,
                "exp_win_rate": 0.64,
                "exp_goals_for": 1.6,
                "exp_goals_against": 0.9,
            }
        ]
    )


@pytest.mark.asyncio
async def test_save_rankings_retries_without_optional_exp_goal_columns(monkeypatch):
    team_id = "team-1"
    teams_df = pd.DataFrame([{"team_id": team_id}])
    monkeypatch.setattr(calc, "v53e_to_rankings_full_format", lambda *_args, **_kwargs: _sample_rankings_full_df(team_id))

    calls = []

    async def fake_save_batch(_supabase_client, table_name, records, table_name_display=None):
        calls.append((table_name, records, table_name_display))
        if len(calls) == 1:
            raise RuntimeError("Could not find the 'exp_goals_against' column of 'rankings_full' in the schema cache")
        return len(records)

    monkeypatch.setattr(calc, "_save_batch_with_retry", fake_save_batch)

    saved = await calc.save_rankings_to_supabase(
        _FakeSupabase(team_id),
        teams_df,
        use_rankings_full=True,
        maintain_backward_compat=False,
    )

    assert saved == 1
    assert [call[0] for call in calls] == ["rankings_full", "rankings_full"]
    retry_record = calls[1][1][0]
    assert "exp_margin" not in retry_record
    assert "exp_win_rate" not in retry_record
    assert "exp_goals_for" not in retry_record
    assert "exp_goals_against" not in retry_record


@pytest.mark.asyncio
async def test_save_rankings_raises_when_rankings_full_publish_is_incomplete(monkeypatch):
    team_id = "team-2"
    teams_df = pd.DataFrame([{"team_id": team_id}])
    monkeypatch.setattr(calc, "v53e_to_rankings_full_format", lambda *_args, **_kwargs: _sample_rankings_full_df(team_id))

    calls = []

    async def fake_save_batch(_supabase_client, table_name, records, table_name_display=None):
        calls.append((table_name, len(records), table_name_display))
        return 0

    monkeypatch.setattr(calc, "_save_batch_with_retry", fake_save_batch)

    with pytest.raises(RuntimeError, match="rankings_full publish incomplete"):
        await calc.save_rankings_to_supabase(
            _FakeSupabase(team_id),
            teams_df,
            use_rankings_full=True,
            maintain_backward_compat=False,
        )

    assert calls == [("rankings_full", 1, "rankings_full")]


def test_python_backfill_uses_non_destructive_upsert_semantics():
    source = Path("scripts/calculate_rankings.py").read_text(encoding="utf-8")
    assert 'upsert(records, on_conflict="team_id", default_to_null=False)' in source


@pytest.mark.asyncio
async def test_save_batch_with_retry_raises_optional_schema_errors_immediately():
    class _AlwaysSchemaErrorTable:
        def upsert(self, _batch):
            return self

        def execute(self):
            raise RuntimeError("Could not find the 'exp_goals_against' column of 'rankings_full' in the schema cache")

    class _Supabase:
        def table(self, _table_name):
            return _AlwaysSchemaErrorTable()

    with pytest.raises(RuntimeError, match="exp_goals_against"):
        await calc._save_batch_with_retry(
            _Supabase(),
            "rankings_full",
            [{"team_id": "team-3", "exp_goals_against": 0.9}],
            table_name_display="rankings_full",
        )
