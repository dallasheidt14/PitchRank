"""Publish a verified ranking archive privately; default is a local read-only preview."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rankings.archive_storage import publish_archive  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--execute", action="store_true", help="Upload private objects and register server availability"
    )
    args = parser.parse_args()
    client = None
    if args.execute:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ValueError("Configure existing Supabase URL and server role key")
        client = create_client(url, key)
    print(json.dumps(publish_archive(client, args.directory, dry_run=not args.execute), indent=2))


if __name__ == "__main__":
    main()
