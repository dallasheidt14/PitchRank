"""Read server-registered archives; saved metadata alone never authenticates a dataset."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.predictions.form_study_contract import FORM_STUDY_KIND, utc_timestamp, validate_study_definition
from src.rankings.archive_storage import BUCKET, INDEX, MAX_RAW_BYTES, SHA256, references, verify_archive
from src.rankings.input_archive import FORECAST_ARCHIVE_KIND, FORECAST_TABLE


def _object_reference(reference: dict) -> tuple[str, str, int]:
    sha, size, name = reference.get("sha256"), reference.get("bytes"), reference.get("object")
    if (not isinstance(sha, str) or not SHA256.fullmatch(sha) or name != f"objects/{sha}.gz"
            or type(size) is not int or not 0 <= size <= MAX_RAW_BYTES):
        raise ValueError("Invalid registered archive object reference")
    return name, sha, size


def _object_bytes(compressed: bytes, reference: dict) -> bytes:
    _, sha, size = _object_reference(reference)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
        raw = handle.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("Registered archive object failed integrity verification")
    return raw


def _registered_manifest(client, manifest_sha256: str) -> tuple[dict, dict, bytes]:
    if not isinstance(manifest_sha256, str) or not SHA256.fullmatch(manifest_sha256):
        raise ValueError("Expected a registered manifest SHA256")
    record = client.table(INDEX).select("*").eq("manifest_sha256", manifest_sha256).single().execute().data
    if not isinstance(record, dict):
        raise ValueError("Archive has no authoritative server index record")
    key = f"runs/{manifest_sha256}/manifest.json"
    if record.get("manifest_sha256") != manifest_sha256 or record.get("manifest_path") != key:
        raise ValueError("Server index does not match the requested archive")
    raw = client.storage.from_(BUCKET).download(key)
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise ValueError("Server manifest failed integrity verification")
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete" or manifest.get("errors"):
        raise ValueError("Server manifest is not a complete input archive")
    if record.get("source_revision") != manifest.get("source_revision"):
        raise ValueError("Server index source revision differs from its manifest")
    for field, manifest_field in (("capture_started_at", "started_at"), ("capture_finished_at", "finished_at")):
        if utc_timestamp(record[field]) != utc_timestamp(manifest[manifest_field]):
            raise ValueError("Server index capture time differs from its manifest")
    if not (utc_timestamp(record["capture_started_at"]) <= utc_timestamp(record["capture_finished_at"])
            <= utc_timestamp(record["recorded_at"])):
        raise ValueError("Server index archive chronology is invalid")
    identities = {}
    for reference in references(manifest):
        name, sha, size = _object_reference(reference)
        if name in identities and identities[name] != (sha, size):
            raise ValueError("Conflicting registered archive object references")
        identities[name] = (sha, size)
    if not identities or type(record.get("object_count")) is not int or record["object_count"] != len(identities):
        raise ValueError("Server index object count differs from its manifest")
    if manifest.get("configuration", {}).get("capture_kind") == FORM_STUDY_KIND:
        validate_study_definition(manifest["configuration"]["study_definition"], registered_at=record["recorded_at"])
    return record, manifest, raw


ARCHIVE_INVENTORY_QUERY = """
SELECT current_setting('transaction_read_only') AS read_only,
       clock_timestamp() AS observed_at,
       coalesce((SELECT jsonb_agg(x ORDER BY x.manifest_sha256) FROM (
           SELECT manifest_sha256,source_revision,manifest_path,capture_started_at,
                  capture_finished_at,object_count,recorded_at
           FROM public.prediction_input_archives
       ) x), '[]'::jsonb) AS archives;
