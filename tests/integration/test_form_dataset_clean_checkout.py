"""Exercise the real clean-revision, source-verification and assembly path with simulated private services."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmark_compare_form import run_predictor
from src.predictions import form_dataset
from src.predictions.forecast_archive import FORECAST_FIELDS
from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES, PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.predictions.form_study import register_form_study
from src.rankings import input_archive
from src.rankings.archive_storage import publish_archive
from src.rankings.input_archive import FORECAST_TABLE, InputArchive
from tests.unit.test_form_dataset import DatasetServer

ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "frontend/node_modules/tsx/dist/loader.mjs"


@pytest.mark.skipif(not LOADER.exists() or not shutil.which("node"), reason="Requires frontend npm ci and Node")
def test_clean_registered_revision_assembles_and_reauthenticates_a_real_node_forecast(tmp_path, monkeypatch):
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        pytest.skip("Requires a clean committed checkout; run after commit and in CI")
    server = DatasetServer()
    monkeypatch.setattr(input_archive, "utc_now", lambda: "2026-11-12T00:00:00Z")
    server.recorded_at = "2026-11-12T01:00:00Z"
    study = tmp_path / "study"
    registered = register_form_study(server, ROOT, study, dry_run=False)
    sample = json.loads((ROOT / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    calibrations = {name: json.loads((ROOT / "frontend/public/data/calibration" / name).read_text())
                    for name in CALIBRATION_SNAPSHOT_FILES.values()}
    replay = tmp_path / "replay"
    replay.mkdir()
    case = {**{key: sample[key] for key in ("teamA", "teamB", "games")},
            "reference_time": "2026-11-19T12:00:00.000Z", "fixture": {"source_game_id": "target"}}
    result = run_predictor({"schema_version": 1, "predictor_revision": PINNED_REVISION,
                            "calibrations": calibrations, "cases": [case]}, replay)
    row = {name: None for name in FORECAST_FIELDS.split(",")}
    home, away = [sample[key]["team_id_master"] for key in ("teamA", "teamB")]
    snapshot = {"id": "target", "game_date": "2026-11-20", "home_team_master_id": home,
                "away_team_master_id": away, "provider_id": "p", "source_url": "https://x/events/100/matches/1"}
    version = "heuristic_v6_canonical_evidence_v1"
    row.update(id="forecast-target", source_game_id="target", fixture_key="database:target", game_date="2026-11-20",
               provider_code="gotsport", source_system="database_games", source_event_id="100",
               evaluation_group_kind="event", evaluation_group_key="gotsport:100",
               home_team_master_id=home, away_team_master_id=away, fixture_payload={"source_snapshot": snapshot},
               heuristic_prediction_status="completed", heuristic_model_version=version,
               heuristic_predicted_at="2026-11-19T12:00:00.000Z", heuristic_prediction={
                   "modelVersion": version, "codeRevision": PINNED_REVISION, "modelSignature": PINNED_MODEL_SIGNATURE,
                   "response": {"prediction": result["outputs"]["baseline"][0]["prediction"]},
                   "shadowContext": {"predictorVersion": version, "teamAInput": sample["teamA"],
                                     "teamBInput": sample["teamB"], "calibration": {
                                         key: calibrations[name] for key, name in CALIBRATION_SNAPSHOT_FILES.items()
                                     }, "preOutcomeCalibration": [.4, .3, .3],
                                     "frozenEvidence": {"as_of": "2026-11-19", "games": sample["games"]}},
               })
    script = tmp_path / "hash.mjs"
    script.write_text(
        "import{createHash}from'node:crypto';"
        f"import{{stableJson}}from{json.dumps((ROOT / 'frontend/lib/canonicalJson.ts').as_uri())};"
        "let text='';for await(const chunk of process.stdin)text+=chunk;const row=JSON.parse(text);"
        "const fields='id,fixture_key,game_date,source_game_id,provider_code,home_team_master_id,"
        "away_team_master_id,fixture_payload'.split(',');"
        "const fixture=Object.fromEntries(fields.map(key=>[key,row[key]]));"
        "row.heuristic_prediction.inputHash=createHash('sha256').update(stableJson({fixture,"
        "context:row.heuristic_prediction.shadowContext})).digest('hex');process.stdout.write(JSON.stringify(row));",
        encoding="utf-8",
    )
    hashed = subprocess.run(["node", "--import", LOADER.as_uri(), str(script)], input=json.dumps(row),
                            text=True, capture_output=True, timeout=30, check=True)
    row = json.loads(hashed.stdout)
    monkeypatch.setattr(input_archive, "utc_now", lambda: "2026-11-19T13:00:00Z")
    captured = InputArchive(tmp_path / "captured", ROOT, {"capture_kind": "frozen_compare_forecasts"})
    captured.query(FORECAST_TABLE, [["select", [FORECAST_FIELDS], {}]],
                   SimpleNamespace(data=[row]), input_archive.utc_now(), "select")
    captured.finish(True)
    server.recorded_at = "2026-11-19T14:00:00Z"
    publish_archive(server, captured.directory, dry_run=False)
    server.ledger[row["id"]] = {**row, "evaluation_status": "settled", "actual_game_id": "target",
                               "actual_home_score": 2, "actual_away_score": 0, "actual_outcome": "team_a"}
    server.games["target"] = {**snapshot, "home_score": 2, "away_score": 0, "is_excluded": False}
    # Substitute external authority transport only. All study/code/source/content/cohort guards remain real.
    monkeypatch.setattr(form_dataset, "registered_inventory", lambda *args: {
        "as_of": "2027-01-11T00:00:00Z",
        "archives": sorted(server.rows.values(), key=lambda row: row["manifest_sha256"]),
    })
    output = tmp_path / "dataset"
    report = form_dataset.assemble_dataset(server, "url", "token", study, output, dry_run=False)
    assert report["cases"] == 1 and report["study_manifest_sha256"] == registered["manifest_sha256"]
    report, verified = form_dataset.verified_dataset(server, "url", "token", output)
    assert report["status"] == "insufficient_data" and report["production_promotion"] is False
    assert report["audit"]["periods"]["development"] == {"games": 1, "groups": 1}
    assert report["audit"]["periods"]["evaluation"] == {"games": 0, "groups": 0}
    assert len(verified[3]) == 1
