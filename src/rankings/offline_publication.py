"""Shared publication-policy implementation and retained offline attribution profiles.

Support is a policy diagnostic, NOT a probability. Opponent evidence changes
publication authority and ceiling assignment; ratings and ML predictions stay put.
The band profile is attribution only. The continuous profile is the sole complete
policy candidate. The named reproducible-v2 profile selects the corrected v2 path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_recency_weights, compute_repeat_opponent_weights, game_outcome, resolve_as_of
from src.rankings.shared import sos_ml_blend


@dataclass(frozen=True)
class PublicationExperiment:
    profile: str = "support-continuous-v1"
    independent_prior_mass: float = 4.0
    connectivity_floor: float = 0.5

    def validate(self):
        if self.profile not in {"support-bands-v1", "support-continuous-v1", "support-continuous-v2"}:
            raise ValueError("Unknown offline publication profile")
        if (self.independent_prior_mass, self.connectivity_floor) != (4., .5):
            raise ValueError("Changed policy settings require a new candidate version")

    def manifest(self):
        self.validate()
        revised = self.profile == "support-continuous-v2"
        return {**asdict(self), "evidence_pool": (
                    "engine-selected same-gender games against same-age or older opponents"
                    if revised else "engine-selected same-board games only"),
                "opponent_quality": "powerscore_adj, continuous, missing=0",
                "outcome": "existing clipped logarithmic goal-margin outcome",
                "opponent_mass": "1-exp(-sum(raw rating weights))",
                "support": "connectivity * sum(opponent_mass * quality * mean_outcome) / (4 + total_mass)",
                "connectivity": ("0.5 + 0.5 * weighted_state_diversity * opponent_external_fraction; "
                                 "unknown state joins largest state; "
                                 "external means beyond the team's own opponent set"),
                "positive_ml_authority": "existing SOS gate times support; negative corrections unchanged",
                "raw_shrink": "legacy raw maximum * (1-support) * max(0,1-difficulty/legacy raw quality threshold)",
                "publication_penalty": ("(1-support)*(legacy field max*quality shortfall "
                                        "+ legacy freshness max*staleness "
                                        "+ legacy connectivity max*(1-connectivity)), capped at legacy 0.08"),
                "bands": [[.25, 2000], [.62, 400], [.84, 250], [1., None]],
                "continuous": "pre_cap - max(0, gross - gross/(1+(1-support)*gross) - existing_discount)",
                "gross": "min(1, pre_cap + provisional_loss + raw_shrink + publication_penalty)",
                "older_opponent_policy": (
                    "older results use the same outcome-weighted support and publication transformation; "
                    "opponent quality remains its own-cohort adjusted score; no added age bonus or legacy exemption"
                    if revised else "qualifying play-up rows retain original publication path exactly"),
                "interpretation": "heuristic support and sensitivity discount, not calibrated confidence"}


def _finite_unit(values, label):
    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all() or ((arr < 0) | (arr > 1)).any():
        raise ValueError(f"Invalid {label}: finite [0,1] values required")
    return arr


def continuous_score(pre_cap, support, existing_discount, cfg=PublicationExperiment()):
    """Downward only and monotone at fixed support/discount; no cohort-count input.

    Credit the existing measurable provisional/raw/publication discounts against
    this budget instead of charging the entire uncertainty concern again.
    """
    cfg.validate()
    b = _finite_unit(pre_cap, "pre-cap score")
    s = _finite_unit(support, "support")
    c = np.asarray(existing_discount, dtype=float)
    if not np.isfinite(c).all() or (c < 0).any():
        raise ValueError("Invalid existing discount")
    gross = np.minimum(1., b + c)
    budget = gross - gross / (1. + (1. - s) * gross)
    extra = np.maximum(0., budget - c)
    return np.maximum(0., b - extra)


def support_band(support):
    """Attribution-only assignment to existing bands, retaining their operator."""
    s = float(_finite_unit(support, "support"))
    if s < .25:
        return 2000
    if s < .62:
        return 400
    if s < .84:
        return 250
    return None


def evidence(selected, teams, as_of, rating_cfg, cfg=PublicationExperiment()):
    """Compute independent-opponent support from the actual selected, clipped rows.

    No new game selection, recency formula, result scoring or rank-based quality
    threshold. Missing opponents supply no quality support. V2 also includes
    older same-gender opponents, using their own-cohort quality without a new
    age bonus. The engine already accounts for age in its rating updates.
    """
    cfg.validate()
    if not isinstance(rating_cfg, GlickoConfig) or rating_cfg.RATING_UPDATE_MODE != "fixed-prior-mode-v2":
        raise ValueError("Publication candidates require the complete confidence v2 profile")
    if teams.team_id.duplicated().any() or teams.team_id.isna().any():
        raise ValueError("Ambiguous team identities")
    required = {"team_id", "opp_id", "date", "age", "gender", "opp_age", "opp_gender", "gf", "ga"}
    if not required.issubset(selected):
        raise ValueError("Missing selected-game columns")
    work = selected.copy()
    if work[["team_id", "opp_id", "date", "gf", "ga"]].isna().any().any():
        raise ValueError("Missing selected-game evidence")
    work["team_id"] = work.team_id.astype(str)
    work["opp_id"] = work.opp_id.astype(str)
    at = resolve_as_of(as_of)
    work["date"] = pd.to_datetime(work.date, utc=True)
    days = (at - work.date).dt.total_seconds() / 86400
    if not days.between(0, rating_cfg.WINDOW_DAYS).all():
        raise ValueError("Selected evidence outside as-of window")
    if work.groupby("team_id").size().gt(rating_cfg.MAX_GAMES).any():
        raise ValueError("Evidence is not the engine-selected game pool")
    # Stable recency ordering matches the engine's encounter order for discounts.
    sort = ["team_id", "date", *[c for c in ("game_id", "id", "opp_id") if c in work]]
    work = work.sort_values(sort, ascending=[True, False, *([True] * (len(sort) - 2))], kind="stable")
    known = teams.set_index(teams.team_id.astype(str), verify_integrity=True)
    quality = pd.to_numeric(known.powerscore_adj, errors="raise")
    _finite_unit(quality, "opponent power")
    state = (known.state_code.fillna("UNKNOWN").astype(str).str.upper()
             if "state_code" in known else pd.Series("UNKNOWN", index=known.index))
    same = ((work.age.astype(str).str.lower().str.lstrip("u")
             == work.opp_age.astype(str).str.lower().str.lstrip("u"))
            & (work.gender.str.lower() == work.opp_gender.str.lower()))
    work["same_board"] = same
    if not set(work.team_id).issubset(known.index):
        raise ValueError("Selected game refers to missing team")
    # Reuse the engine's weight functions, with a compound encounter identity so
    # one team's rematches do not discount another team's games.
    work["rating_weight"] = np.asarray(compute_recency_weights(
        work.date, at, rating_cfg.RECENCY_LAMBDA, normalize=False,
    )) * compute_repeat_opponent_weights(list(zip(work.team_id, work.opp_id)), rating_cfg)
    if cfg.profile == "support-continuous-v2":
        own_age = pd.to_numeric(work.age.astype(str).str.lower().str.lstrip("u"), errors="coerce")
        opp_age = pd.to_numeric(work.opp_age.astype(str).str.lower().str.lstrip("u"), errors="coerce")
        eligible = (work.gender.str.lower() == work.opp_gender.str.lower()) & opp_age.ge(own_age)
        sg = work[eligible].copy()
    else:
        sg = work[work.same_board].copy()
    sg["policy_outcome"] = [game_outcome(int(gf), int(ga), rating_cfg.MAX_GD) for gf, ga in zip(sg.gf, sg.ga)]
    sg["opponent_quality"] = sg.opp_id.map(quality).fillna(0.)
    sg["opponent_state"] = sg.opp_id.map(state).fillna("UNKNOWN").replace(
        {"": "UNKNOWN", "NONE": "UNKNOWN", "NAN": "UNKNOWN"})
    sg["weighted_outcome"] = sg.rating_weight * sg.policy_outcome
    opponents = sg.groupby(["team_id", "opp_id"], sort=True).agg(
        weight=("rating_weight", "sum"), result=("weighted_outcome", "sum"),
        quality=("opponent_quality", "first"), state=("opponent_state", "first"),
    )
    opponents["mass"] = -np.expm1(-opponents.weight)
    opponents["performance"] = opponents.result / opponents.weight
    opponents["supported"] = opponents.mass * opponents.quality * opponents.performance
    opponents["difficulty"] = opponents.mass * opponents.quality
    # A closed opponent group cannot manufacture national support merely by
    # containing clubs from several states. Observe opponents' other selected
    # connections, treating the selected graph as undirected. This remains a
    # coverage diagnostic, not a claim to identify every regional bubble.
    neighbors = {}
    for own, opp in zip(sg.team_id, sg.opp_id):
        neighbors.setdefault(own, set()).add(opp)
        neighbors.setdefault(opp, set()).add(own)
    qmap = quality.to_dict()
    neighbor_quality = {team: sum(qmap.get(opp, 0.) for opp in sorted(others)) for team, others in neighbors.items()}
    external = {}
    for team, group in opponents.groupby(level="team_id", sort=True):
        closed = neighbors.get(team, set()) | {team}
        weighted = denominator = 0.
        for (_, opp), difficulty_mass in group.difficulty.items():
            total_quality = neighbor_quality.get(opp, 0.)
            outside_quality = sum(qmap.get(other, 0.) for other in sorted(neighbors.get(opp, set()) - closed))
            fraction = outside_quality / total_quality if total_quality else 0.
            weighted += float(difficulty_mass) * fraction
            denominator += float(difficulty_mass)
        external[team] = weighted / denominator if denominator else 0.
    summary = pd.DataFrame(index=known.index)
    totals = opponents.groupby(level="team_id").sum(numeric_only=True)
    summary["policy_independent_mass"] = totals.mass
    summary["policy_difficulty"] = totals.difficulty / totals.mass
    summary["policy_performance_support"] = totals.supported / totals.mass
    summary["policy_selected_same_age_games"] = sg[sg.same_board].groupby("team_id").size()
    if cfg.profile == "support-continuous-v2":
        summary["policy_selected_older_games"] = sg[~sg.same_board].groupby("team_id").size()
        summary["policy_selected_evidence_games"] = sg.groupby("team_id").size()
    summary["policy_distinct_opponents"] = opponents.groupby(level="team_id").size()
    summary["policy_raw_rating_weight"] = totals.weight
    connectivity, coverage = {}, {}
    for team_id, states in opponents.reset_index().groupby(["team_id", "state"]).mass.sum().groupby(level="team_id"):
        masses = states.droplevel(0).to_dict()
        total = sum(masses.values())
        unknown = masses.pop("UNKNOWN", 0.)
        coverage[team_id] = (total - unknown) / total
        if masses:
            biggest = max(masses, key=masses.get)
            masses[biggest] += unknown
        else:
            masses["UNKNOWN"] = unknown
        diversity = max(0., 1. - sum((v / total)**2 for v in masses.values()))
        connectivity[team_id] = (cfg.connectivity_floor
                                 + (1. - cfg.connectivity_floor) * diversity * external[team_id])
    summary["policy_connectivity"] = pd.Series(connectivity, dtype=float)
    summary["policy_state_coverage"] = pd.Series(coverage, dtype=float)
    summary["policy_external_opponent_fraction"] = pd.Series(external, dtype=float)
    summary["policy_support"] = (summary.policy_connectivity * totals.supported
                                 / (cfg.independent_prior_mass + totals.mass))
    summary = summary.fillna(0.)
    _finite_unit(summary.policy_support, "computed support")
    packet = sg.drop(columns="weighted_outcome").merge(
        opponents[["mass", "performance", "supported"]].rename(columns={
            "mass": "opponent_independent_mass", "performance": "opponent_weighted_outcome",
            "supported": "opponent_support_contribution",
        }), left_on=["team_id", "opp_id"], right_index=True, validate="many_to_one",
    )
    # Per-opponent contribution is repeated for each meeting in this game packet;
    # it must not be summed as if each row were independent evidence.
    return summary, packet


def apply_publication_experiment(teams_age, pre_cap, legacy_scores, support, raw_shrink,
                                 publish_penalty, cfg, calculator):
    """One calculation path shared by the offline replay and orchestrator hook."""
    cfg.validate()
    aligned = support.reindex(teams_age.team_id.astype(str)).copy()
    aligned.index = teams_age.index
    if aligned.policy_support.isna().any():
        raise ValueError("Missing publication support")
    older = teams_age.apply(lambda row: calculator._has_play_up_support(
        calculator._safe_float(row.get("play_up_game_share")) or 0.,
        calculator._safe_int(row.get("play_up_top500_non_loss_opp_count")),
        calculator._safe_int(row.get("play_up_top1000_non_loss_opp_count")),
        calculator._safe_float(row.get("play_up_avg_opp_power_adj")),
        calculator._same_age_evidence_policy(calculator._safe_int(row.get("age_num"))),
    ), axis=1)
    preserve_older = older & (cfg.profile != "support-continuous-v2")
    # Replace the rank-category-driven same-age authority, raw shrink and
    # publication penalty together. Leaving one of them active would preserve
    # the very top-100/500 discontinuities the experiment is intended to test.
    # Constants below come from the existing policy; no fit to named team ranks.
    policy_rows = []
    for idx, row in teams_age.iterrows():
        s = float(aligned.loc[idx, "policy_support"])
        q = float(aligned.loc[idx, "policy_difficulty"])
        c = float(aligned.loc[idx, "policy_connectivity"])
        policy = calculator._same_age_evidence_policy(calculator._safe_int(row.get("age_num")))
        raw = float(policy["raw_shrink_max"]) * (1. - s) * max(
            0., 1. - q / float(policy["raw_shrink_max_avg_opp_power"]))
        penalty = min(.08, (1. - s) * (
            float(policy["publish_field_penalty_max"]) * max(0., 1. - q / float(policy["min_avg_opp_power"]))
            + float(policy["publish_freshness_penalty_max"]) * (1. - calculator._freshness_score(row, policy))
            + float(policy["publish_connectivity_penalty_max"]) * (1. - c)))
        adj = float(row.powerscore_adj)
        ml = calculator._safe_float(row.get("powerscore_ml"))
        sos = calculator._safe_float(row.get("sos_norm"))
        if ml is None or sos is None:
            blended = adj
        else:
            # SOS gating uses the existing shared implementation. Support
            # restricts only positive authority; no new performance bonus.
            sos_only = sos_ml_blend(adj, float(ml), float(sos))
            blended = adj + (sos_only - adj) * (s if sos_only > adj else 1.)
            if preserve_older.loc[idx]:
                blended = adj + (sos_only - adj) * (
                    float(row.positive_ml_evidence_scale) if sos_only > adj else 1.)
        policy_rows.append({"policy_ml_blended": blended, "policy_raw_shrink": raw,
                            "policy_publish_penalty": penalty,
                            "policy_pre_cap": max(0., blended - raw - penalty),
                            "policy_ml_authority": s})
    stages = pd.DataFrame(policy_rows, index=teams_age.index)
    policy_base = stages.policy_pre_cap.copy()
    policy_base.loc[preserve_older] = pre_cap.loc[preserve_older]
    stages.loc[preserve_older, "policy_ml_authority"] = teams_age.loc[preserve_older, "positive_ml_evidence_scale"]
    stages.loc[preserve_older, "policy_raw_shrink"] = raw_shrink.loc[preserve_older]
    stages.loc[preserve_older, "policy_publish_penalty"] = publish_penalty.loc[preserve_older]
    credit = ((teams_age.powerscore_core - teams_age.powerscore_adj).clip(lower=0.)
              + stages.policy_raw_shrink + stages.policy_publish_penalty)
    cap_rank = aligned.policy_support.map(support_band)
    applied_cap = cap_rank.copy() if cfg.profile == "support-bands-v1" else pd.Series(np.nan, index=teams_age.index)
    cap_score = pd.Series(np.nan, index=teams_age.index)
    if cfg.profile == "support-bands-v1":
        band_frame = teams_age.copy()
        band_frame["publication_experiment"] = cfg.profile
        band_frame["publication_cap_rank"] = cap_rank
        band_frame["publication_cap_score"] = calculator._compute_publication_cap_scores(band_frame, policy_base)
        cap_score = band_frame.publication_cap_score
        result = calculator._apply_publication_cap_band(policy_base, band_frame)
    else:
        result = pd.Series(continuous_score(policy_base, aligned.policy_support, credit, cfg), index=pre_cap.index)
    # Preserve the measured v1 profiles for attribution. V2 uses one score scale
    # for everyone; older results earn support rather than an exempt final score.
    result.loc[preserve_older] = legacy_scores.loc[preserve_older]
    applied_cap.loc[preserve_older] = teams_age.loc[preserve_older, "publication_cap_rank"]
    cap_score.loc[preserve_older] = teams_age.loc[preserve_older, "publication_cap_score"]
    if not np.isfinite(result).all() or (result > policy_base + 1e-14).any():
        raise ValueError("Invalid publication adjustment")
    aligned["team_id"] = teams_age.team_id
    aligned["policy_profile"] = cfg.profile
    aligned["policy_older_preserved"] = preserve_older
    if cfg.profile == "support-continuous-v2":
        aligned["policy_legacy_older_qualified"] = older
    for column in stages:
        aligned[column] = stages[column]
    aligned["policy_pre_cap"] = policy_base
    aligned["policy_legacy_pre_cap"] = pre_cap
    aligned["policy_legacy_final"] = legacy_scores
    aligned["policy_final"] = result
    aligned["policy_existing_discount_credit"] = credit
    aligned["policy_additional_discount"] = policy_base - result
    aligned["policy_attribution_cap_rank"] = cap_rank
    aligned["policy_applied_cap_rank"] = applied_cap
    aligned["policy_applied_cap_score"] = cap_score
    return result, aligned
