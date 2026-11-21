import gzip
import hashlib
import json

import pytest

from scripts.verify_partial_compare_archive import verify
from src.rankings.input_archive import FORECAST_ARCHIVE_KIND, FORECAST_TABLE


@pytest.mark.parametrize("saved_id,valid", [("inside", True), ("aged-out-at-midnight", False)])
def test_partial_receipt_requires_every_saved_id_in_published_window(tmp_path, saved_id, valid):
    folder = tmp_path / "frozen-forecast-inputs"
    objects = folder / "objects"
    objects.mkdir(parents=True)
    raw = json.dumps([{"id": "inside", "heuristic_prediction_status": "completed"}]).encode()
    sha = hashlib.sha256(raw).hexdigest()
    compressed = gzip.compress(raw)
    (objects / f"{sha}.gz").write_bytes(compressed)
    ref = {"object": f"objects/{sha}.gz", "sha256": sha, "bytes": len(raw), "compressed_bytes": len(compressed)}
    manifest = json.dumps({"configuration": {"capture_kind": FORECAST_ARCHIVE_KIND},
                           "queries": [{"table": FORECAST_TABLE, "operation": "select", "response": ref}]}).encode()
    (folder / "manifest.json").write_bytes(manifest)
    (tmp_path / "forecast-publication.json").write_text(json.dumps({
        "registered": True, "recorded_at": "2026-11-22T00:01:00Z",
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }))
    (tmp_path / "prospective-capture.json").write_text(json.dumps({
        "errored": 1, "deadlineReached": False, "frozenIds": [saved_id], "frozen": 1
    }))
    if valid:
        verify(tmp_path)
    else:
        with pytest.raises(ValueError, match="missing 1 newly frozen"):
            verify(tmp_path)
