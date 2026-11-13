"""Publish detailed reports to the existing private bucket, never public Actions artifacts."""

import argparse
import hashlib
import os
from pathlib import Path

from supabase import create_client


def publish(client, directory, *, dry_run=True):
    files = sorted(directory.glob("*/*"))
    if not files or any(p.is_symlink() or p.suffix not in (".md", ".json") for p in files):
        raise ValueError("Expected a private monitoring report directory")
    set_sha = hashlib.sha256(
        b"".join(str(p.relative_to(directory)).encode() + p.read_bytes() for p in files)
    ).hexdigest()
    if not dry_run:
        for path in files:
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            key = f"compare-monitoring/reports/{path.parent.name}/{set_sha}/{sha}/{path.name}"
            bucket = client.storage.from_("prediction-input-archives")
            # Content-addressed overwrite has identical bytes; no forecast is replaced.
            bucket.upload(
                key,
                raw,
                {"upsert": "true", "content-type": "application/json" if path.suffix == ".json" else "text/markdown"},
            )
    return {"files": len(files), "published": not dry_run}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    print(publish(client, args.directory, dry_run=not args.execute))


if __name__ == "__main__":
    main()
