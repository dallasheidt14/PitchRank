"""Keep the offline formula comparison behind the existing release gate."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.predictions import formula_diagnostics as study


def prediction(a=0.6, b=0.2):
    return {"winProbabilityA": a, "winProbabilityB": b, "drawProbability": 1-a-b,
            "blowout4PlusProbability": 0.15, "expectedMargin": 1,
            "expectedScore": {"teamA": 2, "teamB": 1}, "formA": 0, "formB": 0, "predictedWinner": "team_a"}


def fixture():
    context = {"teamAInput": {"team_id_master": "a", "age": 12, "gender": "M", "sos_norm": 0.7, "power_score_final": 0.5},
               "teamBInput": {"team_id_master": "b", "age": 12, "gender": "M", "sos_norm": 0.4, "power_score_final": 0.4},
               "frozenEvidence": {"games": []}}
    p = prediction()
    clock = "2026-11-13T12:00:00Z"
    payload = {"context": context, "prediction": p, "reference_time": clock}
    variants = {arm: {"prediction": p if arm == "baseline" else prediction(0.8, 0.1),
                      "receipt": {"aa_parity": True, "reference_time": clock}} for arm in study.ARMS}
    row = {"baseline_forecast_id": "one", "open": True, "payload": payload, "fixture": {"source_game_id": "game"},
           "game_date": "2026-11-15", "provider": "gotsport", "group": "event1", "group_kind": "event",
           "captured_at": clock}
    report = {"study": "compare-formula-diagnostic-v1", "live_formula_changed": False, "model_signature": "signature",
              "cases": [{"id": "one", "context": context, "variants": variants}]}
    return row, report


class Client:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def rpc(self, name, params):
        if name == "compare_monitor_clock":
            return SimpleNamespace(execute=lambda: SimpleNamespace(data="2026-11-16T12:00:00Z"))
        assert name == "compare_monitor_review", "Unexpected database write or unguarded read"
        def execute():
            self.calls.append((name, params))
            return SimpleNamespace(data=self.rows[params["p_offset"]:params["p_offset"]+1000])
        return SimpleNamespace(execute=execute)


def allow_result(monkeypatch):
    monkeypatch.setattr(study, "strict_resolver", lambda _: None)
    monkeypatch.setattr(study, "settlement_aliases", lambda _: {})
    calls = []
    def result(client, fixture, resolver, aliases):
        calls.append(fixture)
        return {"id": "physical1", "home_score": 1, "away_score": 2}, True, "settled"
    monkeypatch.setattr(study, "database_result", result)
    return calls


def test_sealed_results_are_not_read_and_preview_does_not_settle(monkeypatch):
    row, report = fixture()
    calls = allow_result(monkeypatch)
    sealed = {**row, "open": False, "payload": None, "fixture": None}
    records, coverage = study.released_formula_records(Client([sealed]), report, preview=False)
    assert not records and coverage["sealed_or_future"] == 1 and not calls
    records, coverage = study.released_formula_records(Client([row]), report)
    assert not records and coverage["reviewable"] == 1 and not calls
    with pytest.raises(ValueError, match="sealed"):
        study.released_formula_records(Client([{**row, "open": False}]), report, preview=False)


def test_pairs_exact_inputs_and_reverses_settlement_scores(monkeypatch):
    row, report = fixture()
    calls = allow_result(monkeypatch)
    records, coverage = study.released_formula_records(Client([row]), report, preview=False)
    assert len(calls) == 1 and coverage["settled"] == 1
    assert records[0]["scores"] == [2, 1]
    assert set(records[0]["payload"]["variants"]) == set(study.ARMS)
    report["cases"][0]["context"] = {"changed": True}
    with pytest.raises(ValueError, match="inputs"):
        study.released_formula_records(Client([row]), report, preview=False)


@pytest.mark.parametrize("defect", ["missing_arm", "missing_risk", "changed_baseline", "missing_group"])
def test_rejects_incomplete_pair_before_source_read(monkeypatch, defect):
    row, report = deepcopy(fixture())
    calls = allow_result(monkeypatch)
    variants = report["cases"][0]["variants"]
    if defect == "missing_arm":
        del variants["sos_x0"]
    elif defect == "missing_risk":
        variants["sos_x0"]["prediction"] = {**prediction(), "blowout4PlusProbability": None}
    elif defect == "changed_baseline":
        variants["baseline"]["prediction"] = prediction(0.7, 0.1)
    else:
        row["group"] = None
    if defect == "missing_group":
        assert study.released_formula_records(Client([row]), report, preview=False)[1]["missing_group"] == 1
    else:
        with pytest.raises(ValueError):
            study.released_formula_records(Client([row]), report, preview=False)
    assert not calls


def test_gate_pages_every_forecast_and_counts_missing_candidates():
    row, report = fixture()
    rows = [{**row, "baseline_forecast_id": str(i), "open": False, "payload": None, "fixture": None} for i in range(1001)]
    client = Client(rows)
    _, coverage = study.released_formula_records(client, report)
    assert [params["p_offset"] for _, params in client.calls] == [0, 1000]
    assert coverage["missing_candidate_replay"] == 1001
    assert coverage["missing_server_forecast"] == 1


def test_reports_coverage_only_before_predeclared_minimum(monkeypatch):
    row, report = fixture()
    allow_result(monkeypatch)
    records, coverage = study.released_formula_records(Client([row]), report, preview=False)
    result = study.formula_accuracy_report(records + records, coverage)
    assert result["paired_matches"] == 1
    assert result["duplicate_observations_removed"] == 1
    assert result["minimum_matches"] == 1000 and result["minimum_groups"] == 20
    assert result["metrics"] is None and result["adoption_decision"] == "not_authorized"


def test_scores_all_candidates_on_identical_physical_fixtures(monkeypatch):
    row, report = fixture()
    allow_result(monkeypatch)
    records, coverage = study.released_formula_records(Client([row]), report, preview=False)
    paired = [{**records[0], "actual_game_id": str(i), "baseline_forecast_id": str(i), "group": f"event{i % 20}"} for i in range(1000)]
    result = study.formula_accuracy_report(paired, coverage)
    assert result["status"] == "exploratory_comparison" and result["groups"] == 20
    a = result["metrics"]["baseline"]["overall"]
    b = result["metrics"]["sos_x0"]["overall"]
    assert a["games"] == b["games"] == 1000
    assert a["winner_accuracy"] == 1
    assert b["brier_score"] < a["brier_score"]
    assert b["log_loss"] < a["log_loss"]
    assert result["metrics"]["sos_x0"]["paired_log_loss_difference_95"][1] < 0
    assert a["blowout_4plus_probability_games"] == 1000
    assert result["adoption_decision"] == "not_authorized"


@pytest.mark.parametrize("matches,groups", [(999, 20), (1000, 19)])
def test_each_minimum_is_required_independently(monkeypatch, matches, groups):
    row, report = fixture()
    allow_result(monkeypatch)
    records, coverage = study.released_formula_records(Client([row]), report, preview=False)
    paired = [{**records[0], "actual_game_id": str(i), "group": f"event{i % groups}"} for i in range(matches)]
    result = study.formula_accuracy_report(paired, coverage)
    assert result["status"] == "insufficient_data" and result["metrics"] is None


def test_emitted_draw_is_scored_instead_of_probability_argmax(monkeypatch):
    row, report = fixture()
    allow_result(monkeypatch)
    records, coverage = study.released_formula_records(Client([row]), report, preview=False)
    for p in records[0]["payload"]["variants"].values():
        p.update(winProbabilityA=0.4, winProbabilityB=0.4, drawProbability=0.2, predictedWinner="draw")
    paired = [{**records[0], "actual_game_id": str(i), "scores": [1, 1], "group": f"event{i % 20}"} for i in range(1000)]
    result = study.formula_accuracy_report(paired, coverage)
    for arm in study.ARMS:
        assert result["metrics"][arm]["overall"]["winner_accuracy"] == 1


def test_evaluator_wrapper_preview_and_write_boundaries(monkeypatch, tmp_path):
    import json
    import subprocess
    from scripts import evaluate_compare_formula as command
    from src.predictions import private_research_output
    row, report = fixture()
    calls = allow_result(monkeypatch)
    output = tmp_path / "evaluation.json"
    assert command.run(Client([row]), report)["coverage"]["reviewable"] == 1
    assert not calls and not list(tmp_path.iterdir())
    with pytest.raises(ValueError):
        command.run(Client([row]), report, output=output)
    def refuse(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git check-ignore")
    monkeypatch.setattr(private_research_output.subprocess, "run", refuse)
    with pytest.raises(subprocess.CalledProcessError):
        command.run(Client([row]), report, execute=True, output=output)
    assert not calls
    monkeypatch.setattr(private_research_output.subprocess, "run", lambda *args, **kwargs: None)
    command.run(Client([row]), report, execute=True, output=output)
    assert len(calls) == 1
    saved = json.loads(output.read_text())
    assert saved["provenance"]["model_signature"] == "signature"
    assert saved["provenance"]["observed_at"] == "2026-11-16T12:00:00Z"
    assert saved["provenance"]["observations"][0]["scores"] == [2, 1]
    assert len(saved["provenance"]["replay_report_sha256"]) == 64
    with pytest.raises(ValueError, match="overwrite"):
        command.run(Client([row]), report, execute=True, output=output)
