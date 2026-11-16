import json
from copy import deepcopy

import numpy as np
import pytest

from src.predictions.score_challenger import build_score_batch, candidate_definition, score_candidate


def baseline():
    return {
        "winProbabilityA": 0.6, "drawProbability": 0.2, "winProbabilityB": 0.2,
        "predictedWinner": "team_a", "expectedScore": {"teamA": 3, "teamB": 1},
        "expectedGoals": {"teamA": 3.2, "teamB": 1.2}, "expectedMargin": 2.0,
        "blowout4PlusProbability": 0.3, "modelSignature": "collecting-signature",
        "internal": {"history": [1, 2]},
    }


def batch():
    return {"rows": [{
        "id": "baseline-1", "source_game_id": "source-1", "game_date": "2026-11-15",
        "group": "event-1", "eligibility": "eligible", "learned_rates": [1.5, 0.9],
        "variants": {"baseline": baseline()},
    }]}


def fit():
    return {"receipt": {"cutoff": "2026-11-14", "latest_training_game": "2026-11-12", "optimizer_success": True}}


@pytest.mark.parametrize("candidate", ["baseline", "blend_25", "tail_guard_full"])
def test_candidate_preserves_outcomes_and_does_not_mutate_inputs(candidate):
    base = baseline()
    frozen = deepcopy(base)
    result = score_candidate(base, [1.5, 0.9], candidate=candidate)
    np.testing.assert_allclose(result.matrix.sum(), 1, atol=1e-12, rtol=0)
    margin = np.arange(41)[:, None] - np.arange(41)[None, :]
    for mask, key in [(margin > 0, "winProbabilityA"), (margin == 0, "drawProbability"),
                      (margin < 0, "winProbabilityB")]:
        assert result.matrix[mask].sum() == pytest.approx(base[key], abs=1e-12)
        assert result.prediction[key] == base[key]
    assert result.prediction["predictedWinner"] == "team_a"
    assert result.prediction["expectedScore"]["teamA"] > result.prediction["expectedScore"]["teamB"]
    assert np.isfinite(result.matrix).all() and (result.matrix >= 0).all()
    assert base == frozen
    if candidate != "baseline":
        assert "modelSignature" not in result.prediction


def test_blend_uses_exactly_one_quarter_challenger_mass():
    base = baseline()
    original = score_candidate(base, candidate="baseline").matrix
    from scipy.stats import poisson
    axis = np.arange(41)
    donor = np.outer(poisson.pmf(axis, 1.5), poisson.pmf(axis, 0.9))
    margin = axis[:, None] - axis[None, :]
    for mask, target in [(margin > 0, .6), (margin == 0, .2), (margin < 0, .2)]:
        donor[mask] *= target / donor[mask].sum()
    result = score_candidate(base, [1.5, 0.9])
    np.testing.assert_allclose(result.matrix, .75 * original + .25 * donor, rtol=0, atol=1e-14)


@pytest.mark.parametrize("a,d,b,risk,winner", [
    (1., 0., 0., 1., "team_a"), (0., 0., 1., 1., "team_b"), (0., 1., 0., 0., "draw"),
    (.9, .05, .05, .94, "team_a"), (.05, .05, .9, .94, "team_b"),
    (.4, .2, .4, 0., "team_a"), (.4, .2, .4, .8, "team_b"),
])
def test_tail_guard_handles_extreme_feasible_masses(a, d, b, risk, winner):
    base = baseline() | {"winProbabilityA": a, "drawProbability": d, "winProbabilityB": b,
                         "blowout4PlusProbability": risk, "predictedWinner": winner}
    result = score_candidate(base, [1.5, 0.9], candidate="tail_guard_full")
    assert result.prediction["blowout4PlusProbability"] == pytest.approx(risk, abs=1e-12)
    margin = np.arange(41)[:, None] - np.arange(41)[None, :]
    for mask, target in [(margin > 0, a), (margin == 0, d), (margin < 0, b)]:
        assert result.matrix[mask].sum() == pytest.approx(target, abs=1e-12)


