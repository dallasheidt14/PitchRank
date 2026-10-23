import asyncio
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.etl import glicko_engine as engine
from src.etl.glicko_config import GlickoConfig
from src.rankings import calculator, joint_field_scoring
from src.rankings.layer13_predictive_adjustment import Layer13Config


AS_OF = pd.Timestamp("2026-10-12", tz="UTC")
CFG = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2")


def pool(age=15, league="ECNL", opponents=4, offset=0):
    ids = [f"00000000-0000-4000-8000-{i+offset:012d}" for i in range(opponents+1)]
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            for team, opp in [(a, b), (b, a)]:
                rows.append(dict(team_id=team, opp_id=opp, id=f"{a}/{b}", game_id=f"{a}/{b}",
                    date=AS_OF.tz_localize(None), gf=1, ga=1, age=str(age), gender="Male",
                    opp_age=str(age), opp_gender="Male"))
    metadata = pd.DataFrame(dict(team_id_master=ids, state_code="WA", league=league, is_deprecated=False))
    return pd.DataFrame(rows), metadata


def fit(games, metadata):
    return joint_field_scoring.prepare_joint_scoring(list(games.groupby(["age", "gender"])),
        metadata, CFG, AS_OF, team_state_map=dict(zip(metadata.team_id_master, metadata.state_code)),
        tier_league_map=dict(zip(metadata.team_id_master, metadata.league)))


@pytest.mark.parametrize("age", [14, 15, 16, 17, 19])
@pytest.mark.parametrize("league,expected", [("MLS_NEXT_HD", 1500.), ("ECNL", 1470.), ("ECNL_RL", 1425.)])
def test_more_neutral_results_do_not_multiply_league_penalties(age, league, expected):
    four = fit(*pool(age, league, 4)).state
    thirty = fit(*pool(age, league, 30)).state
    np.testing.assert_allclose(four.mu, expected, atol=1e-9, rtol=0)
    np.testing.assert_allclose(thirty.mu, expected, atol=1e-9, rtol=0)
    assert thirty.sigma.max() < four.sigma.min()


def test_both_passes_reuse_snapshot_and_effective_explanation_weights(monkeypatch):
    games, metadata = pool()
    scoring = fit(games, metadata)
    monkeypatch.setattr(engine, "run_glicko2_cohort", lambda *a, **k: pytest.fail("Conditional refit"))
    before = scoring.state.copy(deep=True)
    first = engine.compute_rankings_v2(games, AS_OF, CFG, pass_label="Pass1", joint_scoring=scoring)
    second = engine.compute_rankings_v2(games, AS_OF, CFG, pass_label="Pass2", joint_scoring=scoring)
    pd.testing.assert_frame_equal(first["teams"], second["teams"], check_exact=True)
    pd.testing.assert_frame_equal(scoring.state, before, check_exact=True)
    explanations = second["game_explainability"].set_index(["team_id", "game_id"])
    expected = scoring.evidence.set_index(["team_id", "game_id"])
    np.testing.assert_allclose(explanations.recency_weight.sort_index(), expected.joint_weight.sort_index(), atol=0)
    assert second["solver_diagnostics"].snapshot_reused.all()
    assert second["teams"].mu.eq(1470.).all()
    # SOS must use 1470 directly, not apply the ECNL multiplier to it again.
    np.testing.assert_allclose(second["teams"].sos, 1470., atol=1e-9)


def test_snapshot_rejects_changed_inputs_and_settings():
    games, metadata = pool()
    scoring = fit(games, metadata)
    changed = games.copy()
    changed.loc[0, "gf"] = 2
    with pytest.raises(ValueError, match="source games changed"):
        engine.compute_rankings_v2(changed, AS_OF, CFG, joint_scoring=scoring)
    with pytest.raises(ValueError, match="date or configuration"):
        engine.compute_rankings_v2(games, AS_OF+pd.Timedelta(days=1), CFG, joint_scoring=scoring)
    with pytest.raises(ValueError, match="date or configuration"):
        engine.compute_rankings_v2(games, AS_OF, replace(CFG, MAX_GD=5), joint_scoring=scoring)


