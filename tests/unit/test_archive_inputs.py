import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.predictions.archive_inputs import (
    ARCHIVE_INVENTORY_QUERY,
    authenticate_archive,
    download_archive,
    registered_inventory,
)
from src.predictions.forecast_archive import archive_forecasts
from src.rankings.archive_storage import publish_archive
from tests.unit.test_forecast_archive import DAY, client_and_requests, fixture
from tests.unit.test_ranking_archive_storage import FakeServer

ROOT = Path(__file__).resolve().parents[2]


class ReadOnlyServer(FakeServer):
    def upload(self, *args):
        raise AssertionError("Reader attempted an upload")

    class Query(FakeServer.Query):
        def execute(self):
            if self.record is not None:
                raise AssertionError("Reader attempted an index write")
            return super().execute()


@pytest.fixture
def registered(tmp_path):
    client, http, _ = client_and_requests([fixture(1), fixture(2)])
    source = tmp_path / "source"
    try:
        archive_forecasts(client, ROOT, source, dry_run=False, today=DAY)
    finally:
        http.close()
    publishing_server = FakeServer()
    published = publish_archive(publishing_server, source, dry_run=False)
    server = ReadOnlyServer()
    server.objects = publishing_server.objects.copy()
    server.rows = deepcopy(publishing_server.rows)
    return source, server, published


def test_default_preview_reads_only_the_index_and_manifest_and_writes_nothing(registered, tmp_path):
    _, server, published = registered
    output = tmp_path / "not-written"
    before = deepcopy(server.rows)
    report = download_archive(server, published["manifest_sha256"], output)
    assert report["dry_run"] is True
    assert report["full_archive_verified"] is False and report["research_eligible"] is False
    assert report["recorded_at"] == published["recorded_at"] and not output.exists()
    assert server.rows == before
    assert server.calls == [("index", published["manifest_sha256"]),
                            ("download", f"runs/{published['manifest_sha256']}/manifest.json")]


def test_download_and_fresh_authentication_bind_exact_archive_members(registered, tmp_path):
    _, server, published = registered
    output = tmp_path / "downloaded"
    report = download_archive(server, published["manifest_sha256"], output, dry_run=False)
    assert report["full_archive_verified"] is True and report["research_eligible"] is False
    stored_record = json.loads((output / "server-record.json").read_text())
    stored_record["recorded_at"] = "2020-01-01T00:00:00Z"
    (output / "server-record.json").write_text(json.dumps(stored_record))
    archive = authenticate_archive(server, output)
    assert archive.recorded_at == published["recorded_at"]
    assert archive.manifest_sha256 == published["manifest_sha256"]
    rows = archive.frozen_rows()
    assert len(rows) == 2
    assert rows[0]["record"]["heuristic_prediction"]["shadowContext"]["frozenEvidence"]["games"][0]["id"] == "history"
    assert rows[0]["binding"] == {
        "manifest_sha256": published["manifest_sha256"],
        "response_sha256": archive.manifest["queries"][0]["response"]["sha256"],
        "row_number": 0, "ledger_id": "1",
    }
    assert "actual_home_score" not in rows[0]["record"]
    manifest_copy = archive.manifest
    manifest_copy["queries"].clear()
    assert len(archive.manifest["queries"]) == 1
    before = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        download_archive(server, published["manifest_sha256"], output, dry_run=False)
    after = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert before == after
    assert all(call[0] in {"index", "download"} for call in server.calls)


def test_fresh_download_returns_verified_members_without_repeating_remote_reads(registered, tmp_path):
    _, server, published = registered
    archive = download_archive(server, published["manifest_sha256"], tmp_path / "downloaded",
                               dry_run=False, return_verified=True)
    assert archive.manifest_sha256 == published["manifest_sha256"] and len(archive.frozen_rows()) == 2
    downloads = [path for operation, path in server.calls if operation == "download"]
    assert len(downloads) == len(set(downloads)) == published["objects"] + 1
    with pytest.raises(ValueError, match="complete download"):
        download_archive(server, published["manifest_sha256"], tmp_path / "preview", return_verified=True)
    assert not (tmp_path / "preview").exists()


