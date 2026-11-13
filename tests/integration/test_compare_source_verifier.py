"""Drive the real TypeScript verifier against the pinned collector's input hash contract."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.predictions.form_policy import PINNED_MODEL_SIGNATURE, PINNED_REVISION

ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "frontend/node_modules/tsx/dist/loader.mjs"


@pytest.mark.skipif(not LOADER.exists() or not shutil.which("node"), reason="Requires frontend npm ci and Node")
def test_source_verifier_checks_the_collector_hash_identity_and_cutoff(tmp_path, monkeypatch):
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
        "away_team_master_id": sample["teamB"]["team_id_master"],
        "fixture_payload": {"cohort": "u13|Male", "source_snapshot": {
            "game_date": "2026-11-14", "home_team_master_id": sample["teamA"]["team_id_master"],
            "away_team_master_id": sample["teamB"]["team_id_master"],
        }},
        "heuristic_prediction_status": "completed", "heuristic_model_version": version,
        "heuristic_predicted_at": "2026-11-11 12:00:00.123456+00:00",
        "heuristic_prediction": {
            "modelVersion": version, "codeRevision": PINNED_REVISION, "modelSignature": PINNED_MODEL_SIGNATURE,
            "response": {"prediction": sample["prediction"]},
            "shadowContext": {"predictorVersion": version, "teamAInput": sample["teamA"],
                              "teamBInput": sample["teamB"],
                              "frozenEvidence": {"as_of": "2026-11-11", "games": sample["games"]},
                              "calibration": calibrations, "preOutcomeCalibration": [.4, .3, .3]},
        },
    }
    hour_only = deepcopy(row)
    hour_only["id"] = "hour-only"
    hour_only["heuristic_predicted_at"] = "2026-11-11 12:00:00.123456+00"
    aliased = deepcopy(row)
    aliased["id"] = "aliased"
    aliased["home_team_master_id"] = "alias-a"
    aliased["heuristic_prediction"]["shadowContext"]["resolvedTeamAIds"] = [
        sample["teamA"]["team_id_master"], "alias-a",
    ]
    aliased["heuristic_prediction"]["shadowContext"]["resolvedTeamBIds"] = [sample["teamB"]["team_id_master"]]
    variants = [("valid", row), ("hour-only", hour_only), ("aliased", aliased)]
    for name in ("input_hash", "calibration", "orientation", "timestamp", "model_version", "projection",
                 "source_fixture", "incomplete", "code_revision", "timezone", "invalid_day", "signature",
                 "alias_overlap", "invalid_aliases", "source_mapping", "source_date"):
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
        elif name == "alias_overlap":
            payload["shadowContext"]["resolvedTeamBIds"] = [changed["home_team_master_id"]]
        elif name == "invalid_aliases":
            payload["shadowContext"]["resolvedTeamAIds"] = "unverified-alias-list"
        elif name == "source_mapping":
            changed["fixture_payload"]["source_snapshot"]["home_team_master_id"] = "unrelated-source-team"
        elif name == "source_date":
            changed["fixture_payload"]["source_snapshot"]["game_date"] = "2026-11-15"
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
        "rows[3].heuristic_prediction.inputHash='0'.repeat(64);"
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
    assert receipts[2]["verified"] and receipts[2]["id"] == "aliased" and not receipts[2]["authority_verified"]
    expected = {
        "input_hash": "frozen_input_hash_mismatch", "calibration": "baseline_model_signature_changed",
        "orientation": "frozen_team_orientation_mismatch", "timestamp": "invalid_pre_match_timestamp",
        "model_version": "invalid_frozen_fixture", "projection": "missing_fixture_member",
        "source_fixture": "invalid_frozen_fixture", "incomplete": "missing_object",
        "code_revision": "invalid_code_revision", "timezone": "invalid_pre_match_timestamp",
        "invalid_day": "invalid_pre_match_timestamp", "signature": "baseline_model_signature_changed",
        "alias_overlap": "frozen_team_orientation_mismatch", "invalid_aliases": "frozen_team_orientation_mismatch",
        "source_mapping": "frozen_source_team_mapping_mismatch", "source_date": "frozen_source_snapshot_mismatch",
    }
    assert len(receipts) == 20
    assert [receipt["id"] for receipt in receipts[3:-1]] == list(expected)
    for receipt in receipts[3:-1]:
        assert not receipt["verified"] and receipt["reason"] == expected[receipt["id"]]
    assert receipts[-1] == {"verified": False, "id": None, "reason": "missing_object"}
    streamed = subprocess.run([*command[:-2], "-", "-"], input=source.read_text(encoding="utf-8"),
                             capture_output=True, text=True, timeout=60)
    assert streamed.returncode == 0, streamed.stderr
    assert json.loads(streamed.stdout) == json.loads(output.read_text())
    from src.predictions.archive_inputs import authenticate_archive
    from src.predictions.form_archive_sources import FrozenSourceIndex, _source_checks
    from src.predictions.form_research import prediction_input_error
    from src.rankings import input_archive
    from src.rankings.archive_storage import publish_archive
    from src.rankings.input_archive import InputArchive
    from tests.unit.test_ranking_archive_storage import FakeServer

    parsed = json.loads(source.read_text(encoding="utf-8"))
    assert _source_checks(parsed[:-1], ROOT) == receipts[:-1]
    monkeypatch.setattr(input_archive, "utc_now", lambda: "2026-11-11T13:00:00Z")
    captured = InputArchive(tmp_path / "source-archive", ROOT, {"capture_kind": "frozen_compare_forecasts"})
    captured.query("prospective_match_predictions", [["select", ["*"], {}]],
                   SimpleNamespace(data=[parsed[2]]), input_archive.utc_now(), "select")
    captured.finish(True)
    server = FakeServer(recorded_at=input_archive.utc_now())
    publish_archive(server, captured.directory, dry_run=False)
    authenticated = authenticate_archive(server, captured.directory)
    sources = FrozenSourceIndex([authenticated], ROOT)
    binding = authenticated.frozen_rows()[0]["binding"]
    case = {**sources.case_inputs(binding), "predictor_revision": PINNED_REVISION,
            "fixture": {"source_game_id": "fixture", "game_date": "2026-11-14",
                        "home_team_master_id": sample["teamA"]["team_id_master"],
                        "away_team_master_id": sample["teamB"]["team_id_master"]}}
    assert sources.record(binding)["home_team_master_id"] == "alias-a"
    assert sources.metadata(binding)["home_team_master_id"] == sample["teamA"]["team_id_master"]
    assert prediction_input_error(case, "2026-11-14") == "unverified_archive_witness"
    assert prediction_input_error(case, "2026-11-14", sources) is None
    assert "input_provenance" not in case
    saved = output.read_bytes()
    duplicate = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert duplicate.returncode != 0 and output.read_bytes() == saved
