"""Offline v2 conditional-mode update with one fixed prior per snapshot.

This is a versioned model correction, not the standard one-step Glicko update.
For fixed opponents we solve the strictly concave weighted logistic posterior
with a Gaussian prior. RD is its local curvature approximation, not calibrated
confidence. The Glicko volatility update still evaluates the original prior.
"""
from __future__ import annotations

import numpy as np
from scipy.special import expit


class DampedAnderson:
    """Bounded-memory acceleration of guesses, never additional evidence.

    Every proposal is evaluated by the true fixed-prior map on the next outer
    iteration. A growing residual restarts from the preceding damped step.
    """

    def __init__(self, teams, damping):
        self.teams = teams
        self.damping = damping
        self.scale = np.array([173.7178, 173.7178, .06])
        self.history = []
        self.restarts = 0

    def propose(self, current, updated):
        x = (np.array([current[t] for t in self.teams]) / self.scale).ravel()
        f = (np.array([updated[t] for t in self.teams]) / self.scale).ravel() - x
        norm = np.linalg.norm(f)
        if self.history and norm > 1.2 * np.linalg.norm(self.history[-1][1]):
            previous_x, previous_f = self.history[-1]
            proposal = previous_x + self.damping * previous_f
            self.history.clear()
            self.restarts += 1
        else:
            self.history.append((x, f))
            self.history = self.history[-7:]
            proposal = x + self.damping * f
            if len(self.history) > 1:
                dx = np.column_stack([b[0] - a[0] for a, b in zip(self.history, self.history[1:])])
                df = np.column_stack([b[1] - a[1] for a, b in zip(self.history, self.history[1:])])
                coefficients = np.linalg.lstsq(df, f, rcond=1e-10)[0]
                accelerated = proposal - (dx + self.damping * df) @ coefficients
                # Limit extrapolation, and never propose an invalid RD/volatility.
                values = accelerated.reshape(-1, 3) * self.scale
                if (np.isfinite(values).all() and (values[:, 1:] > 0).all()
                        and np.linalg.norm(accelerated - x) <= 50 * max(norm, 1e-15)):
                    proposal = accelerated
        return {t: tuple(v) for t, v in zip(self.teams, proposal.reshape(-1, 3) * self.scale)}


