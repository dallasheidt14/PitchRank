"""Synthetic development cases; no desired real-team rank is a target."""
import asyncio

import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_rating_weights
from src.rankings import calculator
from src.rankings.offline_publication import (
    PublicationExperiment, apply_publication_experiment, continuous_score, evidence, support_band,
)

AS_OF = pd.Timestamp("2026-10-12", tz="UTC")
CFG = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2")


def fixture(n=12, rematch=False, quality=.6, gf=3, ga=0, states=4):
    games = pd.DataFrame([dict(team_id="a", opp_id=f"o{0 if rematch else i}",
                               date=AS_OF - pd.Timedelta(days=i), game_id=str(i), id=str(i),
                               age="11", opp_age="11", gender="Male", opp_gender="Male", gf=gf, ga=ga)
                              for i in range(n)])
    ids = ["a", *sorted(set(games.opp_id))]
    teams = pd.DataFrame([dict(team_id=t, powerscore_adj=.8 if t == "a" else quality,
                               powerscore_core=.9, state_code=f"S{i % states}",
                               age_num=11, age="11", gender="Male", status="Active",
                               publication_cap_rank=2000, publication_cap_score=.4,
                               positive_ml_evidence_scale=.25, powerscore_ml=.82, sos_norm=.6)
                              for i, t in enumerate(ids)])
    return games, teams


def support(games, teams):
    return evidence(games, teams, AS_OF, CFG)[0].loc["a", "policy_support"]


def outside_connections(g, t):
    extra, rows = [], []
    for opp in sorted(set(g.opp_id)):
        for i in range(3):
            other = f"outside-{opp}-{i}"
            extra.append(dict(team_id=opp, opp_id=other, date=AS_OF, game_id=other, id=other,
                              age="11", opp_age="11", gender="Male", opp_gender="Male", gf=1, ga=1))
            row = t.iloc[0].to_dict()
            row.update(team_id=other, powerscore_adj=.9)
            rows.append(row)
    return pd.concat([g, pd.DataFrame(extra)], ignore_index=True), pd.concat([t, pd.DataFrame(rows)], ignore_index=True)


def test_opponent_exposure_is_not_result_support():
    strong_losses = fixture(quality=.95, gf=0, ga=6)
    good_wins = fixture(quality=.6, gf=3, ga=0)
    assert support(*strong_losses) == 0
    assert support(*good_wins) > support(*strong_losses)
    # An excellent opponent can still make a competitive loss informative.
    close_loss = fixture(quality=.95, gf=0, ga=1)
    weak_win = fixture(quality=.1, gf=1, ga=0)
    assert support(*close_loss) > support(*weak_win)


def test_unbeaten_weak_schedule_never_gets_full_support():
    g, t = fixture(n=30, quality=.2, gf=6)
    s = support(g, t)
    assert 0 < s < .2
    assert continuous_score(.95, s, .03) < .60


def test_rematches_are_discounted_and_do_not_become_independent():
    g, t = fixture(n=30, rematch=True, gf=6)
    summary, packet = evidence(g, t, AS_OF, CFG)
    np.testing.assert_array_equal(packet.rating_weight, compute_rating_weights(g, AS_OF, CFG))
    assert summary.loc["a", "policy_independent_mass"] < 1
    assert support(*fixture(n=4, gf=6, states=1)) > support(g, t)


def test_independent_evidence_increases_support_and_locality_remains_penalized():
    assert support(*fixture(n=30)) > support(*fixture(n=4))
    local = support(*fixture(n=30, states=1, gf=6, quality=1.))
    broad = support(*outside_connections(*fixture(n=30, states=4, gf=6, quality=1.)))
    assert local < .5 < broad


def test_missing_metadata_cannot_earn_connectivity_relief():
    g, t = outside_connections(*fixture())
    before = support(g, t)
    t.loc[t.team_id.str.startswith("o"), "state_code"] = None
    assert support(g, t) < before


def test_multistate_closed_group_cannot_claim_external_support():
    g, t = fixture(n=20, states=4, gf=6, quality=1.)
    summary, _ = evidence(g, t, AS_OF, CFG)
    assert summary.loc["a", "policy_external_opponent_fraction"] == 0
    assert summary.loc["a", "policy_connectivity"] == .5
    assert summary.loc["a", "policy_support"] < .5


