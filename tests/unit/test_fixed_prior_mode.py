"""Independent numerical checks for the offline v2 posterior approximation."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq
from scipy.special import expit

from src.etl.fixed_prior import FixedPriorProblem
from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import RatingConvergenceError, run_glicko2_cohort


def fixture(n=16):
    rng = np.random.default_rng(1)
    strengths = rng.normal(0, 1.7, n)
    rows = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            margin = int(np.clip(np.rint((strengths[i] - strengths[j]) * 2), -6, 6))
            rows.append(dict(team_id=str(i), opp_id=str(j), gf=max(margin, 0), ga=max(-margin, 0),
                             age="14", gender="female", opp_age="14", opp_gender="female",
                             date=pd.Timestamp("2026-10-01"), game_id=f"{min(i,j)}-{max(i,j)}"))
    return pd.DataFrame(rows)


def solve(frame, **kwargs):
    diagnostics = {}
    cfg = kwargs.pop("cfg", GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2"))
    result, games = run_glicko2_cohort(frame, cfg, pd.Timestamp("2026-10-12"),
                                      solver_diagnostics=diagnostics, **kwargs)
    return result.set_index("team_id")[["mu", "sigma", "volatility"]].sort_index(), games, diagnostics


def test_conditional_mode_matches_independent_scalar_root_and_curvature():
    cfg = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2")
    arr = {"A": dict(opp_ids=["B", "C", "D"], cross_age_mask=None,
                     weights=[1., .8, .4], outcomes=[1., .7, 0.])}
    problem = FixedPriorProblem(["A", "B", "C", "D"],
                                {**arr, "B": None, "C": None, "D": None},
                                cfg, "14", "female", None, lambda _: 1.)
    estimates = {"A": (2400., 40., .2), "B": (2100., 80., .06),
                 "C": (1600., 150., .06), "D": (900., 250., .06)}
    actual = problem.update(estimates)["A"]
    scale = 173.7178
    means = (np.array([2100., 1600., 900.]) - 1500) / scale
    attenuation = 1 / np.sqrt(1 + 3 * (np.array([80., 150., 250.]) / scale)**2 / np.pi**2)
    precision = 1 / ((350 / scale)**2 + actual[2]**2)
    def gradient(mu):
        return np.sum(np.array([1., .8, .4]) * attenuation *
                      (np.array([1., .7, 0.]) - expit(attenuation * (mu - means)))) - precision * mu
    root = brentq(gradient, -100., 100., xtol=1e-13)
    expected = expit(attenuation * (root - means))
    curvature = precision + np.sum(np.array([1., .8, .4]) * attenuation**2 * expected * (1-expected))
    assert actual[0] == pytest.approx(1500 + scale * root, abs=1e-8)
    assert actual[1] == pytest.approx(scale / np.sqrt(curvature), abs=1e-8)
    changed = {**estimates, "A": (800., 300., .01)}
    assert problem.update(changed)["A"] == actual  # Own posterior never replaces its prior.


def test_v2_cold_warm_and_row_order_agree():
    frame = fixture()
    cold, _, diag = solve(frame)
    warm = {str(i): (900. + i * 80, 40. + i * 10, .1) for i in range(16)}
    other, _, other_diag = solve(frame.sample(frac=1, random_state=17), initial_ratings=warm)
    assert diag["converged"] and other_diag["converged"]
    assert diag["iterations"] <= 200 and other_diag["iterations"] <= 200
    np.testing.assert_allclose(cold[["mu", "sigma"]], other[["mu", "sigma"]], atol=.0001, rtol=0)
    np.testing.assert_allclose(cold.volatility, other.volatility, atol=1e-8, rtol=0)
    resumed, _, _ = solve(frame, initial_ratings={t: tuple(r) for t, r in cold.iterrows()})
    np.testing.assert_allclose(cold, resumed, atol=.0001, rtol=0)


def test_disconnected_groups_do_not_move_existing_estimates():
    frame = fixture(8)
    extra = fixture(11).assign(team_id=lambda f: "X" + f.team_id, opp_id=lambda f: "X" + f.opp_id)
    alone, _, _ = solve(frame)
    both, _, _ = solve(pd.concat([frame, extra], ignore_index=True))
    np.testing.assert_allclose(alone, both.loc[alone.index], atol=.001, rtol=0)


def test_twenty_extra_undamped_updates_do_not_change_solution(monkeypatch):
    frame = fixture()
    converged, _, _ = solve(frame)
    original = FixedPriorProblem.solve

    def extra_updates(self, estimates, diagnostics):
        result = original(self, estimates, diagnostics)
        for _ in range(20):
            result = self.update(result)
        return result

    monkeypatch.setattr(FixedPriorProblem, "solve", extra_updates)
    extended, _, _ = solve(frame)
    np.testing.assert_allclose(converged[["mu", "sigma"]], extended[["mu", "sigma"]], atol=.0001, rtol=0)
    np.testing.assert_allclose(converged.volatility, extended.volatility, atol=1e-8, rtol=0)


def test_v2_fails_visibly_at_iteration_limit():
    cfg = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2", FIXED_PRIOR_MAX_ITERATIONS=1)
    with pytest.raises(RatingConvergenceError) as error:
        solve(fixture(), cfg=cfg)
    assert not error.value.diagnostics["converged"]


def test_v2_uses_raw_evidence_and_keeps_legacy_default():
    assert GlickoConfig().RATING_UPDATE_MODE == "legacy"
    assert not GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2").normalize_rating_weights
    assert replace(GlickoConfig(), RATING_UPDATE_MODE="fixed-prior-normalized-v1").normalize_rating_weights
    normalized = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-normalized-v2")
    assert normalized.conditional_mode and normalized.normalize_rating_weights
    normalized.validate_solver()
    result, _, diag = solve(fixture(), cfg=normalized)
    assert diag["converged"] and len(result) == 16
    assert diag["update_equation"] == "fixed-gaussian-prior-conditional-logistic-mode-v2"


def test_independent_information_exceeds_rematches():
    def star(count, independent):
        rows = []
        for i in range(count):
            opponent = f"B{i}" if independent else "B"
            for a, b in [("A", opponent), (opponent, "A")]:
                rows.append(dict(team_id=a, opp_id=b, gf=1, ga=1, age="14", gender="female",
                                 opp_age="14", opp_gender="female", date=pd.Timestamp("2026-10-01"),
                                 game_id=str(i)))
        return pd.DataFrame(rows)
    four, _, _ = solve(star(4, True))
    thirty, _, _ = solve(star(30, True))
    repeats, _, _ = solve(star(30, False))
    assert thirty.loc["A", "sigma"] < four.loc["A", "sigma"]
    assert thirty.loc["A", "sigma"] < repeats.loc["A", "sigma"]


@pytest.mark.parametrize("component,delta", [(0, .00015), (1, .00015), (2, 1.5e-8)])
def test_one_unstable_team_cannot_hide_in_average(monkeypatch, component, delta):
    def unstable(self, estimates):
        result = dict.fromkeys(self.teams, (1500., 350., .06))
        value = list(result[self.teams[0]])
        value[component] += delta
        result[self.teams[0]] = tuple(value)
        return result
    monkeypatch.setattr(FixedPriorProblem, "update", unstable)
    cfg = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2", FIXED_PRIOR_MAX_ITERATIONS=1)
    with pytest.raises(RatingConvergenceError):
        solve(fixture(), cfg=cfg)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_conditional_update_fails(monkeypatch, bad):
    def broken(self, estimates):
        return dict.fromkeys(self.teams, (bad, 350., .06))
    monkeypatch.setattr(FixedPriorProblem, "update", broken)
    with pytest.raises(RatingConvergenceError, match="Non-finite"):
        solve(fixture())


def test_v2_likelihood_equation_uses_fixed_cross_age_map_and_tiers():
    cfg = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2")
    arr = {"A": dict(opp_ids=["B"], opp_ages=["15"], opp_genders=["female"],
                     cross_age_mask=[True], weights=[1.], outcomes=[.7]), "B": None}
    problem = FixedPriorProblem(["A", "B"], arr, cfg, "14", "female", {"B": 1700.}, lambda _: .94)
    one = problem.update({"A": (1500., 350., .06), "B": (1000., 40., .1)})
    two = problem.update({"A": (2000., 50., .1), "B": (2300., 350., .06)})
    assert one == two  # Cross-age uses the supplied map with prior RD, not warm estimates.
    assert problem.mult[0] == .94
