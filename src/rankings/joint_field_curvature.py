"""Exact joint loss curvature for offline rankings; not calibrated confidence.

The selected inverse recursion and verification settings are the evaluated
prototype's. Field variance and team-field covariance enter team uncertainty.
Numba optionally accelerates exactly the same deterministic recursion.
"""

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csc_matrix, diags
from scipy.sparse.linalg import splu
from threadpoolctl import threadpool_limits

try:
    from numba import njit
except ImportError:
    njit = None


def _selected_diagonal(indptr, indices, lower, diagonal):
    n = len(diagonal)
    values = np.zeros(len(lower))
    for j in range(n - 1, -1, -1):
        begin, end = indptr[j], indptr[j + 1]
        if indices[begin] != j:
            raise ValueError("Missing factor diagonal")
        degree = end - begin - 1
        totals = np.zeros(degree)
        for q in range(degree):
            i = indices[begin + 1 + q]
            pointer = indptr[i]
            for p in range(q, degree):
                k = indices[begin + 1 + p]
                while pointer < indptr[i + 1] and indices[pointer] < k:
                    pointer += 1
                if pointer >= indptr[i + 1] or indices[pointer] != k:
                    raise ValueError("Nonchordal factor pattern")
                value = values[pointer]
                totals[q] += lower[begin + 1 + p] * value
                if p != q:
                    totals[p] += lower[begin + 1 + q] * value
        total = 0.
        for q in range(degree):
            position = begin + 1 + q
            values[position] = -totals[q]
            total += lower[position] * values[position]
        values[begin] = 1 / diagonal[j] - total
    out = np.empty(n)
    for j in range(n):
        out[j] = values[indptr[j]]
    return out


_kernel = njit(cache=False)(_selected_diagonal) if njit is not None else _selected_diagonal


def _exact_inverse_diagonal(matrix, progress=None):
    matrix = csc_matrix(matrix)
    if matrix.shape[0] != matrix.shape[1] or not matrix.shape[0] or not np.isfinite(matrix.data).all():
        raise ValueError("Invalid joint curvature matrix")
    asymmetry = matrix - matrix.T
    if np.abs(asymmetry.data).max(initial=0) > 1e-12:
        raise ValueError("Asymmetric joint curvature matrix")
    if njit is None and matrix.shape[0] > 2000:
        raise RuntimeError("Large exact offline inversion requires the optional Numba accelerator")
    factor = splu(matrix, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0,
                  options={"SymmetricMode": True})
    if not np.array_equal(factor.perm_r, factor.perm_c):
        raise ValueError("Unexpected asymmetric factor permutation")
    lower = factor.L.tocsc()
    lower.sort_indices()
    diagonal = factor.U.diagonal()
    if not np.isfinite(diagonal).all() or (diagonal <= 0).any():
        raise ValueError("Joint curvature matrix is not positive definite")
    defect = factor.U - diags(diagonal) @ lower.T
    max_defect = float(np.abs(defect.data).max(initial=0))
    if max_defect > 1e-10 * max(1., float(np.abs(factor.U.data).max(initial=0))):
        raise ValueError("Unverified symmetric factorization")
    del defect
    work = int(np.square(np.diff(lower.indptr).astype(np.int64) - 1).sum())
    if progress:
        progress(f"factor: {lower.nnz} lower entries; selected work {work}; computing exact diagonal")
    selected = _kernel(lower.indptr, lower.indices, lower.data, diagonal)
    inverse = selected[factor.perm_c]
    if not np.isfinite(inverse).all() or (inverse <= 0).any():
        raise ValueError("Invalid selected inverse")
    checks = np.unique(np.linspace(0, len(inverse) - 1, min(64, len(inverse)), dtype=int))
    max_error = max_residual = 0.
    for index in checks:
        rhs = np.zeros(len(inverse))
        rhs[index] = 1.
        solution = factor.solve(rhs)
        residual = np.linalg.norm(matrix @ solution - rhs)
        error = abs(solution[index] - inverse[index]) / max(abs(solution[index]), 1e-15)
        max_residual, max_error = max(max_residual, residual), max(max_error, error)
    if max_residual > 1e-8 or max_error > 1e-8:
        raise ValueError(f"Selected inverse verification failed: residual {max_residual}, error {max_error}")
    return inverse, factor, {"method": "exact-grounded-LDL-selected-inverse",
                             "accelerator": "numba" if njit is not None else "python",
                             "parameters": len(inverse), "factor_lower_nonzeros": lower.nnz,
                             "selected_work": work, "basis_checks": len(checks),
                             "max_basis_residual": max_residual, "max_diagonal_relative_error": max_error,
                             "max_factor_defect": max_defect}


@dataclass(frozen=True)
class JointCurvature:
    team_sigma: np.ndarray
    parameter_inverse_diagonal: np.ndarray
    diagnostics: dict


def compute_joint_curvature(hessian, field_parameter_index, progress=None):
    """Compute Var(team residual + shared field), including their covariance."""
    hessian = csc_matrix(hessian)
    supplied = np.asarray(field_parameter_index)
    if (supplied.ndim != 1 or not len(supplied) or not np.issubdtype(supplied.dtype, np.integer)
            or hessian.shape[0] < len(supplied) or (supplied < -1).any()
            or (supplied >= hessian.shape[0]).any()
            or ((supplied >= 0) & (supplied < len(supplied))).any()):
        raise ValueError("Invalid team field parameter indices")
    groups = supplied.astype(int)
    count = len(groups)
    with threadpool_limits(limits=1):
        diagonal, factor, info = _exact_inverse_diagonal(hessian, progress)
        variance = diagonal[:count].copy()
        maximum_residual = 0.
        for index in sorted(set(groups) - {-1}):
            rhs = np.zeros(len(diagonal))
            rhs[index] = 1.
            covariance = factor.solve(rhs)
            residual = float(np.linalg.norm(hessian @ covariance-rhs))
            if not np.isfinite(covariance).all() or residual > 1e-8:
                raise ValueError("Unverified field covariance solve")
            maximum_residual = max(maximum_residual, residual)
            selected = groups == index
            variance[selected] += diagonal[index] + 2*covariance[:count][selected]
    if not np.isfinite(variance).all() or (variance <= 0).any():
        raise ValueError("Invalid full team curvature variance")
    return JointCurvature(173.7178*np.sqrt(variance), diagonal,
                          {**info, "max_field_basis_residual": maximum_residual,
                           "interpretation": "joint loss curvature; not calibrated confidence"})