def test_continuous_quality_and_no_top100_or_top500_category_input():
    g, t = fixture()
    original = support(g, t)
    t["rank_in_cohort_final"] = range(len(t))
    assert support(g, t) == original
    t.loc[t.team_id == "o0", "powerscore_adj"] += 1e-8
    assert 0 < support(g, t) - original < 1e-8


def test_game_and_team_row_order_is_exactly_repeatable():
    g, t = fixture(n=30, rematch=True)
    first, packet = evidence(g, t, AS_OF, CFG)
    second, other = evidence(g.sample(frac=1, random_state=7), t.sample(frac=1, random_state=8), AS_OF, CFG)
    pd.testing.assert_frame_equal(first.sort_index(), second.sort_index(), check_exact=True)
    pd.testing.assert_frame_equal(packet.reset_index(drop=True), other.reset_index(drop=True), check_exact=True)


def test_older_results_do_not_enter_new_same_age_metric():
    g, t = fixture()
    g.loc[0, "opp_age"] = "12"
    first = support(g, t)
    g.loc[0, ["gf", "ga"]] = [0, 10]
    assert support(g, t) == first


def test_disconnected_group_does_not_change_support():
    g, t = fixture()
    a, b = fixture()
    for col in ("team_id", "opp_id"):
        a[col] = "other-" + a[col]
    b.team_id = "other-" + b.team_id
    before = support(g, t)
    assert support(pd.concat([g, a]), pd.concat([t, b])) == before


@pytest.mark.parametrize("credit", [0., .08, .40])
@pytest.mark.parametrize("s", [0., .1, .25, .62, .84, 1.])
def test_ceiling_is_strictly_monotone_bounded_downward_and_count_independent(credit, s):
    x = np.linspace(0., 1., 10001)
    y = continuous_score(x, s, credit)
    assert (np.diff(y) > 0).all()
    assert (y >= 0).all() and (y <= x).all()
    assert (x - y).max() <= .5
    assert np.max(np.diff(y)) <= .000100000001
    assert continuous_score(.8, s, credit) == continuous_score([.8] * 100, s, credit)[0]


def test_continuous_boundary_changes_and_discount_credit():
    for boundary in (.25, .62, .84):
        assert 0 < continuous_score(.9, boundary + 1e-8, .04) - continuous_score(.9, boundary - 1e-8, .04) < 2e-8
    assert continuous_score(.8, .2, .1) > continuous_score(.8, .2, 0.)
    assert continuous_score(.4, .2, .5) == .4


def test_whole_resume_can_keep_head_to_head_winner_lower():
    # A single encounter provides no override: full upstream performance and
    # independent supporting results continue to determine the score.
    assert continuous_score(.55, .2, .08) < continuous_score(.8, .5, .08)


def test_improved_result_cannot_lower_new_policy_score_at_fixed_upstream():
    g, t = fixture(gf=0, ga=1)
    prior = continuous_score(.8, support(g, t), .05)
    g.loc[0, ["gf", "ga"]] = [3, 0]
    assert continuous_score(.8, support(g, t), .05) > prior


def test_actual_publication_path_ignores_old_rank_boundaries_and_improves_with_results():
    g, t = fixture(gf=0, ga=1)
    row = t[t.team_id == "a"].copy()
    def score():
        s, _ = evidence(g, t, AS_OF, CFG)
        return apply_publication_experiment(row, pd.Series([.75]), pd.Series([.4]), s,
                                            pd.Series([.02]), pd.Series([.03]),
                                            PublicationExperiment(), calculator)[0].iloc[0]
    prior = score()
    row["same_age_top100_opp_count"] = 3
    row["same_age_top500_opp_count"] = 8
    row["same_age_top100_non_loss_opp_count"] = 2
    assert score() == prior
    g.loc[0, ["gf", "ga"]] = [3, 0]
    assert score() > prior


