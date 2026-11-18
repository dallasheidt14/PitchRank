import gzip
import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from storage3.exceptions import StorageApiError

from src.rankings.archive_storage import INDEX, MAX_OBJECT_BYTES, download_object, publish_archive, verify_archive
from src.rankings.input_archive import InputArchive, utc_now

ROOT = Path(__file__).resolve().parents[2]
PART_BYTES = 64 * 1024
SERVER_LIMIT = 1024 * 1024


def capture_ranking_archive(directory, games=()):
    archive = InputArchive(directory, ROOT, {"ml": False})
    for name in ("games", "teams", "team_merge_map", "team_ranking_exclusions"):
        rows = list(games) if name == "games" else []
        archive.query(name, [["select", ["*"], {}]], SimpleNamespace(data=rows), utc_now(), "select")
    archive.engine_configuration({"engine": "glicko", "as_of": "2026-11-11"})
    archive.finish(True)
    return archive.directory


def capture_oversized_archive(directory):
    """A games page that compresses past SERVER_LIMIT, archived beside a manifest larger than PART_BYTES."""
    page = [{"id": random.Random(0).randbytes(1_500_000).hex()}]
    directory = capture_ranking_archive(directory, page)
    assert (directory / "manifest.json").stat().st_size > PART_BYTES
    return directory


@pytest.fixture
def captured(tmp_path):
    return capture_ranking_archive(tmp_path / "capture")


@pytest.fixture
def oversized(tmp_path, monkeypatch):
    monkeypatch.setattr("src.rankings.archive_storage.MAX_OBJECT_BYTES", PART_BYTES)
    return capture_oversized_archive(tmp_path / "oversized")


class FakeServer:
    # Storage refuses any single upload over the project's global file size limit (50 MB by default).
    def __init__(self, recorded_at=None, max_object_bytes=50 * 1024 * 1024):
        self.objects, self.rows, self.calls = {}, {}, []
        self.recorded_at = recorded_at
        self.max_object_bytes = max_object_bytes
        self.storage = SimpleNamespace(from_=lambda bucket: self)

    def upload(self, path, content, options):
        self.calls.append(("upload", path))
        assert options["upsert"] == "false"
        if len(content) > self.max_object_bytes:
            raise StorageApiError("The object exceeded the maximum allowed size", "Payload too large", "413")
        if path in self.objects:
            raise StorageApiError("exists", "Duplicate", 409)
        self.objects[path] = content

    def download(self, path):
        self.calls.append(("download", path))
        if path not in self.objects:
            raise StorageApiError("Object not found", "not_found", "404")
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


