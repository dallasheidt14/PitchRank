import numpy as np
import pytest
from scipy.sparse import csc_matrix, diags

from src.rankings import joint_field_curvature as curvature


def test_team_uncertainty_includes_field_variance_and_signed_covariance():
    hessian = csc_matrix([[2., -1., .3], [-1., 2., -.3], [.3, -.3, 1.]])
    dense = np.linalg.inv(hessian.toarray())
    result = curvature.compute_joint_curvature(hessian, np.array([-1, 2]))
    expected = 173.7178*np.sqrt([dense[0, 0], dense[1, 1] + dense[2, 2] + 2*dense[1, 2]])
    np.testing.assert_allclose(result.team_sigma, expected, rtol=1e-13, atol=1e-12)
    np.testing.assert_allclose(result.parameter_inverse_diagonal, np.diag(dense), rtol=1e-13, atol=1e-14)
    assert result.team_sigma[1] != pytest.approx(173.7178/np.sqrt(hessian[1, 1]))
    assert result.diagnostics["max_field_basis_residual"] < 1e-8


def test_selected_recursion_matches_dense_inverse_and_python_path(monkeypatch):
    rng = np.random.default_rng(73)
    design = rng.normal(size=(12, 9))
    matrix = csc_matrix(design.T@design + np.eye(9))
    first, _, _ = curvature._exact_inverse_diagonal(matrix)
    monkeypatch.setattr(curvature, "_kernel", curvature._selected_diagonal)
    second, _, _ = curvature._exact_inverse_diagonal(matrix)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_allclose(second, np.diag(np.linalg.inv(matrix.toarray())), rtol=1e-12, atol=1e-14)


@pytest.mark.parametrize("matrix", [np.array([[1., .3], [.4, 1.]]), np.array([[1., 2.], [2., 1.]]),
                                     np.array([[np.inf, 0.], [0., 1.]])])
def test_invalid_curvature_is_rejected(matrix):
    with pytest.raises(ValueError):
        curvature.compute_joint_curvature(matrix, np.array([-1, -1]))


@pytest.mark.parametrize("indices", [np.array([0, 2]), np.array([-2, 2]), np.array([-1, 3]),
                                      np.array([-1., 2.]), np.array([], dtype=int)])
def test_invalid_field_indices_are_rejected(indices):
    with pytest.raises(ValueError, match="field parameter indices"):
        curvature.compute_joint_curvature(diags([1., 1., 1.]), indices)


def test_large_inversion_without_acceleration_fails_visibly(monkeypatch):
    monkeypatch.setattr(curvature, "njit", None)
    with pytest.raises(RuntimeError, match="Numba"):
        curvature.compute_joint_curvature(diags(np.ones(2001)), np.full(2001, -1))
