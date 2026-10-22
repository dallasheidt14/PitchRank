"""Build the isolated joint-field likelihood from already selected game rows.

This module performs no fetching, persistence, publication or game selection.
The physical likelihood uses the union of endpoint selections. Shared field
priors change marginal team priors; they are not independent Glicko priors.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, csc_matrix
from threadpoolctl import threadpool_limits

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_recency_weights, compute_repeat_opponent_weights, get_anchor, resolve_as_of
from src.rankings import joint_field_solver
from src.rankings.constants import LEAGUE_MULTIPLIER_FEMALE, LEAGUE_MULTIPLIER_MALE, get_tier_multiplier


@dataclass(frozen=True)
class JointFieldProblem:
    as_of: pd.Timestamp
    configuration_json: str
    nodes: pd.DataFrame
    selected: pd.DataFrame
    physical: pd.DataFrame
    edges: pd.DataFrame
    prior: np.ndarray
    precision: np.ndarray
    design: csc_matrix
    offset: np.ndarray

    def fingerprint(self):
        """Bind numerical inputs, selected membership, metadata, settings and cutoff."""
        digest = hashlib.sha256()
        digest.update(b"joint-field-problem-v1\0")
        digest.update(Path(joint_field_solver.__file__).read_bytes())
        digest.update(b"solver-threads=1\0")
        digest.update(self.as_of.isoformat().encode())
        digest.update(self.configuration_json.encode())
        for frame in [self.nodes, self.selected, self.physical, self.edges]:
            digest.update(json.dumps([(str(c), str(frame[c].dtype)) for c in frame.columns]).encode())
            digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
        for array in [self.prior, self.precision, self.offset, self.design.data,
                      self.design.indices, self.design.indptr]:
            digest.update(str((array.dtype.str, array.shape)).encode())
            digest.update(array.tobytes())
        digest.update(str(self.design.shape).encode())
        return digest.hexdigest()

    def solve(self, start=None):
        """One prior and one physical likelihood, independent of numerical starts."""
        with threadpool_limits(limits=1):
            return joint_field_solver.solve(self.prior, self.precision, self.design, self.offset,
                                            self.edges.w.to_numpy(), self.edges.y.to_numpy(), start=start)

    def ratings(self, mode):
        """Return point estimates only; uncertainty requires full joint curvature."""
        mode = np.asarray(mode, dtype=float)
        if mode.shape != self.prior.shape or not np.isfinite(mode).all():
            raise ValueError("Invalid joint-field mode")
        config = json.loads(self.configuration_json)
        index = self.nodes.field_parameter_index.to_numpy(dtype=int)
        beta = np.zeros(len(index))
        keep = index >= 0
        beta[keep] = mode[index[keep]]
        return pd.Series(config["INITIAL_MU"] + 173.7178 * (mode[:len(index)] + beta), index=self.nodes.index)


def build_joint_field_problem(selected, teams, metadata, cfg, as_of):
    """Compile the evaluated equations without running the legacy conditional fit.

    ``selected`` must come from the existing per-team selection and goal-clipping
    path. This builder validates that contract's dimensions and preserves those
    rows; it does not substitute a different selection or silently drop records.
    """
    if not isinstance(cfg, GlickoConfig) or cfg.RATING_UPDATE_MODE != "fixed-prior-mode-v2":
        raise ValueError("Joint-field input requires the complete v2 evidence configuration")
    cfg.validate_solver()
    required = {"team_id", "opp_id", "id", "game_id", "date", "gf", "ga", "age", "gender", "opp_age", "opp_gender"}
    if not required.issubset(selected) or not {"team_id", "age_num", "gender"}.issubset(teams):
        raise ValueError("Missing joint-field input columns")
    if selected.empty or teams.team_id.isna().any() or teams.team_id.duplicated().any():
        raise ValueError("Empty or ambiguous joint-field inputs")
    if selected[list(required - {"game_id"})].isna().any().any():
        raise ValueError("Missing selected-game values")
    if selected.duplicated(["team_id", "id"]).any() or selected.team_id.eq(selected.opp_id).any():
        raise ValueError("Duplicate perspectives or self games")
    if not selected.team_id.isin(teams.team_id).all():
        raise ValueError("Selected source team is outside the modeled source teams")
    if not np.isfinite(selected[["gf", "ga"]].to_numpy(dtype=float)).all() or selected[["gf", "ga"]].lt(0).any().any():
        raise ValueError("Invalid selected scores")
    if selected.groupby("team_id").size().gt(cfg.MAX_GAMES).any():
        raise ValueError("Selected game count exceeds the existing maximum")
    at = resolve_as_of(as_of)
    e = selected[[c for c in selected.columns if c in required]].copy()
    e["date"] = pd.to_datetime(e.date, utc=True).dt.tz_localize(None)
    today = at.tz_localize(None)
    if e.date.gt(today).any() or e.date.lt(today - pd.Timedelta(days=cfg.WINDOW_DAYS)).any():
        raise ValueError("Selected dates are outside the effective window")
    e = e.sort_values(["team_id", "date", "game_id", "id", "opp_id"],
                      ascending=[True, False, True, True, True], kind="stable").reset_index(drop=True)
    e["source_weight"] = np.asarray(compute_recency_weights(e.date, today, cfg.RECENCY_LAMBDA, normalize=False))
    e["source_weight"] *= compute_repeat_opponent_weights(list(zip(e.team_id, e.opp_id)), cfg)
    e["source_outcome"] = (.5 + np.sign(e.gf-e.ga)*.5
                           * np.log1p(np.minimum(np.abs(e.gf-e.ga), cfg.MAX_GD))/np.log1p(cfg.MAX_GD))
    before = e.team_id.lt(e.opp_id)
    e["a"], e["b"] = e.team_id.where(before, e.opp_id), e.opp_id.where(before, e.team_id)
    e["weighted_canonical_outcome"] = e.source_weight * e.source_outcome.where(before, 1-e.source_outcome)
    physical = e.groupby(["a", "b", "id", "date"], sort=True, dropna=False).agg(
        joint_weight=("source_weight", "mean"), weighted_outcome=("weighted_canonical_outcome", "mean"),
        perspectives=("team_id", "size")).reset_index()
    physical["canonical_outcome"] = physical.weighted_outcome / physical.joint_weight
    if physical.perspectives.gt(2).any() or not np.isfinite(physical.canonical_outcome).all():
        raise ValueError("Invalid physical-game aggregation")
    ids = pd.Index(sorted(set(teams.team_id) | set(e.opp_id)), name="team_id")
    if not {"team_id_master", "state_code", "league", "is_deprecated"}.issubset(metadata):
        raise ValueError("Missing frozen team metadata")
    nodes = metadata.set_index("team_id_master", verify_integrity=True)[
        ["state_code", "league", "is_deprecated"]].reindex(ids).copy()
    attributes = pd.concat([
        e[["team_id", "age", "gender"]],
        e[["opp_id", "opp_age", "opp_gender"]].rename(columns={
            "opp_id": "team_id", "opp_age": "age", "opp_gender": "gender"}),
    ], ignore_index=True)
    attributes["age_num"] = pd.to_numeric(
        attributes.age.astype(str).str.replace(r"^[uU]", "", regex=True), errors="coerce").replace(18, 19)
    attributes["gender"] = attributes.gender.str.lower()
    if attributes.groupby("team_id")[["age_num", "gender"]].nunique(dropna=False).gt(1).any().any():
        raise ValueError("Conflicting endpoint cohorts")
    attributes = attributes.drop_duplicates("team_id").set_index("team_id")
    nodes["age_num"], nodes["gender"] = attributes.age_num.reindex(ids), attributes.gender.reindex(ids)
    source = teams.set_index("team_id")
    nodes.loc[source.index, "age_num"] = source.age_num
    nodes.loc[source.index, "gender"] = source.gender.str.lower()
    if not nodes.gender.isin(["male", "female"]).all():
        raise ValueError("Unknown endpoint gender")
    age = nodes.age_num.map(lambda n: "None" if pd.isna(n) else str(int(n)))
    nodes["anchor_offset"] = [cfg.ANCHOR_SCALE_FACTOR * get_anchor(a, g, cfg) for a, g in zip(age, nodes.gender)]
    nodes["tier"] = [get_tier_multiplier(None if pd.isna(league) else league, gender.title(),
                     None if pd.isna(age_value) else int(age_value))
                     for league, gender, age_value in zip(nodes.league, nodes.gender, nodes.age_num)]
    labels = []
    for row in nodes.itertuples():
        mapping = LEAGUE_MULTIPLIER_FEMALE if row.gender == "female" else LEAGUE_MULTIPLIER_MALE
        label = ("YOUNGER" if row.age_num < 13 else "REFERENCE" if row.league in mapping and row.tier == 1
                 else row.league if row.league in mapping else "UNAFFILIATED")
        labels.append(f"{row.gender}/{label}")
    labels = np.asarray(labels)
    names = sorted(label for label in set(labels) if not label.endswith("/REFERENCE"))
    lookup = {name: k + len(ids) for k, name in enumerate(names)}
    groups = np.array([lookup.get(label, -1) for label in labels])
    nodes["field_label"], nodes["field_parameter_index"] = labels, groups
    pairs = physical.groupby(["a", "b"], sort=True)[["joint_weight", "weighted_outcome"]].sum().reset_index()
    pairs["w"] = pairs.joint_weight
    pairs["y"] = pairs.weighted_outcome / pairs.w
    same = pairs.a.map(nodes.gender).eq(pairs.b.map(nodes.gender))
    edges = pd.concat([pairs[same & pairs.a.map(nodes.gender).eq(g)] for g in ["female", "male"]]
                      + [pairs[~same]], ignore_index=True)[["a", "b", "w", "y"]]
    i, j = ids.get_indexer(edges.a), ids.get_indexer(edges.b)
    rows = np.arange(len(i))
    row, col, values = [rows, rows], [i, j], [np.ones(len(i)), -np.ones(len(i))]
    for endpoint, sign in [(i, 1.), (j, -1.)]:
        keep = groups[endpoint] >= 0
        row.append(rows[keep])
        col.append(groups[endpoint][keep])
        values.append(np.full(keep.sum(), sign))
    design = coo_matrix((np.concatenate(values), (np.concatenate(row), np.concatenate(col))),
                        shape=(len(i), len(ids)+len(names))).tocsc()
    design.eliminate_zeros()
    field_priors = []
    for name in names:
        tiers = nodes.tier.to_numpy()[labels == name]
        if not np.all(tiers == tiers[0]):
            raise ValueError("Inconsistent field prior tiers")
        field_priors.append(cfg.INITIAL_MU*(tiers[0]-1)/173.7178)
    prior = np.r_[np.zeros(len(ids)), field_priors]
    precision = np.full(len(prior), 1/((cfg.INITIAL_SIGMA/173.7178)**2+cfg.INITIAL_VOLATILITY**2))
    offset = (nodes.anchor_offset.to_numpy()[i]-nodes.anchor_offset.to_numpy()[j])/173.7178
    selected_columns = ["team_id", "opp_id", "id", "game_id", "date", "gf", "ga", "age", "gender",
                        "opp_age", "opp_gender", "source_weight", "source_outcome"]
    return JointFieldProblem(at, json.dumps(asdict(cfg), sort_keys=True), nodes, e[selected_columns], physical,
                             edges, prior, precision, design, offset)
