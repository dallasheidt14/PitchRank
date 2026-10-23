"""Fixed-prior joint-field solver for isolated offline ranking experiments.

Numerical settings are frozen for the joint-field-consistent-v1 candidate. Each
solve evaluates one prior and one selected physical-game likelihood. Field
effects enter the supplied design matrix and are learned from cross-field games.
The returned Hessian describes this custom loss, not calibrated confidence.
No production entry point selects this module.
"""

import numpy as np
from scipy.sparse import csc_matrix, diags
from scipy.sparse.linalg import LinearOperator, cg
from scipy.special import expit


def loss_gradient(x, prior, precision, design, offset, w, y):
    delta = design @ x + offset
    p = expit(delta)
    loss = float(
        np.sum(w * (np.logaddexp(0, delta) - y * delta))
        + 0.5 * np.sum(precision * (x - prior) ** 2)
    )
    gradient = precision * (x - prior) + design.T @ (w * (p - y))
    return loss, np.asarray(gradient), p


def solve(prior, precision, design, offset, w, y, start=None):
    prior, precision, offset, w, y = [
        np.asarray(v, dtype=float) for v in [prior, precision, offset, w, y]
    ]
    design = csc_matrix(design)
    if (
        design.shape != (len(y), len(prior))
        or len(precision) != len(prior)
        or len(offset) != len(w)
        or len(w) != len(y)
        or not all(
            np.isfinite(v).all() for v in [prior, precision, offset, w, y, design.data]
        )
        or (precision <= 0).any()
        or (w <= 0).any()
        or ((y < 0) | (y > 1)).any()
    ):
        raise ValueError("Invalid hierarchical diagnostic inputs")
    x = prior.copy() if start is None else np.asarray(start, dtype=float).copy()
    if x.shape != prior.shape or not np.isfinite(x).all():
        raise ValueError("Invalid initial estimates")
    trace = []
    for iteration in range(50):
        loss, gradient, p = loss_gradient(x, prior, precision, design, offset, w, y)
        residual = float(np.abs(gradient).max(initial=0))
        if not np.isfinite(loss) or not np.isfinite(gradient).all():
            raise ValueError("Non-finite hierarchy solve")
        trace.append(
            dict(iteration=iteration + 1, objective=loss, max_gradient=residual)
        )
        curvature = w * p * (1 - p)
        hessian = diags(precision) + design.T @ diags(curvature) @ design
        if not np.isfinite(hessian.data).all():
            raise ValueError("Non-finite joint curvature")
        if residual < 1e-8:
            return (
                x,
                csc_matrix(hessian),
                dict(
                    converged=True,
                    iterations=iteration + 1,
                    max_gradient=residual,
                    trace=trace,
                ),
            )
        diagonal = hessian.diagonal()
        preconditioner = LinearOperator(
            hessian.shape, matvec=lambda v: v / diagonal, dtype=float
        )
        step, code = cg(
            hessian, -gradient, M=preconditioner, rtol=1e-10, atol=1e-12, maxiter=2000
        )
        error = float(np.linalg.norm(hessian @ step + gradient))
        if (
            code
            or not np.isfinite(step).all()
            or error > max(1.001e-12, 1e-8 * np.linalg.norm(gradient))
        ):
            raise ValueError(f"Invalid hierarchy Newton step {code} {error}")
        directional = float(gradient @ step)
        if directional >= 0:
            raise ValueError("Non-descending hierarchy direction")
        length = 1.0
        for _ in range(30):
            proposal = x + length * step
            trial, trial_gradient, _ = loss_gradient(
                proposal, prior, precision, design, offset, w, y
            )
            roundoff = 8 * np.finfo(float).eps * max(1.0, abs(loss))
            unresolved = (
                -length * directional < roundoff
                and trial <= loss + roundoff
                and np.abs(trial_gradient).max(initial=0) < 0.5 * residual
            )
            if trial <= loss + 1e-4 * length * directional or unresolved:
                x = proposal
                break
            length /= 2
        else:
            raise ValueError("Hierarchy line search failed")
    error = ValueError("Hierarchy did not converge")
    error.diagnostics = dict(converged=False, trace=trace)
    raise error
