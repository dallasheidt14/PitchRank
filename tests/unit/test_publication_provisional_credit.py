"""Keep provisional uncertainty out of the shared publication discount credit."""

import asyncio

import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.rankings import calculator
from src.rankings.offline_publication import (
    PublicationExperiment,
    apply_publication_experiment,
    continuous_score,
    evidence,
)

CANDIDATE = PublicationExperiment("support-retained-provisional-v1")
CURRENT = PublicationExperiment("support-continuous-v2")
RATING = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2")


def resume(adjusted=.72):
    at = pd.Timestamp("2026-10-12", tz="UTC")
    games = pd.DataFrame([dict(team_id="a", opp_id=f"o{i}", date=at-pd.Timedelta(days=i),
        id=str(i), game_id=str(i), age="11", opp_age="12", gender="Male", opp_gender="Male",
        gf=3, ga=0) for i in range(12)])
    teams = pd.DataFrame([dict(team_id=team, powerscore_core=.9,
        powerscore_adj=adjusted if team == "a" else .35, powerscore_ml=adjusted,
        sos_norm=.3, state_code="WA", age_num=11 if team == "a" else 12,
        age="11" if team == "a" else "12", gender="Male", status="Active",
        positive_ml_evidence_scale=.25, last_calculated=at, last_game=at,
        games_last_60_days=12, games_last_120_days=12, publication_cap_rank=2000,
        publication_cap_score=.4) for team in ["a", *sorted(set(games.opp_id))]])
    return games, teams, at


def final(adjusted, profile):
    games, teams, at = resume(adjusted)
    support, _ = evidence(games, teams, at, RATING, profile)
    row = teams[teams.team_id.eq("a")].copy()
    return apply_publication_experiment(row, pd.Series([.65]), pd.Series([.4]), support,
        pd.Series([.02]), pd.Series([.03]), profile, calculator)


def test_uncertainty_loss_is_not_cancelled_and_other_penalties_are_preserved():
    current, old = final(.72, CURRENT)
    candidate, new = final(.72, CANDIDATE)
    assert new.policy_provisional_discount_credit.eq(0).all()
    assert new.policy_retained_provisional_loss.iloc[0] == pytest.approx(.18)
    assert new.policy_raw_shrink.iloc[0] > 0 and new.policy_publish_penalty.iloc[0] > 0
    for column in ["policy_support", "policy_difficulty", "policy_connectivity", "policy_ml_blended",
                   "policy_raw_shrink", "policy_publish_penalty", "policy_pre_cap"]:
        pd.testing.assert_series_equal(old[column], new[column], check_exact=True)
    assert new.policy_existing_discount_credit.iloc[0] == pytest.approx(
        new.policy_raw_shrink.iloc[0] + new.policy_publish_penalty.iloc[0])
    assert old.policy_existing_discount_credit.iloc[0]-new.policy_existing_discount_credit.iloc[0] == pytest.approx(.18)
    assert candidate.iloc[0] < current.iloc[0]
    old_more_uncertain, _ = final(.60, CURRENT)
    new_more_uncertain, _ = final(.60, CANDIDATE)
    assert old_more_uncertain.iloc[0] == pytest.approx(current.iloc[0], abs=1e-14)
    assert new_more_uncertain.iloc[0] < candidate.iloc[0]-.02


def test_source_evidence_and_older_results_are_identical_to_current_profile():
    games, teams, at = resume()
    before = evidence(games, teams, at, RATING, CURRENT)
    after = evidence(games, teams, at, RATING, CANDIDATE)
    for left, right in zip(before, after):
        pd.testing.assert_frame_equal(left, right, check_exact=True)
    assert after[0].loc["a", "policy_selected_older_games"] == 12
    _, diag = final(.72, CANDIDATE)
    assert not diag.policy_older_preserved.any() and diag.policy_applied_cap_rank.isna().all()


def test_reducing_credit_cannot_raise_scores_or_create_zeroes():
    rng = np.random.default_rng(13)
    before = rng.uniform(1e-6, 1, 10000)
    support = rng.uniform(0, 1, len(before))
    raw_publication_credit = rng.uniform(0, .12, len(before))
    provisional_credit = rng.uniform(0, .8, len(before))
    old = continuous_score(before, support, raw_publication_credit+provisional_credit, CURRENT)
    new = continuous_score(before, support, raw_publication_credit, CANDIDATE)
    assert (new <= old+1e-15).all() and (new > 0).all()


@pytest.mark.parametrize("support", [0., .25, .62, .84, 1.])
def test_curve_is_continuous_and_strictly_increases_with_strength(support):
    strength = np.linspace(0, 1, 10001)
    score = continuous_score(strength, support, .04, CANDIDATE)
    assert (np.diff(score) > 0).all()
    assert np.diff(score).max() < .000101
    assert score[0] == 0 and score[-1] <= 1


@pytest.mark.parametrize("unsafe", ["fetch_from_supabase", "persist_game_residuals",
    "persist_game_explainability", "save_snapshot", "calculate_rank_changes_enabled"])
def test_each_live_option_is_rejected_before_client_access(unsafe):
    class NoClientAccess:
        def __getattr__(self, name):
            raise AssertionError("Offline rejection must precede client access")

    args = dict(fetch_from_supabase=False, persist_game_residuals=False,
        persist_game_explainability=False, save_snapshot=False, calculate_rank_changes_enabled=False,
        publication_policy=CANDIDATE, glicko_cfg=RATING)
    args[unsafe] = True
    with pytest.raises(ValueError):
        asyncio.run(calculator.compute_all_cohorts(NoClientAccess(), **args))


def test_production_profile_stays_current_and_candidate_requires_explicit_offline_selection():
    assert calculator._ranking_profile_configuration("reproducible-v2")[1].profile == "support-continuous-v2"
    with pytest.raises(ValueError):
        asyncio.run(calculator.compute_all_cohorts(None, ranking_profile="reproducible-v2",
            publication_policy=CANDIDATE))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -.01, 1.01])
def test_invalid_values_fail_visibly(bad):
    with pytest.raises(ValueError):
        continuous_score(bad, .2, .04, CANDIDATE)