def test_older_qualified_team_retains_legacy_cap_output():
    g, t = fixture()
    s, _ = evidence(g, t, AS_OF, CFG)
    row = t[t.team_id == "a"].copy()
    row["play_up_game_share"] = .5
    row["play_up_top500_non_loss_opp_count"] = 3
    row["play_up_top1000_non_loss_opp_count"] = 5
    row["play_up_avg_opp_power_adj"] = .65
    for profile in ("support-bands-v1", "support-continuous-v1"):
        score, diag = apply_publication_experiment(row, pd.Series([.8]), pd.Series([.71]), s,
                                                  pd.Series([.01]), pd.Series([.02]),
                                                  PublicationExperiment(profile), calculator)
        assert score.iloc[0] == .71
        assert diag.policy_older_preserved.iloc[0]


@pytest.mark.parametrize("value", [np.nan, np.inf, -1., 1.01])
def test_invalid_policy_values_fail(value):
    with pytest.raises(ValueError):
        continuous_score(.8, value, .05)


def test_invalid_selected_pool_and_profile_fail():
    g, t = fixture(n=31)
    with pytest.raises(ValueError, match="selected game pool"):
        evidence(g, t, AS_OF, CFG)
    g, t = fixture()
    with pytest.raises(ValueError, match="confidence v2"):
        evidence(g, t, AS_OF, GlickoConfig())
    g.loc[0, "date"] = AS_OF + pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="as-of window"):
        evidence(g, t, AS_OF, CFG)


@pytest.mark.parametrize("unsafe", ["fetch_from_supabase", "persist_game_residuals", "persist_game_explainability", "save_snapshot", "calculate_rank_changes_enabled"])
def test_actual_orchestrator_refuses_each_live_option(unsafe):
    args = dict(fetch_from_supabase=False, persist_game_residuals=False, persist_game_explainability=False,
                save_snapshot=False, calculate_rank_changes_enabled=False,
                publication_policy=PublicationExperiment(), glicko_cfg=CFG)
    args[unsafe] = True
    with pytest.raises(ValueError):
        asyncio.run(calculator.compute_all_cohorts(None, **args))


def test_attribution_bands_are_explicit_and_not_adoption_profile():
    assert [support_band(x) for x in (0., .249, .25, .619, .62, .839, .84, 1.)] == [2000, 2000, 400, 400, 250, 250, None, None]
    assert PublicationExperiment().profile == "support-continuous-v1"
    with pytest.raises(ValueError, match="new candidate version"):
        PublicationExperiment(independent_prior_mass=3.).validate()


def test_final_policy_does_not_reward_heavy_elite_losses_over_good_wins():
    def final_score(quality, gf, ga):
        games, teams = fixture(quality=quality, gf=gf, ga=ga)
        measured, _ = evidence(games, teams, AS_OF, CFG)
        row = teams[teams.team_id == "a"].copy()
        return apply_publication_experiment(
            row, pd.Series([.75]), pd.Series([.4]), measured,
            pd.Series([.02]), pd.Series([.03]), PublicationExperiment(), calculator,
        )[0].iloc[0]
    assert final_score(.6, 3, 0) > final_score(.95, 0, 6)
    assert final_score(.6, 3, 0) > final_score(.1, 3, 0)


V2 = PublicationExperiment("support-continuous-v2")


def test_v2_retains_v1_score_for_same_age_resume_without_exemption():
    games, teams = fixture()
    row = teams[teams.team_id == "a"].copy()
    results = []
    for cfg in (PublicationExperiment(), V2):
        summary, _ = evidence(games, teams, AS_OF, CFG, cfg)
        final, _ = apply_publication_experiment(
            row, pd.Series([.8]), pd.Series([.71]), summary,
            pd.Series([.01]), pd.Series([.02]), cfg, calculator,
        )
        results.append(final)
    pd.testing.assert_series_equal(*results, check_exact=True)


def test_v2_counts_earned_older_results_without_age_bonus_or_heavy_loss_support():
    games, teams = fixture(gf=3, ga=0)
    same, _ = evidence(games, teams, AS_OF, CFG, V2)
    games["opp_age"] = "12"
    older, packet = evidence(games, teams, AS_OF, CFG, V2)
    assert older.loc["a", "policy_support"] == same.loc["a", "policy_support"]
    assert older.loc["a", "policy_selected_older_games"] == 12
    assert older.loc["a", "policy_selected_same_age_games"] == 0
    assert len(packet) == 12
    games[["gf", "ga"]] = [0, 6]
    losses, _ = evidence(games, teams, AS_OF, CFG, V2)
    assert losses.loc["a", "policy_support"] == 0
    assert losses.loc["a", "policy_difficulty"] == older.loc["a", "policy_difficulty"]


