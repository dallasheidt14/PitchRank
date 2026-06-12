"""
Regression tests for the rank_change_7d apples-to-oranges bug.

Before the fix, calculate_rank_changes ran in compute_rankings_with_ml on a
DataFrame that did NOT yet have rank_in_cohort_final populated, so the "current"
side fell back to rank_in_cohort_ml while the historical side (read from
ranking_history) resolved to rank_in_cohort_final — producing impossible deltas
like #1 ↓16 for top-of-cohort teams.

The fix relocates the call into compute_all_cohorts after rank_in_cohort_final
is set. Live bug shape: Illinois Magic FC 2014 (u12 male) had
rank_in_cohort_final=1, rank_in_cohort_ml=23, historical 7d ago = 7. Correct
delta is 7 - 1 = +6. The bug produced 7 - 23 = -16.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from src.rankings import calculator, ranking_history


@pytest.mark.asyncio
async def test_rank_change_uses_rank_in_cohort_final_not_ml(monkeypatch):
    """rank_change_7d must use rank_in_cohort_final on the current side."""
    team_a = "00000000-0000-0000-0000-00000000000a"
    team_b = "00000000-0000-0000-0000-00000000000b"

    current_df = pd.DataFrame(
        {
            "team_id": [team_a, team_b],
            "age_group": ["u12", "u12"],
            "gender": ["male", "male"],
            "rank_in_cohort_final": pd.array([1, 5], dtype="Int64"),
            "rank_in_cohort_ml": pd.array([23, 7], dtype="Int64"),
            "rank_in_cohort": pd.array([44, 10], dtype="Int64"),
            "state_code": ["IL", "IL"],
            "power_score_final": [0.845, 0.700],
            "status": ["Active", "Active"],
        }
    )

    monkeypatch.setattr(
        ranking_history,
        "get_historical_ranks",
        AsyncMock(side_effect=[{team_a: 7, team_b: 9}, {}]),
    )
    monkeypatch.setattr(
        ranking_history,
        "get_historical_state_ranks",
        AsyncMock(side_effect=[{}, {}]),
    )

    result = await ranking_history.calculate_rank_changes(
        supabase_client=None,
        current_rankings_df=current_df,
    )

    # team_a: 7 - 1 = +6 (bug would have produced 7 - 23 = -16)
    assert result.loc[result["team_id"] == team_a, "rank_change_7d"].iloc[0] == 6, (
        "rank_change_7d for team_a must use rank_in_cohort_final (=1), not "
        "rank_in_cohort_ml (=23). Got -16 means the bug is back."
    )
    # team_b: 9 - 5 = +4
    assert result.loc[result["team_id"] == team_b, "rank_change_7d"].iloc[0] == 4
    assert pd.isna(result.loc[result["team_id"] == team_a, "rank_change_30d"].iloc[0])


@pytest.mark.asyncio
async def test_rank_change_falls_back_to_ml_when_final_is_na(monkeypatch):
    """3-level fallback (final → ml → cohort) is preserved for pre-migration/Inactive teams."""
    team_a = "00000000-0000-0000-0000-00000000000a"

    # rank_in_cohort_final is NA (Inactive team or pre-migration row); fallback
    # to rank_in_cohort_ml=23. Historical also has only ml available (final=NA).
    current_df = pd.DataFrame(
        {
            "team_id": [team_a],
            "age_group": ["u12"],
            "gender": ["male"],
            "rank_in_cohort_final": pd.array([pd.NA], dtype="Int64"),
            "rank_in_cohort_ml": pd.array([23], dtype="Int64"),
            "rank_in_cohort": pd.array([44], dtype="Int64"),
            "state_code": ["IL"],
            "power_score_final": [0.700],
            "status": ["Inactive"],
        }
    )

    monkeypatch.setattr(
        ranking_history,
        "get_historical_ranks",
        AsyncMock(side_effect=[{team_a: 30}, {}]),
    )
    monkeypatch.setattr(
        ranking_history,
        "get_historical_state_ranks",
        AsyncMock(side_effect=[{}, {}]),
    )

    result = await ranking_history.calculate_rank_changes(
        supabase_client=None,
        current_rankings_df=current_df,
    )

    # final=NA → fallback to ml=23 for current; historical=30 → 30 - 23 = +7
    assert result.loc[result["team_id"] == team_a, "rank_change_7d"].iloc[0] == 7


@pytest.mark.asyncio
async def test_state_rank_change_uses_current_state_rank(monkeypatch):
    """State-rank delta uses the current state rank computed from power_score_final."""
    team_a = "00000000-0000-0000-0000-00000000000a"
    team_b = "00000000-0000-0000-0000-00000000000b"

    # Both teams in IL. power_score_final orders A > B → A is state rank 1, B is 2.
    current_df = pd.DataFrame(
        {
            "team_id": [team_a, team_b],
            "age_group": ["u12", "u12"],
            "gender": ["male", "male"],
            "rank_in_cohort_final": pd.array([1, 5], dtype="Int64"),
            "rank_in_cohort_ml": pd.array([1, 5], dtype="Int64"),
            "rank_in_cohort": pd.array([1, 5], dtype="Int64"),
            "state_code": ["IL", "IL"],
            "power_score_final": [0.845, 0.700],
            "status": ["Active", "Active"],
        }
    )

    monkeypatch.setattr(
        ranking_history,
        "get_historical_ranks",
        AsyncMock(side_effect=[{}, {}]),
    )
    monkeypatch.setattr(
        ranking_history,
        "get_historical_state_ranks",
        AsyncMock(side_effect=[{team_a: 3, team_b: 4}, {}]),
    )

    result = await ranking_history.calculate_rank_changes(
        supabase_client=None,
        current_rankings_df=current_df,
    )

    # team_a: current state rank 1, historical 3 → 3 - 1 = +2
    assert result.loc[result["team_id"] == team_a, "rank_change_state_7d"].iloc[0] == 2
    # team_b: current state rank 2, historical 4 → 4 - 2 = +2
    assert result.loc[result["team_id"] == team_b, "rank_change_state_7d"].iloc[0] == 2


@pytest.mark.asyncio
async def test_compute_all_cohorts_invokes_calculate_rank_changes_after_final_rank(monkeypatch):
    """Integration: the relocated call runs against teams_combined with rank_in_cohort_final populated."""
    captured: dict = {}

    async def fake_calculate_rank_changes(supabase_client, current_rankings_df, reference_date=None):
        captured["call_count"] = captured.get("call_count", 0) + 1
        captured["has_final_column"] = "rank_in_cohort_final" in current_rankings_df.columns
        captured["final_values"] = current_rankings_df["rank_in_cohort_final"].tolist()
        current_rankings_df["rank_change_7d"] = 0
        current_rankings_df["rank_change_30d"] = 0
        current_rankings_df["rank_change_state_7d"] = 0
        current_rankings_df["rank_change_state_30d"] = 0
        return current_rankings_df

    monkeypatch.setattr(calculator, "calculate_rank_changes", fake_calculate_rank_changes)

    # Stub compute_rankings_with_ml to return a minimal teams DataFrame so
    # compute_all_cohorts can finish without touching the real engine.
    async def fake_compute_rankings_with_ml(
        supabase_client,
        games_df,
        today,
        v53_cfg=None,
        layer13_cfg=None,
        fetch_from_supabase=False,
        lookback_days=365,
        provider_filter=None,
        ctx=None,
    ):
        age = str(games_df["age"].iloc[0])
        rows = [
            {
                "team_id": f"team-{age}-{tid}",
                "age": age,
                "age_num": int(age),
                "gender": "male",
                "mu": 1500.0 + i * 10,
                "sigma": 80.0,
                "volatility": 0.06,
                "abs_strength": 0.5,
                "sos_norm": 0.50,
                "powerscore_adj": 0.50,
                "powerscore_ml": 0.50,
                "power_score_true": 0.50 + i * 0.05,
                "power_score_final": 0.50 + i * 0.05,
                "status": "Active",
            }
            for i, tid in enumerate(["A", "B"])
        ]
        return {
            "teams": pd.DataFrame(rows),
            "games_used": games_df.copy(),
            "pre_sos_state": {"legacy": age},
        }

    async def fake_save(*_args, **_kwargs):
        return None

    monkeypatch.setattr(calculator, "compute_rankings_with_ml", fake_compute_rankings_with_ml)
    monkeypatch.setattr(calculator, "save_ranking_snapshot", fake_save)
    monkeypatch.setattr(calculator, "_save_prediction_feature_snapshot_safe", fake_save)

    games = pd.DataFrame(
        [
            {
                "team_id": "A",
                "opp_id": "B",
                "gf": 2,
                "ga": 1,
                "date": pd.Timestamp("2026-03-01"),
                "age": "14",
                "gender": "male",
                "opp_age": "14",
                "opp_gender": "male",
            },
            {
                "team_id": "B",
                "opp_id": "A",
                "gf": 1,
                "ga": 2,
                "date": pd.Timestamp("2026-03-01"),
                "age": "14",
                "gender": "male",
                "opp_age": "14",
                "opp_gender": "male",
            },
        ]
    )

    class _DummySupabaseQuery:
        def select(self, *_args, **_kwargs):
            return self

        def in_(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class _DummySupabase:
        def __init__(self):
            self.client = None

        def table(self, _name: str):
            return _DummySupabaseQuery()

    await calculator.compute_all_cohorts(
        supabase_client=_DummySupabase(),
        games_df=games,
        fetch_from_supabase=False,
        use_glicko=True,
        calculate_rank_changes_enabled=True,
        save_snapshot=False,
    )

    assert captured.get("call_count") == 1, (
        f"calculate_rank_changes must be awaited exactly once at the compute_all_cohorts "
        f"layer, got {captured.get('call_count')}. Per-cohort invocations would mean the "
        f"relocation has regressed."
    )
    assert captured["has_final_column"], (
        "calculate_rank_changes must receive a DataFrame with rank_in_cohort_final populated. "
        "Missing column means the call was relocated to before the final-rank publication step."
    )
    assert any(v is not pd.NA for v in captured["final_values"]), (
        "rank_in_cohort_final must contain at least one non-NA value when "
        "calculate_rank_changes runs (the published rank for Active teams)."
    )
