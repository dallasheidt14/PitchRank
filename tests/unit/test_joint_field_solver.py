import numpy as np
import pytest
from scipy.optimize import minimize
from scipy.sparse import coo_matrix, csc_matrix

from src.rankings.joint_field_solver import loss_gradient, solve


def test_nonfinite_curvature_is_rejected_even_at_a_stationary_point():
    # A finite objective and zero gradient do not imply finite curvature.
    with np.errstate(over="ignore"):
        with pytest.raises(ValueError, match="Non-finite joint curvature"):
            solve(np.zeros(1), np.ones(1), csc_matrix([[4.]]),
                  np.zeros(1), np.array([1e308]), np.array([.5]))


def test_matches_dense_optimizer_and_derivatives():
    rng = np.random.default_rng(73)
    design = csc_matrix(rng.normal(size=(70, 14)))
    prior = rng.normal(size=14)
    precision = np.full(14, 0.246)
    offset = rng.normal(0, 0.1, 70)
    w = rng.uniform(0.2, 1, 70)
    y = rng.uniform(0, 1, 70)
    args = prior, precision, design, offset, w, y
    x, h, receipt = solve(*args)
    other = minimize(
        lambda z: loss_gradient(z, *args)[:2],
        prior,
        jac=True,
        method="BFGS",
        options={"gtol": 1e-10},
    )
    np.testing.assert_allclose(x, other.x, rtol=0, atol=1e-7)
    numerical = np.column_stack(
        [
            (
                loss_gradient(x + np.eye(14)[i] * 1e-5, *args)[1]
                - loss_gradient(x - np.eye(14)[i] * 1e-5, *args)[1]
            )
            / (2e-5)
            for i in range(14)
        ]
    )
    np.testing.assert_allclose(h.toarray(), numerical, rtol=1e-8, atol=1e-8)
    assert receipt["max_gradient"] < 1e-8


@pytest.mark.parametrize("draws", [4, 10, 30])
def test_within_field_draws_do_not_change_field_level(draws):
    n = draws + 1
    i, j = np.triu_indices(n, 1)
    r = np.arange(len(i))
    # The last parameter is this field's level. Same-field games cancel it.
    design = coo_matrix(
        (np.r_[np.ones(len(i)), -np.ones(len(i))], (np.r_[r, r], np.r_[i, j])),
        shape=(len(i), n + 1),
    ).tocsc()
    prior = np.r_[np.zeros(n), -0.26]
    x, _, _ = solve(
        prior,
        np.full(n + 1, 0.246),
        design,
        np.zeros(len(i)),
        np.ones(len(i)),
        np.full(len(i), 0.5),
    )
    np.testing.assert_array_equal(x, prior)


def test_cross_field_outcomes_identify_level_and_warm_start_matches():
    # Four teams from field A face four reference teams, each across all pairs.
    i = np.repeat(np.arange(4), 4)
    j = np.tile(np.arange(4, 8), 4)
    r = np.arange(len(i))
    design = coo_matrix(
        (
            np.r_[np.ones(len(i)), -np.ones(len(i)), np.ones(len(i))],
            (np.r_[r, r, r], np.r_[i, j, np.full(len(i), 8)]),
        ),
        shape=(len(i), 9),
    ).tocsc()
    prior = np.zeros(9)
    precision = np.full(9, 0.246)
    weak, _, _ = solve(
        prior,
        precision,
        design,
        np.zeros(len(i)),
        np.ones(len(i)),
        np.full(len(i), 0.2),
    )
    strong, _, _ = solve(
        prior,
        precision,
        design,
        np.zeros(len(i)),
        np.ones(len(i)),
        np.full(len(i), 0.8),
    )
    assert weak[-1] < 0 and strong[-1] > 0
    warm, _, _ = solve(
        prior,
        precision,
        design,
        np.zeros(len(i)),
        np.ones(len(i)),
        np.full(len(i), 0.8),
        start=np.ones(9) * 2,
    )
    np.testing.assert_allclose(strong, warm, atol=1e-7, rtol=0)
