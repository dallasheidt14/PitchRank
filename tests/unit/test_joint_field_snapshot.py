import numpy as np
import pandas as pd

from src.etl.glicko_config import GlickoConfig
from src.rankings.joint_field_snapshot import fit_joint_field_snapshot


def fixture():
    a, b = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
    selected = pd.DataFrame([
        dict(team_id=a, opp_id=b, id="draw", game_id="draw", date=pd.Timestamp("2026-10-12"),
             gf=1, ga=1, age="15", gender="female", opp_age="15", opp_gender="female"),
        dict(team_id=b, opp_id=a, id="draw", game_id="draw", date=pd.Timestamp("2026-10-12"),
             gf=1, ga=1, age="15", gender="female", opp_age="15", opp_gender="female"),
    ])
    teams = pd.DataFrame(dict(team_id=[a, b], age_num=[15, 15], gender=["female", "female"]))
    metadata = pd.DataFrame(dict(team_id_master=[a, b], state_code=["WA", "WA"],
                                 league=[None, None], is_deprecated=[False, False]))
    return selected, teams, metadata


def test_snapshot_binds_point_uncertainty_and_effective_evidence_without_mutating_inputs():
    selected, teams, metadata = fixture()
    copies = [frame.copy(deep=True) for frame in [selected, teams, metadata]]
    snapshot = fit_joint_field_snapshot(selected, teams, metadata,
        GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2"), "2026-10-12")
    np.testing.assert_array_equal(snapshot.state.mu, [1455., 1455.])
    # The shared field is unidentified by internal draws; its uncertainty remains.
    assert snapshot.state.sigma.gt(350).all()
    assert snapshot.state.incident_physical_games.tolist() == [1, 1]
    assert snapshot.state.incident_evidence_weight.tolist() == [1., 1.]
    assert snapshot.selected_evidence.joint_weight.tolist() == [1., 1.]
    assert snapshot.selected_evidence.joint_outcome.tolist() == [.5, .5]
    assert len(snapshot.physical_evidence) == 1
    assert snapshot.diagnostics["source_teams_with_extra_incident_games"] == 0
    assert snapshot.diagnostics["solver"]["max_gradient"] < 1e-8
    for before, after in zip(copies, [selected, teams, metadata]):
        pd.testing.assert_frame_equal(before, after, check_exact=True)


def test_cold_and_warm_snapshot_fits_use_the_same_prior_and_information():
    args = fixture()
    cfg = GlickoConfig(RATING_UPDATE_MODE="fixed-prior-mode-v2")
    first = fit_joint_field_snapshot(*args, cfg, "2026-10-12")
    reused = fit_joint_field_snapshot(*args, cfg, "2026-10-12", start=first.mode)
    pd.testing.assert_frame_equal(first.state, reused.state, check_exact=True)
    pd.testing.assert_frame_equal(first.selected_evidence, reused.selected_evidence, check_exact=True)
    assert first.diagnostics["problem_fingerprint"] == reused.diagnostics["problem_fingerprint"]
