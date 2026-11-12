import json
import math
from copy import deepcopy

import pytest

from src.predictions import form_dataset as dataset
from src.predictions import form_dataset_benchmark as benchmark
from src.predictions.form_policy import FORM_CANDIDATES, PINNED_MODEL_SIGNATURE, PINNED_REVISION, ResearchPolicy
from tests.unit import test_form_dataset

registered_study = test_form_dataset.registered_study


@pytest.mark.parametrize("sealed", [True, False])
def test_sealed_or_insufficient_study_never_runs_predictor(registered_study, tmp_path, sealed):
    server, study, day = registered_study
    if sealed:
        day["server_time"] = "2026-12-20T23:59:59Z"
    directory, output = tmp_path / "data", tmp_path / "benchmark"
    dataset.assemble_dataset(server, "url", "token", study, directory, dry_run=False)

    def forbidden(*args):
        raise AssertionError("Predictor ran before the registered gates passed")

    report = benchmark.benchmark_dataset(server, "url", "token", directory, forbidden, output)
    assert report["evaluation"] == "not_performed" and not output.exists()
    report = benchmark.benchmark_dataset(server, "url", "token", directory, forbidden, output, dry_run=False)
    assert report["status"] == ("evaluation_sealed" if sealed else "insufficient_data")
    assert report["production_promotion"] is False and not list(output.glob("batch-*"))


@pytest.mark.parametrize("invalid", [None, "signature", "parity", "missing", "duplicate"])
def test_batched_replay_keeps_inputs_residuals_and_periods_paired(registered_study, tmp_path, monkeypatch, invalid):
    server, study, _ = registered_study
    directory, output = tmp_path / "data", tmp_path / "benchmark"
    dataset.assemble_dataset(server, "url", "token", study, directory, dry_run=False)
    report, verified = dataset.verified_dataset(server, "url", "token", directory)
    manifest, policy, sources, eligible = verified
    # Isolate replay contracts with three fixtures; production still uses the validated 1,000/20 registration.
    unit_policy = ResearchPolicy(**{**vars(policy), "minimum_games": 1, "minimum_groups": 1, "bootstrap_samples": 20})
    report["audit"]["status"] = report["status"] = "eligible"
    monkeypatch.setattr(benchmark, "verified_dataset", lambda *args: (
        report, (manifest, unit_policy, sources, eligible),
    ))
    monkeypatch.setattr(benchmark, "CASE_BATCH_SIZE", 1)
    # The real bootstrap requires multiple evaluation events, covered by its own tests.
    monkeypatch.setattr("src.predictions.form_research.paired_event_interval", lambda *args, **kwargs: (0., 0.))
    calls = []

    def runner(bundle, folder):
        calls.append(deepcopy(bundle))
        assert len(bundle["cases"]) == 1
        case = bundle["cases"][0]
        identity = case["fixture"]["source_game_id"]
        if identity != "h":
            assert case["formOverrides"]["residual_sequence"]["a"] == -.25
            assert case["games"][0]["home_score"] == 2 and case["expectations"]["h"]["expected_home_margin"] == 4
        prediction = {"winProbabilityA": .6, "drawProbability": .2, "winProbabilityB": .2,
                      "blowout4PlusProbability": .1, "predictedWinner": "team_a_win", "expectedMargin": 1,
                      "expectedScore": {"teamA": 2, "teamB": 1}}
        names = list(FORM_CANDIDATES)
        if case["period"] == "development":
            names.extend(name + "_ml_off" for name in FORM_CANDIDATES[1:])
        outputs = {name: [{"id": identity, "prediction": prediction}] for name in names}
        result = {"aa_parity": True, "cases": 1, "predictor_revision": PINNED_REVISION,
                  "model_signature": PINNED_MODEL_SIGNATURE, "outputs": outputs}
        if invalid == "signature":
            result["model_signature"] = "wrong"
        elif invalid == "parity":
            result["aa_parity"] = False
        elif invalid == "missing":
            outputs.pop("residual_sequence")
        elif invalid == "duplicate":
            outputs["baseline"] *= 2
        (folder / "runner-input.json").write_text(json.dumps(bundle), encoding="utf-8")
        (folder / "runner-output.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    if invalid:
        with pytest.raises(ValueError):
            benchmark.benchmark_dataset(server, "url", "token", directory, runner, output, dry_run=False)
        assert not (output / "report.json").exists()
        return
    result = benchmark.benchmark_dataset(server, "url", "token", directory, runner, output, dry_run=False)
    assert result["status"] == "no_advancement" and result["evaluation_status"] == "performed"
    saved = json.loads((output / "report.json").read_text())
    assert saved["evaluation_status"] == "performed" and saved["evaluation"] == result["evaluation"]
    for metrics in result["evaluation"].values():
        assert metrics["games"] == 1
        assert metrics["log_loss"] == pytest.approx(-math.log(.6))
        assert metrics["brier_score"] == pytest.approx(.24)
        assert metrics["margin_mae"] == 1
        assert metrics["blowout_4plus_brier"] == pytest.approx(.01)
    assert set(result["evaluation"]) == {"baseline", "candidate"}
    assert result["aa_parity"] is True and result["production_promotion"] is False
    assert len(result["batches"]) == len(calls) == 3
    assert [call["cases"][0]["period"] for call in calls] == ["development", "development", "evaluation"]
    assert len(result["residual_coverage"]) == 3