"""


def registered_inventory(project_url: str, access_token: str) -> dict:
    """Read one database snapshot and its server clock through the enforced read-only API."""
    parsed = urlparse(project_url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith(".supabase.co") or not access_token:
        raise ValueError("Configure the existing Supabase project URL and management access token")
    response = requests.post(
        f"https://api.supabase.com/v1/projects/{host.split('.')[0]}/database/query/read-only",
        headers={"Authorization": "Bearer " + access_token}, json={"query": ARCHIVE_INVENTORY_QUERY},
        timeout=60, allow_redirects=False,
    )
    if not response.ok:
        raise RuntimeError("Read-only archive inventory failed: HTTP " + str(response.status_code))
    payload = response.json()
    if not isinstance(payload, list) or len(payload) != 1 or payload[0].get("read_only") != "on":
        raise ValueError("Archive inventory was not returned by a read-only transaction")
    snapshot = payload[0]
    observed = utc_timestamp(snapshot["observed_at"])
    records = snapshot.get("archives")
    if not isinstance(records, list):
        raise ValueError("Missing archive inventory rows")
    cursor = None
    for record in records:
        sha = record["manifest_sha256"]
        if (not isinstance(sha, str) or not SHA256.fullmatch(sha)
                or (cursor is not None and sha <= cursor) or utc_timestamp(record["recorded_at"]) > observed):
            raise ValueError("Invalid ordered archive snapshot or server clock")
        cursor = sha
    return {"as_of": snapshot["observed_at"], "archives": records}


@dataclass(frozen=True)
class RegisteredArchive:
    directory: Path
    manifest_sha256: str
    recorded_at: str
    _manifest: dict

    @property
    def manifest(self) -> dict:
        return deepcopy(self._manifest)

    def object_bytes(self, reference: dict) -> bytes:
        identity = _object_reference(reference)
        if identity not in {_object_reference(ref) for ref in references(self._manifest)}:
            raise ValueError("Object is not a member of the authenticated archive")
        target = (self.directory / identity[0]).resolve()
        if target.parent != self.directory / "objects":
            raise ValueError("Authenticated object escaped its archive directory")
        return _object_bytes(target.read_bytes(), reference)

    def object_json(self, reference: dict):
        return json.loads(self.object_bytes(reference))

    def frozen_rows(self) -> list[dict]:
        if self._manifest.get("configuration", {}).get("capture_kind") != FORECAST_ARCHIVE_KIND:
            raise ValueError("Expected a frozen forecast archive")
        result = []
        for query in self._manifest["queries"]:
            if query["table"] != FORECAST_TABLE or query["operation"] != "select":
                raise ValueError("Unexpected source in a frozen forecast archive")
            rows = self.object_json(query["response"])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Frozen forecast response must contain object rows")
            for position, row in enumerate(rows):
                result.append({"record": row, "binding": {
                    "manifest_sha256": self.manifest_sha256,
                    "response_sha256": query["response"]["sha256"], "row_number": position,
                    "ledger_id": row.get("id"),
                }})
        return result


def authenticate_archive(client, directory: Path) -> RegisteredArchive:
    """Recheck the live index and exact remote contents; no local receipt is trusted."""
    directory = directory.resolve()
    local_manifest, raw, files = verify_archive(directory)
    sha = hashlib.sha256(raw).hexdigest()
    record, manifest, remote_raw = _registered_manifest(client, sha)
    if raw != remote_raw or local_manifest != manifest:
        raise ValueError("Local archive differs from its authoritative server manifest")
    bucket = client.storage.from_(BUCKET)
    by_name = {ref["object"]: ref for ref in references(manifest)}
    for name in sorted(files):
        _object_bytes(bucket.download(name), by_name[name])
    return RegisteredArchive(directory, sha, record["recorded_at"], deepcopy(manifest))


def download_archive(
    client, manifest_sha256: str, output: Path | None = None, *, dry_run: bool = True, return_verified: bool = False,
) -> dict | RegisteredArchive:
    """Default preview reads only the server index/manifest; execute saves new local files."""
    if not dry_run and output is None:
        raise ValueError("Archive download requires a new output directory")
    if return_verified and dry_run:
        raise ValueError("An authenticated archive handle requires a complete download")
    record, manifest, raw = _registered_manifest(client, manifest_sha256)
    report = {"dry_run": dry_run, "manifest_sha256": manifest_sha256, "recorded_at": record["recorded_at"],
              "capture_kind": manifest.get("configuration", {}).get("capture_kind"),
              "objects": record["object_count"], "full_archive_verified": False, "research_eligible": False}
    if dry_run:
        return report
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "objects").mkdir()
    with (output / "manifest.json").open("xb") as handle:
        handle.write(raw)
    by_name = {ref["object"]: ref for ref in references(manifest)}
    bucket = client.storage.from_(BUCKET)
    for name, reference in sorted(by_name.items()):
        compressed = bucket.download(name)
        _object_bytes(compressed, reference)
        with (output / name).open("xb") as handle:
            handle.write(compressed)
    verify_archive(output)
    with (output / "server-record.json").open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, allow_nan=False)
    if return_verified:
        return RegisteredArchive(output, manifest_sha256, record["recorded_at"], deepcopy(manifest))
    return {**report, "full_archive_verified": True}
