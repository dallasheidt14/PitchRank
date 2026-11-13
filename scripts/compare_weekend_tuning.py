"""Prepare or report a private weekend diagnostic; previews write nothing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions.archive_inputs import (  # noqa: E402
    _registered_manifest,
    download_archive,
    registered_inventory,
)
from src.predictions.form_archive_sources import FrozenSourceIndex  # noqa: E402
from src.predictions.weekend_tuning import (  # noqa: E402
    DEFINITION,
    clean_revision,
    eligible_inputs,
    load_bundle,
    register_bundle,
    replay_candidates,
    require_registration_time,
)
from src.predictions.weekend_tuning_report import evaluate, final_summary, read_final, results_open  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "report"))
    parser.add_argument(
        "manifest_sha256", help="Source forecast archive (prepare) or registered weekend bundle (report)"
    )
    parser.add_argument("--output-dir", type=Path, help="New private working directory; required with --execute")
    parser.add_argument("--execute", action="store_true", help="Write private artifacts; never change the public model")
    args = parser.parse_args()
    if args.execute and args.output_dir is None:
        parser.error("--execute requires --output-dir")
    from supabase import create_client

    url, key, token = (
        os.environ.get(n) for n in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN")
    )
    if not all((url, key, token)):
        parser.error("Configure the existing Supabase URL, server key, and management token")
    client = create_client(url, key)
    inventory = registered_inventory(url, token)
    _, manifest, _ = _registered_manifest(client, args.manifest_sha256)
    if args.mode == "prepare":
        require_registration_time(inventory["as_of"])
        if not args.execute:
            result = {
                "status": "preview",
                "definition": DEFINITION,
                "outcomes_read": False,
                "source_archive": args.manifest_sha256,
                "writes": False,
            }
        else:
            clean_revision(ROOT)
            args.output_dir.mkdir(parents=True, exist_ok=False)
            source = download_archive(
                client, args.manifest_sha256, args.output_dir / "source", dry_run=False, return_verified=True
            )
            sources = FrozenSourceIndex([source], ROOT)
            _, _, cases, _ = eligible_inputs(sources)
            from scripts.benchmark_compare_form import run_predictor

            records, receipts = replay_candidates(cases, run_predictor, args.output_dir)
            # Refresh the authoritative clock after replay and before any registration writes.
            require_registration_time(registered_inventory(url, token)["as_of"])
            result = register_bundle(
                client, ROOT, sources, records, receipts, args.output_dir / "bundle", [args.manifest_sha256]
            )
    else:
        if manifest.get("weekend_tuning", {}).get("definition") != DEFINITION:
            raise ValueError("Expected the separately registered weekend diagnostic")
        if not results_open(inventory["as_of"]):
            result = evaluate(client, args.manifest_sha256, None, inventory["as_of"], dry_run=not args.execute)
        elif not args.execute:
            # Preview checks the seal without creating download folders or reading outcome rows.
            result = {"status": "closed_window_preview", "outcomes_read": False, "writes": False}
        elif existing := read_final(client, args.manifest_sha256):
            result = final_summary(existing)
        else:
            args.output_dir.mkdir(parents=True, exist_ok=False)
            archive = download_archive(
                client, args.manifest_sha256, args.output_dir / "bundle", dry_run=False, return_verified=True
            )
            result = evaluate(client, args.manifest_sha256, load_bundle(archive), inventory["as_of"], dry_run=False)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