class ReadOnlyMetadata:
    def table(self, name):
        assert name == "teams"
        return self

    def select(self, columns):
        assert columns == "team_id_master"
        return self

    def in_(self, *args):
        return self

    def eq(self, *args):
        assert args == ("is_deprecated", True)
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def test_real_all_cohort_orchestration_fits_once_and_never_runs_conditional_solver(monkeypatch, tmp_path):
    a, ma = pool(15, "ECNL", 10)
    b, mb = pool(16, "MLS_NEXT_HD", 10, offset=100)
    games, metadata = pd.concat([a, b], ignore_index=True), pd.concat([ma, mb], ignore_index=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(calculator, "batch_fetch_rows", lambda *a, **k: metadata.to_dict("records"))
    monkeypatch.setattr(engine, "run_glicko2_cohort", lambda *a, **k: pytest.fail("Conditional refit"))
    original = joint_field_scoring.fit_joint_field_snapshot
    fits = []

    def counted(*a, **k):
        result = original(*a, **k)
        fits.append(result)
        return result

    monkeypatch.setattr(joint_field_scoring, "fit_joint_field_snapshot", counted)
    result = asyncio.run(calculator.compute_all_cohorts(ReadOnlyMetadata(), games, AS_OF,
        layer13_cfg=Layer13Config(enabled=False), fetch_from_supabase=False,
        persist_game_residuals=False, persist_game_explainability=False,
        calculate_rank_changes_enabled=False, save_snapshot=False,
        ranking_profile="joint-field-quality-support-v1"))
    assert len(fits) == 1
    assert len(result["teams"]) == 22
    assert result["teams"].status.eq("Active").all()
    assert len(result["solver_diagnostics"]) == 4
    assert result["solver_diagnostics"].snapshot_reused.all()
    assert result["joint_solver_diagnostics"]["solver"]["converged"]
    assert set(result["publication_diagnostics"].policy_profile) == {"support-quality-only-v1"}
    assert len(result["games_used"]) == len(games)
    assert not list(tmp_path.rglob("*.parquet"))


@pytest.mark.parametrize("failure", ["non-convergence", "non-finite"])
def test_failed_joint_fit_aborts_before_any_scoring_or_writes(monkeypatch, tmp_path, failure):
    games, metadata = pool()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(calculator, "batch_fetch_rows", lambda *a, **k: metadata.to_dict("records"))
    monkeypatch.setattr(calculator, "compute_rankings_with_ml", lambda *a, **k: pytest.fail("Scoring after failure"))

    def fail(*a, **k):
        raise ValueError(failure)

    monkeypatch.setattr(joint_field_scoring, "fit_joint_field_snapshot", fail)
    # Persistence is enabled intentionally. No query other than metadata may execute.
    with pytest.raises(ValueError, match=failure):
        asyncio.run(calculator.compute_all_cohorts(ReadOnlyMetadata(), games, AS_OF,
            fetch_from_supabase=False, ranking_profile="joint-field-quality-support-v1"))


def test_cross_age_opponent_uses_same_state_in_both_passes():
    a, ma = pool(15, "ECNL", 4)
    b, mb = pool(16, "MLS_NEXT_HD", 4, offset=100)
    younger, older = ma.team_id_master.iloc[0], mb.team_id_master.iloc[0]
    bridge = pd.DataFrame([
        dict(team_id=younger, opp_id=older, id="bridge", game_id="bridge", date=AS_OF.tz_localize(None),
             gf=2, ga=0, age="15", gender="Male", opp_age="16", opp_gender="Male"),
        dict(team_id=older, opp_id=younger, id="bridge", game_id="bridge", date=AS_OF.tz_localize(None),
             gf=0, ga=2, age="16", gender="Male", opp_age="15", opp_gender="Male"),
    ])
    games, metadata = pd.concat([a, b, bridge], ignore_index=True), pd.concat([ma, mb], ignore_index=True)
    scoring = fit(games, metadata)
    cohort = games[games.age.eq("15")]
    first = engine.compute_rankings_v2(cohort, AS_OF, CFG, pass_label="Pass1", joint_scoring=scoring)
    second = engine.compute_rankings_v2(cohort, AS_OF, CFG, pass_label="Pass2", joint_scoring=scoring)
    pd.testing.assert_frame_equal(first["teams"], second["teams"], check_exact=True)
    row = second["game_explainability"].query("game_id == 'bridge'").iloc[0]
    expected = scoring.state.loc[older, "mu"] + 10.8  # Male U16 .962 minus U15 .935, times 400.
    assert row.opp_mu == pytest.approx(expected)
    assert row.opp_sigma == scoring.state.loc[older, "sigma"]


def test_cli_accepts_joint_profile_and_keeps_reproducible_rollback():
    from scripts.calculate_rankings import _resolve_ranking_profile

    assert _resolve_ranking_profile("glicko", "joint-field-quality-support-v1") == "joint-field-quality-support-v1"
    assert _resolve_ranking_profile("glicko", "reproducible-v2") == "reproducible-v2"
    with pytest.raises(ValueError):
        _resolve_ranking_profile("v53e", "joint-field-quality-support-v1")


@pytest.mark.parametrize("valid", [False, True])
def test_actual_joint_cli_requires_solver_receipt_and_preserves_dry_run(monkeypatch, valid):
    import sys
    from scripts import calculate_rankings as command

    monkeypatch.setattr(sys, "argv", ["calculate_rankings.py", "--dry-run", "--ml",
                                    "--ranking-profile", "joint-field-quality-support-v1"])
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    monkeypatch.setattr(command, "create_client", lambda *_: object())
    monkeypatch.setattr(command, "MergeResolver", lambda *_: SimpleNamespace(
        load_merge_map=lambda: None, has_merges=False, version="fixture"))
    seen = []

    async def compute(**kwargs):
        seen.append(kwargs)
        assert kwargs["ranking_profile"] == "joint-field-quality-support-v1"
        assert kwargs["persist_game_residuals"] is False
        assert kwargs["persist_game_explainability"] is False
        assert kwargs["save_snapshot"] is False
        result = {"teams": pd.DataFrame()}
        if valid:
            result["joint_solver_diagnostics"] = {"solver": {"converged": True}}
        return result

    monkeypatch.setattr(command, "compute_all_cohorts", compute)
    monkeypatch.setattr(command, "save_rankings_to_supabase", lambda *a, **k: pytest.fail("Dry-run write"))
    if valid:
        asyncio.run(command.main())
    else:
        with pytest.raises(SystemExit) as error:
            asyncio.run(command.main())
        assert error.value.code == 1
    assert len(seen) == 1
