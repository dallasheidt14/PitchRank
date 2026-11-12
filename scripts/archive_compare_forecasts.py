"""Preview frozen forecast coverage; --execute saves a new LOCAL input archive."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions.forecast_archive import archive_forecasts  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New local directory; required with --execute")
    parser.add_argument(
        "--execute", action="store_true", help="Save local files; never writes forecast/database records"
    )
    args = parser.parse_args()
    if args.execute and args.output_dir is None:
        parser.error("--execute requires --output-dir")
    from supabase import create_client

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        parser.error("Configure the existing Supabase URL and server key")
    summary = archive_forecasts(create_client(url, key), ROOT, args.output_dir, dry_run=not args.execute)
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
