"""Drive the real TypeScript verifier against the pinned collector's input hash contract."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from src.predictions.form_policy import PINNED_MODEL_SIGNATURE, PINNED_REVISION

ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "frontend/node_modules/tsx/dist/loader.mjs"


@pytest.mark.skipif(not LOADER.exists() or not shutil.which("node"), reason="Requires frontend npm ci and Node")
def test_source_verifier_checks_the_collector_hash_identity_and_cutoff(tmp_path):
    sample = json.loads((ROOT / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    calibration_files = {
        "ageGroups": "age_group_parameters.json", "probability": "probability_parameters.json",
        "margin": "margin_parameters_v2.json", "outcome": "heuristic_outcome_calibration.json",
        "confidence": "confidence_parameters_v2.json",
    }
    calibrations = {key: json.loads((ROOT / "frontend/public/data/calibration" / name).read_text())
                    for key, name in calibration_files.items()}
    version = "heuristic_v6_canonical_evidence_v1"
    row = {
        "id": "forecast", "fixture_key": "database:fixture", "game_date": "2026-11-14",
        "source_game_id": "fixture", "provider_code": "gotsport", "source_system": "database_games",
        "home_team_master_id": sample["teamA"]["team_id_master"],
        "away_team_master_id": sample["teamB"]["team_id_master"], "fixture_payload": {"cohort": "u13|Male"},
        "heuristic_prediction_status": "completed", "heuristic_model_version": version,
        "heuristic_predicted_at": "2026-11-11 12:00:00.123456+00:00",
        "heuristic_prediction": {
            "modelVersion": version, "codeRevision": PINNED_REVISION, "modelSignature": PINNED_MODEL_SIGNATURE,
            "response": {"prediction": sample["prediction"]},
            "shadowContext": {"predictorVersion": version, "teamAInput": sample["teamA"],
                              "teamBInput": sample["teamB"], "frozenEvidence": {"games": sample["games"]},
                              "calibration": calibrations, "preOutcomeCalibration": [.4, .3, .3]},
        },
    }
    hour_only = deepcopy(row)
    hour_only["id"] = "hour-only"
    hour_only["heuristic_predicted_at"] = "2026-11-11 12:00:00.123456+00"
    variants = [("valid", row), ("hour-only", hour_only)]
    for name in ("input_hash", "calibration", "orientation", "timestamp", "model_version", "projection",
                 "source_fixture", "incomplete", "code_revision", "timezone", "invalid_day", "signature"):
        changed = deepcopy(row)
        changed["id"] = name
        payload = changed["heuristic_prediction"]
        if name == "calibration":
            payload["shadowContext"]["calibration"]["outcome"] = {}
        elif name == "orientation":
            payload["shadowContext"]["teamAInput"]["team_id_master"] = "wrong-team"
        elif name == "timestamp":
            changed["heuristic_predicted_at"] = "2026-11-14T00:00:00Z"
        elif name == "model_version":
            payload["shadowContext"]["predictorVersion"] = "later"
        elif name == "projection":
            del changed["fixture_payload"]
        elif name == "source_fixture":
            changed["fixture_key"] = "database:different-fixture"
        elif name == "incomplete":
            payload["shadowContext"].pop("frozenEvidence")
        elif name == "code_revision":
            payload["codeRevision"] = "not-a-commit"
        elif name == "timezone":
            changed["heuristic_predicted_at"] = "2026-11-11T12:00:00"
        elif name == "invalid_day":
            changed["game_date"] = "2026-02-30"
        elif name == "signature":
            payload["modelSignature"] = "0" * 64
        variants.append((name, changed))
    source = tmp_path / "input.json"
    source.write_text(json.dumps([value for _, value in variants]), encoding="utf-8")
    # Use the collector's actual JS serialization, including its float representation.
    hash_script = tmp_path / "hash.mjs"
    hash_script.write_text(
        "import {readFile,writeFile} from 'node:fs/promises'; import {createHash} from 'node:crypto';"
        f"import {{stableJson}} from {json.dumps((ROOT / 'frontend/lib/canonicalJson.ts').as_uri())};"
        "const rows=JSON.parse(await readFile(process.argv[2],'utf8'));"
        "const fields='id,fixture_key,game_date,source_game_id,provider_code,home_team_master_id,"
        "away_team_master_id,fixture_payload'.split(',');"
        "for(const row of rows){const fixture=Object.fromEntries(fields.filter(k=>k in row).map(k=>[k,row[k]]));"
        "row.heuristic_prediction.inputHash=createHash('sha256').update(stableJson({fixture,"
        "context:row.heuristic_prediction.shadowContext})).digest('hex');}"
        "rows[2].heuristic_prediction.inputHash='0'.repeat(64);"
        "await writeFile(process.argv[2],JSON.stringify([...rows,null]));",
        encoding="utf-8",
    )
    generated = subprocess.run(["node", "--import", LOADER.as_uri(), str(hash_script), str(source)],
                               capture_output=True, text=True, timeout=30)
    assert generated.returncode == 0, generated.stderr
    output = tmp_path / "verified.json"
    command = ["node", "--import", LOADER.as_uri(), str(ROOT / "frontend/scripts/verify-compare-source.ts"),
               str(source), str(output)]
    checked = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stderr
    receipts = json.loads(output.read_text())["receipts"]
    valid = receipts[0]
    assert valid["verified"] and not valid["authority_verified"]
    assert valid["model_signature"] == "1718e7be40328a18901f93df30ed31f99581b7b481af71de9277f700462dde05"
    assert valid["reference_time"] == "2026-11-11T12:00:00.123Z"
    assert valid["id"] == "forecast"
    assert receipts[1]["verified"] and receipts[1]["reference_time"] == "2026-11-11T12:00:00.123Z"
    assert receipts[1]["id"] == "hour-only" and not receipts[1]["authority_verified"]
    expected = {
        "input_hash": "frozen_input_hash_mismatch", "calibration": "baseline_model_signature_changed",
        "orientation": "frozen_team_orientation_mismatch", "timestamp": "invalid_pre_match_timestamp",
        "model_version": "invalid_frozen_fixture", "projection": "missing_fixture_member",
        "source_fixture": "invalid_frozen_fixture", "incomplete": "missing_object",
        "code_revision": "invalid_code_revision", "timezone": "invalid_pre_match_timestamp",
        "invalid_day": "invalid_pre_match_timestamp", "signature": "baseline_model_signature_changed",
    }
    assert len(receipts) == 15
    assert [receipt["id"] for receipt in receipts[2:-1]] == list(expected)
    for receipt in receipts[2:-1]:
        assert not receipt["verified"] and receipt["reason"] == expected[receipt["id"]]
    assert receipts[-1] == {"verified": False, "id": None, "reason": "missing_object"}
    saved = output.read_bytes()
    duplicate = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert duplicate.returncode != 0 and output.read_bytes() == saved
