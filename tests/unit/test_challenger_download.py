import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.predictions.archive_inputs import download_archive
from src.predictions.challenger_download import CachedArchiveClient
from src.rankings.archive_storage import BUCKET, publish_archive, verify_archive
from src.rankings.input_archive import InputArchive, utc_now
from tests.unit.test_ranking_archive_storage import FakeServer

ROOT = Path(__file__).resolve().parents[2]


def test_executing_cli_reuses_shared_objects_across_archives(tmp_path, monkeypatch, capsys):
    from scripts import capture_compare_challenger as cli

    server = FakeServer()
    hashes = []
    for number in range(2):
        archive = InputArchive(tmp_path / f"source-{number}", ROOT, {"capture_kind": "frozen_compare_forecasts"})
        archive.query("prospective_match_predictions", [["select", ["*"], {}]],
                      SimpleNamespace(data=[{"id": str(number)}]), utc_now(), "select")
        archive.finish(True)
        hashes.append(publish_archive(server, archive.directory, dry_run=False)["manifest_sha256"])
    server.calls.clear()
    monkeypatch.setattr(cli, "_supabase_client", lambda: server)
    monkeypatch.setattr(cli, "capture_preflight", lambda *args: {"eligible_prematch": 1})
    monkeypatch.setattr(cli, "forecast_archive_headers",
                        lambda client: [{"manifest_sha256": sha} for sha in hashes])
    monkeypatch.setattr(cli, "FrozenSourceIndex", lambda archives, root: archives)

    def capture(client, signature, archives, runner, *, dry_run, limit):
        assert client is server and signature == "candidate" and not dry_run and limit == 20
        assert len(archives) == 2
        for archive in archives:
            verify_archive(archive.directory)
        return {"captured": 1, "errors": {}}

    monkeypatch.setattr(cli, "capture_candidate", capture)
    monkeypatch.setattr("sys.argv", ["capture_compare_challenger.py", "candidate", "--download-archives",
                                   str(tmp_path / "download"), "--execute", "--limit", "20"])
    cli.main()
    counts = Counter(name for action, name in server.calls if action == "download")
    assert any(name.startswith("objects/") for name in counts)
    assert all(count == 1 for name, count in counts.items() if name.startswith("objects/"))
    assert [counts[f"runs/{sha}/manifest.json"] for sha in hashes] == [1, 1]
    assert [sha for action, sha in server.calls if action == "index"] == hashes
    assert json.loads(capsys.readouterr().out)["archive_object_reuse"]["objects_reused"] > 0


def test_shared_objects_download_once_but_each_manifest_is_authenticated(tmp_path):
    server = FakeServer()
    hashes = []
    for number in range(2):
        archive = InputArchive(tmp_path / f"source-{number}", ROOT, {"capture_kind": "frozen_compare_forecasts"})
        archive.query("prospective_match_predictions", [["select", ["*"], {}]],
                      SimpleNamespace(data=[{"id": str(number)}]), utc_now(), "select")
        archive.finish(True)
        hashes.append(publish_archive(server, archive.directory, dry_run=False)["manifest_sha256"])
    server.calls.clear()
    output = tmp_path / "download"
    output.mkdir()
    cached = CachedArchiveClient(server, output, dry_run=False)
    for sha in hashes:
        archive = download_archive(cached, sha, output / sha, dry_run=False, return_verified=True)
        cached.share_local_objects(archive)
        cached.share_local_objects(archive)
        verify_archive(archive.directory)
        assert not list((archive.directory / "objects").glob("*.link"))
    counts = Counter(name for action, name in server.calls if action == "download")
    assert all(count == 1 for name, count in counts.items() if name.startswith("objects/"))
    assert cached.counts["objects_reused"] > 0
    assert [counts[f"runs/{sha}/manifest.json"] for sha in hashes] == [1, 1]
    assert [sha for action, sha in server.calls if action == "index"] == hashes


@pytest.mark.parametrize("corrupt", ["remote", "cache"])
def test_corrupt_objects_cannot_be_reused(tmp_path, corrupt):
    raw = b"frozen evidence"
    sha = hashlib.sha256(raw).hexdigest()
    name = f"objects/{sha}.gz"
    server = FakeServer()
    server.objects[name] = gzip.compress(raw)
    cached = CachedArchiveClient(server, tmp_path, dry_run=False)
    bucket = cached.storage.from_(BUCKET)
    if corrupt == "remote":
        server.objects[name] = gzip.compress(b"different")
    else:
        assert bucket.download(name) == server.objects[name]
        (cached.objects / (sha + ".gz")).write_bytes(gzip.compress(b"different"))
    with pytest.raises(ValueError, match="content verification"):
        bucket.download(name)


def test_hardlink_failure_keeps_the_verified_download(tmp_path, monkeypatch):
    raw = b"saved input"
    sha = hashlib.sha256(raw).hexdigest()
    name = f"objects/{sha}.gz"
    server = FakeServer()
    server.objects[name] = gzip.compress(raw)
    cached = CachedArchiveClient(server, tmp_path, dry_run=False)
    compressed = cached.download(name)
    directory = tmp_path / "archive"
    (directory / "objects").mkdir(parents=True)
    target = directory / name
    target.write_bytes(compressed)
    def unsupported(*args): raise OSError("no hardlinks")
    monkeypatch.setattr("src.predictions.challenger_download.os.link", unsupported)
    cached.share_local_objects(SimpleNamespace(directory=directory, manifest={
        "source_files": {"a.py": {"object": name, "sha256": sha, "bytes": len(raw)}}}))
    assert target.read_bytes() == compressed


def test_default_preview_cannot_write_cache_files(tmp_path):
    server = FakeServer()
    raw = b"preview"
    name = "objects/" + hashlib.sha256(raw).hexdigest() + ".gz"
    server.objects[name] = gzip.compress(raw)
    cached = CachedArchiveClient(server, tmp_path)
    assert cached.download(name) == server.objects[name]
    cached.share_local_objects(None)
    assert not list(tmp_path.iterdir())