@pytest.mark.parametrize("change", ["manifest", "path", "source_revision", "count", "time", "server_time"])
def test_corrupt_authority_metadata_is_rejected_before_creating_local_files(registered, tmp_path, change):
    _, server, published = registered
    sha = published["manifest_sha256"]
    if change == "manifest":
        server.objects[f"runs/{sha}/manifest.json"] = b"{}"
    elif change == "path":
        server.rows[sha]["manifest_path"] = "../elsewhere"
    elif change == "source_revision":
        server.rows[sha]["source_revision"] = "0" * 40
    elif change == "count":
        server.rows[sha]["object_count"] += 1
    elif change == "time":
        server.rows[sha]["capture_started_at"] = "2020-01-01T00:00:00Z"
    else:
        server.rows[sha]["recorded_at"] = "2020-01-01T00:00:00Z"
    output = tmp_path / "not-written"
    with pytest.raises(ValueError):
        download_archive(server, sha, output, dry_run=False)
    assert not output.exists()


def test_corrupt_remote_object_cannot_produce_a_verified_download(registered, tmp_path):
    _, server, published = registered
    name = next(name for name in server.objects if name.endswith(".gz"))
    server.objects[name] = gzip.compress(b"changed")
    output = tmp_path / "incomplete"
    with pytest.raises(ValueError, match="integrity"):
        download_archive(server, published["manifest_sha256"], output, dry_run=False)
    assert not (output / "server-record.json").exists()


def test_local_corruption_after_authentication_cannot_change_a_bound_member(registered, tmp_path):
    _, server, published = registered
    output = tmp_path / "downloaded"
    download_archive(server, published["manifest_sha256"], output, dry_run=False)
    archive = authenticate_archive(server, output)
    reference = archive.manifest["queries"][0]["response"]
    (output / reference["object"]).write_bytes(gzip.compress(b"[]"))
    with pytest.raises(ValueError, match="integrity"):
        archive.frozen_rows()
    server.calls.clear()
    with pytest.raises(ValueError, match="integrity"):
        authenticate_archive(server, output)
    assert server.calls == []


def test_reference_outside_the_registered_member_set_is_not_read(registered, tmp_path):
    _, server, published = registered
    output = tmp_path / "downloaded"
    download_archive(server, published["manifest_sha256"], output, dry_run=False)
    archive = authenticate_archive(server, output)
    ref = {"object": "objects/" + "0" * 64 + ".gz", "sha256": "0" * 64, "bytes": 0}
    with pytest.raises(ValueError, match="not a member"):
        archive.object_bytes(ref)


def test_invalid_archive_identity_is_rejected_without_a_remote_call(tmp_path):
    class NoRemote:
        def __getattr__(self, name):
            raise AssertionError("Invalid identity reached the server")

    with pytest.raises(ValueError, match="manifest SHA256"):
        download_archive(NoRemote(), "../not-a-hash", tmp_path / "not-written")


def test_inventory_uses_one_enforced_read_only_snapshot_and_server_clock(monkeypatch):
    from types import SimpleNamespace

    records = [{"manifest_sha256": f"{i:064x}", "recorded_at": "2027-01-11T01:00:00Z"} for i in range(1001)]
    calls = []

    def post(url, *, headers, json, timeout, allow_redirects):
        calls.append(url)
        assert url == "https://api.supabase.com/v1/projects/example/database/query/read-only"
        assert headers == {"Authorization": "Bearer dummy-token"} and timeout == 60
        assert allow_redirects is False and json == {"query": ARCHIVE_INVENTORY_QUERY}
        assert "jsonb_agg(x ORDER BY x.manifest_sha256)" in json["query"]
        assert "current_setting('transaction_read_only')" in json["query"]
        assert "clock_timestamp() AS observed_at" in json["query"]
        return SimpleNamespace(ok=True, status_code=201,
                               json=lambda: [{"read_only": "on", "observed_at": "2027-01-11T01:00:01Z",
                                              "archives": records}])

    monkeypatch.setattr("src.predictions.archive_inputs.requests.post", post)
    result = registered_inventory("https://example.supabase.co", "dummy-token")
    assert len(calls) == 1 and len(result["archives"]) == 1001
    assert result["as_of"] == "2027-01-11T01:00:01Z"
    assert result["archives"][-1]["manifest_sha256"] == f"{1000:064x}"


def test_inventory_rejects_an_unproven_transaction_before_using_its_clock(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("src.predictions.archive_inputs.requests.post", lambda *args, **kwargs:
                        SimpleNamespace(ok=True, json=lambda: [{"read_only": "off", "observed_at": "2099-01-01Z"}]))
    with pytest.raises(ValueError, match="read-only transaction"):
        registered_inventory("https://example.supabase.co", "dummy-token")
