"""Fit one offline joint snapshot for reuse by both ranking passes.

This module has no database client, fetch operation, publication operation or
writer. The caller supplies the existing selected records and frozen metadata.
"""

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csc_matrix

from src.etl import glicko_config, glicko_engine
from src.rankings import constants, joint_field_curvature, joint_field_problem, joint_field_solver


@dataclass(frozen=True)
class JointFieldSnapshot:
    as_of: pd.Timestamp
    state: pd.DataFrame
    selected_evidence: pd.DataFrame
    physical_evidence: pd.DataFrame
    mode: np.ndarray
    hessian: csc_matrix
    diagnostics: dict


def fit_joint_field_snapshot(selected, teams, metadata, cfg, as_of, *, start=None, progress=None):
    """Solve once, then retain full joint uncertainty and effective game weights.

    ``state`` is a separate model-state table, not a replacement published team
    table. A second engine pass reuses it without fitting its posterior again.
    Shared-field priors and the union of endpoint selections remain explicit.
    """
    started = datetime.now(timezone.utc).isoformat()
    clock = time.perf_counter()
    source_root = Path(__file__).resolve().parents[2]
    modules = [glicko_config, glicko_engine, constants, joint_field_problem,
               joint_field_solver, joint_field_curvature]
    paths = [Path(module.__file__).resolve() for module in modules] + [Path(__file__).resolve()]
    if any(source_root not in path.parents for path in paths):
        raise ValueError("Mixed ranking source roots")

    def fingerprints():
        return {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    before = fingerprints()
    problem = joint_field_problem.build_joint_field_problem(selected, teams, metadata, cfg, as_of)
    problem_fingerprint = problem.fingerprint()
    mode, hessian, solver = problem.solve(start=start)
    point_finished = datetime.now(timezone.utc).isoformat()
    if progress:
        progress(f"Joint point solve converged in {solver['iterations']} iterations")
    curvature = joint_field_curvature.compute_joint_curvature(
        hessian, problem.nodes.field_parameter_index.to_numpy(), progress=progress)
    state = problem.nodes.copy()
    state["mu"] = problem.ratings(mode)
    state["sigma"] = curvature.team_sigma
    state["volatility"] = cfg.INITIAL_VOLATILITY
    incident = problem.physical.groupby("a").size().add(problem.physical.groupby("b").size(), fill_value=0)
    state["incident_physical_games"] = incident.reindex(state.index, fill_value=0).astype(int)
    i, j = state.index.get_indexer(problem.edges.a), state.index.get_indexer(problem.edges.b)
    state["incident_evidence_weight"] = (
        np.bincount(i, weights=problem.edges.w.to_numpy(), minlength=len(state))
        + np.bincount(j, weights=problem.edges.w.to_numpy(), minlength=len(state)))
    if not np.isfinite(state[["mu", "sigma", "volatility", "incident_evidence_weight"]]).all().all():
        raise ValueError("Non-finite joint snapshot")
    evidence = problem.selected.copy()
    forward = evidence.team_id.lt(evidence.opp_id)
    evidence["a"] = evidence.team_id.where(forward, evidence.opp_id)
    evidence["b"] = evidence.opp_id.where(forward, evidence.team_id)
    evidence = evidence.merge(problem.physical[["a", "b", "id", "date", "joint_weight", "canonical_outcome"]],
                              on=["a", "b", "id", "date"], how="left", validate="many_to_one", sort=False)
    forward = evidence.team_id.lt(evidence.opp_id)
    evidence["joint_outcome"] = evidence.canonical_outcome.where(forward, 1-evidence.canonical_outcome)
    evidence = evidence.drop(columns=["a", "b", "canonical_outcome"])
    if not np.isfinite(evidence[["joint_weight", "joint_outcome"]]).all().all():
        raise ValueError("Missing effective joint evidence")
    if fingerprints() != before or problem.fingerprint() != problem_fingerprint:
        raise ValueError("Joint source or inputs changed during the snapshot solve")
    own = problem.selected.groupby("team_id").size().reindex(teams.team_id, fill_value=0)
    extra = state.incident_physical_games.reindex(teams.team_id).to_numpy() > own.to_numpy()
    diagnostics = dict(profile="joint-field-consistent-v1", as_of=problem.as_of.isoformat(),
        started_at=started, point_finished_at=point_finished, finished_at=datetime.now(timezone.utc).isoformat(),
        seconds=time.perf_counter()-clock, solver=solver, curvature=curvature.diagnostics,
        problem_fingerprint=problem_fingerprint, configuration_json=problem.configuration_json,
        source_sha256=before, modeled_nodes=len(state), source_teams=len(teams),
        selected_perspectives=len(evidence), physical_games=len(problem.physical),
        source_teams_with_extra_incident_games=int(extra.sum()),
        evidence_pool="physical games selected by either endpoint; own selected records remain separate",
        snapshot_reuse="same solved state for both passes; no posterior-as-prior update",
        interpretation="joint loss curvature and evidence diagnostics; not calibrated confidence")
    return JointFieldSnapshot(problem.as_of, state, evidence, problem.physical.copy(), mode, hessian, diagnostics)
