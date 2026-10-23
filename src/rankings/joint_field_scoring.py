"""Reuse one joint snapshot consistently throughout the ranking pipeline.

The solver, derived opponent inputs and explanation weights share the same state.
No module patching, database access or implicit refit occurs in this bridge.
"""

import hashlib
import json
from dataclasses import asdict

import numpy as np
import pandas as pd
from scipy.special import expit

from src.etl import glicko_engine as engine
from src.rankings.joint_field_snapshot import fit_joint_field_snapshot


def _cohort_key(games):
    return str(games.age.iloc[0]), str(games.gender.iloc[0]).lower()


def _input_digest(games):
    return hashlib.sha256(pd.util.hash_pandas_object(games, index=True).values.tobytes()).hexdigest()


class EffectiveRatings(dict):
    """Iterate local recipients; resolve any actual selected opponent globally."""

    def __init__(self, local, state, offset):
        super().__init__(local)
        self.state = state
        self.offset = offset

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self.state.index

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        row = self.state.loc[key]
        return (row.mu+row.anchor_offset-self.offset, row.sigma, row.volatility)

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default


class JointFieldScoring:
    """Validated solved state plus unchanged per-team selected game records."""

    def __init__(self, snapshot, prepared, cfg):
        self.snapshot = snapshot
        self.state = snapshot.state
        self.evidence = snapshot.selected_evidence
        self.config = cfg
        self.engine = engine
        self.as_of = snapshot.as_of.tz_localize(None)
        self.prepared = prepared
        self.by_cohort = {_cohort_key(frame): frame for _, frame in
                          self.evidence.groupby(["age", "gender"], sort=False)}
        self.weights = self.evidence.set_index(["team_id", "id"], verify_integrity=True).joint_weight
        solver = snapshot.diagnostics["solver"]
        if (solver.get("converged") is not True or not 1 <= solver["iterations"] <= 50
                or not np.isfinite(solver["max_gradient"]) or not 0 <= solver["max_gradient"] < 1e-8):
            raise ValueError("Unconverged joint snapshot")
        if (not np.isfinite(self.state[["mu", "sigma", "volatility", "anchor_offset",
                                      "incident_evidence_weight", "incident_physical_games"]]).all().all()
                or not self.state[["sigma", "volatility"]].gt(0).all().all()):
            raise ValueError("Invalid joint snapshot state")

    def cohort(self, games, cfg, today, diagnostics):
        if (engine.resolve_as_of(today) != self.snapshot.as_of
                or json.dumps(asdict(cfg), sort_keys=True) != self.snapshot.diagnostics["configuration_json"]):
            raise ValueError("Joint snapshot date or configuration mismatch")
        key = _cohort_key(games)
        digest, selected = self.prepared[key]
        if _input_digest(games) != digest:
            raise ValueError("Joint snapshot source games changed")
        updated = self.state.reindex(list(selected))
        if updated[["mu", "sigma", "volatility"]].isna().any().any():
            raise ValueError("Joint snapshot does not cover recipients")
        ratings = dict(zip(updated.index, zip(updated.mu, updated.sigma, updated.volatility)))
        diagnostics.update(age=key[0], gender=key[1], profile="joint-field-consistent-v1",
            **self.snapshot.diagnostics["solver"], snapshot_reused=True,
            problem_fingerprint=self.snapshot.diagnostics["problem_fingerprint"],
            uncertainty="joint curvature with field covariance; not calibrated confidence")
        return engine.summarize_cohort_games(selected, ratings), selected

    def annotate_result(self, result, team_games):
        evidence = result["rating_evidence"]
        evidence["profile"] = "joint-field-consistent-v1"
        evidence["selected_rating_weight_sum"] = [
            float(self.rating_weights(team_games[t], self.as_of, self.config).sum()) for t in evidence.team_id]
        evidence["rating_weight_sum"] = evidence.team_id.map(self.state.incident_evidence_weight)
        evidence["incident_physical_games"] = evidence.team_id.map(self.state.incident_physical_games)
        evidence["evidence_pool"] = "physical games selected by either endpoint"
        evidence["distinct_opponents_scope"] = "own selected record list"
        if evidence[["rating_weight_sum", "incident_physical_games"]].isna().any().any():
            raise ValueError("Missing incident evidence diagnostics")
        return result

    def effective_map(self, ratings, games_df):
        age, gender = games_df.age.iloc[0], games_df.gender.iloc[0]
        offset = self.engine.get_anchor(str(age), str(gender), self.config) * self.config.ANCHOR_SCALE_FACTOR
        return EffectiveRatings(ratings, self.state, offset)

    def rating_weights(self, games, today, cfg):
        if self.engine.resolve_as_of(today).tz_localize(None) != self.as_of:
            raise ValueError("Joint evidence as-of mismatch")
        if games.empty:
            return np.array([], dtype=float)
        keys = pd.MultiIndex.from_frame(games[['team_id', 'id']])
        result = self.weights.reindex(keys).to_numpy()
        if not np.isfinite(result).all():
            raise ValueError('Selected perspective not in joint evidence')
        return result

    def explain(self, games_df, team_ratings, cfg, today, team_games=None, global_rating_map=None):
        del global_rating_map
        if self.engine.resolve_as_of(today).tz_localize(None) != self.as_of:
            raise ValueError("Joint evidence as-of mismatch")
        parts = [frame for frame in (team_games or {}).values() if not frame.empty]
        if not parts:
            return pd.DataFrame(columns=self.engine._EXPLAIN_COLUMNS)
        selected = pd.concat(parts, ignore_index=True)
        evidence = self.by_cohort[(str(games_df.age.iloc[0]), str(games_df.gender.iloc[0]).lower())]
        keys = ['team_id', 'opp_id', 'game_id', 'id', 'date', 'gf', 'ga']
        frame = selected[keys].merge(evidence[keys+['joint_weight', 'joint_outcome', 'source_outcome']],
                               on=keys, how='left', validate='one_to_one', sort=False)
        for name in ['joint_weight', 'joint_outcome', 'source_outcome']:
            if not np.isfinite(frame[name]).all():
                raise ValueError('Missing joint explanation evidence')
        frame['team_mu'] = frame.team_id.map(self.state.mu)
        frame['team_sigma'] = frame.team_id.map(self.state.sigma)
        frame['opp_mu'] = (frame.opp_id.map(self.state.mu)+frame.opp_id.map(self.state.anchor_offset)
                           - frame.team_id.map(self.state.anchor_offset))
        frame['opp_sigma'] = frame.opp_id.map(self.state.sigma)
        frame['expected_outcome'] = expit((frame.team_mu-frame.opp_mu)/173.7178)
        frame['actual_outcome'] = frame.joint_outcome
        frame['source_actual_outcome'] = frame.source_outcome
        frame['outcome_surprise'] = frame.actual_outcome-frame.expected_outcome
        frame['g_factor'] = 1.
        frame['recency_weight'] = frame.joint_weight
        frame['rating_contribution'] = frame.joint_weight*frame.outcome_surprise
        average = games_df.gf.mean() if len(games_df) else 0.
        expected_elo = 1/(1+np.power(10., (frame.opp_mu-frame.team_mu)/400.))
        frame['off_residual'] = frame.gf-average*expected_elo
        frame['def_residual'] = average*(1-expected_elo)-frame.ga
        frame = frame.rename(columns={'date': 'game_date'})
        return frame[self.engine._EXPLAIN_COLUMNS+['source_actual_outcome']]


def prepare_joint_scoring(cohorts, metadata, cfg, today, *, team_state_map=None, tier_league_map=None,
                          progress=None):
    """Select once using the existing path, then fit once for all cohort passes."""
    prepared, selected, sources = {}, [], []
    if cfg.BALANCED_SELECTION_ENABLED:
        raise ValueError("Joint profile requires the evaluated newest-game selection")
    for (age, gender), games in cohorts:
        if progress:
            progress(f"Preparing joint selected games: U{age} {gender}")
        _, team_games, _, _, _ = engine.prepare_cohort_games(
            games, cfg, today, tier_league_map=tier_league_map, cohort_gender=str(gender).capitalize(),
            team_state_map=team_state_map)
        prepared[_cohort_key(games)] = (_input_digest(games), team_games)
        selected.extend(frame for frame in team_games.values() if not frame.empty)
        sources.extend(dict(team_id=team, age_num=int(str(age).lower().lstrip("u")), gender=gender)
                       for team in team_games)
    snapshot = fit_joint_field_snapshot(pd.concat(selected, ignore_index=True), pd.DataFrame(sources),
                                       metadata, cfg, today, progress=progress)
    return JointFieldScoring(snapshot, prepared, cfg)