@pytest.mark.parametrize("candidate", ["blend_25", "tail_guard_full"])
def test_swapping_teams_reverses_scores_and_margin(candidate):
    base = baseline()
    reverse = base | {"winProbabilityA": .2, "winProbabilityB": .6, "predictedWinner": "team_b",
                      "expectedGoals": {"teamA": 1.2, "teamB": 3.2}}
    first = score_candidate(base, [1.5, .9], candidate=candidate)
    second = score_candidate(reverse, [.9, 1.5], candidate=candidate)
    np.testing.assert_allclose(first.matrix.T, second.matrix, rtol=0, atol=1e-14)
    assert first.prediction["expectedScore"] == {
        "teamA": second.prediction["expectedScore"]["teamB"],
        "teamB": second.prediction["expectedScore"]["teamA"],
    }
    assert first.prediction["expectedMargin"] == pytest.approx(-second.prediction["expectedMargin"])


@pytest.mark.parametrize("eligibility,rates,status", [
    ("cross_cohort", [1.5, .9], "cross_cohort"), ("unseen_team", None, "unseen_team"),
    ("eligible", None, "missing_learned_rates"),
])
def test_unavailable_challenger_is_an_explicit_unchanged_fallback(eligibility, rates, status):
    base = baseline()
    result = score_candidate(base, rates, eligibility=eligibility)
    assert result.status == status
    assert result.prediction == base
    result.prediction["internal"]["history"].append(3)
    assert base["internal"]["history"] == [1, 2]


@pytest.mark.parametrize("rates", [[0, 1], [-1, 1], [float("nan"), 1], [float("inf"), 1], [1], [100, 1]])
def test_invalid_goal_rates_are_rejected(rates):
    with pytest.raises(ValueError):
        score_candidate(baseline(), rates)


@pytest.mark.parametrize("changes", [
    {"winProbabilityA": True}, {"drawProbability": float("nan")}, {"winProbabilityB": .3},
    {"predictedWinner": "unknown"}, {"blowout4PlusProbability": None},
    {"expectedScore": {"teamA": True, "teamB": 0}},
])
def test_invalid_baseline_is_not_hidden_by_a_fallback(changes):
    with pytest.raises(ValueError):
        score_candidate(baseline() | changes, eligibility="unseen_team")


def test_risk_protection_refuses_incompatible_baseline():
    with pytest.raises(ValueError, match="total win"):
        score_candidate(baseline() | {"blowout4PlusProbability": .9}, [1.5, .9], candidate="tail_guard_full")


def test_batch_retains_exact_fixture_identity_and_reports_fallbacks():
    data = batch()
    data["rows"].append(data["rows"][0] | {"id": "baseline-2", "source_game_id": "source-2",
                                             "eligibility": "cross_cohort"})
    saved = deepcopy(data)
    result = build_score_batch(data, fit())
    assert result["coverage"] == {"applied": 1, "cross_cohort": 1}
    assert result["rows"][0]["source_game_id"] == "source-1"
    assert result["rows"][0]["group"] == "event-1"
    assert result["production_promotion"] is False
    assert result["formal_confirmation_registered"] is False
    assert data == saved
    assert build_score_batch(data, fit()) == result


@pytest.mark.parametrize("key", ["id", "source_game_id"])
def test_duplicate_forecasts_and_source_fixtures_are_rejected(key):
    data = batch()
    second = data["rows"][0] | {"id": "baseline-2", "source_game_id": "source-2"}
    second[key] = data["rows"][0][key]
    data["rows"].append(second)
    with pytest.raises(ValueError, match="unique"):
        build_score_batch(data, fit())


@pytest.mark.parametrize("cutoff,latest", [("2026-11-16", "2026-11-12"),
                                          ("2026-11-15", "2026-11-15"),
                                          ("2026-11-14", "2026-11-14")])
def test_later_training_cannot_be_used_for_an_earlier_match(cutoff, latest):
    model = fit()
    model["receipt"].update(cutoff=cutoff, latest_training_game=latest)
    with pytest.raises(ValueError):
        build_score_batch(batch(), model)


def test_unknown_candidates_and_empty_batches_are_rejected():
    with pytest.raises(ValueError):
        candidate_definition("live")
    with pytest.raises(ValueError, match="nonempty"):
        build_score_batch({"rows": []}, fit())


def test_definition_disables_live_and_keeps_candidates_distinct():
    assert candidate_definition("blend_25")["challenger_weight"] == .25
    assert candidate_definition("tail_guard_full")["preserve_four_goal_risk"] is True
    assert candidate_definition("blend_25")["live_enabled"] is False
    assert json.dumps(candidate_definition("blend_25")) != json.dumps(candidate_definition("tail_guard_full"))
