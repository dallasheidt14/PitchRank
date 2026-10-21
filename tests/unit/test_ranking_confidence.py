"""Failure-oriented regressions for the offline fixed-prior experiment."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.etl import glicko_engine as engine
from src.etl.glicko_config import GlickoConfig
from src.rankings import calculator

AS_OF = pd.Timestamp("2026-10-12T00:00:00Z")


def games(n=10, *, a="A", b="B", gf=1, ga=1, independent=False):
    rows = []
    for i in range(n):
        opponent = f"{b}{i}" if independent else b
        for team, opp, goals, against in [(a, opponent, gf, ga), (opponent, a, ga, gf)]:
            rows.append(dict(team_id=team, opp_id=opp, gf=goals, ga=against,
                             date=pd.Timestamp("2026-10-01"), age="14", gender="male",
                             opp_age="14", opp_gender="male", game_id=f"{a}-{b}-{i}"))
    return pd.DataFrame(rows)


def candidate(**kw):
    return GlickoConfig(RATING_UPDATE_MODE="fixed-prior-v1", **kw)


def solve(frame, cfg=None, **kw):
    diagnostic = {}
    team, selected = engine.run_glicko2_cohort(
        frame, cfg or candidate(), AS_OF, solver_diagnostics=diagnostic, **kw)
    return team.set_index("team_id"), selected, diagnostic


def core(team):
    return team[["mu", "sigma", "volatility"]].sort_index()


def test_disconnected_group_cannot_manufacture_certainty():
    alone, _, _ = solve(games())
    expanded, _, _ = solve(pd.concat([games(), games(a="C", b="D", gf=6, ga=0)]))
    np.testing.assert_allclose(core(alone), core(expanded.loc[alone.index]), atol=.001, rtol=0)


def test_independent_evidence_volume_and_rematch_discount():
    four, _, _ = solve(games(4, independent=True))
    thirty, _, _ = solve(games(30, independent=True))
    rematches, _, _ = solve(games(30))
    assert thirty.loc["A", "sigma"] < four.loc["A", "sigma"]
    assert thirty.loc["A", "sigma"] < rematches.loc["A", "sigma"]
    weights = engine.compute_rating_weights(games(4).query("team_id == 'A'"), AS_OF, candidate())
    np.testing.assert_allclose(weights, np.exp(-11 / 365) * np.array([1, .8, .6, .4]), rtol=1e-14)


def test_priors_reset_on_every_iteration_and_on_second_pass(monkeypatch):
    priors = []
    original = engine.glicko2_update

    def record(mu, rd, vol, *args):
        priors.append((mu, rd, vol))
        return original(mu, rd, vol, *args)

    monkeypatch.setattr(engine, "glicko2_update", record)
    first, _, _ = solve(games(gf=3))
    warm = {team: tuple(row) for team, row in core(first).iterrows()}
    second, _, diagnostic = solve(games(gf=3), initial_ratings=warm)
    assert len(priors) > 2
    assert set(priors) == {(1500., 350., .06)}
    np.testing.assert_allclose(core(first), core(second), atol=.001, rtol=0)
    assert diagnostic["converged"]


@pytest.mark.xfail(strict=True, reason="v1 residual convergence does not guarantee 0.0001 cold/warm output agreement")
def test_warm_cold_outputs_agree_at_solver_precision():
    frame = games(gf=3)
    cold, _, _ = solve(frame)
    warm, _, _ = solve(frame, initial_ratings={"A": (2200., 40., .1), "B": (900., 90., .03)})
    for column, tolerance in (("mu", .0001), ("sigma", .0001), ("volatility", 1e-8)):
        np.testing.assert_allclose(core(cold)[column], core(warm)[column], atol=tolerance, rtol=0)


def test_additional_iterations_do_not_materially_change_solution():
    frame = games(gf=3)
    cold, _, _ = solve(frame)
    tighter, _, _ = solve(frame, candidate(FIXED_PRIOR_RATING_TOLERANCE=1e-7,
                                          FIXED_PRIOR_RD_TOLERANCE=1e-7,
                                          FIXED_PRIOR_VOLATILITY_TOLERANCE=1e-11))
    for column, tolerance in (("mu", .0001), ("sigma", .0001), ("volatility", 1e-8)):
        np.testing.assert_allclose(core(cold)[column], core(tighter)[column], atol=tolerance, rtol=0)


@pytest.mark.parametrize("component,delta", [(0, .00015), (1, .00015), (2, 1.5e-8)])
def test_undamped_maximum_not_mean_or_rating_only(monkeypatch, component, delta):
    # 1 moving team among 202: the mean rating residual would be below 0.0001.
    frame = pd.concat([games(1, gf=3), *[games(1, a=f"X{i}", b=f"Y{i}") for i in range(100)]])

    def unstable(mu, rd, vol, opponents, outcomes, weights, tau):
        result = [mu, rd, vol]
        if outcomes[0] > .5:
            result[component] += delta
        return tuple(result)

    monkeypatch.setattr(engine, "glicko2_update", unstable)
    with pytest.raises(engine.RatingConvergenceError) as error:
        solve(frame, candidate(FIXED_PRIOR_MAX_ITERATIONS=1))
    assert not error.value.diagnostics["converged"]
    assert error.value.diagnostics["iterations"] == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_update_fails(monkeypatch, bad):
    monkeypatch.setattr(engine, "glicko2_update", lambda *args: (bad, 100., .06))
    with pytest.raises(engine.RatingConvergenceError, match="Non-finite"):
        solve(games())


def test_nonfinite_start_fails():
    with pytest.raises(engine.RatingConvergenceError):
        solve(games(), initial_ratings={"A": (1500., float("nan"), .06)})


def test_engine_weights_explanations_and_selection_match():
    frame = games(35)
    outputs = [engine.compute_rankings_v2(frame, today=AS_OF, cfg=GlickoConfig(RATING_UPDATE_MODE=p))
               for p in ("legacy", "fixed-prior-normalized-v1", "fixed-prior-v1", "fixed-prior-mode-v2",
                         "fixed-prior-mode-normalized-v2")]
    for result in outputs:
        assert result["teams"]["games_played"].eq(30).all()
        pd.testing.assert_frame_equal(outputs[0]["games_used"], result["games_used"])
        evidence = result["rating_evidence"].set_index("team_id")
        observed = result["game_explainability"].groupby("team_id")["recency_weight"].sum()
        np.testing.assert_allclose(evidence.loc[observed.index, "rating_weight_sum"], observed)
        assert evidence["distinct_opponents"].eq(1).all()
    assert outputs[2]["rating_evidence"]["rating_weight_sum"].iloc[0] == pytest.approx(
        outputs[1]["rating_evidence"]["rating_weight_sum"].iloc[0] * 30 * np.exp(-11 / 365))


def test_utc_offset_is_converted_before_removing_timezone():
    offset = pd.Timestamp("2026-10-11T17:00:00-07:00")
    assert engine.resolve_as_of(offset) == AS_OF
    assert calculator._normalize_snapshot_date(offset).isoformat() == "2026-10-12"
    dates = pd.Series(pd.to_datetime(["2026-10-11T18:00:00-07:00"]))
    assert not engine._game_window_mask(dates, AS_OF, 365).iloc[0]
    np.testing.assert_allclose(engine.compute_recency_weights(dates, AS_OF, 1., normalize=False),
                               engine.compute_recency_weights(dates.dt.tz_convert("UTC"), AS_OF, 1., normalize=False))


@pytest.mark.parametrize("profile", ["legacy", "fixed-prior-v1", "fixed-prior-mode-v2"])
def test_wall_clock_does_not_affect_explicit_as_of(monkeypatch, profile):
    real_timestamp = pd.Timestamp

    class ClockTimestamp(real_timestamp):
        wall = "2026-10-14T23:59:59Z"

        @classmethod
        def now(cls, tz=None):
            return real_timestamp(cls.wall).tz_convert(tz) if tz else real_timestamp(cls.wall).tz_localize(None)

        @classmethod
        def utcnow(cls):
            return real_timestamp(cls.wall)

    frame = games()
    monkeypatch.setattr(pd, "Timestamp", ClockTimestamp)
    first = engine.compute_rankings_v2(frame, today=AS_OF, cfg=GlickoConfig(RATING_UPDATE_MODE=profile))
    ClockTimestamp.wall = "2026-10-15T00:00:01Z"
    second = engine.compute_rankings_v2(frame, today=AS_OF, cfg=GlickoConfig(RATING_UPDATE_MODE=profile))
    for key in first:
        pd.testing.assert_frame_equal(first[key], second[key])
    assert first["teams"]["last_calculated"].eq(AS_OF).all()


class NoDatabase:
    def __getattr__(self, key):
        raise AssertionError(f"Unexpected database access: {key}")


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["fixed-prior-v1", "fixed-prior-mode-v2"])
@pytest.mark.parametrize("flag", ["fetch_from_supabase", "save_snapshot", "persist_game_residuals",
                                "persist_game_explainability", "calculate_rank_changes_enabled"])
async def test_candidate_rejects_live_fetch_and_each_side_effect(flag, profile):
    kw = dict(fetch_from_supabase=False, save_snapshot=False, persist_game_residuals=False,
              persist_game_explainability=False, calculate_rank_changes_enabled=False)
    kw[flag] = True
    with pytest.raises(ValueError, match="frozen inputs"):
        await calculator.compute_all_cohorts(NoDatabase(), games_df=games(), today=AS_OF,
                                             glicko_cfg=GlickoConfig(RATING_UPDATE_MODE=profile), use_glicko=True, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["fixed-prior-v1", "fixed-prior-mode-v2"])
async def test_cache_hit_miss_and_incompatible_settings(monkeypatch, tmp_path, profile):
    monkeypatch.chdir(tmp_path)
    calls = []
    original = calculator.compute_rankings_v2

    def record(*args, **kw):
        calls.append(kw)
        return original(*args, **kw)

    # Keep ML outside this cache test; the engine's cached values must match exactly.
    async def ml(**kw):
        return kw["teams_df"].copy(), pd.DataFrame()

    monkeypatch.setattr(calculator, "compute_rankings_v2", record)
    monkeypatch.setattr(calculator, "apply_predictive_adjustment", ml)
    cfg = GlickoConfig(RATING_UPDATE_MODE=profile)
    ctx = calculator.RankingContext(use_glicko=True, glicko_cfg=cfg,
                                    persist_game_residuals=False, persist_game_explainability=False,
                                    save_snapshot=False)

    async def run(date=AS_OF, context=ctx):
        return await calculator.compute_rankings_with_ml(NoDatabase(), games_df=games(), today=date,
                                                        fetch_from_supabase=False, ctx=context)

    miss = await run()
    hit = await run()
    assert len(calls) == 1
    for key in ("teams", "games_used", "solver_diagnostics", "rating_evidence"):
        pd.testing.assert_frame_equal(miss[key].reset_index(drop=True), hit[key].reset_index(drop=True))
    await run(AS_OF + pd.Timedelta(hours=1))
    await run(context=replace(ctx, glicko_cfg=replace(cfg, FIXED_PRIOR_DAMPING=.4)))
    await run(context=replace(ctx, glicko_cfg=GlickoConfig(RATING_UPDATE_MODE="fixed-prior-normalized-v1")))
    assert len(calls) == 4
    if profile == "fixed-prior-mode-v2":
        for path in (tmp_path / "data/cache").glob("*_solver.parquet"):
            df = pd.read_parquet(path)
            df["max_rating_residual"] = 5e-6  # Meets v1's limit but violates v2's actual limit.
            df.to_parquet(path, index=False)
        await run()
        assert len(calls) == 5
    for path in (tmp_path / "data/cache").glob("*_solver.parquet"):
        df = pd.read_parquet(path)
        df["converged"] = False
        df.to_parquet(path, index=False)
    await run()
    assert len(calls) == (6 if profile == "fixed-prior-mode-v2" else 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["fixed-prior-v1", "fixed-prior-mode-v2"])
async def test_one_resolved_date_and_config_reach_both_passes(monkeypatch, tmp_path, profile):
    monkeypatch.chdir(tmp_path)
    seen = []
    cfg = GlickoConfig(RATING_UPDATE_MODE=profile)

    class Query:
        def select(self, *_):
            return self

        def in_(self, *_):
            return self

        def eq(self, *_):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    client = SimpleNamespace(table=lambda *_: Query())
    original = calculator.compute_rankings_with_ml

    async def record(*args, **kw):
        seen.append((kw["today"], kw["ctx"].glicko_cfg, kw["ctx"].pass_label))
        return await original(*args, **kw)

    monkeypatch.setattr(calculator, "compute_rankings_with_ml", record)
    result = await calculator.compute_all_cohorts(client, games_df=games(), today=AS_OF,
        fetch_from_supabase=False, use_glicko=True, glicko_cfg=cfg, persist_game_residuals=False,
        persist_game_explainability=False, calculate_rank_changes_enabled=False, save_snapshot=False)
    assert [(x[0], x[2]) for x in seen] == [(AS_OF.tz_localize(None), "Pass1"),
                                          (AS_OF.tz_localize(None), "Pass2")]
    assert all(x[1] is cfg for x in seen)
    assert len(result["solver_diagnostics"]) == 2
    assert result["teams"]["last_calculated"].eq(AS_OF).all()


@pytest.mark.asyncio
async def test_default_date_resolved_before_legacy_live_fetch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    clocks, fetched = [], []
    original = calculator.resolve_as_of

    def clock(value=None):
        if value is None:
            clocks.append(True)
            return AS_OF
        return original(value)

    async def fetch(**kw):
        fetched.append(kw["today"])
        return games()

    async def ml(**kw):
        return kw["teams_df"].copy(), pd.DataFrame()

    monkeypatch.setattr(calculator, "resolve_as_of", clock)
    monkeypatch.setattr(calculator, "fetch_games_for_rankings", fetch)
    monkeypatch.setattr(calculator, "apply_predictive_adjustment", ml)
    ctx = calculator.RankingContext(use_glicko=True, persist_game_residuals=False,
                                    persist_game_explainability=False, save_snapshot=False)
    result = await calculator.compute_rankings_with_ml(NoDatabase(), today=None, ctx=ctx)
    assert clocks == [True]
    assert fetched == [AS_OF.tz_localize(None)]
    assert result["teams"].last_calculated.eq(AS_OF).all()


def test_saved_ceiling_discontinuity_remains_a_diagnostic_fixture():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/ranking-confidence-ceiling.json").read_text())
    row = pd.Series(fixture["inputs"])
    assert calculator._publication_cap_rank(row) == 250
    row["play_up_top500_non_loss_opp_count"] = 1
    assert calculator._publication_cap_rank(row) == 1800


def test_older_opponent_core_sos_disagreement_is_preserved(monkeypatch):
    frame = games(1).query("team_id == 'A'").copy()
    frame["age"], frame["opp_age"] = "11", "12"
    observed = []
    original = engine.glicko2_update

    def capture(mu, rd, vol, opponents, *args):
        observed.append(opponents[0][0])
        return original(mu, rd, vol, opponents, *args)

    monkeypatch.setattr(engine, "glicko2_update", capture)
    team, selected, _ = solve(frame, global_rating_map={"B": 1800.})
    assert observed[0] > 1800.
    ratings = {"A": tuple(core(team).loc["A"])}
    sos = engine.compute_sos(frame, ratings, candidate(), AS_OF.tz_localize(None), team_games=selected)
    assert sos.iloc[0].sos_raw == 1500.
    low_rd = engine.compute_sos(frame, {**ratings, "B": (1800., 20., .06)}, candidate(), AS_OF)
    high_rd = engine.compute_sos(frame, {**ratings, "B": (1800., 350., .06)}, candidate(), AS_OF)
    pd.testing.assert_frame_equal(low_rd, high_rd)


@pytest.mark.parametrize("own,older,expected", [(16, 17, 1), (17, 19, 0)])
def test_older_evidence_age_gap_regression(own, older, expected):
    frame = games(1).query("team_id == 'A'").copy()
    frame["age"], frame["opp_age"] = str(own), str(older)
    teams = pd.DataFrame(dict(team_id=["A", "B"], age=[str(own), str(older)],
                              gender=["male", "male"], powerscore_adj=[.5, .7], status=["Active", "Active"]))
    evidence = calculator._compute_same_age_evidence_metrics(frame, teams).set_index("team_id")
    assert evidence.loc["A", "play_up_games"] == expected
