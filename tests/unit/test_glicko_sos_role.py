from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_rankings_v2, run_glicko2_cohort
from src.rankings import calculator


def _make_game_pair(
    team_a: str,
    team_b: str,
    gf: int,
    ga: int,
    date: str,
    *,
    age: str = "14",
    gender: str = "male",
    opp_age: str | None = None,
    opp_gender: str | None = None,
) -> list[dict]:
    opp_age = opp_age or age
    opp_gender = opp_gender or gender
    ts = pd.Timestamp(date)
    return [
        {
            "team_id": team_a,
            "opp_id": team_b,
            "gf": gf,
            "ga": ga,
            "date": ts,
            "age": age,
            "gender": gender,
            "opp_age": opp_age,
            "opp_gender": opp_gender,
        },
        {
            "team_id": team_b,
            "opp_id": team_a,
            "gf": ga,
            "ga": gf,
            "date": ts,
            "age": opp_age,
            "gender": opp_gender,
            "opp_age": age,
            "opp_gender": gender,
        },
    ]


def _align(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("team_id").set_index("team_id")


def _core_cols(df: pd.DataFrame) -> pd.DataFrame:
    aligned = _align(df)
    return aligned[["mu", "sigma", "volatility", "rank_in_cohort"]]


def _convergence_cols(df: pd.DataFrame) -> pd.DataFrame:
    aligned = _align(df)
    return aligned[["mu", "sigma", "volatility"]]


def _assert_core_fields_unchanged(left: pd.DataFrame, right: pd.DataFrame) -> None:
    left_core = _core_cols(left)
    right_core = _core_cols(right)
    np.testing.assert_allclose(left_core["mu"], right_core["mu"], atol=1e-9)
    np.testing.assert_allclose(left_core["sigma"], right_core["sigma"], atol=1e-9)
    np.testing.assert_allclose(left_core["volatility"], right_core["volatility"], atol=1e-12)
    np.testing.assert_allclose(left_core["rank_in_cohort"], right_core["rank_in_cohort"], atol=0.0)


def _assert_convergence_fields_unchanged(left: pd.DataFrame, right: pd.DataFrame) -> None:
    left_conv = _convergence_cols(left)
    right_conv = _convergence_cols(right)
    np.testing.assert_allclose(left_conv["mu"], right_conv["mu"], atol=1e-9)
    np.testing.assert_allclose(left_conv["sigma"], right_conv["sigma"], atol=1e-9)
    np.testing.assert_allclose(left_conv["volatility"], right_conv["volatility"], atol=1e-12)


def _max_abs_diff(left: pd.DataFrame, right: pd.DataFrame, column: str) -> float:
    left_aligned = _align(left)[column].astype(float)
    right_aligned = _align(right)[column].astype(float)
    return float((left_aligned - right_aligned).abs().max())


def _run_glicko(
    games_df: pd.DataFrame,
    cfg: GlickoConfig,
    *,
    team_state_map: dict[str, str] | None = None,
    tier_league_map: dict[str, str] | None = None,
    global_rating_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    result = compute_rankings_v2(
        games_df,
        today=pd.Timestamp("2026-03-31"),
        cfg=cfg,
        team_state_map=team_state_map,
        tier_league_map=tier_league_map,
        global_rating_map=global_rating_map,
    )
    return result["teams"]


def _build_round_robin_cohort() -> pd.DataFrame:
    rows: list[dict] = []
    rows += _make_game_pair("A", "B", 4, 0, "2026-03-01")
    rows += _make_game_pair("A", "C", 4, 1, "2026-03-02")
    rows += _make_game_pair("A", "D", 5, 0, "2026-03-03")
    rows += _make_game_pair("B", "C", 2, 0, "2026-03-04")
    rows += _make_game_pair("B", "D", 3, 1, "2026-03-05")
    rows += _make_game_pair("C", "D", 2, 1, "2026-03-06")
    return pd.DataFrame(rows)


def _build_repeat_cap_fixture() -> pd.DataFrame:
    rows: list[dict] = []
    for i in range(8):
        rows += _make_game_pair("A", "Elite", 1, 2, f"2026-02-{i + 1:02d}")
    for i in range(2):
        rows += _make_game_pair("A", "Weak", 4, 0, f"2026-03-{i + 1:02d}")
    for i in range(2):
        rows += _make_game_pair("Elite", "Weak", 3, 0, f"2026-03-{i + 10:02d}")
    return pd.DataFrame(rows)


def _build_isolated_bubble_fixture() -> tuple[pd.DataFrame, dict[str, str]]:
    rows: list[dict] = []
    bubble_teams = ["bubble_star", "bubble_b", "bubble_c", "bubble_d"]

    day = 1
    for _ in range(3):
        for opp in bubble_teams[1:]:
            rows += _make_game_pair("bubble_star", opp, 4, 0, f"2026-03-{day:02d}")
            day += 1

    pair_scores = [(2, 1), (1, 1), (2, 2)]
    for i, home in enumerate(bubble_teams[1:]):
        for away in bubble_teams[i + 2 :]:
            gf, ga = pair_scores[(day - 1) % len(pair_scores)]
            rows += _make_game_pair(home, away, gf, ga, f"2026-03-{day:02d}")
            day += 1

    state_map = {team: "ID" for team in bubble_teams}
    return pd.DataFrame(rows), state_map


class TestGlickoSOSAblations:
    def test_sos_adjustment_only_changes_publication_outputs(self):
        games = _build_round_robin_cohort()
        cfg_on = GlickoConfig(MIN_GAMES_PROVISIONAL=1, SOS_ADJ_ENABLED=True)
        cfg_off = GlickoConfig(MIN_GAMES_PROVISIONAL=1, SOS_ADJ_ENABLED=False)

        teams_on = _run_glicko(games, cfg_on)
        teams_off = _run_glicko(games, cfg_off)

        _assert_core_fields_unchanged(teams_on, teams_off)
        np.testing.assert_allclose(_align(teams_on)["sos_raw"], _align(teams_off)["sos_raw"], atol=1e-9)
        np.testing.assert_allclose(_align(teams_on)["sos_norm"], _align(teams_off)["sos_norm"], atol=1e-9)

        sos_norm = _align(teams_on)["sos_norm"]
        assert ((sos_norm < cfg_on.SOS_ADJ_WEAK_THRESHOLD) | (sos_norm > cfg_on.SOS_ADJ_STRONG_THRESHOLD)).any()
        assert _max_abs_diff(teams_on, teams_off, "powerscore_core") > 1e-6
        assert _max_abs_diff(teams_on, teams_off, "power_score_final") > 1e-6

    def test_repeat_cap_and_trim_change_sos_but_not_glicko_core(self):
        games = _build_repeat_cap_fixture()
        baseline = GlickoConfig(MIN_GAMES_PROVISIONAL=1)
        altered = GlickoConfig(
            MIN_GAMES_PROVISIONAL=1,
            SOS_REPEAT_CAP=8,
            SOS_TRIM_BOTTOM_PCT=0.0,
            SOS_TRIM_TOP_PCT=0.0,
        )

        teams_baseline = _run_glicko(games, baseline)
        teams_altered = _run_glicko(games, altered)

        _assert_core_fields_unchanged(teams_baseline, teams_altered)
        assert _max_abs_diff(teams_baseline, teams_altered, "sos_raw") > 1e-6
        assert _max_abs_diff(teams_baseline, teams_altered, "sos_norm") > 1e-6
        assert _max_abs_diff(teams_baseline, teams_altered, "power_score_final") > 1e-6

    def test_scf_is_post_convergence_mu_and_sos_dampening(self):
        games, state_map = _build_isolated_bubble_fixture()
        scf_on = GlickoConfig(MIN_GAMES_PROVISIONAL=1, SCF_ENABLED=True)
        scf_off = GlickoConfig(MIN_GAMES_PROVISIONAL=1, SCF_ENABLED=False)

        converged_on, _ = run_glicko2_cohort(games, scf_on, pd.Timestamp("2026-03-31"))
        converged_off, _ = run_glicko2_cohort(games, scf_off, pd.Timestamp("2026-03-31"))
        _assert_convergence_fields_unchanged(converged_on, converged_off)

        teams_on = _run_glicko(games, scf_on, team_state_map=state_map)
        teams_off = _run_glicko(games, scf_off, team_state_map=state_map)

        on_row = _align(teams_on).loc["bubble_star"]
        off_row = _align(teams_off).loc["bubble_star"]
        neutral = scf_on.INITIAL_MU
        assert abs(on_row["sos_raw"] - neutral) < abs(off_row["sos_raw"] - neutral)
        assert abs(on_row["mu"] - neutral) < abs(off_row["mu"] - neutral)
        assert _max_abs_diff(teams_on, teams_off, "sos_norm") > 1e-6


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
    def table(self, _name: str):
        return _DummySupabaseQuery()


class _RecordingRpcResult:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _RecordingSupabase:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, payload: dict):
        self.calls.append((name, payload))
        row_count = len(payload.get("rows", []))
        return _RecordingRpcResult(row_count)


@pytest.mark.asyncio
async def test_compute_all_cohorts_builds_glicko_pass2_map_from_mu(monkeypatch):
    calls: list[dict] = []

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
        from src.rankings.calculator import RankingContext

        ctx = ctx or RankingContext()
        pass_label = ctx.pass_label
        global_strength_map = ctx.global_strength_map
        initial_ratings = ctx.initial_ratings
        use_glicko = ctx.use_glicko
        assert use_glicko is True

        age = str(games_df["age"].iloc[0])
        teams_for_age = {
            "14": {
                "A": (1610.0, 0.11),
                "B": (1520.0, 0.22),
            },
            "15": {
                "C": (1580.0, 0.33),
                "D": (1490.0, 0.44),
            },
        }[age]

        rows = []
        for team_id, (mu, abs_strength) in teams_for_age.items():
            rows.append(
                {
                    "team_id": team_id,
                    "age": age,
                    "age_num": int(age),
                    "gender": "male",
                    "mu": mu,
                    "sigma": 80.0,
                    "volatility": 0.06,
                    "abs_strength": abs_strength,
                    "sos_norm": 0.50,
                    "powerscore_adj": 0.50,
                    "powerscore_ml": 0.50,
                    "power_score_true": 0.50,
                    "power_score_final": 0.50,
                    "status": "Active",
                }
            )

        calls.append(
            {
                "pass_label": pass_label,
                "age": age,
                "global_strength_map": dict(global_strength_map or {}),
                "initial_ratings": dict(initial_ratings or {}),
            }
        )

        return {
            "teams": pd.DataFrame(rows),
            "games_used": games_df.copy(),
            "pre_sos_state": {"legacy": age},
        }

    async def fake_save_ranking_snapshot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(calculator, "compute_rankings_with_ml", fake_compute_rankings_with_ml)
    monkeypatch.setattr(calculator, "save_ranking_snapshot", fake_save_ranking_snapshot)

    games = pd.DataFrame(
        _make_game_pair("A", "B", 2, 1, "2026-03-01", age="14")
        + _make_game_pair("C", "D", 3, 2, "2026-03-02", age="15")
    )

    result = await calculator.compute_all_cohorts(
        supabase_client=_DummySupabase(),
        games_df=games,
        fetch_from_supabase=False,
        use_glicko=True,
    )

    assert not result["teams"].empty

    pass1_calls = [call for call in calls if call["pass_label"] == "Pass1"]
    pass2_calls = [call for call in calls if call["pass_label"] == "Pass2"]
    assert len(pass1_calls) == 2
    assert len(pass2_calls) == 2

    expected_map = {
        "A": 1610.0,
        "B": 1520.0,
        "C": 1580.0,
        "D": 1490.0,
    }
    for call in pass2_calls:
        assert call["global_strength_map"] == expected_map
        assert call["initial_ratings"]


@pytest.mark.asyncio
async def test_compute_all_cohorts_can_skip_snapshot_and_rank_change_side_effects(monkeypatch):
    calls: list[dict] = []
    save_calls = {"ranking": 0, "prediction": 0}

    async def fake_compute_rankings_with_ml(
        supabase_client,
        games_df,
        today,
        v53_cfg=None,
        layer13_cfg=None,
        fetch_from_supabase=True,
        lookback_days=365,
        provider_filter=None,
        ctx=None,
    ):
        pass_label = ctx.pass_label if ctx else None
        age = str(games_df.iloc[0]["age"])
        rows = []
        ratings = {
            "14": {"A": 1610.0, "B": 1520.0},
            "15": {"C": 1580.0, "D": 1490.0},
        }[age]
        gender = "male"

        for team_id, mu in ratings.items():
            rows.append(
                {
                    "team_id": team_id,
                    "age": int(age),
                    "age_num": int(age),
                    "gender": gender,
                    "mu": mu,
                    "sigma": 80.0,
                    "volatility": 0.06,
                    "sos": 0.5,
                    "sos_norm": 0.5,
                    "power_score_true": 0.5,
                    "power_score_final": 0.5,
                    "powerscore_adj": 0.5,
                    "powerscore_ml": 0.5,
                    "positive_ml_evidence_scale": 1.0,
                    "publication_cap_score": pd.NA,
                    "status": "Active",
                    "rank_in_cohort_final": 1,
                }
            )

        calls.append(
            {
                "pass_label": pass_label,
                "persist_game_residuals": ctx.persist_game_residuals if ctx else None,
                "save_snapshot": ctx.save_snapshot if ctx else None,
            }
        )

        return {
            "teams": pd.DataFrame(rows),
            "games_used": games_df.copy(),
            "pre_sos_state": {"legacy": age},
        }

    async def fake_save_ranking_snapshot(*_args, **_kwargs):
        save_calls["ranking"] += 1
        return None

    async def fake_save_prediction_feature_snapshot(*_args, **_kwargs):
        save_calls["prediction"] += 1
        return None

    rank_change_spy = AsyncMock()

    monkeypatch.setattr(calculator, "compute_rankings_with_ml", fake_compute_rankings_with_ml)
    monkeypatch.setattr(calculator, "save_ranking_snapshot", fake_save_ranking_snapshot)
    monkeypatch.setattr(calculator, "_save_prediction_feature_snapshot_safe", fake_save_prediction_feature_snapshot)
    monkeypatch.setattr(calculator, "calculate_rank_changes", rank_change_spy)

    games = pd.DataFrame(
        _make_game_pair("A", "B", 2, 1, "2026-03-01", age="14")
        + _make_game_pair("C", "D", 3, 2, "2026-03-02", age="15")
    )

    result = await calculator.compute_all_cohorts(
        supabase_client=_DummySupabase(),
        games_df=games,
        fetch_from_supabase=False,
        use_glicko=True,
        persist_game_residuals=False,
        calculate_rank_changes_enabled=False,
        save_snapshot=False,
    )

    assert not result["teams"].empty
    assert save_calls == {"ranking": 0, "prediction": 0}
    rank_change_spy.assert_not_called()
    assert len(calls) == 4
    assert all(call["persist_game_residuals"] is False for call in calls)
    assert all(call["save_snapshot"] is False for call in calls)
    assert "same_age_games" in result["teams"].columns
    assert "publication_cap_rank" in result["teams"].columns


@pytest.mark.asyncio
async def test_persist_game_explainability_shapes_batch_rpc_payload():
    supabase = _RecordingSupabase()
    explainability = pd.DataFrame(
        [
          {
              "id": "11111111-1111-1111-1111-111111111111",
              "game_id": "provider-game-1",
              "team_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
              "opp_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
              "game_date": pd.Timestamp("2026-04-01"),
              "gf": 3,
              "ga": 1,
              "team_mu": 1510.5,
              "team_sigma": 82.2,
              "opp_mu": 1544.1,
              "opp_sigma": 79.8,
              "expected_outcome": 0.41,
              "actual_outcome": 0.83,
              "outcome_surprise": 0.42,
              "g_factor": 0.94,
              "recency_weight": 1.18,
              "rating_contribution": 0.13,
              "off_residual": 1.2,
              "def_residual": 0.7,
          },
          {
              "id": None,
              "game_id": "provider-game-2",
              "team_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
              "opp_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
              "game_date": pd.Timestamp("2026-04-02"),
              "gf": 1,
              "ga": 2,
              "team_mu": 1510.5,
              "team_sigma": 82.2,
              "opp_mu": 1490.0,
              "opp_sigma": 75.0,
              "expected_outcome": 0.58,
              "actual_outcome": 0.24,
              "outcome_surprise": -0.34,
              "g_factor": 0.93,
              "recency_weight": 1.05,
              "rating_contribution": -0.08,
              "off_residual": -0.9,
              "def_residual": -0.6,
          },
        ]
    )

    updated, failed = await calculator._persist_game_explainability(supabase, explainability)

    assert updated == 1
    assert failed == 0
    assert len(supabase.calls) == 1

    rpc_name, payload = supabase.calls[0]
    assert rpc_name == "batch_upsert_game_explainability"
    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["game_uuid"] == "11111111-1111-1111-1111-111111111111"
    assert row["team_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert row["opp_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert row["game_date"] == "2026-04-01"
    assert row["gf"] == 3
    assert row["ga"] == 1
    assert row["rating_contribution"] == pytest.approx(0.13)


@pytest.mark.asyncio
async def test_persist_game_explainability_dedupes_team_game_primary_key():
    supabase = _RecordingSupabase()
    explainability = pd.DataFrame(
        [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "game_id": "provider-game-1",
                "team_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "opp_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "game_date": pd.Timestamp("2026-04-01"),
                "gf": 2,
                "ga": 1,
                "team_mu": 1510.5,
                "team_sigma": 82.2,
                "opp_mu": 1544.1,
                "opp_sigma": 79.8,
                "expected_outcome": 0.41,
                "actual_outcome": 0.83,
                "outcome_surprise": 0.42,
                "g_factor": 0.94,
                "recency_weight": 1.18,
                "rating_contribution": 0.11,
                "off_residual": 0.9,
                "def_residual": 0.6,
            },
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "game_id": "provider-game-1-revised",
                "team_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "opp_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "game_date": pd.Timestamp("2026-04-01"),
                "gf": 3,
                "ga": 1,
                "team_mu": 1512.0,
                "team_sigma": 81.0,
                "opp_mu": 1540.0,
                "opp_sigma": 80.0,
                "expected_outcome": 0.43,
                "actual_outcome": 0.85,
                "outcome_surprise": 0.42,
                "g_factor": 0.95,
                "recency_weight": 1.19,
                "rating_contribution": 0.14,
                "off_residual": 1.1,
                "def_residual": 0.5,
            },
        ]
    )

    updated, failed = await calculator._persist_game_explainability(supabase, explainability)

    assert updated == 1
    assert failed == 0
    assert len(supabase.calls) == 1
    rpc_name, payload = supabase.calls[0]
    assert rpc_name == "batch_upsert_game_explainability"
    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["game_id"] == "provider-game-1-revised"
    assert row["gf"] == 3
    assert row["team_mu"] == pytest.approx(1512.0)


