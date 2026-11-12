"""Capture a registered form challenger alongside authenticated baseline forecasts; preview by default."""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.benchmark_compare_form import run_predictor  # noqa: E402
from scripts.settle_prospective_match_predictions import _supabase_client  # noqa: E402
from src.predictions.archive_inputs import _registered_manifest, authenticate_archive, download_archive  # noqa: E402
from src.predictions.challenger_capture import capture_candidate, capture_preflight  # noqa: E402
from src.predictions.challenger_download import CachedArchiveClient  # noqa: E402
from src.predictions.form_archive_sources import FrozenSourceIndex  # noqa: E402
from src.predictions.prospective_fixtures import paged  # noqa: E402
from src.rankings.input_archive import FORECAST_ARCHIVE_KIND  # noqa: E402


def forecast_archive_headers(client):
    # Earlier results can supply form history; every expectation still has to be prematch authenticated.
    earliest = (datetime.now(timezone.utc) - timedelta(days=366)).isoformat()
    records = paged(lambda: client.table("prediction_input_archives").select("manifest_sha256")
                    .gte("recorded_at", earliest).order("recorded_at").order("manifest_sha256"))
    headers = []
    for record in records:
        _, manifest, _ = _registered_manifest(client, record["manifest_sha256"])
        if manifest.get("configuration", {}).get("capture_kind") == FORECAST_ARCHIVE_KIND:
            headers.append(record)
    return headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_signature")
    archives = parser.add_mutually_exclusive_group(required=True)
    archives.add_argument("--archive", type=Path, action="append",
                        help="An existing private forecast archive; repeat to supply frozen historical expectations")
    archives.add_argument("--download-archives", type=Path,
                         help="New private local directory for registered forecast archives; execute only")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary-path", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = _supabase_client()
    cache = None
    preflight = capture_preflight(client, args.candidate_signature)
    if preflight["eligible_prematch"] == 0:
        result = {**preflight, "dry_run": not args.execute, "captured": 0, "errors": {}, "archives_downloaded": False}
        if args.execute and args.summary_path:
            args.summary_path.parent.mkdir(parents=True, exist_ok=True)
            with args.summary_path.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, allow_nan=False)
        print(json.dumps(result, indent=2))
        return
    if args.download_archives:
        headers = forecast_archive_headers(client)
        if not args.execute:
            print(json.dumps({"dry_run": True, "candidate_signature": args.candidate_signature,
                              "forecast_archives_available": len(headers), "downloaded": False,
                              "capture_performed": False, "inputs_verified": False}))
            return
        args.download_archives.mkdir(parents=True, exist_ok=False)
        cache = CachedArchiveClient(client, args.download_archives, dry_run=False)
        archives = []
        for header in headers:
            archive = download_archive(cache, header["manifest_sha256"],
                args.download_archives / header["manifest_sha256"], dry_run=False, return_verified=True)
            cache.share_local_objects(archive)
            archives.append(archive)
    else:
        archives = [authenticate_archive(client, directory) for directory in args.archive]
    result = capture_candidate(client, args.candidate_signature, FrozenSourceIndex(archives, ROOT),
                               run_predictor, dry_run=not args.execute, limit=args.limit)
    if cache is not None:
        result["archive_object_reuse"] = dict(cache.counts)
    if args.execute and args.summary_path:
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        with args.summary_path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
