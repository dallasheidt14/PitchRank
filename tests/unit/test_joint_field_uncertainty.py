"""Independent dense checks of the candidate's joint uncertainty semantics."""

import numpy as np
import pytest
from scipy.sparse import block_diag, coo_matrix, csc_matrix

from src.rankings.joint_field_solver import loss_gradient, solve

SCALE = 173.7178
PRECISION = 1 / ((350 / SCALE) ** 2 + .06 ** 2)


def star(opponents, weights=None):
    rows = np.arange(opponents)
    design = coo_matrix((np.r_[np.ones(opponents), -np.ones(opponents)],
                         (np.r_[rows, rows], np.r_[np.zeros(opponents, dtype=int), rows + 1])),
                        shape=(opponents, opponents + 1)).tocsc()
    return (np.zeros(opponents + 1), np.full(opponents + 1, PRECISION), design,
            np.zeros(opponents), np.ones(opponents) if weights is None else np.asarray(weights),
            np.full(opponents, .5))


def marginal_rd(hessian, index=0):
    # Small fixtures use a dense inverse independent of the large selected inverse.
    return SCALE * np.sqrt(np.linalg.inv(hessian.toarray())[index, index])


def test_independent_results_reduce_deviation_and_rematches_are_less_informative():
    _, four, _ = solve(*star(4))
    _, thirty, _ = solve(*star(30))
    # Existing repeat multipliers: 1, .8, .6, then .4 for all subsequent meetings.
    repeat_mass = 1 + .8 + .6 + 27 * .4
    _, rematches, _ = solve(*star(1, [repeat_mass]))
    assert marginal_rd(thirty) < marginal_rd(four) < 350
    assert marginal_rd(thirty) < marginal_rd(rematches)


def test_disconnected_results_do_not_change_existing_points_or_joint_curvature():
    prior, precision, design, offset, weights, outcome = star(4)
    outcome = np.array([.8, .2, .65, .5])
    before, before_hessian, _ = solve(prior, precision, design, offset, weights, outcome)
    extra = star(30)
    after, after_hessian, _ = solve(np.r_[prior, extra[0]], np.r_[precision, extra[1]],
        block_diag([design, extra[2]], format="csc"), np.r_[offset, extra[3]],
        np.r_[weights, extra[4]], np.r_[outcome, extra[5]])
    np.testing.assert_allclose(SCALE * before, SCALE * after[:len(before)], atol=.001, rtol=0)
    assert abs(marginal_rd(before_hessian) - marginal_rd(after_hessian)) < .001


def test_full_field_covariance_retains_unidentified_field_uncertainty():
    prior, precision, design, offset, weights, outcome = star(30)
    # All matches are within the same unanchored field, so its level cancels.
    with_field = csc_matrix(np.c_[design.toarray(), np.zeros(design.shape[0])])
    _, hessian, _ = solve(np.r_[prior, 0.], np.r_[precision, PRECISION],
                           with_field, offset, weights, outcome)
    inverse = np.linalg.inv(hessian.toarray())
    ability_variance = inverse[0, 0] + inverse[-1, -1] + 2 * inverse[0, -1]
    conditional_shortcut = 1 / hessian[0, 0]
    assert ability_variance > conditional_shortcut
    assert SCALE * np.sqrt(ability_variance) > 350
    assert inverse[-1, -1] == pytest.approx(1 / PRECISION)


def test_an_unstable_team_cannot_hide_in_a_cohort_average_and_reuse_adds_no_evidence():
    args = star(1000)
    start = args[0].copy()
    start[1] = .000001
    _, initial_gradient, _ = loss_gradient(start, *args)
    assert np.abs(initial_gradient).mean() < 1e-8 < np.abs(initial_gradient).max()
    mode, hessian, diagnostic = solve(*args, start=start)
    assert diagnostic["iterations"] > 1 and diagnostic["max_gradient"] < 1e-8
    reused, second_hessian, second_diagnostic = solve(*args, start=mode)
    np.testing.assert_array_equal(mode, reused)
    np.testing.assert_array_equal(hessian.toarray(), second_hessian.toarray())
    assert second_diagnostic["iterations"] == 1


@pytest.mark.parametrize("name,value", [("weight", float("nan")), ("outcome", float("inf")),
                                       ("precision", 0.), ("weight", -1.)])
def test_invalid_inputs_fail_visibly(name, value):
    prior, precision, design, offset, weights, outcome = star(4)
    {"weight": weights, "outcome": outcome, "precision": precision}[name][0] = value
    with pytest.raises(ValueError, match="Invalid hierarchical diagnostic inputs"):
        solve(prior, precision, design, offset, weights, outcome)