def test_v2_excludes_younger_and_other_gender_from_publication_support():
    games, teams = fixture()
    original, _ = evidence(games, teams, AS_OF, CFG, V2)
    extra = games.iloc[:2].copy()
    extra["game_id"] += "-excluded"
    extra["id"] += "-excluded"
    extra.loc[extra.index[0], "opp_age"] = "10"
    extra.loc[extra.index[1], "opp_gender"] = "Female"
    # Different opponent identities keep the added rows from changing the
    # existing encounter discounts. Engine selection itself is unchanged.
    extra["opp_id"] += "-excluded"
    measured, packet = evidence(pd.concat([games, extra]), teams, AS_OF, CFG, V2)
    pd.testing.assert_frame_equal(original, measured, check_exact=True)
    assert len(packet) == len(games)


def test_v2_older_rematches_keep_engine_discounts_and_one_opponent_mass():
    games, teams = fixture(n=30, rematch=True, gf=6)
    games["opp_age"] = "12"
    summary, packet = evidence(games, teams, AS_OF, CFG, V2)
    np.testing.assert_array_equal(packet.rating_weight, compute_rating_weights(games, AS_OF, CFG))
    assert summary.loc["a", "policy_independent_mass"] < 1
    assert summary.loc["a", "policy_selected_older_games"] == 30


def test_v2_legacy_qualification_and_final_score_cannot_change_new_score():
    games, teams = fixture()
    summary, _ = evidence(games, teams, AS_OF, CFG, V2)
    row = teams[teams.team_id == "a"].copy()

    def score(legacy=.71):
        return apply_publication_experiment(
            row, pd.Series([.8]), pd.Series([legacy]), summary,
            pd.Series([.01]), pd.Series([.02]), V2, calculator,
        )

    before, _ = score()
    row["play_up_game_share"] = .5
    row["play_up_top500_non_loss_opp_count"] = 3
    row["play_up_top1000_non_loss_opp_count"] = 5
    row["play_up_avg_opp_power_adj"] = .65
    after, diag = score(.99)
    pd.testing.assert_series_equal(before, after, check_exact=True)
    assert diag.policy_legacy_older_qualified.iloc[0]
    assert not diag.policy_older_preserved.iloc[0]
    assert diag.policy_applied_cap_rank.isna().all()
    expected = continuous_score(diag.policy_pre_cap, diag.policy_support,
                                diag.policy_existing_discount_credit, V2)
    np.testing.assert_array_equal(after, expected)


def test_v2_full_path_rewards_older_wins_and_is_exactly_order_independent():
    games, teams = fixture(gf=0, ga=6)
    games["opp_age"] = "12"
    row = teams[teams.team_id == "a"].copy()

    def score(g, t):
        summary, packet = evidence(g, t, AS_OF, CFG, V2)
        final, _ = apply_publication_experiment(
            row, pd.Series([.8]), pd.Series([.71]), summary,
            pd.Series([.01]), pd.Series([.02]), V2, calculator,
        )
        return final.iloc[0], summary, packet

    losses, _, _ = score(games, teams)
    games[["gf", "ga"]] = [3, 0]
    wins, summary, packet = score(games, teams)
    assert wins > losses
    shuffled, other, reordered = score(games.sample(frac=1, random_state=12),
                                      teams.sample(frac=1, random_state=13))
    assert shuffled == wins
    pd.testing.assert_frame_equal(summary.sort_index(), other.sort_index(), check_exact=True)
    pd.testing.assert_frame_equal(packet.reset_index(drop=True), reordered.reset_index(drop=True), check_exact=True)


@pytest.mark.parametrize("unsafe", ["fetch_from_supabase", "persist_game_residuals", "persist_game_explainability", "save_snapshot", "calculate_rank_changes_enabled"])
def test_v2_orchestrator_refuses_live_operations(unsafe):
    args = dict(fetch_from_supabase=False, persist_game_residuals=False, persist_game_explainability=False,
                save_snapshot=False, calculate_rank_changes_enabled=False,
                publication_policy=V2, glicko_cfg=CFG)
    args[unsafe] = True
    with pytest.raises(ValueError):
        asyncio.run(calculator.compute_all_cohorts(None, **args))
