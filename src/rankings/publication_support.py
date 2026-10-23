"""Offline policy-only experiment: separate observed quality from own uncertainty."""
import numpy as np


def quality_only_support(checkpoint):
    """Return a separate evidence frame; never mutate the measured checkpoint.

    The original independent-opponent masses still define the weighted mean.
    This removes only its extra prior-mass dilution. The caller must separately
    retain own uncertainty, using the unchanged retained-provisional operator.
    """
    columns = ["policy_independent_mass", "policy_performance_support", "policy_connectivity"]
    if not set(columns).issubset(checkpoint):
        raise ValueError("Missing quality-support checkpoint columns")
    values = checkpoint[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (values[:, 1:] > 1).any():
        raise ValueError("Invalid quality-support checkpoint")
    result = checkpoint.copy(deep=True)
    result["policy_support"] = np.where(values[:, 0] > 0, values[:, 1] * values[:, 2], 0.)
    return result


def manifest():
    return dict(profile="joint-field-quality-support-v1",
        support="connectivity * sum(opponent_mass * quality * mean_outcome) / sum(opponent_mass); zero mass gives zero",
        removed_component="four-opponent prior-mass dilution in publication support only",
        own_uncertainty="retained; zero provisional-loss credit",
        upstream="sealed joint-field-consistent-v1 model and ML checkpoints",
        interpretation="heuristic publication support, not calibrated confidence")
