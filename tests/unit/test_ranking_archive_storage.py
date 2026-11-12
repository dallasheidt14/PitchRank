import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from storage3.exceptions import StorageApiError

from src.rankings.archive_storage import INDEX, publish_archive, verify_archive
from src.rankings.input_archive import InputArchive, utc_now

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def captured(tmp_path):
    archive = InputArchive(tmp_path / "capture", ROOT, {"ml": False})
    for name in ("games", "teams", "team_merge_map", "team_ranking_exclusions"):
        archive.query(name, [["select", ["*"], {}]], SimpleNamespace(data=[]), utc_now(), "select")
    archive.engine_configuration({"engine": "glicko", "as_of": "2026-11-11"})
    archive.finish(True)
    return archive.directory


class FakeServer:
    def __init__(self, recorded_at=None):
        self.objects, self.rows, self.calls = {}, {}, []
        self.recorded_at = recorded_at
        self.storage = SimpleNamespace(from_=lambda bucket: self)

    def upload(self, path, content, options):
        self.calls.append(("upload", path))
        assert options["upsert"] == "false"
        if path in self.objects:
            raise StorageApiError("exists", "Duplicate", 409)
        self.objects[path] = content

    def download(self, path):
        self.calls.append(("download", path))
        return self.objects[path]

    def table(self, name):
        assert name == INDEX
        return self.Query(self)

    class Query:
        def __init__(self, server):
            self.server, self.record, self.sha = server, None, None

        def upsert(self, row, *, on_conflict, ignore_duplicates):
            assert on_conflict == "manifest_sha256" and ignore_duplicates is True
            self.record = row.copy()
            return self

        def select(self, columns):
            assert columns == "*"
            return self

        def eq(self, field, value):
            assert field == "manifest_sha256"
            self.sha = value
            return self

        def single(self):
            return self

        def execute(self):
            self.server.calls.append(("index", self.sha))
            if self.record is not None:
                self.server.rows.setdefault(
                    self.record["manifest_sha256"],
                    {
                        **self.record,
                        "recorded_at": self.server.recorded_at or datetime.now(timezone.utc).isoformat(),
                    },
                )
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=self.server.rows[self.sha].copy())


def test_preview_never_constructs_or_calls_a_remote_client(captured):
    result = publish_archive(None, captured)
    assert result["dry_run"] is True and result["registered"] is False and result["objects"] > 0


def test_publish_is_verified_and_idempotent_without_overwriting_server_time(captured):
    server = FakeServer()
    first = publish_archive(server, captured, dry_run=False)
    before = server.objects.copy()
    second = publish_archive(server, captured, dry_run=False)
    assert first == second and first["registered"] is True
    assert server.objects == before
    assert len(server.rows) == 1
    assert server.calls[-1][0] == "index"


def test_existing_remote_object_corruption_prevents_registration(captured):
    server = FakeServer()
    _, _, files = verify_archive(captured)
    first_key = sorted(files)[0]
    server.objects[first_key] = b"corrupted"
    with pytest.raises(ValueError, match="differs"):
        publish_archive(server, captured, dry_run=False)
    assert not server.rows


def test_equivalent_gzip_encodings_reuse_raw_content_identity(captured):
    server = FakeServer()
    first = publish_archive(server, captured, dry_run=False)
    name = next(name for name in server.objects if name.endswith(".gz"))
    original = server.objects[name]
    server.objects[name] = gzip.compress(gzip.decompress(original), mtime=123)
    assert server.objects[name] != original
    second = publish_archive(server, captured, dry_run=False)
    assert first == second
    assert len(server.rows) == 1


@pytest.mark.parametrize("change", ["content", "path", "size", "incomplete", "missing_inputs"])
def test_tampered_or_incomplete_archives_are_rejected_before_network_calls(captured, change):
    manifest_path = captured / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    ref = next(iter(manifest["source_files"].values()))
    if change == "content":
        (captured / ref["object"]).write_bytes(gzip.compress(b"different"))
    elif change == "path":
        ref["object"] = "../outside.gz"
    elif change == "size":
        ref["bytes"] += 1
    elif change == "incomplete":
        manifest["status"] = "recording"
    else:
        manifest["queries"] = []
    manifest_path.write_text(json.dumps(manifest))
    server = FakeServer()
    with pytest.raises(ValueError):
        publish_archive(server, captured, dry_run=False)
    assert not server.calls


def test_storage_outage_does_not_create_a_false_complete_index(captured):
    server = FakeServer()
    server.upload = lambda *args: (_ for _ in ()).throw(StorageApiError("outage", "Unavailable", 503))
    with pytest.raises(StorageApiError):
        publish_archive(server, captured, dry_run=False)
    assert not server.rows