@pytest.mark.asyncio
async def test_compute_all_cohorts_merges_game_explainability_and_threads_flag(monkeypatch):
    calls: list[dict] = []

    async def fake_compute_rankings_with_ml(
        supabase_client,
        games_df,
        today,
        v53_cfg=None,
        layer13_cfg=None,
        fetch_from_supabase=True,
        lookback_days=365,
        provider_filter=None,
        ctx=None,
    ):
        pass_label = ctx.pass_label if ctx else None
        age = str(games_df.iloc[0]["age"])
        team_id = "A" if age == "14" else "C"
        opp_id = "B" if age == "14" else "D"

        calls.append(
            {
                "pass_label": pass_label,
                "persist_game_explainability": ctx.persist_game_explainability if ctx else None,
            }
        )

        return {
            "teams": pd.DataFrame(
                [
                    {
                        "team_id": team_id,
                        "age": int(age),
                        "age_num": int(age),
                        "gender": "male",
                        "mu": 1500.0,
                        "sigma": 80.0,
                        "volatility": 0.06,
                        "sos": 0.5,
                        "sos_norm": 0.5,
                        "power_score_true": 0.5,
                        "power_score_final": 0.5,
                        "powerscore_adj": 0.5,
                        "powerscore_ml": 0.5,
                        "positive_ml_evidence_scale": 1.0,
                        "publication_cap_score": pd.NA,
                        "status": "Active",
                        "rank_in_cohort_final": 1,
                    }
                ]
            ),
            "games_used": games_df.copy(),
            "game_explainability": pd.DataFrame(
                [
                    {
                        "team_id": team_id,
                        "opp_id": opp_id,
                        "game_uuid": f"{age}-{pass_label}",
                        "rating_contribution": 0.1,
                    }
                ]
            ),
            "pre_sos_state": {"legacy": age},
        }

    async def fake_save_ranking_snapshot(*_args, **_kwargs):
        return None

    async def fake_save_prediction_feature_snapshot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(calculator, "compute_rankings_with_ml", fake_compute_rankings_with_ml)
    monkeypatch.setattr(calculator, "save_ranking_snapshot", fake_save_ranking_snapshot)
    monkeypatch.setattr(calculator, "_save_prediction_feature_snapshot_safe", fake_save_prediction_feature_snapshot)

    games = pd.DataFrame(
        _make_game_pair("A", "B", 2, 1, "2026-03-01", age="14")
        + _make_game_pair("C", "D", 3, 2, "2026-03-02", age="15")
    )

    result = await calculator.compute_all_cohorts(
        supabase_client=_DummySupabase(),
        games_df=games,
        fetch_from_supabase=False,
        use_glicko=True,
        persist_game_explainability=False,
        calculate_rank_changes_enabled=False,
        save_snapshot=False,
    )

    assert not result["game_explainability"].empty
    assert sorted(result["game_explainability"]["game_uuid"].tolist()) == ["14-Pass2", "15-Pass2"]
    assert len(calls) == 4
    assert all(call["persist_game_explainability"] is False for call in calls)
