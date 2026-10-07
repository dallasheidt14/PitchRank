"""Ceilings must not reverse teams with the same publication restriction."""
import pandas as pd
import pytest

from src.rankings.calculator import _apply_publication_cap_band, _compute_publication_cap_scores


def _frame():
    return pd.DataFrame({
        "team_id": ["strong", "middle", "below", "low", "uncapped"],
        "age_num": [13] * 5,
        "gender": ["male"] * 5,
        "status": ["Active"] * 5,
        "publication_cap_rank": [250, 250, 250, 250, None],
        "publication_cap_score": [0.70, 0.70, 0.70, 0.70, None],
    }, index=[11, 29, 47, 63, 80])


def test_ceiling_boundary_cannot_reverse_stronger_team():
    teams = _frame()
    base = pd.Series([0.80, 0.75, 0.6999, 0.69, 0.68], index=teams.index)
    result = _apply_publication_cap_band(base, teams)

    # The former band ended at .694999, below the untouched .6999 team.
    assert result[11] > result[29] > result[47] > result[63]
    assert result[80] == base[80]
    assert (result <= base).all()
    assert result.loc[[11, 29, 47, 63]].max() < 0.70
    # Reassign existing score slots, without changing the ceiling or its band.
    assert sorted(result.tolist()) == pytest.approx([0.68, 0.69, 0.694999, 0.6999, 0.699999])


def test_ceiling_order_does_not_exchange_scores_between_boards_or_statuses():
    teams = _frame()
    teams["publication_cap_rank"] = 250
    teams["publication_cap_score"] = 0.70
    teams["gender"] = ["male", "male", "female", "male", "male"]
    teams["status"] = ["Active", "Active", "Active", "Inactive", "Active"]
    base = pd.Series([0.80, 0.75, 0.69995, 0.69998, 0.6999], index=teams.index)
    result = _apply_publication_cap_band(base, teams)

    assert result[11] > result[29] > result[80]
    assert result[47] == base[47]
    assert result[63] == base[63]


def test_ceiling_order_is_deterministic_with_shuffled_rows_and_tied_bases():
    teams = _frame()
    base = pd.Series([0.80, 0.75, 0.6999, 0.6999, 0.68], index=teams.index)
    result = _apply_publication_cap_band(base, teams)
    shuffled = teams.loc[[63, 11, 80, 47, 29]]
    replay = _apply_publication_cap_band(base.loc[shuffled.index], shuffled)

    pd.testing.assert_series_equal(result.sort_index(), replay.sort_index())
    assert result[29] > result[47] >= result[63]
    assert (result <= base).all()


def test_ceiling_order_preserves_an_already_ordered_group():
    teams = _frame()
    base = pd.Series([0.80, 0.75, 0.68, 0.67, 0.66], index=teams.index)
    result = _apply_publication_cap_band(base, teams)
    assert result.tolist() == pytest.approx([0.699999, 0.694999, 0.68, 0.67, 0.66])


def test_ceiling_order_does_not_exchange_scores_between_restrictions():
    teams = _frame().iloc[:4].copy()
    teams["publication_cap_rank"] = [250, 250, 400, 400]
    base = pd.Series([0.80, 0.75, 0.69995, 0.6999], index=teams.index)
    result = _apply_publication_cap_band(base, teams)
    assert result[47] == base[47]
    assert result[63] == base[63]
    assert result[11] > result[29]


@pytest.mark.parametrize("cap", [0.0, 1e-8, 0.001, 0.70])
def test_ceiling_order_keeps_scores_bounded_at_small_ceilings(cap):
    teams = _frame().iloc[:4].copy()
    teams["publication_cap_score"] = cap
    base = pd.Series([0.90, 0.80, cap * 0.999, 0.0], index=teams.index)
    result = _apply_publication_cap_band(base, teams)
    assert result.between(0.0, cap).all()
    assert (result <= base).all()
    assert result.is_monotonic_decreasing


def test_ceiling_order_propagates_across_three_tied_score_slots():
    teams = _frame()
    teams["team_id"] = ["strong", "middle", "a", "b", "c"]
    teams["publication_cap_rank"] = 250
    teams["publication_cap_score"] = 0.70
    base = pd.Series([0.80, 0.75, 0.6999, 0.6999, 0.6999], index=teams.index)
    result = _apply_publication_cap_band(base, teams)
    published = teams.assign(score=result).sort_values(["score", "team_id"], ascending=[False, True])
    assert published.team_id.tolist() == ["strong", "middle", "a", "b", "c"]
    assert (result <= base).all()


def test_ceiling_order_survives_published_age_scaling():
    teams = _frame().iloc[:2].copy()
    teams["team_id"] = ["z-strong", "a-weaker"]
    base = pd.Series([0.80, 0.70 - 1e-6], index=teams.index)
    result = _apply_publication_cap_band(base, teams)
    # U13's actual published anchor: a single float step can disappear here.
    published = teams.assign(score=result * 0.896).sort_values(["score", "team_id"], ascending=[False, True])
    assert published.team_id.tolist() == ["z-strong", "a-weaker"]
    assert (result <= base).all()


@pytest.mark.parametrize("other_status", ["Inactive", "Provisional"])
def test_ceiling_cutoff_ignores_ineligible_high_scores(other_status):
    teams = pd.DataFrame({
        "team_id": ["a", "b", "c"], "age_num": [10] * 3,
        "gender": ["male"] * 3, "status": ["Active", "Active", other_status],
        "publication_cap_rank": [2] * 3,
    })
    result = _compute_publication_cap_scores(teams, pd.Series([.6, .5, .99]))
    assert result.tolist() == pytest.approx([.5 - 1e-6] * 3)


@pytest.mark.parametrize("other_kind", ["gender", "status", "age_num"])
def test_ceiling_compression_matches_processing_each_board_and_status_alone(other_kind):
    own = _frame().iloc[:3].copy()
    own["publication_cap_rank"] = 250
    own["publication_cap_score"] = .7
    other = own.copy()
    other.index = [101, 103, 109]
    other["team_id"] = ["other-strong", "other-middle", "other-below"]
    other[other_kind] = {"gender": "female", "status": "Inactive", "age_num": 14}[other_kind]
    teams = pd.concat([own, other])
    base = pd.Series([.8, .75, .6999, .99, .9, .6998], index=teams.index)

    together = _apply_publication_cap_band(base, teams)
    for group in (own, other):
        alone = _apply_publication_cap_band(base.loc[group.index], group)
        pd.testing.assert_series_equal(together.loc[group.index], alone)
    shuffled = teams.sample(frac=1, random_state=42)
    pd.testing.assert_series_equal(
        together.sort_index(),
        _apply_publication_cap_band(base.loc[shuffled.index], shuffled).sort_index(),
    )
    assert (together <= base).all()