class FixedPriorProblem:
    """Compile the selected-game graph once; evaluate all teams simultaneously."""

    SCALE = 173.7178
    INNER_LIMIT = 64
    INNER_TOLERANCE = 1e-12

    def solve(self, estimates, diagnostics):
        from src.etl.glicko_engine import RatingConvergenceError

        accelerator = DampedAnderson(self.teams, self.cfg.FIXED_PRIOR_DAMPING)
        tolerances = np.asarray(self.cfg.solver_tolerances)
        diagnostics.update(update_equation="fixed-gaussian-prior-conditional-logistic-mode-v2",
                           acceleration=f"anderson-depth6-damping{self.cfg.FIXED_PRIOR_DAMPING}",
                           effective_tolerances=tolerances.tolist())
        for iteration in range(self.cfg.FIXED_PRIOR_MAX_ITERATIONS):
            diagnostics["iterations"] = iteration + 1
            try:
                updated = self.update(estimates)
            except (ValueError, OverflowError, FloatingPointError) as error:
                raise RatingConvergenceError(str(error), diagnostics) from error
            values = np.array(list(updated.values()))
            if not np.isfinite(values).all() or (len(values) and (values[:, 1:] <= 0).any()):
                raise RatingConvergenceError("Non-finite or invalid fixed-prior update", diagnostics)
            residuals = np.array([np.abs(np.asarray(updated[t]) - estimates[t]) for t in self.teams])
            maxima = residuals.max(axis=0) if len(residuals) else np.zeros(3)
            diagnostics.update(
                max_rating_residual=float(maxima[0]), max_rd_residual=float(maxima[1]),
                max_volatility_residual=float(maxima[2]),
                max_inner_iterations=self.max_inner_iterations,
                acceleration_restarts=accelerator.restarts,
                converged=bool(np.all(maxima < tolerances)),
            )
            if diagnostics["converged"]:
                return estimates  # These estimates, not an unchecked next step, passed.
            estimates = accelerator.propose(estimates, updated)
        raise RatingConvergenceError(
            f"Fixed-prior solve did not converge in {self.cfg.FIXED_PRIOR_MAX_ITERATIONS} iterations", diagnostics,
        )

    def __init__(self, teams, arrays, cfg, cohort_age, cohort_gender, global_map, tier_mult):
        from src.etl.glicko_engine import _apply_tier_mult, scale_cross_age_rating

        self.teams = teams
        self.cfg = cfg
        self.prior = np.array([cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY])
        self.n = len(teams)
        lookup = {team: i for i, team in enumerate(teams)}
        sources, destinations, fixed, offsets, multipliers, weights, outcomes = [], [], [], [], [], [], []
        for team_index, team in enumerate(teams):
            arr = arrays[team]
            if arr is None:
                continue
            for i, opponent in enumerate(arr["opp_ids"]):
                cross = arr["cross_age_mask"] is not None and arr["cross_age_mask"][i]
                destination = lookup.get(opponent, self.n)
                fixed_mu = cfg.INITIAL_MU
                if cross and global_map is not None:
                    destination = self.n
                    fixed_mu = scale_cross_age_rating(
                        global_map.get(opponent, cfg.INITIAL_MU), str(arr["opp_ages"][i]),
                        str(arr["opp_genders"][i]), str(cohort_age), str(cohort_gender), cfg,
                    )
                multiplier = tier_mult(opponent)
                sources.append(team_index)
                destinations.append(destination)
                fixed.append(_apply_tier_mult(fixed_mu, multiplier, cfg))
                multipliers.append(multiplier)
                offsets.append(cfg.INITIAL_MU * (1 - multiplier) if cfg.TIER_MULT_CENTERED else 0.)
                weights.append(arr["weights"][i])
                outcomes.append(arr["outcomes"][i])
        self.src = np.array(sources, dtype=int)
        self.dst = np.array(destinations, dtype=int)
        self.fixed = np.array(fixed)
        self.mult = np.array(multipliers)
        self.offset = np.array(offsets)
        self.weights = np.array(weights)
        self.outcomes = np.array(outcomes)
        self.has_games = np.bincount(self.src, minlength=self.n) > 0
        self.max_inner_iterations = 0
        if not np.isfinite(self.fixed).all() or not np.isfinite(self.weights).all():
            raise ValueError("Non-finite fixed-prior game inputs")
        if (self.weights < 0).any() or not np.isfinite(self.outcomes).all():
            raise ValueError("Invalid fixed-prior evidence")

    def update(self, estimates):
        from src.etl.glicko_engine import _update_volatility

        if not self.n:
            return {}
        current = np.array([estimates[t] for t in self.teams], dtype=float)
        opponents = np.vstack([current, self.prior])[self.dst]
        opponent_mu = np.where(
            self.dst == self.n, self.fixed, opponents[:, 0] * self.mult + self.offset,
        )
        opponent_mu = (opponent_mu - self.cfg.INITIAL_MU) / self.SCALE
        g = 1 / np.sqrt(1 + 3 * (opponents[:, 1] / self.SCALE) ** 2 / np.pi**2)
        phi = self.cfg.INITIAL_SIGMA / self.SCALE

        def total(values):
            return np.bincount(self.src, weights=values, minlength=self.n)

        # Volatility is updated from the fixed prior, never last iteration's RD.
        expected_prior = expit(-g * opponent_mu)
        information = total(self.weights * g**2 * expected_prior * (1 - expected_prior))
        gradient_prior = total(self.weights * g * (self.outcomes - expected_prior))
        volatility = self.prior[2] * np.ones(self.n)
        for i in np.flatnonzero(information > 0):
            variance = 1 / information[i]
            volatility[i] = _update_volatility(
                self.prior[2], variance * gradient_prior[i], phi, variance, self.cfg.TAU,
            )
        precision = 1 / (phi**2 + volatility**2)
        # The likelihood gradient is bounded by sum(w*g), which brackets the
        # unique conditional mode on both sides of the prior mean (zero here).
        bound = total(self.weights * g) / precision
        lower, upper = -bound, bound
        mu = np.zeros(self.n)
        for iteration in range(self.INNER_LIMIT):
            expected = expit(g * (mu[self.src] - opponent_mu))
            gradient = total(self.weights * g * (self.outcomes - expected)) - precision * mu
            curvature = precision + total(self.weights * g**2 * expected * (1 - expected))
            step = gradient / curvature
            done = np.abs(step) < self.INNER_TOLERANCE
            if done.all():
                break
            lower = np.where(gradient > 0, mu, lower)
            upper = np.where(gradient <= 0, mu, upper)
            proposal = mu + step
            inside = (proposal > lower) & (proposal < upper)
            mu = np.where(done, mu, np.where(inside, proposal, (lower + upper) / 2))
        else:
            raise ValueError("Fixed-prior conditional mode did not converge")
        self.max_inner_iterations = max(self.max_inner_iterations, iteration + 1)
        result = np.column_stack([
            self.cfg.INITIAL_MU + self.SCALE * mu, self.SCALE / np.sqrt(curvature), volatility,
        ])
        result[~self.has_games] = self.prior
        return {team: tuple(value) for team, value in zip(self.teams, result)}
