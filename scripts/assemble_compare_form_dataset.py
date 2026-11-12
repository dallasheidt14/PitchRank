"""Preview a registered form study; --execute creates a new local dataset, never remote records."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions.form_dataset import assemble_dataset  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_dir", type=Path, help="Downloaded, registered private study archive")
    parser.add_argument("--output-dir", type=Path, help="New local directory; required with --execute")
    parser.add_argument("--execute", action="store_true", help="Save local files; no database writes")
    args = parser.parse_args()
    if args.execute and args.output_dir is None:
        parser.error("--execute requires --output-dir")
    url, key, token = (os.environ.get(name) for name in (
        "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN",
    ))
    if not url or not key or not token:
        parser.error("Configure the existing Supabase URL, server key, and management access token")
    from supabase import create_client

    report = assemble_dataset(create_client(url, key), url, token, args.study_dir, args.output_dir,
                              dry_run=not args.execute)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
