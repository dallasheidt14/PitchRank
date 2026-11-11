"""Real Node/TypeScript research intervention, with local calibration and no database."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

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
    run = subprocess.run(command, cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text())
    assert result["aa_parity"] is True
    expected = result["outputs"]["baseline"][0]["prediction"]
    candidate = result["outputs"]["residual_sequence"][0]["prediction"]
    assert candidate["components"]["formDiffRaw"] == 8
    assert candidate["components"]["formDiffRaw"] != expected["components"]["formDiffRaw"]
    for key in ["powerDiff", "sosDiff", "matchupAdvantage", "commonOpponentSignal"]:
        assert candidate["components"][key] == expected["components"][key]
    assert candidate != result["outputs"]["residual_sequence_ml_off"][0]["prediction"]
    saved = out.read_bytes()
    rerun = subprocess.run(command, cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60)
    assert rerun.returncode != 0 and out.read_bytes() == saved
    payload["predictor_revision"] = "incorrect"
    source.write_text(json.dumps(payload))
    out.unlink()
    invalid = subprocess.run(command, cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60)
    assert invalid.returncode != 0 and not out.exists()
