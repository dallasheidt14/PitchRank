"""Real Node/TypeScript research intervention, with local calibration and no database."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.predictions.form_research import CALIBRATION_ROLES, PINNED_REVISION, digest, valid_expectation

ROOT = Path(__file__).resolve().parents[2]
TSX = ROOT / "frontend/node_modules/tsx/dist/cli.mjs"


@pytest.mark.skipif(not TSX.exists() or not shutil.which("node"), reason="Requires frontend npm ci and Node")
def test_pinned_runner_intervenes_without_changing_the_baseline(tmp_path):
    baseline = json.loads((ROOT / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    a, b = baseline["teamA"]["team_id_master"], baseline["teamB"]["team_id_master"]
    games = baseline["games"]
    for g in games:
        g["ml_overperformance"] = 0
    games[0]["ml_overperformance"] = 3
    names = [
        "age_group_parameters.json",
        "probability_parameters.json",
        "margin_parameters_v2.json",
        "heuristic_outcome_calibration.json",
        "confidence_parameters_v2.json",
    ]
    payload = {
        "schema_version": 1,
        "predictor_revision": "866f30c73a84524028b9fe8e55b3108ec8d544fc",
        "calibrations": {n: json.loads((ROOT / "frontend/public/data/calibration" / n).read_text()) for n in names},
        "cases": [
            {
                "reference_time": "2026-11-11T12:00:00Z",
                "fixture": {"source_game_id": "test"},
                "period": "development",
                "teamA": baseline["teamA"],
                "teamB": baseline["teamB"],
                "games": games,
                "formOverrides": {"residual_sequence": {a: 4, b: -4}},
            }
        ],
    }
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload))
    out = tmp_path / "output.json"
    command = ["node", str(TSX), str(ROOT / "frontend/scripts/run-form-research.ts"), str(source), str(out)]

    def invoke(args, env=None):
        with TemporaryDirectory(prefix="compare-form-research-") as workspace:
            return subprocess.run([*args, workspace], cwd=ROOT / "frontend", capture_output=True, text=True,
                                  timeout=60, env=env)

    run = invoke(command)
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text())
    assert result["aa_parity"] is True
    assert result["model_signature"] == "1718e7be40328a18901f93df30ed31f99581b7b481af71de9277f700462dde05"
    expected = result["outputs"]["baseline"][0]["prediction"]
    candidate = result["outputs"]["residual_sequence"][0]["prediction"]
    assert candidate["components"]["formDiffRaw"] == 8
    assert candidate["components"]["formDiffRaw"] != expected["components"]["formDiffRaw"]
    for key in ["powerDiff", "sosDiff", "matchupAdvantage", "commonOpponentSignal"]:
        assert candidate["components"][key] == expected["components"][key]
    assert candidate != result["outputs"]["residual_sequence_ml_off"][0]["prediction"]
    clock_payload = json.loads(json.dumps(payload))
    clock_payload["cases"][0]["reference_time"] = "2026-08-01T00:00:00Z"
    for game in clock_payload["cases"][0]["games"]:
        game["game_date"] = (datetime.fromisoformat(game["game_date"]) - timedelta(days=120)).date().isoformat()
    for team in (clock_payload["cases"][0]["teamA"], clock_payload["cases"][0]["teamB"]):
        team["team_name"] = "Fixture Academy 17B"
        team["age"] = None
    clock_input = tmp_path / "clock-input.json"
    clock_input.write_text(json.dumps(clock_payload), encoding="utf-8")
    reference_output = tmp_path / "clock-reference.json"
    reference = invoke([*command[:3], str(clock_input), str(reference_output)], env={**os.environ, "TZ": "UTC"})
    assert reference.returncode == 0, reference.stderr
    future_clock = tmp_path / "future-clock.mjs"
    future_clock.write_text(
        "const NativeDate = Date; globalThis.Date = class extends NativeDate {"
        " constructor(...args) { super(...(args.length ? args : ['2030-08-02T00:00:00Z'])); }"
        " static now() { return NativeDate.parse('2030-08-02T00:00:00Z'); } };",
        encoding="utf-8",
    )
    future_output = tmp_path / "clock-future.json"
    with TemporaryDirectory(prefix="compare-form-research-") as workspace:
        future = subprocess.run(
            ["node", "--import", (ROOT / "frontend/node_modules/tsx/dist/loader.mjs").as_uri(),
             "--import", future_clock.as_uri(), command[2], str(clock_input), str(future_output), workspace],
            cwd=ROOT / "frontend", env={**os.environ, "TZ": "America/Los_Angeles"},
            capture_output=True, text=True, timeout=60,
        )
    assert future.returncode == 0, future.stderr
    assert json.loads(future_output.read_text()) == json.loads(reference_output.read_text())
    for g in payload["cases"][0]["games"]:
        g["ml_overperformance"] = -37
    source.write_text(json.dumps(payload))
    changed_out = tmp_path / "changed-ml.json"
    changed = invoke([*command[:-1], str(changed_out)])
    assert changed.returncode == 0, changed.stderr
    changed_result = json.loads(changed_out.read_text())
    assert changed_result["outputs"]["residual_sequence_ml_off"] == result["outputs"]["residual_sequence_ml_off"]
    saved = out.read_bytes()
    rerun = invoke(command)
    assert rerun.returncode != 0 and out.read_bytes() == saved
    payload["predictor_revision"] = "incorrect"
    source.write_text(json.dumps(payload))
    out.unlink()
    invalid = invoke(command)
    assert invalid.returncode != 0 and not out.exists()


@pytest.mark.skipif(not TSX.exists() or not shutil.which("node"), reason="Requires frontend npm ci and Node")
def test_reconstruction_cli_uses_real_baseline_and_truthful_timestamps(tmp_path):
    baseline = json.loads((ROOT / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    calibrations = {
        name: json.loads((ROOT / "frontend/public/data/calibration" / name).read_text())
        for name in CALIBRATION_ROLES.values()
    }
    provenance = {
        "code_revision": PINNED_REVISION, "created_at": "2026-10-31T01:00:00Z",
        "last_calculated": "2026-10-31T00:30:00Z", "snapshot_date": "2026-10-31",
        "trained_at": "2026-10-30T00:00:00Z", "training_cutoff": "2026-10-29",
    }
    fixture = dict(source_game_id="reconstruction-example", game_date="2026-11-01",
                   home_team_master_id="a", away_team_master_id="b")
    payloads = {
        "team_a_snapshot": baseline["teamA"], "team_b_snapshot": baseline["teamB"],
        **{role: calibrations[file] for role, file in CALIBRATION_ROLES.items()},
    }
    for game in baseline["games"]:
        game["result_available_at"] = game["game_date"] + "T12:00:00Z"
        game["result_sha256"] = digest({key: game.get(key) for key in (
            "id", "game_date", "home_team_master_id", "away_team_master_id", "home_score", "away_score",
            "result_available_at",
        )})
        if game.get("ml_overperformance") is not None:
            game["ml_provenance"] = {
                **provenance, "sha256": digest({"id": game["id"], "ml_overperformance": game["ml_overperformance"]}),
            }
    case = {
        **baseline, "fixture": {**fixture, "home_score": 100, "away_score": 0},
        "formOverrides": {"forbidden-candidate": {"a": 100, "b": -100}},
        "input_provenance": [{**provenance, "role": role, "sha256": digest(value)} for role, value in payloads.items()],
    }
    payload = dict(schema_version=1, predictor_revision=PINNED_REVISION, calibrations=calibrations, cases=[case])
    source = tmp_path / "inputs.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "reconstructed"
    command = [sys.executable, str(ROOT / "scripts/benchmark_compare_form.py"), "--input", str(source),
               "--reconstruct-expectations", "--output-dir", str(out)]
    preview = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["status"] == "reconstruction_inputs_ready" and not out.exists()
    started = datetime.now(timezone.utc)
    run = subprocess.run([*command, "--execute"], capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["status"] == "reconstructed" and report["historical_selection"] == "not_performed"
    expected = json.loads((out / "expectations.json").read_text())[fixture["source_game_id"]]
    assert started <= datetime.fromisoformat(expected["provenance"]["created_at"]) <= datetime.now(timezone.utc)
    assert valid_expectation(expected, {**fixture, "id": fixture["source_game_id"]})
    receipt = expected["reconstruction"]
    assert "home_score" not in receipt["inputs"]["fixture"]
    assert "formOverrides" not in receipt["inputs"]
    runner = json.loads((out / "runner-output.json").read_text())
    assert set(runner["outputs"]) == {"baseline"}
    assert receipt["prediction"] == runner["outputs"]["baseline"][0]["prediction"]
    assert receipt["model_signature"] == "1718e7be40328a18901f93df30ed31f99581b7b481af71de9277f700462dde05"
    assert receipt["inputs"]["reference_time"] == "2026-10-31T23:59:59.999+00:00"
    original = (out / "expectations.json").read_bytes()
    duplicate = subprocess.run([*command, "--execute"], capture_output=True, text=True, timeout=60)
    assert duplicate.returncode != 0 and (out / "expectations.json").read_bytes() == original
