"""Preview a separate future form study; --execute registers it in private immutable storage."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions.form_study import register_form_study  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New archive directory; required with --execute")
    parser.add_argument("--execute", action="store_true", help="Register the fixed study; does not deploy a predictor")
    args = parser.parse_args()
    if args.execute and args.output_dir is None:
        parser.error("--execute requires --output-dir")
    client = None
    if args.execute:
        from supabase import create_client

        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            parser.error("Configure the existing Supabase URL and server key")
        client = create_client(url, key)
    result = register_form_study(client, ROOT, args.output_dir, dry_run=not args.execute)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
