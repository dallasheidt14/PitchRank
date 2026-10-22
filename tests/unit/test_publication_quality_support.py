import numpy as np
import pandas as pd
import pytest
import asyncio

from src.rankings.publication_support import quality_only_support
from src.rankings import calculator
from src.rankings.offline_publication import PublicationExperiment, evidence, apply_publication_experiment
from tests.unit.test_publication_provisional_credit import resume, final, RATING

PROFILE = PublicationExperiment("support-quality-only-v1")


def frame(mass, performance, connectivity):
    return pd.DataFrame(dict(policy_independent_mass=mass,
        policy_performance_support=performance, policy_connectivity=connectivity,
        policy_support=np.zeros(len(mass))))


def test_fixed_observed_quality_does_not_get_a_second_count_discount():
    source = frame([1., 5., 20.], [.4]*3, [.5]*3)
    before = source.copy(deep=True)
    result = quality_only_support(source)
    np.testing.assert_array_equal(result.policy_support, [.2, .2, .2])
    pd.testing.assert_frame_equal(source, before, check_exact=True)


def test_weak_opponents_cannot_supply_high_support_by_count_alone():
    result = quality_only_support(frame([1., 20.], [.05, .05], [.5, .5]))
    np.testing.assert_array_equal(result.policy_support, [.025, .025])


def test_better_observed_performance_increases_support():
    result = quality_only_support(frame([5.]*3, [.1, .4, .8], [.5]*3))
    np.testing.assert_array_equal(result.policy_support, [.05, .2, .4])


def test_zero_evidence_has_zero_support():
    assert quality_only_support(frame([0.], [.8], [.5])).policy_support.iloc[0] == 0.


@pytest.mark.parametrize("column,value", [("policy_independent_mass", -1.),
    ("policy_performance_support", np.nan), ("policy_performance_support", 1.1),
    ("policy_connectivity", np.inf), ("policy_connectivity", -.1)])
def test_invalid_checkpoint_fails(column, value):
    source = frame([2.], [.4], [.5])
    source[column] = value
    with pytest.raises(ValueError, match="Invalid"):
        quality_only_support(source)


def test_missing_checkpoint_columns_fail():
    with pytest.raises(ValueError, match="Missing"):
        quality_only_support(pd.DataFrame())


def test_real_evidence_path_uses_quality_without_mass_dilution():
    games, teams, at = resume()
    support, packet = evidence(games, teams, at, RATING, PROFILE)
    assert support.loc["a", "policy_support"] == pytest.approx(.5 * .35 * (.5 + .5*np.log(4)/np.log(7)))
    assert support.loc["a", "policy_selected_older_games"] == 12
    assert len(packet) == 12
    old, old_packet = evidence(games, teams, at, RATING, PublicationExperiment("support-continuous-v2"))
    pd.testing.assert_frame_equal(packet, old_packet, check_exact=True)
    assert support.loc["a", "policy_support"] > old.loc["a", "policy_support"]
    pd.testing.assert_frame_equal(support.drop(columns="policy_support"), old.drop(columns="policy_support"), check_exact=True)


def test_new_profile_retains_own_uncertainty_and_zero_provisional_credit():
    higher, diagnostics = final(.72, PROFILE)
    lower, _ = final(.60, PROFILE)
    assert lower.iloc[0] < higher.iloc[0]
    assert diagnostics.policy_provisional_discount_credit.eq(0).all()
    assert not diagnostics.policy_older_preserved.any()
    assert PROFILE.manifest()["publication_prior_mass_applied"] is False


def test_publication_rejects_a_stale_mass_diluted_support_checkpoint():
    games, teams, at = resume()
    support, _ = evidence(games, teams, at, RATING, PublicationExperiment("support-continuous-v2"))
    row = teams[teams.team_id.eq("a")].copy()
    with pytest.raises(ValueError, match="stale support"):
        apply_publication_experiment(row, pd.Series([.65]), pd.Series([.4]), support,
            pd.Series([.02]), pd.Series([.03]), PROFILE, calculator)


@pytest.mark.parametrize("unsafe", ["fetch_from_supabase", "persist_game_residuals",
    "persist_game_explainability", "save_snapshot", "calculate_rank_changes_enabled"])
def test_quality_profile_cannot_fetch_or_persist(unsafe):
    class NoClient:
        def __getattr__(self, name):
            raise AssertionError("Client accessed before offline guard")
    args = dict(fetch_from_supabase=False, persist_game_residuals=False,
        persist_game_explainability=False, save_snapshot=False, calculate_rank_changes_enabled=False,
        publication_policy=PROFILE, glicko_cfg=RATING)
    args[unsafe] = True
    with pytest.raises(ValueError):
        asyncio.run(calculator.compute_all_cohorts(NoClient(), **args))


def test_production_default_is_unchanged():
    assert calculator._ranking_profile_configuration("reproducible-v2")[1].profile == "support-continuous-v2"
