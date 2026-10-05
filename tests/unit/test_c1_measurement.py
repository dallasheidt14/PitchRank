"""Decision ordering, fixed subgroup membership and failure before held-out reads."""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

TOOLS = Path(__file__).resolve().parents[2] / ".claude/skills/measuring-ranking-changes/scripts"
sys.path.insert(0, str(TOOLS))
c1 = importlib.import_module("score_c1")
scorer = importlib.import_module("score_later_games")
checks = importlib.import_module("c1_validation")


def metrics(delta=.25, p=.049, n=300, ci=(-2., 1.)):
    return {"delta": delta, "p": p, "n": n, "ci95": list(ci)}


@pytest.mark.parametrize("change,expected", [
    ({}, "pass"),
    ({"overall": {"delta": .249999}}, "inconclusive"),
    ({"overall": {"p": .05}}, "inconclusive"),
    ({"overall": {"delta": -.01}}, "harm"),
    ({"cut": {"n": 299}}, "inconclusive"),
    ({"cut": {"delta": -1.00001}}, "inconclusive"),
    ({"cut": {"ci95": [-2.00001, 1.]}}, "inconclusive"),
    ({"cut": {"n": 12, "delta": -3, "ci95": [-5., -1.01]}}, "harm"),
    ({"board": {"ci95": [-4., -1.01]}}, "harm"),
    ({"board": {"delta": -1.1, "ci95": [-3., -1.]}}, "pass"),
    ({"missing_board": True}, "inconclusive"),
    ({"cut": {"n": 0, "delta": None, "ci95": None}}, "inconclusive"),
    ({"overall": {"p": float("nan")}}, "inconclusive"),
])
def test_verdict_thresholds_and_precedence(change, expected):
    overall = metrics()
    boards = {name: metrics(delta=.5) for name in c1.BOARDS}
    cut = metrics(delta=-1.)
    overall.update(change.get("overall", {}))
    cut.update(change.get("cut", {}))
    boards["10M"].update(change.get("board", {}))
    if change.get("missing_board"):
        del boards["10F"]
    assert c1.verdict(overall, boards, cut) == expected


def test_zero_equal_board_average_blocks_pass():
    assert c1.verdict(metrics(), {b: metrics(delta=0.) for b in c1.BOARDS}, metrics()) == "inconclusive"


@pytest.mark.parametrize("change,expected", [
    ({}, "pass"),
    ({"board": [-3., -1.01]}, "harm"),
    ({"board": [-3., -1.]}, "pass"),
    ({"cut": [-3., -1.01]}, "harm"),
    ({"cut": None}, "inconclusive"),
    ({"missing_board": True}, "inconclusive"),
    ({"incremental": "harm", "missing_board": True}, "harm"),
    ({"incremental": "inconclusive"}, "inconclusive"),
])
def test_release_cumulative_harm_cannot_be_hidden_by_incremental_pass(change, expected):
    boards = {name: metrics(delta=.5) for name in c1.BOARDS}
    cut = metrics(delta=0.)
    if "board" in change:
        boards["10F"]["ci95"] = change["board"]
    if "cut" in change:
        cut["ci95"] = change["cut"]
    if change.get("missing_board"):
        del boards["10M"]
    assert c1.release_verdict(
        {"verdict": change.get("incremental", "pass")},
        {"boards": boards, "isolation_cut": cut},
    ) == expected


def test_canonical_comparison_preserves_duplicates_and_exact_changes():
    a = pd.DataFrame({"team_id": ["a", "a", "b"], "score": [.1, .1, .2]}, index=[0, 0, 1])
    checks.assert_equal_frames(a, a.iloc[::-1], "duplicates")
    with pytest.raises(checks.InvalidRun):
        checks.assert_equal_frames(a, a.iloc[1:], "deleted duplicate")
    b = a.copy()
    b.iloc[0, 1] += 1e-14
    with pytest.raises(checks.InvalidRun):
        checks.assert_equal_frames(a, b, "tiny upstream change")


