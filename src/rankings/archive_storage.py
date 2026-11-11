"""Verify local ranking archives and publish them to private, immutable storage."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path

from storage3.exceptions import StorageApiError

BUCKET = "prediction-input-archives"
INDEX = "prediction_input_archives"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_RAW_BYTES = 512 * 1024 * 1024


def references(value):
    if isinstance(value, dict):
        if "object" in value:
            yield value
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def verify_archive(directory: Path) -> tuple[dict, bytes, dict[str, Path]]:
    root = directory.resolve()
    raw = (root / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete" or manifest.get("errors"):
        raise ValueError("Only complete, error-free input archives can be published")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_revision", "")):
        raise ValueError("Missing source revision")
    start = datetime.fromisoformat(manifest["started_at"])
    end = datetime.fromisoformat(manifest["finished_at"])
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise ValueError("Invalid archive chronology")
    required = {"games", "teams", "team_merge_map", "team_ranking_exclusions"}
    reads = {q["table"] for q in manifest.get("queries", []) if q["operation"] == "select"}
    if not required <= reads or not manifest.get("engine_configurations"):
        raise ValueError("Archive is missing required ranking inputs or resolved configuration")
    if manifest.get("configuration", {}).get("ml") and not manifest.get("model_outputs"):
        raise ValueError("Archive is missing ML outputs or explicit passthrough evidence")
    files = {}
    sizes = {}
    for reference in references(manifest):
        sha, size, name = reference.get("sha256"), reference.get("bytes"), reference.get("object")
        if not isinstance(sha, str) or not SHA256.fullmatch(sha) or name != f"objects/{sha}.gz":
            raise ValueError("Invalid archive object identity")
        if not isinstance(size, int) or not 0 <= size <= MAX_RAW_BYTES:
            raise ValueError("Invalid archive object size")
        target = (root / name).resolve()
        if target.parent != root / "objects" or not target.is_file():
            raise ValueError("Archive object escaped its directory or is missing")
        if name not in files:
            with gzip.open(target, "rb") as handle:
                data = handle.read(size + 1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("Archive object failed integrity verification")
            files[name] = target
            sizes[name] = size
        elif sizes[name] != size:
            raise ValueError("Conflicting archive object sizes")
    if not files:
        raise ValueError("Empty input archive")
    return manifest, raw, files


def publish_archive(client, directory: Path, *, dry_run: bool = True) -> dict:
    manifest, raw, files = verify_archive(directory)
    sha = hashlib.sha256(raw).hexdigest()
    key = f"runs/{sha}/manifest.json"
    summary = {"dry_run": dry_run, "manifest_sha256": sha, "objects": len(files), "registered": False}
    if dry_run:
        return summary
    bucket = client.storage.from_(BUCKET)

    def upload_once(name: str, data: bytes, content_type: str, reference=None):
        try:
            bucket.upload(name, data, {"content-type": content_type, "upsert": "false"})
        except StorageApiError as error:
            if error.code not in {"Duplicate", "ResourceAlreadyExists"}:
                raise
        # Raw-SHA object identity is independent of a runtime's gzip encoding.
        stored = bucket.download(name)
        valid = stored == data
        if reference is not None:
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(stored)) as handle:
                    raw_object = handle.read(reference["bytes"] + 1)
                valid = (
                    len(raw_object) == reference["bytes"]
                    and hashlib.sha256(raw_object).hexdigest() == reference["sha256"]
                )
            except (OSError, EOFError):
                valid = False
        if not valid:
            raise ValueError("Stored archive differs from its verified local object")

    by_name = {ref["object"]: ref for ref in references(manifest)}
    for name, path in sorted(files.items()):
        upload_once(name, path.read_bytes(), "application/gzip", by_name[name])
    upload_once(key, raw, "application/json")
    record = {
        "manifest_sha256": sha,
        "source_revision": manifest["source_revision"],
        "manifest_path": key,
        "capture_started_at": manifest["started_at"],
        "capture_finished_at": manifest["finished_at"],
        "object_count": len(files),
    }
    client.table(INDEX).upsert(record, on_conflict="manifest_sha256", ignore_duplicates=True).execute()
    result = client.table(INDEX).select("*").eq("manifest_sha256", sha).single().execute().data
    if any(result.get(k) != v for k, v in record.items() if k not in {"capture_started_at", "capture_finished_at"}):
        raise ValueError("Registered archive metadata changed")
    for field in ("capture_started_at", "capture_finished_at"):
        if datetime.fromisoformat(result[field]) != datetime.fromisoformat(record[field]):
            raise ValueError("Registered archive chronology changed")
    summary.update({"registered": True, "recorded_at": result["recorded_at"]})
    return summary