@pytest.mark.parametrize("error_type", [httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError])
def test_interrupted_verification_download_is_retried(captured, monkeypatch, error_type):
    server = FakeServer()
    download = server.download
    delays, attempts = [], []

    def interrupted_once(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise error_type("interrupted transfer")
        return download(path)

    monkeypatch.setattr(server, "download", interrupted_once)
    monkeypatch.setattr("src.rankings.archive_storage.time.sleep", delays.append)
    result = publish_archive(server, captured, dry_run=False)
    assert result["registered"] is True
    assert delays == [0.5] and attempts[0] == attempts[1]
    assert sum(kind == "upload" and path == attempts[0] for kind, path in server.calls) == 1


def test_committed_upload_with_lost_response_is_verified_without_overwriting(captured, monkeypatch):
    server = FakeServer()
    upload = server.upload
    calls, delays = [], []

    def lost_acknowledgement(path, content, options):
        calls.append(path)
        upload(path, content, options)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("response lost after object was stored")

    monkeypatch.setattr(server, "upload", lost_acknowledgement)
    monkeypatch.setattr("src.rankings.archive_storage.time.sleep", delays.append)
    result = publish_archive(server, captured, dry_run=False)
    assert result["registered"] is True and len(server.rows) == 1
    assert calls[0] == calls[1] and delays == [0.5]
    assert len(server.objects) == result["objects"] + 1


def test_committed_registration_with_lost_response_preserves_first_server_timestamp(captured, monkeypatch):
    server = FakeServer()
    execute = FakeServer.Query.execute
    recorded, delays = [], []

    def lost_acknowledgement(query):
        result = execute(query)
        if query.record is not None:
            recorded.append(server.rows[query.record["manifest_sha256"]]["recorded_at"])
            if len(recorded) == 1:
                raise httpx.ReadTimeout("registration committed but response lost")
        return result

    monkeypatch.setattr(FakeServer.Query, "execute", lost_acknowledgement)
    monkeypatch.setattr("src.rankings.archive_storage.time.sleep", delays.append)
    result = publish_archive(server, captured, dry_run=False)
    assert result["registered"] is True and len(server.rows) == 1
    assert len(recorded) == 2 and recorded[0] == recorded[1] == result["recorded_at"]
    assert delays == [0.5]


def test_registration_verification_read_can_recover_independently(captured, monkeypatch):
    server = FakeServer()
    execute = FakeServer.Query.execute
    reads, delays = [], []

    def interrupted_read(query):
        if query.record is None:
            reads.append(query.sha)
            if len(reads) == 1:
                raise httpx.ReadTimeout("read interrupted")
        return execute(query)

    monkeypatch.setattr(FakeServer.Query, "execute", interrupted_read)
    monkeypatch.setattr("src.rankings.archive_storage.time.sleep", delays.append)
    result = publish_archive(server, captured, dry_run=False)
    assert result["registered"] is True and len(server.rows) == 1
    assert reads == [result["manifest_sha256"]] * 2 and delays == [0.5]


def test_persistent_transfer_failures_are_bounded_and_never_register(captured, monkeypatch):
    server = FakeServer()
    attempts, delays = [], []

    def interrupted(path, content, options):
        attempts.append(path)
        raise httpx.RemoteProtocolError("persistent interruption")

    monkeypatch.setattr(server, "upload", interrupted)
    monkeypatch.setattr("src.rankings.archive_storage.time.sleep", delays.append)
    with pytest.raises(httpx.RemoteProtocolError):
        publish_archive(server, captured, dry_run=False)
    assert len(attempts) == 4 and len(set(attempts)) == 1
    assert delays == [0.5, 1.0, 2.0]
    assert not server.rows and not server.objects


def test_integrity_failure_after_transport_recovery_is_not_retried(captured, monkeypatch):
    server = FakeServer()
    attempts, delays = [], []

    def interrupted_then_corrupt(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("interrupted")
        return b"corrupted"

    monkeypatch.setattr(server, "download", interrupted_then_corrupt)
    monkeypatch.setattr("src.rankings.archive_storage.time.sleep", delays.append)
    with pytest.raises(ValueError, match="differs"):
        publish_archive(server, captured, dry_run=False)
    assert len(attempts) == 2 and delays == [0.5]
    assert not server.rows


def test_object_over_the_storage_upload_limit_is_published_in_parts(oversized):
    server = FakeServer(max_object_bytes=SERVER_LIMIT)
    _, _, files = verify_archive(oversized)
    split = sorted(name for name, path in files.items() if path.stat().st_size > SERVER_LIMIT)
    assert split
    first = publish_archive(server, oversized, dry_run=False)
    assert first["registered"] is True and len(server.rows) == 1
    assert not any(name in server.objects for name in split)
    assert all(download_object(server, name) == files[name].read_bytes() for name in split)
    before = server.objects.copy()
    assert publish_archive(server, oversized, dry_run=False) == first
    assert server.objects == before


def test_interrupted_parts_of_another_gzip_encoding_do_not_corrupt_a_later_publish(oversized, tmp_path):
    server = FakeServer(max_object_bytes=SERVER_LIMIT)
    _, _, files = verify_archive(oversized)
    name = next(name for name, path in files.items() if path.stat().st_size > SERVER_LIMIT)
    other = shutil.copytree(oversized, tmp_path / "other-encoding")
    raw = gzip.decompress((other / name).read_bytes())
    (other / name).write_bytes(gzip.compress(raw, compresslevel=1, mtime=0))
    assert (other / name).read_bytes() != files[name].read_bytes()
    upload = server.upload

    def interrupted_after_one_part(path, content, options):
        if ".part-" in path and any(".part-" in stored for stored in server.objects):
            raise StorageApiError("outage", "Unavailable", "503")
        upload(path, content, options)

    server.upload = interrupted_after_one_part
    with pytest.raises(StorageApiError):
        publish_archive(server, other, dry_run=False)
    server.upload = upload
    assert publish_archive(server, oversized, dry_run=False)["registered"] is True
    assert download_object(server, name) == files[name].read_bytes()


def test_object_read_failure_other_than_missing_is_not_read_as_parts(captured):
    server = FakeServer()
    publish_archive(server, captured, dry_run=False)
    name = next(name for name in server.objects if name.startswith("objects/"))

    def unavailable(path):
        server.calls.append(("download", path))
        raise StorageApiError("outage", "Unavailable", "503")

    server.download = unavailable
    server.calls.clear()
    with pytest.raises(StorageApiError) as error:
        download_object(server, name)
    assert error.value.code == "Unavailable"
    assert server.calls == [("download", name)]


def test_shipped_part_size_stays_below_the_largest_object_storage_accepted_whole():
    # 16,695,965 bytes is the largest archive object the project's Storage has accepted in one upload.
    assert MAX_OBJECT_BYTES == 15 * 1024 * 1024
    assert MAX_OBJECT_BYTES < 16_695_965
