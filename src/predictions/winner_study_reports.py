"""Content-addressed private winner-study reports."""

from storage3.exceptions import StorageApiError

from src.predictions.score_study import digest, serialized
from src.rankings.archive_storage import _retry_transport


def preserve_report(client, signature, report, *, dry_run=True):
    raw = serialized(report).encode()
    key = f"compare-winner-studies/reports/{signature}/{digest(raw)}.json"
    if not dry_run:
        bucket = client.storage.from_("prediction-input-archives")

        def upload():
            try:
                bucket.upload(key, raw, {"content-type": "application/json", "upsert": "false"})
            except StorageApiError as error:
                if error.code not in {"Duplicate", "ResourceAlreadyExists"}:
                    raise

        _retry_transport(upload)
        if _retry_transport(lambda: bucket.download(key)) != raw:
            raise ValueError("Private report readback differs")
    return {"published": not dry_run, "object": key, "sha256": digest(raw)}
