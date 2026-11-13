import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from storage3.exceptions import StorageApiError

from src.predictions import weekend_tuning as tuning
from src.predictions import weekend_tuning_report as reporting
from src.predictions.form_dataset import FORECAST_FIELDS


def prediction():
    return {
        "winProbabilityA": 0.6,
        "drawProbability": 0.2,
        "winProbabilityB": 0.2,
        "predictedWinner": "team_a",
        "expectedMargin": 1,
        "expectedScore": {"teamA": 2, "teamB": 1},
        "blowout4PlusProbability": 0.1,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"drawProbability": float("nan")},
        {"winProbabilityA": 1.1},
        {"blowout4PlusProbability": None},
        {"blowout4PlusProbability": 2},
        {"expectedMargin": None},
        {"expectedScore": {"teamA": 2}},
    ],
)
def test_incomplete_arm_cannot_be_frozen(change):
    with pytest.raises(ValueError, match="Incomplete"):
        tuning.prediction_check({**prediction(), **change})


def test_registration_and_outcome_boundaries_are_utc_and_strict():
    tuning.require_registration_time("2026-11-13T23:59:59.999Z")
    with pytest.raises(ValueError, match="deadline"):
        tuning.require_registration_time("2026-11-13T17:00:00-07:00")
    assert not reporting.results_open("2026-11-15T23:59:59Z")
    assert reporting.results_open("2026-11-15T17:00:00-07:00")
    assert tuning.DEFINITION["match_end"] < "2026-11-16"


def test_preclose_evaluation_never_reads_results_or_storage():
    class Forbidden:
        def __getattr__(self, key):
            raise AssertionError("Early query: " + key)

    result = reporting.evaluate(Forbidden(), "a" * 64, None, "2026-11-15T23:59:59Z", dry_run=False)
    assert result["status"] == "waiting_for_window_close" and not result["outcomes_read"]


class PrivateStorage:
    def __init__(self):
        self.objects, self.uploads = {}, []
        self.storage = self
        self.lose_marker_ack = False

    def from_(self, bucket):
        assert bucket == "prediction-input-archives"
        return self

    def upload(self, key, raw, options):
        assert options["upsert"] == "false"
        self.uploads.append(key)
        if key in self.objects:
            raise StorageApiError("exists", "Duplicate", 409)
        self.objects[key] = raw
        if key.endswith("report.json") and self.lose_marker_ack:
            raise TimeoutError("acknowledgement lost")

    def download(self, key):
        if key not in self.objects:
            raise StorageApiError("missing", "not_found", 404)
        return self.objects[key]


@pytest.mark.parametrize("lost_ack", [False, True])
def test_first_report_wins_and_lost_upload_ack_is_verified(lost_ack):
    client = PrivateStorage()
    client.lose_marker_ack = lost_ack
    report = {
        "study_manifest_sha256": "a" * 64,
        "definition": tuning.DEFINITION,
        "status": "preliminary_diagnostic",
        "server_observed_at": "2026-11-16T17:20:00Z",
        "paired_settled_matches": 1001,
    }
    assert reporting.save_final(client, report) == report
    assert reporting.save_final(client, {**report, "paired_settled_matches": 1200}) == report
    uploads = len(client.uploads)
    # Reuse must not touch the result tables, even if more matches have settled.
    result = reporting.evaluate(client, "a" * 64, None, "2026-11-18T17:20:00Z", dry_run=False)
    assert result["reused_final_report"] and result["paired_settled_matches"] == 1001
    assert len(client.uploads) == uploads


def test_final_result_object_tampering_is_rejected():
    client = PrivateStorage()
    report = {
        "study_manifest_sha256": "a" * 64,
        "definition": tuning.DEFINITION,
        "status": "insufficient_data",
        "server_observed_at": "2026-11-23T00:00:00Z",
    }
    reporting.save_final(client, report)
    key = next(k for k in client.objects if k.startswith("objects/"))
    client.objects[key] = b"corrupt"
    with pytest.raises((ValueError, OSError)):
        reporting.read_final(client, "a" * 64)