def test_scoring_uses_incumbent_subgroup_and_excludes_unknown_states(monkeypatch):
    games = pd.DataFrame({"id": ["1", "2", "3", "4"], "a": ["a", "c", "e", "g"],
                          "b": ["b", "d", "f", "h"], "gf_a": [2]*4, "ga_a": [0]*4})
    monkeypatch.setattr(scorer, "heldout_games", lambda *args: (games, {"games": 4, "draws": 0}))
    base = pd.DataFrame({"team_id": list("abcdefgh"), "age_num": [10, 10, 10, 10, 14, 14, 15, 15],
                         "gender": ["Male", "Male", "Female", "Female", "Male", "Male", "Male", "Male"],
                         "status": ["Active"]*8, "power_score_true": [.8, .2]*4}).set_index("team_id")
    candidate = base.copy()
    candidate["power_score_true"] = [.2, .8]*4
    reference = base.assign(scf=[.5, .8, .7, .8, .2, .8, .2, .3],
                            state_code=["CA", "AZ", "CA", "AZ", "UNKNOWN", "AZ", "NV", "AZ"])
    args = SimpleNamespace(heldout_freeze="unused", train_freeze="unused", start="2026-09-01", end="2026-09-30")
    result = c1._score(args, scorer, base, candidate, reference)
    assert "scf" not in base
    assert result["isolation_cut"]["n"] == 2
    assert result["isolation_cut"]["low_scf_teams"] == 3
    assert result["isolation_cut"]["orderings_changed"] == 2
    assert result["u10_combined"]["n"] == 2
    assert result["population"]["primary_same_board"] == 4


def test_failed_date_gate_never_reads_holdout(tmp_path, monkeypatch):
    freeze = tmp_path / "train"
    freeze.mkdir()
    (freeze / "freeze-manifest.json").write_text(json.dumps({"today": "2026-08-31"}))
    calls = []
    monkeypatch.setattr(scorer, "heldout_games", lambda *a: calls.append(a))
    args = SimpleNamespace(out=str(tmp_path / "report.json"), start="2026-08-31", end="2026-09-30",
                           cand=["c1=unused"], train_freeze=str(freeze), isolation_reference="unused")
    with pytest.raises(SystemExit):
        c1.cmd_c1(args, scorer)
    assert not calls
    assert json.loads(Path(args.out).read_text())["verdict"] == "void"


def test_missing_lock_is_rejected_before_any_outcome_access():
    with pytest.raises(checks.InvalidRun, match="design lock"):
        c1._check_lock(SimpleNamespace(design_lock=None), {}, Path("unused"))


def test_original_dyadic_formula_handles_repeated_pairs_and_ties():
    frame = pd.DataFrame({"a": ["a", "a", "b"], "b": ["b", "b", "c"], "gf_a": [1, 1, 0], "ga_a": [0, 0, 1]})
    assert scorer.credit(frame, pd.Series({"a": .5, "b": .5, "c": .2})).tolist() == [.5, .5, 0.]
    result = scorer.dyadic(frame, np.array([1., 0., -1.]))
    assert result["delta"] == 0.
    assert result["se"] == 0.
    assert result["p"] == 1.
    independent = frame.assign(a=["a", "a", "c"], b=["b", "b", "d"])
    assert scorer.dyadic(independent, np.array([1., 0., -1.]))["se"] == pytest.approx(100 * np.sqrt(2) / 3)


def test_stage_capture_excludes_cap_helper_calls(tmp_path):
    def authority(row):
        return row["strength"]
    funcs = {name: authority for name in ("_same_age_authority_score", "_same_age_raw_shrink", "_play_up_bonus",
                                         "_same_age_publish_penalty", "_positive_ml_evidence_scale")}
    fake = SimpleNamespace(**funcs, apply_predictive_adjustment=None)
    fake._publication_cap_rank = lambda row: fake._same_age_authority_score(row)
    capture = checks.StageCapture(fake, tmp_path)
    capture.install()
    row = pd.Series({"team_id": "a", "strength": .3})
    fake._same_age_authority_score(row)
    fake._publication_cap_rank(row)
    receipt = capture.close()
    observed = pd.read_parquet(tmp_path / "stage-upstream-adjustments.parquet")
    assert observed.to_dict("records") == [{"team_id": "a", "function": "_same_age_authority_score",
                                           "caller": "pipeline", "value": .3}]
    assert receipt["files"]
