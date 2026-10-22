import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.rankings.joint_field_problem import build_joint_field_problem

A = "00000000-0000-4000-8000-000000000001"
B = "00000000-0000-4000-8000-000000000002"
AT = pd.Timestamp("2026-10-12T00:00:00Z")


def inputs(games=1, genders=("female", "female"), ages=(15, 15), leagues=(None, None)):
    rows = []
    for i in range(games):
        for team, opponent, age, other_age, gender, other_gender in [
            (A, B, ages[0], ages[1], genders[0], genders[1]),
            (B, A, ages[1], ages[0], genders[1], genders[0]),
        ]:
            rows.append(dict(team_id=team, opp_id=opponent, id=f"game-{i:02d}", game_id=f"game-{i:02d}",
                             date=pd.Timestamp("2026-10-12"), gf=1, ga=1,
                             age=str(age), opp_age=str(other_age), gender=gender, opp_gender=other_gender))
    selected = pd.DataFrame(rows)
    teams = pd.DataFrame({"team_id": [A, B], "age_num": ages, "gender": genders})
    metadata = pd.DataFrame({"team_id_master": [A, B], "state_code": ["WA", "WA"],
                             "league": leagues, "is_deprecated": [False, False]})
    return selected, teams, metadata


def build(*args, **kwargs):
    return build_joint_field_problem(*args, GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2"), **kwargs)


def test_neutral_field_keeps_one_time_prior_and_one_physical_game():
    problem = build(*inputs(), as_of=AT)
    assert len(problem.selected) == 2 and len(problem.physical) == 1 and len(problem.edges) == 1
    assert problem.physical.perspectives.tolist() == [2]
    assert problem.edges.w.tolist() == [1.0]
    np.testing.assert_array_equal(problem.design.toarray(), [[1., -1., 0.]])
    np.testing.assert_allclose(problem.prior, [0., 0., -45. / 173.7178], rtol=0, atol=1e-15)
    mode, _, diagnostics = problem.solve()
    assert diagnostics["iterations"] == 1 and diagnostics["converged"]
    np.testing.assert_array_equal(problem.ratings(mode), [1455., 1455.])


def test_rematches_keep_raw_mass_without_double_counting_perspectives():
    problem = build(*inputs(games=4), as_of=AT)
    assert len(problem.physical) == 4
    np.testing.assert_array_equal(problem.physical.joint_weight, [1., .8, .6, .4])
    np.testing.assert_allclose(problem.edges.w, [2.8], atol=1e-15, rtol=0)
    assert problem.edges.y.tolist() == [.5]


def test_known_reference_field_and_cross_gender_rows_are_retained():
    reference = build(*inputs(genders=("male", "male"), leagues=("MLS_NEXT_HD", "ECNL")), as_of=AT)
    assert reference.nodes.field_parameter_index.tolist() == [-1, 2]
    np.testing.assert_array_equal(reference.design.toarray(), [[1., -1., -1.]])
    np.testing.assert_allclose(reference.prior, [0., 0., -30. / 173.7178], rtol=0, atol=1e-15)
    cross = build(*inputs(genders=("male", "female")), as_of=AT)
    assert len(cross.edges) == 1
    np.testing.assert_array_equal(cross.design.toarray(), [[1., -1., -1., 1.]])


def test_cross_age_offset_uses_existing_anchors_once():
    problem = build(*inputs(ages=(15, 16)), as_of=AT)
    np.testing.assert_allclose(problem.offset, [-8.8 / 173.7178], rtol=0, atol=1e-15)


def test_as_of_normalizes_to_utc_and_inputs_remain_unchanged():
    selected, teams, metadata = inputs()
    original = selected.copy(deep=True)
    first = build(selected, teams, metadata, as_of=AT)
    other = selected.copy()
    other["date"] = pd.to_datetime(["2026-10-11T17:00:00-07:00"] * len(other))
    second = build(other, teams, metadata, as_of="2026-10-11T17:00:00-07:00")
    assert first.fingerprint() == second.fingerprint()
    shuffled = build(selected.iloc[::-1].reset_index(drop=True), teams.iloc[::-1], metadata.iloc[::-1], as_of=AT)
    assert shuffled.fingerprint() == first.fingerprint()
    pd.testing.assert_frame_equal(selected, original, check_exact=True)
    third = build(selected, teams, metadata, as_of=AT + pd.Timedelta(days=1))
    assert third.fingerprint() != first.fingerprint()
    first.design.data[0] += .01
    assert first.fingerprint() != second.fingerprint()


def test_missing_opponent_metadata_keeps_the_actual_opponent_node():
    selected, teams, metadata = inputs()
    problem = build(selected[selected.team_id.eq(A)], teams[teams.team_id.eq(A)], metadata.iloc[:1], as_of=AT)
    assert problem.nodes.index.tolist() == [A, B]
    assert pd.isna(problem.nodes.loc[B, "league"])
    assert problem.nodes.loc[B, "field_label"] == "female/UNAFFILIATED"
    assert problem.physical.perspectives.tolist() == [1]


@pytest.mark.parametrize("defect", ["duplicate", "future", "old", "score", "cohort", "count", "self"])
def test_invalid_selected_inputs_fail_visibly(defect):
    selected, teams, metadata = inputs(games=31 if defect == "count" else 1)
    if defect == "duplicate":
        selected = pd.concat([selected, selected.iloc[:1]], ignore_index=True)
    elif defect == "future":
        selected.loc[0, "date"] = pd.Timestamp("2026-10-13")
    elif defect == "old":
        selected.loc[0, "date"] = pd.Timestamp("2025-10-11")
    elif defect == "score":
        selected["gf"] = np.inf
    elif defect == "cohort":
        selected.loc[0, "opp_gender"] = "male"
    elif defect == "self":
        selected.loc[0, "opp_id"] = A
    with pytest.raises(ValueError):
        build(selected, teams, metadata, as_of=AT)


def test_legacy_configuration_is_rejected():
    with pytest.raises(ValueError, match="complete v2"):
        build_joint_field_problem(*inputs(), GlickoConfig(), as_of=AT)