class ResultClient(PrivateStorage):
    """Deferred queries project only selected columns and reject broad scans."""

    def __init__(self, raw, settled, game):
        super().__init__()
        self.rows = {"prospective_match_predictions": [settled], "games": [game]}
        self.queries = []

    def table(self, table):
        parent = self

        class Query:
            def select(self, fields):
                self.fields = fields.split(",")
                return self

            def in_(self, key, values):
                assert key == "id" and len(values) <= 100
                self.ids = values
                return self

            def order(self, key):
                assert key == "id"
                self.ordered = True
                return self

            def range(self, first, last):
                assert self.ordered and first == 0
                return self

            def execute(self):
                parent.queries.append((table, self.fields, self.ids))
                return SimpleNamespace(
                    data=[{k: row.get(k) for k in self.fields} for row in parent.rows[table] if row["id"] in self.ids]
                )

        return Query()


def fixture_set():
    source = {
        "id": "g",
        "game_date": "2026-11-14",
        "home_team_master_id": "a",
        "away_team_master_id": "b",
        "provider_id": "p",
        "source_url": "https://x/match/1",
    }
    raw = {k: None for k in FORECAST_FIELDS.split(",")}
    raw.update(id="f", source_game_id="g", game_date="2026-11-14", fixture_payload={"source_snapshot": source})
    settled = {
        **raw,
        "evaluation_status": "settled",
        "actual_game_id": "g",
        "actual_home_score": 1,
        "actual_away_score": 1,
        "actual_outcome": "draw",
    }
    game = {**source, "home_score": 1, "away_score": 1, "is_excluded": False}
    fixture = {
        "source_game_id": "g",
        "game_date": "2026-11-14",
        "home_team_master_id": "a",
        "away_team_master_id": "b",
        "event_group": "event",
        "group_kind": "event",
        "provider": "gotsport",
        "cohort": "u12|Male",
        "history_band": "8+",
    }
    meta = {
        **fixture,
        "id": "f",
        "binding": {},
        "duplicate_sources": [],
        "coverage": {k: fixture[k] for k in ("provider", "cohort", "history_band")},
    }
    sources = SimpleNamespace(record=lambda binding: raw)
    records = [{"fixture": fixture, "predictions": {arm: prediction() for arm in tuning.ARMS}}]
    return ResultClient(raw, settled, game), (sources, [meta], [meta], records)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"actual_game_id": "other"}, "not_exact_source_settlement"),
        ({"heuristic_model_version": "changed"}, "completed_forecast_changed"),
        ({"evaluation_status": "pending"}, "unsettled_result"),
    ],
)
def test_settlement_failures_are_reported_without_partial_arm_evaluation(change, reason):
    client, loaded = fixture_set()
    client.rows["prospective_match_predictions"][0].update(change)
    result = reporting.evaluate(client, "a" * 64, loaded, "2026-11-16T17:20:00Z", dry_run=False)
    assert result["paired_settled_matches"] == 0 and result["exclusions"] == {reason: 1}
    assert not result["report_saved"] and not client.uploads
    assert all(
        ids == ["f"] if table == "prospective_match_predictions" else ids == ["g"] for table, _, ids in client.queries
    )


def test_insufficient_cohort_waits_then_freezes_without_accuracy_metrics():
    client, loaded = fixture_set()
    pending = reporting.evaluate(client, "a" * 64, loaded, "2026-11-16T17:20:00Z", dry_run=False)
    assert pending["status"] == "awaiting_results" and not client.uploads
    final = reporting.evaluate(client, "a" * 64, loaded, "2026-11-23T00:00:00Z", dry_run=False)
    assert final["status"] == "insufficient_data" and final["report_saved"]
    report = reporting.read_final(client, "a" * 64)
    assert "metrics" not in report and report["paired_settled_matches"] == 1
    assert report["outcome_snapshot"]["games"]["g"]["home_score"] == 1


def test_draw_metrics_and_paired_bootstrap_are_deterministic_and_orientation_invariant():
    _, loaded = fixture_set()
    records = loaded[3]
    cases = [{"fixture": {**records[0]["fixture"], "home_score": 1, "away_score": 1}}]
    metrics = reporting._metrics(cases, records)
    assert metrics["metrics"]["baseline"]["log_loss"] == pytest.approx(-np.log(0.2))
    assert metrics["metrics"]["baseline"]["brier_score"] == pytest.approx(1.04)
    assert metrics["metrics"]["baseline"]["blowout_4plus_brier"] == pytest.approx(0.01)
    assert metrics["comparisons"]["form_off"]["log_loss"]["upper"] == 0
    swapped = deepcopy(records)
    for p in swapped[0]["predictions"].values():
        p["winProbabilityA"], p["winProbabilityB"] = p["winProbabilityB"], p["winProbabilityA"]
        p["expectedMargin"] *= -1
        p["predictedWinner"] = "team_b"
    assert (
        reporting._metrics(cases, swapped)["metrics"]["baseline"]["log_loss"]
        == metrics["metrics"]["baseline"]["log_loss"]
    )
    assert reporting.paired_interval(["a", "a", "b"], np.array([1.0, -1.0, 2.0])) == reporting.paired_interval(
        ["a", "a", "b"], np.array([1.0, -1.0, 2.0])
    )


