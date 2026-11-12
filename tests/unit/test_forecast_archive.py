import gzip
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from postgrest import SyncPostgrestClient

from src.predictions.forecast_archive import FORECAST_FIELDS, archive_forecasts
from src.rankings.archive_storage import publish_archive, verify_archive

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 11, 11)


def fixture(i):
    return {
        "id": str(i), "fixture_key": f"database:{i}", "source_game_id": f"source-{i}",
        "provider_code": "gotsport", "source_system": "database_games", "game_date": "2026-11-14",
        "home_team_master_id": "a", "away_team_master_id": "b", "evaluation_group_kind": "event",
        "evaluation_group_key": "gotsport:123", "source_event_id": "123", "fixture_payload": {"cohort": "u13|Male"},
        "heuristic_prediction_status": "completed", "heuristic_model_version": "test-version",
        "heuristic_predicted_at": "2026-11-11T12:00:00Z",
        "heuristic_prediction": {"response": {"prediction": {"expectedMargin": i / 10}},
                                 "shadowContext": {"frozenEvidence": {"games": [{"id": "history", "home_score": 2}]}}},
        "actual_home_score": 99,
    }


def client_and_requests(rows, fail_page=False):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path.endswith("/prospective_match_predictions")
        assert request.url.params["select"] == FORECAST_FIELDS
        assert request.url.params["heuristic_prediction_status"] == "eq.completed"
        assert request.url.params.get_list("game_date") == ["gte.2026-11-12", "lte.2026-11-18"]
        assert request.url.params["order"] == "id.asc"
        assert request.url.params["limit"] == "1000"
        offset = int(request.url.params.get("offset", 0))
        if fail_page and offset:
            return httpx.Response(500, json={"code": "XX000", "message": "fixture failure"})
        fields = request.url.params["select"].split(",")
        limit = int(request.url.params["limit"])
        selected = [{field: row.get(field) for field in fields} for row in rows[offset:offset + limit]]
        return httpx.Response(200, json=selected)

    http = httpx.Client(transport=httpx.MockTransport(respond), headers={"apikey": "test-secret-never-archive"})
    postgres = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
    return SimpleNamespace(table=postgres.from_), http, requests


def test_preview_reads_complete_frozen_records_without_local_or_remote_writes(tmp_path):
    client, http, requests = client_and_requests([fixture(1)])
    output = tmp_path / "untouched"
    try:
        report = archive_forecasts(client, ROOT, output, today=DAY)
    finally:
        http.close()
    assert report["dry_run"] and not report["published"] and not report["eligibility_certified"]
    assert report["archived_rows"] == len(requests) == 1 and not output.exists()


def test_actual_paged_forecasts_are_archived_with_full_inputs_but_without_result_labels(tmp_path):
    rows = [fixture(i) for i in range(1001)]
    client, http, requests = client_and_requests(rows)
    output = tmp_path / "capture"
    try:
        report = archive_forecasts(client, ROOT, output, dry_run=False, today=DAY)
    finally:
        http.close()
    assert report["archived_rows"] == 1001 and len(requests) == 2
    manifest, _, files = verify_archive(output)
    assert manifest["configuration"]["capture_kind"] == "frozen_compare_forecasts"
    captured = []
    for query in manifest["queries"]:
        captured.extend(json.loads(gzip.decompress((output / query["response"]["object"]).read_bytes())))
    assert len(captured) == 1001
    assert captured[0]["heuristic_prediction"] == rows[0]["heuristic_prediction"]
    assert all("actual_home_score" not in row for row in captured)
    assert all(b"test-secret-never-archive" not in gzip.decompress(path.read_bytes()) for path in files.values())
    assert publish_archive(None, output)["dry_run"]
    with pytest.raises(FileExistsError):
        archive_forecasts(client, ROOT, output, dry_run=False, today=DAY)


def test_failed_page_marks_local_archive_failed_and_prevents_publication(tmp_path):
    client, http, _ = client_and_requests([fixture(i) for i in range(1001)], fail_page=True)
    output = tmp_path / "capture"
    try:
        with pytest.raises(Exception, match="fixture failure"):
            archive_forecasts(client, ROOT, output, dry_run=False, today=DAY)
    finally:
        http.close()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["errors"]
    with pytest.raises(ValueError, match="complete, error-free"):
        verify_archive(output)


def test_unknown_capture_kind_cannot_bypass_ranking_requirements(tmp_path):
    client, http, _ = client_and_requests([fixture(1)])
    output = tmp_path / "capture"
    try:
        archive_forecasts(client, ROOT, output, dry_run=False, today=DAY)
    finally:
        http.close()
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["configuration"]["capture_kind"] = "unknown"
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="ranking inputs"):
        verify_archive(output)
