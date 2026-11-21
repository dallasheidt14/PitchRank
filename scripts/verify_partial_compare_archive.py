"""Confirm every newly frozen row is present in the specific privately published archive."""
import hashlib
import json
import sys
from pathlib import Path

from src.predictions.archive_inputs import RegisteredArchive
from src.rankings.input_archive import FORECAST_ARCHIVE_KIND, FORECAST_TABLE


def verify(directory):
    report = json.loads((directory / "prospective-capture.json").read_bytes())
    if not (report["errored"] > 0 or report["deadlineReached"] is True):
        raise ValueError("Missing partial capture receipt")
    required = set(report["frozenIds"])
    if len(required) != report["frozen"] or len(required) != len(report["frozenIds"]):
        raise ValueError("Inconsistent frozen forecast count")
    publication = json.loads((directory / "forecast-publication.json").read_bytes())
    root = (directory / "frozen-forecast-inputs").resolve()
    raw = (root / "manifest.json").read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if publication["registered"] is not True or publication["manifest_sha256"] != sha:
        raise ValueError("Archive publication identity differs")
    manifest = json.loads(raw)
    archive = RegisteredArchive(root, sha, publication["recorded_at"], manifest)
    if manifest["configuration"]["capture_kind"] != FORECAST_ARCHIVE_KIND:
        raise ValueError("Expected a frozen forecast archive")
    for query in manifest["queries"]:
        if query["table"] != FORECAST_TABLE or query["operation"] != "select":
            raise ValueError("Unexpected forecast archive source")
        rows = archive.object_json(query["response"])
        required.difference_update(row["id"] for row in rows if row["heuristic_prediction_status"] == "completed")
    if required:
        raise ValueError(f"Published archive is missing {len(required)} newly frozen forecasts")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