def test_real_predictor_replays_only_the_declared_two_changes(tmp_path):
    from scripts.benchmark_compare_form import run_predictor
    from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES, PINNED_REVISION

    root = Path(__file__).resolve().parents[2]
    sample = json.loads((root / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    calibrations = {
        name: json.loads((root / "frontend/public/data/calibration" / name).read_text())
        for name in CALIBRATION_SNAPSHOT_FILES.values()
    }
    case = {
        **{k: sample[k] for k in ("teamA", "teamB", "games")},
        "reference_time": "2026-11-12T12:00:00Z",
        "fixture": {"source_game_id": "g"},
        "calibrations": calibrations,
    }
    seed = tmp_path / "seed"
    seed.mkdir()
    frozen = run_predictor(
        {"schema_version": 1, "predictor_revision": PINNED_REVISION, "cases": [case], "calibrations": calibrations},
        seed,
    )
    case["frozenPrediction"] = frozen["outputs"]["baseline"][0]["prediction"]
    records, receipts = tuning.replay_candidates([case], run_predictor, tmp_path)
    assert records[0]["predictions"]["baseline"] == case["frozenPrediction"]
    assert set(records[0]["predictions"]) == set(tuning.ARMS)
    assert len(receipts) == 1 and receipts[0]["runs"][0]["aa_parity"]
    assert receipts[0]["runs"][1]["model_signature"] != receipts[0]["runs"][0]["model_signature"]
    assert case["calibrations"]["heuristic_outcome_calibration.json"]["alpha"] == 0.55


@pytest.mark.parametrize(
    "mode,time,execute",
    [
        ("prepare", "2026-11-13T00:00:00Z", False),
        ("report", "2026-11-15T23:59:59Z", True),
        ("report", "2026-11-16T00:00:00Z", False),
    ],
)
def test_cli_preview_and_sealed_execute_create_no_files(tmp_path, monkeypatch, capsys, mode, time, execute):
    import sys

    import supabase
    from scripts import compare_weekend_tuning as cli

    output = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        sys,
        "argv",
        ["compare_weekend_tuning", mode, "a" * 64, "--output-dir", str(output), *(["--execute"] if execute else [])],
    )
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN"):
        monkeypatch.setenv(key, "test")
    monkeypatch.setattr(supabase, "create_client", lambda *args: object())
    monkeypatch.setattr(cli, "registered_inventory", lambda *args: {"as_of": time})
    monkeypatch.setattr(
        cli, "_registered_manifest", lambda *args: ({}, {"weekend_tuning": {"definition": tuning.DEFINITION}}, b"{}")
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Preview entered execution")

    monkeypatch.setattr(cli, "download_archive", forbidden)
    monkeypatch.setattr(cli, "register_bundle", forbidden)
    monkeypatch.setattr(cli, "replay_candidates", forbidden)
    cli.main()
    report = json.loads(capsys.readouterr().out)
    assert not report["outcomes_read"] and not output.exists()


def test_cli_reuses_final_report_before_downloading(tmp_path, monkeypatch, capsys):
    import sys

    import supabase
    from scripts import compare_weekend_tuning as cli

    output = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        sys, "argv", ["compare_weekend_tuning", "report", "a" * 64, "--output-dir", str(output), "--execute"]
    )
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN"):
        monkeypatch.setenv(key, "test")
    monkeypatch.setattr(supabase, "create_client", lambda *args: object())
    monkeypatch.setattr(cli, "registered_inventory", lambda *args: {"as_of": "2026-11-17T17:20:00Z"})
    monkeypatch.setattr(
        cli, "_registered_manifest", lambda *args: ({}, {"weekend_tuning": {"definition": tuning.DEFINITION}}, b"{}")
    )
    report = {
        "status": "preliminary_diagnostic",
        "paired_settled_matches": 1001,
        "metrics": {"sentinel": "never-print-metrics"},
        "outcome_snapshot": "never-print-scores",
    }
    monkeypatch.setattr(cli, "read_final", lambda *args: report)

    def forbidden(*args, **kwargs):
        raise AssertionError("Final report caused a download")

    monkeypatch.setattr(cli, "download_archive", forbidden)
    monkeypatch.setattr(cli, "evaluate", forbidden)
    cli.main()
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == reporting.final_summary(report) and not output.exists()
    assert "never-print" not in stdout


def test_authenticated_weekend_registration_and_reload(tmp_path, monkeypatch):
    import subprocess

    from scripts.benchmark_compare_form import run_predictor
    from src.predictions.archive_inputs import authenticate_archive
    from src.predictions.form_archive_sources import FrozenSourceIndex
    from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES, PINNED_MODEL_SIGNATURE, PINNED_REVISION
    from src.rankings import input_archive
    from src.rankings.archive_storage import publish_archive
    from tests.unit.test_form_dataset import DatasetServer

    root = Path(__file__).resolve().parents[2]
    sample = json.loads((root / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    calibrations = {
        name: json.loads((root / "frontend/public/data/calibration" / name).read_text())
        for name in CALIBRATION_SNAPSHOT_FILES.values()
    }
    initial = tmp_path / "initial"
    initial.mkdir()
    case = {
        **{key: sample[key] for key in ("teamA", "teamB", "games")},
        "reference_time": "2026-11-12T12:00:00.000Z",
        "fixture": {"source_game_id": "target"},
    }
    result = run_predictor(
        {"schema_version": 1, "predictor_revision": PINNED_REVISION, "calibrations": calibrations, "cases": [case]},
        initial,
    )
    home, away = [sample[key]["team_id_master"] for key in ("teamA", "teamB")]
    snapshot = {
        "id": "target",
        "game_date": "2026-11-14",
        "home_team_master_id": home,
        "away_team_master_id": away,
        "provider_id": "p",
        "source_url": "https://x/events/100/matches/1",
    }
    version = "heuristic_v6_canonical_evidence_v1"
    row = {key: None for key in FORECAST_FIELDS.split(",")}
    row.update(
        id="forecast-target",
        source_game_id="target",
        fixture_key="database:target",
        game_date="2026-11-14",
        provider_code="gotsport",
        source_system="database_games",
        source_event_id="100",
        evaluation_group_kind="event",
        evaluation_group_key="gotsport:100",
        home_team_master_id=home,
        away_team_master_id=away,
        fixture_payload={"source_snapshot": snapshot},
        heuristic_prediction_status="completed",
        heuristic_model_version=version,
        heuristic_predicted_at="2026-11-12T12:00:00.000Z",
        heuristic_prediction={
            "modelVersion": version,
            "codeRevision": PINNED_REVISION,
            "modelSignature": PINNED_MODEL_SIGNATURE,
            "response": {"prediction": result["outputs"]["baseline"][0]["prediction"]},
            "shadowContext": {
                "predictorVersion": version,
                "teamAInput": sample["teamA"],
                "teamBInput": sample["teamB"],
                "calibration": {key: calibrations[name] for key, name in CALIBRATION_SNAPSHOT_FILES.items()},
                "preOutcomeCalibration": [0.4, 0.3, 0.3],
                "frozenEvidence": {"as_of": "2026-11-12", "games": sample["games"]},
            },
        },
    )
    script = tmp_path / "hash.mjs"
    script.write_text(
        "import{createHash}from'node:crypto';"
        f"import{{stableJson}}from{json.dumps((root / 'frontend/lib/canonicalJson.ts').as_uri())};"
        "let text='';for await(const chunk of process.stdin)text+=chunk;const row=JSON.parse(text);"
        "const fields='id,fixture_key,game_date,source_game_id,provider_code,home_team_master_id,"
        "away_team_master_id,fixture_payload'.split(',');"
        "const fixture=Object.fromEntries(fields.map(key=>[key,row[key]]));"
        "row.heuristic_prediction.inputHash=createHash('sha256').update(stableJson({fixture,"
        "context:row.heuristic_prediction.shadowContext})).digest('hex');process.stdout.write(JSON.stringify(row));",
        encoding="utf-8",
    )
    hashed = subprocess.run(
        ["node", "--import", (root / "frontend/node_modules/tsx/dist/loader.mjs").as_uri(), str(script)],
        input=json.dumps(row),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    row = json.loads(hashed.stdout)
    second = deepcopy(row)
    second.update(
        id="forecast-target-2", source_game_id="target-2", fixture_key="database:target-2", game_date="2026-11-15"
    )
    second["fixture_payload"]["source_snapshot"].update(
        id="target-2", game_date="2026-11-15", source_url="https://x/events/100/matches/2"
    )
    second = json.loads(
        subprocess.run(
            ["node", "--import", (root / "frontend/node_modules/tsx/dist/loader.mjs").as_uri(), str(script)],
            input=json.dumps(second),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
    )
    monkeypatch.setattr(input_archive, "utc_now", lambda: "2026-11-13T00:00:00Z")
    captured = input_archive.InputArchive(tmp_path / "source", root, {"capture_kind": "frozen_compare_forecasts"})
    for item in (second, row):
        captured.query(
            input_archive.FORECAST_TABLE,
            [["select", [FORECAST_FIELDS], {}], ["in_", ["id", [item["id"]]], {}], ["order", ["id"], {}]],
            SimpleNamespace(data=[item]),
            input_archive.utc_now(),
            "select",
        )
    captured.finish(True)
    server = DatasetServer()
    server.recorded_at = "2026-11-13T01:00:00Z"
    publish_archive(server, captured.directory, dry_run=False)
    server.ledger[row["id"]] = deepcopy(row)
    server.ledger[second["id"]] = deepcopy(second)
    source = authenticate_archive(server, captured.directory)
    sources = FrozenSourceIndex([source], root)
    _, members, cases, _ = tuning.eligible_inputs(sources)
    assert len(cases) == 2 and {c["fixture"]["game_date"] for c in cases} == {"2026-11-14", "2026-11-15"}
    replay = tmp_path / "replay"
    replay.mkdir()
    records, receipts = tuning.replay_candidates(cases, run_predictor, replay)
    # Only bypass checkout dirtiness so this regression also runs before commit.
    monkeypatch.setattr(tuning, "clean_revision", lambda root: None)
    for change in ("baseline", "membership"):
        invalid = deepcopy(records)
        if change == "baseline":
            invalid[0]["predictions"]["baseline"]["expectedMargin"] += 1
        else:
            invalid[0]["fixture"]["source_game_id"] = "other"
        with pytest.raises(ValueError):
            tuning.register_bundle(
                server, root, sources, invalid, receipts, tmp_path / change, [source.manifest_sha256]
            )
        assert not (tmp_path / change).exists()
    before = deepcopy(server.ledger)
    directory = tmp_path / "registered"
    result = tuning.register_bundle(server, root, sources, records, receipts, directory, [source.manifest_sha256])
    assert result["registered"] and result["paired_forecasts"] == 2 and server.ledger == before
    registered = authenticate_archive(server, directory)
    loaded = tuning.load_bundle(registered)
    assert loaded[3] == records and len(loaded[2]) == len(members)
    assert len(registered.manifest["queries"]) == 1 and len(source.manifest["queries"]) == 2
    assert all(table != "games" for table, _ in server.outcome_reads)
    server.ledger[row["id"]]["heuristic_model_version"] = "changed"
    registered_count = len(server.rows)
    with pytest.raises(ValueError, match="Completed forecast changed"):
        tuning.register_bundle(
            server, root, sources, records, receipts, tmp_path / "changed-ledger", [source.manifest_sha256]
        )
    assert len(server.rows) == registered_count
    server.ledger[row["id"]] = deepcopy(row)
    server.recorded_at = "2026-11-14T00:00:00Z"
    monkeypatch.setattr(input_archive, "utc_now", lambda: "2026-11-13T02:00:00Z")
    with pytest.raises(ValueError, match="deadline"):
        tuning.register_bundle(
            server, root, sources, records, receipts, tmp_path / "late-registration", [source.manifest_sha256]
        )
    from dataclasses import replace

    with pytest.raises(ValueError, match="deadline"):
        tuning.load_bundle(replace(registered, recorded_at="2026-11-14T00:00:00Z"))
